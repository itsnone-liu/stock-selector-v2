"""tdx_quotes — TDX 实时快照 drop-in（退役腾讯 qt.gtimg.cn，2026-10-21 定案）。

背景：定案 = TDX 通道已打通 → 腾讯/新浪/东财全部退役；所有 TDX 能快速获取的工程
数据一律走 TDX 通道（老刘 2026-10-21 原话："扔垃圾箱，连复核都不需要"）。

本模块是**腾讯 qt.gtimg.cn 批量行情的直接替代**，字段名与旧解析保持一致，
调用方只需把 `urllib` 那段换成 `from r2.tdx_quotes import quotes`。

兼容字段（与旧腾讯解析同义）:
    name, price, pct(=涨幅%), high, low
新增字段（TDX 原生，旧链无）:
    last_close(昨收), turnover_pct(换手率%), vol(手), amount(元)

实测证据（2026-10-21 17:30 CST，本机 Ubuntu，host 池 2 主站）:
    - snapshot 昨收 vs 本地 /root/tdx_data .day 收盘：8/8 只 diff=0.000（硬锚）
    - sh000001/market=1 返回上证指数（3713.03）→ 可替代 idx_pct()
    - names 表：sh 27677 行 / sz 24454 行，GBK 解码正常（个别基金代码名有替换字符）
    - 北交所(market=2)：主站覆盖不全（实测 920819 有、430047/830799 缺）→
      请求会进 missing，**不静默、不伪造**；工程侧按 missing 显式告警处理。

停牌/无行情判定口径（2026-10-22 客户端 vs CLI 逐字节对拍 C-1/C-2 定案）:
    - **否定** `price==0 && vol==0` 判停牌：盘前 09:10 全市场请求 5598 只、返回 5576 只，
      5576/5576 全部 price=0,vol=0,servertime=8:35:00.000 —— 价格 0 只说明还没撮合。
    - **真信号 = missing**（服务器不给该记录）。C-2 实测 22 只 = 停牌/无行情，
      与本机 .day 最后交易日佐证一致。
    - 少给记录时服务器用**占位行**凑数（C-3：18 个分块里 unexpected 恒为 600839，
      出现次数与 missing 条数严格 1:1）→ 请求集之外的键一律噪声，绝不入榜。

纪律：语义异常 fail-closed；缺失进 missing 而不猜；不伪造 name/交易状态。
"""
from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))
from r2.tdx_client import with_session  # noqa: E402

ROOT = _HERE.parents[1]
NAMES_DIR = ROOT / 'data/r2/tdx_names'
_LAST_MISSING: list[str] = []


def _prefix(code6: str) -> str:
    """6 位纯代码 → 交易所前缀（与旧链规则一致：6/9→sh，4/8→bj，其余→sz）。"""
    c = code6[0]
    return 'bj' if c in '48' else ('sh' if c in '69' else 'sz')


def _split(codes):
    """归一化代码表 → [(prefix, code6)]，保序去重；'sh600125' 前缀优先。

    去重键 = (prefix, code6)：'sz000001'(平安银行) 与 'sh000001'(上证指数) 是两只
    不同标的，不能按 code6 合并（2026-10-21 实测踩过：上证指数被静默吞掉）。
    """
    out, seen = [], set()
    for raw in codes:
        s = str(raw).strip().lower()
        pref = s[:2] if s[:2] in ('sh', 'sz', 'bj') else None
        c6 = s[2:] if pref else s
        if len(c6) != 6 or not c6.isdigit():
            raise ValueError(f'bad stock code: {raw!r}')
        key = ((pref or _prefix(c6)), c6)
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def _key_for(pref: str, c6: str, prefs_of: dict) -> str:
    """返回字典键：正常用 6 位代码（兼容旧链）；同一 code6 出现多个交易所前缀时
    （如 000001 既是平安银行又是上证指数），第二个及以后用 'sh000001' 全码，不静默覆盖。
    """
    return c6 if len(prefs_of[c6]) == 1 else pref + c6


