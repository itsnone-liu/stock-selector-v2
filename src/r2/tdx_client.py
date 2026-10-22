"""TDX 自立门户客户端 — R2 生产模块。

协议实现移植自 tdx-protocol 仓库 realclient/cli.py（commit deab97e，27/27 离线测试 +
本机 Ubuntu 冒烟 + 故障切换复验全部通过）。协议层代码与验证版本保持一致，
仅做模块化处理：去 CLI 化、加日志、bootstrap 模板 sha256 绑定、默认 host 池。

数据源角色（替换腾讯）：
- xdxr_batch:  全市场除权事件表（op15，<=60 只/批）
- adjust:      cat1 仿射链 qfq 自算（client-grounded C2，已验证 <=0.01）
- quotes:      实时批量快照（<=80 只/批，含最新价/昨收/量）
- capital_batch/finance: 流通股本 -> 换手率
- daily/qfq_daily: 网络日线（备胎；主力读本地 TDX 镜像 /root/tdx_data）

纪律（与上游一致）：
- 语义/数据异常一律 fail-closed，不猜不补
- 只有传输错误才切 host；数据损坏不重试
- 输出原子落盘，NaN 拒绝
"""
import hashlib
import json
import logging
import math
import os
import socket
import struct
import tempfile
import zlib
from pathlib import Path

from tdxpy.parser.std.get_security_quotes import GetSecurityQuotesCmd
from tdxpy.parser.std.get_xdxr_info import GetXdXrInfo
from tdxpy.parser.std.get_finance_info import GetFinanceInfo
from tdxpy.parser.std.get_security_bars import GetSecurityBarsCmd

log = logging.getLogger('r2.tdx_client')

# bootstrap 模板绑定（tdx-protocol lab/op11_template.bin 的 sha256）
TEMPLATE_SHA256 = 'd8b33ff083caa96a2fd507a0035405e76295f28d1d2ffec2c8e7d0ae1d1bf4d8'
DEFAULT_TEMPLATE = Path(__file__).resolve().parent.parent.parent / 'data' / 'r2' / 'tdx_bootstrap.bin'

# 官方主站池（tdx-protocol 验证：两 host 均接受同一 bootstrap 模板）
DEFAULT_HOSTS = ['123.60.164.122:7709', '175.178.112.197:7709']

MKT = {'sz': 0, 'sh': 1, 'bj': 2}


def symbol(value):
    """'sh600125' -> (1,'600125')。北交所 market=2。"""
    market = MKT.get(value[:2].lower())
    code = value[2:]
    if market is None or len(code) != 6 or not code.isdigit():
        raise ValueError('expected sh600125 / sz000001 / bj920002')
    return market, code


def _exact(s, n):
    b = bytearray()
    while len(b) < n:
        chunk = s.recv(n - len(b))
        if not chunk:
            raise ConnectionError('truncated response: got %d of %d bytes' % (len(b), n))
        b.extend(chunk)
    return bytes(b)


def _unwrap_frame(body, packed, raw):
    """帧载荷长度闸门（差异清单 A-2）。

    R4/R5 逐字节对拍（2026-10-22）：五个成功时点均满足
    comp_len == len(response) - 16 且 raw_len == len(clear)。
    09:27:55 客户端侧 'truncated response' 正是缺此闸门的表现，故两半都强制校验，
    不再依赖“解出来长度对得上”的弱推断。
    """
    if packed == raw:
        clear = body
    else:
        d = zlib.decompressobj()
        try:
            clear = d.decompress(body) + d.flush()
        except zlib.error as exc:
            raise ValueError('zlib decode failed: %s' % exc)
        if d.unconsumed_tail:
            raise ValueError('compressed stream unconsumed tail: %d bytes' % len(d.unconsumed_tail))
        if d.unused_data:
            raise ValueError('compressed stream trailing bytes: %d bytes' % len(d.unused_data))
    if len(clear) != raw:
        raise ValueError('response size mismatch: header raw_len=%d clear=%d' % (raw, len(clear)))
    return clear