def _market(pref: str) -> int:
    return {'sz': 0, 'sh': 1, 'bj': 2}[pref]


def names_map(markets=(1, 0), date: int | None = None, refresh: bool = False) -> dict:
    """TDX 名称表 → {'sh600125': name, 'sz000001': 平安银行, 'sh000001': 上证指数}。

    键按**交易所+代码**（不是裸 code6）：同一 code6 在两个所是不同标的
    （000001 上证指数 vs 平安银行），裸 code6 会串名（2026-10-21 实测踩过）。
    按日落盘缓存 data/r2/tdx_names/names_<ymd>.json。

    首次拉取实测 ~6s（sh+sz 共 5.2 万行），当日缓存命中 0s。
    """
    day = date or int(time.strftime('%Y%m%d'))
    cache = NAMES_DIR / f'names_{day}.json'
    if cache.exists() and not refresh:
        try:
            data = json.loads(cache.read_text())
            if data and all(len(k) == 8 for k in data):   # 旧缓存（裸 code6 键）作废重建
                return data
        except (OSError, ValueError):
            pass

    def op(s):
        out = {}
        for m in markets:
            tag = {0: 'sz', 1: 'sh', 2: 'bj'}[m]
            r = s.names(m, day)
            for row in r['rows']:
                out[tag + row['code']] = row['name']
        return out

    data = with_session(op)
    NAMES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.replace(cache)
    return data


def quotes(codes, *, with_name: bool = True, batch: int = 80) -> dict:
    """TDX 批量实时快照 → {code6: {name, price, pct, high, low, last_close, turnover_pct, vol, amount}}。

    与旧腾讯 quotes() 同签名同返回结构（仅字段更多），未取到的代码**不出现**在返回里，
    停牌/无行情判定请用 `last_missing()`（服务器不返回记录 = missing = 停牌/无行情）；
    **不要**再用 `price<=0` 判停牌——盘前有记录但 price=0（C-1 已否证）。
    """
    norm = _split(codes)
    if not norm:
        return {}
    prefs_of: dict[str, set] = {}
    for p, c6 in norm:
        prefs_of.setdefault(c6, set()).add(p)
    nm = names_map() if with_name else {}
    res: dict[str, dict] = {}

    def op(s):
        for i in range(0, len(norm), batch):
            chunk = norm[i:i + batch]
            snap = s.snapshot([(_market(p), c) for p, c in chunk], use_batch=True)
            for r in snap['rows']:
                c6, mk = r['code'], r['market']
                pref = {0: 'sz', 1: 'sh', 2: 'bj'}[mk]
                if prefs_of.get(c6) and pref not in prefs_of[c6]:
                    continue  # 服务端串位返回（异常标的）：不污染结果，留给 missing
                res[_key_for(pref, c6, prefs_of)] = {
                    'name': nm.get(pref + c6) or nm.get(c6) or c6,
                    'price': float(r['price'] or 0.0),
                    'pct': round(float(r['pct_change']), 4) if r['pct_change'] is not None else 0.0,
                    'high': float(r['high'] or 0.0),
                    'low': float(r['low'] or 0.0),
                    'last_close': float(r['last_close'] or 0.0),
                    'open': float(r['open'] or 0.0),
                    'ts': str(r.get('servertime') or ''),
                    'turnover_pct': r['turnover_pct'],
                    'vol': r['vol'],
                    'amount': r['amount'],
                }
        return res

    out = with_session(op)
    global _LAST_MISSING
    _LAST_MISSING = [_key_for(p, c, prefs_of) for p, c in norm if _key_for(p, c, prefs_of) not in out]
    return out


def index_pct(code: str = 'sh000001') -> float:
    """指数实时涨幅%（替代旧 idx_pct()；默认上证综指）。"""
    q = quotes([code], with_name=False)
    pref, c6 = _split([code])[0]
    row = q.get(c6) or q.get(pref + c6) or {}
    return float(row.get('pct') or 0.0)