def _recv(s):
    h = _exact(s, 16)
    if h[:4] != bytes.fromhex('b1 cb 74 00'):
        raise ValueError('unexpected header')
    packed, raw = struct.unpack_from('<HH', h, 12)
    body = _exact(s, packed)
    if len(body) != packed:
        raise ValueError('compressed length mismatch: header packed=%d body=%d' % (packed, len(body)))
    return h, _unwrap_frame(body, packed, raw)


def check_quote_count(body, rows):
    """记录数完整性闸门（差异清单 D8 / C-3）。

    quotes 记录**非定长**（实测 64–79 字节，价格字段变宽编码），因此不能靠
    len(body)/stride 推条数，只能用响应头声明的记录数 body[2:4] 作基准。
    解析条数少于声明数 == 解析器/传输损坏 → fail closed；
    多于声明数不抛错（服务器异常，多余键已在调用方由白名单落入 unexpected）。
    """
    if not isinstance(body, (bytes, bytearray)) or len(body) < 4:
        return None
    declared = struct.unpack_from('<H', body, 2)[0]
    if len(rows) < declared:
        raise ValueError('quote record count shortfall: declared %d parsed %d' % (declared, len(rows)))
    return declared


def parse_capital_batch(body, stocks):
    """Decode only verified op16 offsets; reject identity/length corruption."""
    if len(body) < 2:
        raise ValueError('capital count missing')
    n = struct.unpack_from('<H', body)[0]
    if len(body) != 2 + n * 143:
        raise ValueError('capital row length mismatch')
    expected = set(stocks)
    seen = set()
    rows = []
    for off in range(2, len(body), 143):
        r = body[off:off + 143]
        market = r[0]
        code = r[1:7].decode('ascii')
        key = (market, code)
        if key not in expected or key in seen:
            raise ValueError('capital identity mismatch')
        seen.add(key)
        float_wan = struct.unpack_from('<f', r, 7)[0]
        date, ipo = struct.unpack_from('<II', r, 15)
        total_wan = struct.unpack_from('<f', r, 23)[0]
        if not all(math.isfinite(x) and x >= 0 for x in (float_wan, total_wan)):
            raise ValueError('invalid capital values')
        rows.append(dict(market=market, code=code, float_shares=float_wan * 10000,
                         total_shares=total_wan * 10000, data_date=date, ipo_date=ipo))
    if seen != expected:
        raise ValueError('capital missing stocks')
    return rows


class Session:
    def __init__(self, host, port, template=None):
        path = Path(template) if template else DEFAULT_TEMPLATE
        prefix = path.read_bytes()
        if len(prefix) != 284:
            raise ValueError('expected observed 284-byte bootstrap prefix')
        digest = hashlib.sha256(prefix).hexdigest()
        if digest != TEMPLATE_SHA256:
            raise ValueError('bootstrap template sha256 mismatch: ' + digest)
        self.sock = socket.create_connection((host, port), timeout=10)
        self.sock.settimeout(15)
        self.sock.sendall(prefix + b'\0' * 8)
        h, b = _recv(self.sock)
        if struct.unpack_from('<H', h, 10)[0] != 11:
            raise ValueError('bootstrap opcode mismatch')
        log.info('session open %s:%s', host, port)

    def call(self, cmd):
        self.sock.sendall(cmd.send_pkg)
        h, b = _recv(self.sock)
        if struct.unpack_from('<H', h, 10)[0] != struct.unpack_from('<H', cmd.send_pkg, 10)[0]:
            raise ValueError('response opcode mismatch')
        if h[5] != cmd.send_pkg[1]:
            raise ValueError('response sequence mismatch')
        self.last_body = b
        return cmd.parseResponse(b)

    def quotes(self, stocks):
        result = []
        missing = []
        unexpected = []
        for start in range(0, len(stocks), 80):
            chunk = stocks[start:start + 80]
            cmd = GetSecurityQuotesCmd(self.sock)
            cmd.setParams(chunk)
            rows = self.call(cmd) or []
            body = getattr(self, 'last_body', None)
            if isinstance(body, bytes):
                check_quote_count(body, rows)
            expected = set(chunk)
            seen = set()
            for r in rows:
                key = (r['market'], r['code'])
                # 白名单口径（差异清单 D8）：服务器少给几条就用占位行（如 600839）
                # 凑数，出现次数与 missing 条数 1:1。请求集之外的键一律当噪声，
                # 绝不能当数据用。
                if key not in expected:
                    unexpected.append(key)
                    continue
                if key in seen:
                    raise ValueError('duplicate returned quote')
                seen.add(key)
                result.append(r)
            missing.extend(sorted(expected - seen))
        return {'rows': result, 'missing': missing, 'unexpected': unexpected,
                'complete': not missing and not unexpected}

    def xdxr(self, market, code):
        cmd = GetXdXrInfo(self.sock)
        cmd.setParams(market, code)
        return self.call(cmd)

    def _xdxr_one_batch(self, chunk):
        """单批 op15；服务端响应被硬截断时抛错（不返回半成品）。"""
        body = struct.pack('<HH', 15, len(chunk)) + b''.join(
            struct.pack('<B6s', m, c.encode('ascii')) for m, c in chunk)
        self.sock.sendall(b'\0' * 6 + struct.pack('<HH', len(body), len(body)) + body)
        hdr, b = _recv(self.sock)
        if struct.unpack_from('<H', hdr, 10)[0] != 15:
            raise ValueError('batch xdxr opcode mismatch')
        n = struct.unpack_from('<H', b)[0]
        pos = 2
        seen = set()
        result = []
        for _ in range(n):
            market, code, count = struct.unpack_from('<B6sH', b, pos)
            pos += 9
            code = code.decode('ascii')
            key = (market, code)
            if key not in set(chunk) or key in seen:
                raise ValueError('batch xdxr stock identity mismatch')
            seen.add(key)
            events = []
            for _ in range(count):
                em, ec, date, cat, f1, f2, f3, f4 = struct.unpack_from('<B7sIBffff', b, pos)
                pos += 29
                if (em, ec.rstrip(b'\0').decode('ascii')) != key:
                    raise ValueError('event identity mismatch')
                events.append(dict(date=date, category=cat, f1=f1, f2=f2, f3=f3, f4=f4))
            result.append(dict(market=market, code=code, events=events))
        if pos != len(b) or seen != set(chunk):
            raise ValueError('incomplete batch xdxr response')
        return result

    def xdxr_batch(self, stocks, batch_size=10):
        """Actual client op15 format. Return all categories and four raw floats
        without guessing unknown meanings.

        服务端响应上限实测 ≈26,429B（未压缩，两 host 一致）：默认 10 只/批
        （安全余量），遇截断自动二分收缩；单只仍截断则 fail-closed。
        """
        result = []
        pending = [list(stocks[start:start + batch_size])
                   for start in range(0, len(stocks), batch_size)]
        while pending:
            chunk = pending.pop(0)
            try:
                result.extend(self._xdxr_one_batch(chunk))
            except ValueError as e:
                if 'incomplete batch xdxr response' not in str(e) or len(chunk) == 1:
                    raise
                log.warning('op15 truncated at %d stocks, splitting (%s)', len(chunk), chunk)
                mid = len(chunk) // 2
                pending.insert(0, chunk[mid:])
                pending.insert(0, chunk[:mid])
        return result

    def names(self, market, date):
        """Real-client 044E/044D table; no undocumented record-tail decoding."""
        def exchange(op, payload):
            body = struct.pack('<H', op) + payload
            self.sock.sendall(b'\x0c\x01\x18\x64\x01\x01' + struct.pack('<HH', len(body), len(body)) + body)
            hdr, b = _recv(self.sock)
            if struct.unpack_from('<H', hdr, 10)[0] != op:
                raise ValueError('names opcode mismatch')
            return b
        total_body = exchange(0x044e, struct.pack('<HI', market, date))
        if len(total_body) != 2:
            raise ValueError('names count length mismatch')
        total = struct.unpack('<H', total_body)[0]
        rows = []
        seen = set()
        for start in range(0, total, 1600):
            b = exchange(0x044d, struct.pack('<HIH', market, start, 1600) + b'\0' * 6)
            if len(b) < 2:
                raise ValueError('names page missing count')
            n = struct.unpack_from('<H', b)[0]
            if n != min(1600, total - start) or len(b) != 2 + n * 37:
                raise ValueError('names page length mismatch')
            for off in range(2, len(b), 37):
                r = b[off:off + 37]
                code = r[:6].decode('ascii')
                if code in seen:
                    raise ValueError('duplicate names code')
                seen.add(code)
                raw_name = r[8:24].split(b'\0')[0]
                try:
                    name = raw_name.decode('gbk')
                    decode_ok = True
                except UnicodeDecodeError:
                    name = raw_name.decode('gbk', errors='replace')
                    decode_ok = False
                rows.append(dict(market=market, code=code, name=name,
                                 name_decode_ok=decode_ok, volunit=struct.unpack_from('<H', r, 6)[0]))
        return dict(market=market, asof_request_date=date, total=total, rows=rows)

    def capital_batch(self, stocks):
        result = []
        for start in range(0, len(stocks), 100):
            chunk = stocks[start:start + 100]
            body = struct.pack('<HH', 16, len(chunk)) + b''.join(
                struct.pack('<B6s', m, c.encode('ascii')) for m, c in chunk)
            self.sock.sendall(b'\0' * 6 + struct.pack('<HH', len(body), len(body)) + body)
            hdr, response = _recv(self.sock)
            if struct.unpack_from('<H', hdr, 10)[0] != 16:
                raise ValueError('capital opcode mismatch')
            parsed = parse_capital_batch(response, chunk)
            if len(parsed) != len(chunk):
                raise ValueError('capital batch size mismatch: requested %d got %d'
                                 % (len(chunk), len(parsed)))
            result.extend(parsed)
        return result

    def daily(self, market, code, count=400):
        """Bounded daily command, no full-history completeness claim."""
        if count < 1 or count > 12000:
            raise ValueError('count must be 1..12000')
        rows = []
        for start in range(0, count, 800):
            cmd = GetSecurityBarsCmd(self.sock)
            cmd.setParams(4, market, code, start, min(800, count - start))
            page = self.call(cmd) or []
            rows.extend(page)
            if len(page) < min(800, count - start):
                break
        bydate = {}
        for r in rows:
            d = r['datetime'][:10]
            if d in bydate:
                raise ValueError('duplicate daily date')
            values = [r[x] for x in ('open', 'high', 'low', 'close')]
            if not all(math.isfinite(x) and x > 0 for x in values):
                raise ValueError('invalid daily prices')
            bydate[d] = dict(date=d, open=r['open'], high=r['high'], low=r['low'],
                             close=r['close'], volume_hand=r['vol'], amount=r['amount'])
        return [bydate[d] for d in sorted(bydate)]

    def qfq_daily(self, market, code, count, asof):
        raw = [r for r in self.daily(market, code, count) if r['date'] <= asof]
        if not raw:
            raise ValueError('daily baseline unavailable')
        events = self.xdxr(market, code)
        # Categories requiring historical-client behavioral verification fail closed.
        for e in events:
            d = '{:04d}-{:02d}-{:02d}'.format(e['year'], e['month'], e['day'])
            if raw[0]['date'] < d <= asof and e['category'] not in (1, 5, 6, 7, 8, 9, 10, 13, 14):
                raise ValueError('unverified special category in adjustment window: '
                                 + str(e['category']) + ' ' + d)
        result = [dict(r) for r in raw]
        for field in ('open', 'high', 'low', 'close'):
            computed = dict(adjust([(r['date'], r[field]) for r in raw], events, asof))
            for r in result:
                r['raw_' + field] = r[field]
                r[field] = computed[r['date']]
        return dict(market=market, code=code, asof=asof, adjustment='cat1-affine-c2',
                    rows=result, requested_count=count, returned_count=len(result),
                    complete_history=False)

    def finance(self, market, code):
        cmd = GetFinanceInfo(self.sock)
        cmd.setParams(market, code)
        row = self.call(cmd)
        if not row or (row.get('market'), row.get('code')) != (market, code):
            raise ValueError('finance identity mismatch')
        return row

    def snapshot(self, stocks, use_batch=False):
        """Finance should be cached by caller with date; no fake name/trading status.
        Volume hand-to-share factor 100 verified only for sampled A shares.
        """
        result = self.quotes(stocks)
        capitals = {(r['market'], r['code']): r
                    for r in self.capital_batch([(q['market'], q['code']) for q in result['rows']])} if use_batch else {}
        for row in result['rows']:
            if use_batch:
                f = capitals[(row['market'], row['code'])]
                shares = f['float_shares']
                date = f['data_date']
            else:
                f = self.finance(row['market'], row['code'])
                shares = f.get('liutongguben')
                date = f.get('updated_date')
            row['float_shares'] = shares
            row['finance_updated_date'] = date
            row['capital_source'] = 'op16' if use_batch else 'finance_info'
            row['turnover_pct'] = row['vol'] * 10000 / shares if shares and shares > 0 else None
            row['pct_change'] = (row['price'] / row['last_close'] - 1) * 100 \
                if row['last_close'] and row['price'] else None
        return result

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