def name_of(code: str) -> str:
    """单只名称查询（'600125' / 'sh600125' 均可）。"""
    pref, c6 = _split([code])[0]
    nm = names_map()
    return nm.get(pref + c6) or nm.get(c6) or c6


def last_missing() -> list[str]:
    """最近一次 quotes() 未取到的代码（北交所覆盖不全等，供告警用）。"""
    return list(_LAST_MISSING)


def lookup(mapping: dict, code):
    """从 quotes()/split_quotes() 的返回里取一只（'600125' / 'sh600125' 均可）。"""
    s = str(code).strip().lower()
    if s[:2] in ('sh', 'sz', 'bj'):
        return mapping.get(s[2:]) or mapping.get(s)
    return mapping.get(s) or mapping.get('sh' + s) or mapping.get('sz' + s) or mapping.get('bj' + s)


def split_quotes(q: dict, codes, missing=None):
    """给一批 quotes() 结果按**停牌/无行情口径**分桶 → (ok, missing, no_price)。

    口径来源：2026-10-22 客户端 vs CLI 逐字节对拍 C-1/C-2/C-3 定案。

    ok       {key: row} —— 有记录且 price>0，可入榜
    missing  list       —— 服务器**不返回记录** = 停牌/无行情（fail-closed：不猜、不补）
    no_price list       —— 有记录但 price<=0 = 盘前/竞价未撮合，**不是**停牌（单列）

    反例（已证否）：盘前 09:10 全市场请求 5598 只、返回 5576 只，5576/5576 全部
    price=0,vol=0,servertime=8:35:00.000 —— 所以 `price<=0` 不能当停牌信号。

    price 非数值 / 非有限（NaN、Inf）一律 **抛 ValueError**（fail-closed）：这是传输或
    解析损坏，既不能算「有价」也不能冒充「盘前未撮合」，更不能带着 NaN 进榜。

    key 规则与 quotes() 输出一致（常规 6 位；同一 code6 跨所时用 'sh000001' 全码）。
    missing 参数显式给出时以其为准（如跨批次聚合），否则按「请求集 − 有响应集」实算。
    """
    norm = _split(codes)
    if not norm:
        return {}, [], []
    prefs_of: dict[str, set] = {}
    for p, c6 in norm:
        prefs_of.setdefault(c6, set()).add(p)
    ok: dict[str, dict] = {}
    no_price: list[str] = []
    for p, c6 in norm:
        k = _key_for(p, c6, prefs_of)
        row = q.get(k)
        if row is None:
            continue
        px = row.get('price') if isinstance(row, dict) else None
        try:
            px = float(px)
        except (TypeError, ValueError):
            raise ValueError('invalid price for %s: %r' % (k, px))
        if not math.isfinite(px):
            raise ValueError('non-finite price for %s: %r' % (k, px))
        if px <= 0:
            no_price.append(k)
        else:
            ok[k] = row
    if missing is None:
        got = set(ok) | set(no_price)
        miss = [k for k in (_key_for(p, c6, prefs_of) for p, c6 in norm) if k not in got]
    else:
        miss = [str(m) for m in missing]
    return ok, miss, no_price


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description='TDX 实时快照冒烟')
    ap.add_argument('codes', nargs='*', default=['sh600125', 'sz000001', 'sz300750', 'sh000001'])
    a = ap.parse_args()
    t0 = time.time()
    q = quotes(a.codes)
    print(f'elapsed {time.time()-t0:.1f}s  n={len(q)}  missing={last_missing()}')
    for k, v in q.items():
        print(f"{k}  {v['name']:8} price={v['price']:>10.2f} pct={v['pct']:>7.2f}% "
              f"turn={v['turnover_pct'] if v['turnover_pct'] is None else round(v['turnover_pct'],2)}% "
              f"last_close={v['last_close']}")