def adjust(bars, events, asof):
    """Client-grounded C2. bars sorted (ISO date,price); no future event leakage.
    Same-day multiple cat1 records require upstream normalization; fail closed.

    事件字段（GetXdXrInfo 语义）: fenhong 每10股派现 / songzhuangu 每10股送转 /
    peigu 每10股配股 / peigujia 配股价。cat1=除权除息。
    """
    selected = []
    seen = set()
    for e in events:
        if e['category'] != 1:
            continue
        d = '{:04d}-{:02d}-{:02d}'.format(e['year'], e['month'], e['day'])
        if d > asof:
            continue
        if d in seen:
            raise ValueError('multiple cat1 events same date require normalization')
        seen.add(d)
        fh = (e.get('fenhong') or 0) / 10
        pg = (e.get('peigu') or 0) / 10
        selected.append((d, fh - (e.get('peigujia') or 0) * pg, 1 + (e.get('songzhuangu') or 0) / 10 + pg))
    selected.sort()
    i = len(selected)
    D = 0.
    K = 1.
    out = []
    for d, p in sorted(bars, reverse=True):
        if d > asof:
            continue
        while i and selected[i - 1][0] > d:
            _, cash, ke = selected[i - 1]
            D = cash + D * ke
            K *= ke
            i -= 1
        out.append((d, (p - D) / K))
    return list(reversed(out))


def atomic_json(path, value):
    """Preserve existing final output unless complete serialization+replace succeeds."""
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    target = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=target.name + '.', suffix='.tmp', dir=str(target.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf8') as out:
            out.write(text)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_hosts(hosts, port, template, operation, attempt_log):
    """Only transport failures switch hosts; semantic/data corruption fails closed."""
    for endpoint in hosts:
        host = endpoint
        selected_port = port
        if ':' in endpoint:
            host, port_text = endpoint.rsplit(':', 1)
            selected_port = int(port_text)
        s = None
        try:
            s = Session(host, selected_port, template)
            value = operation(s)
            attempt_log.append(dict(host=host, port=selected_port, status='success'))
            return value
        except (OSError, ConnectionError) as e:
            log.warning('host %s:%s transport failed: %r', host, selected_port, e)
            attempt_log.append(dict(host=host, port=selected_port,
                                    status='transport_failed', error=repr(e)))
        finally:
            if s:
                s.close()
    raise ConnectionError('all configured hosts failed: ' + str(attempt_log))


def with_session(operation, hosts=None, template=None, port=7709):
    """便捷入口：host 池故障切换 + 会话管理。operation 接收 Session 返回结果。"""
    attempt_log = []
    return run_hosts(hosts or DEFAULT_HOSTS, port, template, operation, attempt_log)
