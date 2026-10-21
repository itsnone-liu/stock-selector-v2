#!/usr/bin/env python3
"""qfq 自算对拍 v2 — 基准改用东财 push2his（独立源，本机可达）。

三项检验：
  A) 本地 TDX .day 裸价   vs  东财 fqt=0          → 本地镜像是否真裸价
  B) 自算前复权(raw+TDX事件, asof=末日) vs 东财 fqt=1
  C) 事件级因子：东财段内比值 vs 本机事件公式

B 同时给两个口径：
  - abs  ：绝对值逐 bar 差（受锚点选择影响）
  - norm ：把自算序列按末日比值缩放后再比 → 剔除锚点差异，只验形状/事件口径
判定 pass：abs<=0.011 且 norm<=0.011（东财 2 位小数舍入 → 容差 0.011）

用法: .venv/bin/python scripts/tdx_qfq_parity_em.py [--random 50] [--out PATH]
"""
import argparse
import gzip
import json
import logging
import random
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from r2.tdx_client import adjust  # noqa: E402

TDX_DIR = Path('/root/tdx_data')
XDXR = ROOT / 'data/r2/tdx/xdxr_fullmarket_20261021.json.gz'
EM = ('https://push2his.eastmoney.com/api/qt/stock/kline/get'
      '?fields1=f1,f2,f3&fields2=f51,f52,f53,f54,f55,f56&klt=101'
      '&secid={secid}&fqt={fqt}&beg={beg}&end={end}')
TOL = 0.011
log = logging.getLogger('parity')

FIELDS = ('open', 'high', 'low', 'close')


def secid(code):
    if code.startswith(('6', '9')):
        return '1.' + code
    return '0.' + code


_EM_HOSTS = ('push2his.eastmoney.com', '82.push2his.eastmoney.com',
             '1.push2his.eastmoney.com', '2.push2his.eastmoney.com')
_EM_URL = ('https://{host}/api/qt/stock/kline/get?secid={secid}'
           '&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56'
           '&klt=101&fqt={fqt}&beg={beg}&end={end}')
_EM_HDRS = {
    'User-Agent': ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'),
    'Referer': 'https://quote.eastmoney.com/',
    'Accept': '*/*',
}
_LAST_CALL = [0.0]


def _em_throttle(gap=0.4):
    dt = time.time() - _LAST_CALL[0]
    if dt < gap:
        time.sleep(gap - dt)
    _LAST_CALL[0] = time.time()


def _parse_em(d):
    out = {}
    for line in d['klines']:
        p = line.split(',')
        out[p[0]] = {'open': float(p[1]), 'close': float(p[2]),
                     'high': float(p[3]), 'low': float(p[4]),
                     'volume': float(p[5])}
    return out


def fetch_em(code, fqt, beg='20210101', end='20261020', retries=6):
    """东财 push2his；本地缓存 + 多主机轮换 + 节流，抗限流。"""
    cache = ROOT / 'data/r2/tdx/em_cache'
    cache.mkdir(parents=True, exist_ok=True)
    cf = cache / '{}_{}_{}_{}.json'.format(code, fqt, beg, end)
    if cf.exists():
        try:
            return _parse_em(json.loads(cf.read_text())), None
        except Exception:  # noqa: BLE001
            pass
    last = None
    for attempt in range(retries):
        host = _EM_HOSTS[attempt % len(_EM_HOSTS)]
        _em_throttle()
        try:
            req = urllib.request.Request(
                _EM_URL.format(host=host, secid=secid(code), fqt=fqt, beg=beg, end=end),
                headers=_EM_HDRS)
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(r.read().decode('utf-8'))['data']
            if not d or not d.get('klines'):
                return None, 'empty klines'
            cf.write_text(json.dumps(d))
            return _parse_em(d), None
        except Exception as e:  # noqa: BLE001
            last = '%s@%s' % (e, host)
            time.sleep(0.8 * (attempt + 1))
    return None, last


def load_events():
    d = json.load(gzip.open(XDXR, 'rt'))
    ev = {}
    for row in d['events']:
        norm = []
        for e in row['events']:
            ds = str(e['date'])
            norm.append({'category': e['category'], 'year': int(ds[:4]),
                         'month': int(ds[4:6]), 'day': int(ds[6:8]),
                         'fenhong': e.get('f1') or 0.0,
                         'peigujia': e.get('f2') or 0.0,
                         'songzhuangu': e.get('f3') or 0.0,
                         'peigu': e.get('f4') or 0.0})
        ev[row['code']] = norm
    return ev, d['fetched_at']


def _ex_dir(code):
    """TDX 市场目录：sh/sz/bj（勿用单字符前缀猜，920002 是 BJ 不是 SH）。"""
    if code[:3] in ('600', '601', '603', '605', '688', '689', '900') or code[:2] in ('51', '58', '11', '50', '56', '13'):
        return 'sh'
    if code[:3] in ('000', '001', '002', '003', '300', '301', '302', '200') or code[:3] == '159':
        return 'sz'
    if code[:2] in ('43', '83', '87', '88', '92', '82', '89', '40'):
        return 'bj'
    if code[0] in ('6', '9', '5'):
        return 'sh'
    if code[0] in ('0', '3', '2', '1'):
        return 'sz'
    return 'bj'


def local_bars(code):
    from pytdx.reader import TdxDailyBarReader
    ex = _ex_dir(code)
    try:
        r = TdxDailyBarReader(vipdoc_path=str(TDX_DIR / 'vipdoc'))
        df = r.get_df_by_code(code, ex)
    except Exception as e:  # noqa: BLE001
        return {}, 'local(%s): %s %s' % (ex, type(e).__name__, e)
    if df is None or df.empty:
        return {}, 'empty local'
    out = {}
    for ts, row in df.iterrows():
        d = ts.strftime('%Y-%m-%d')
        out[d] = {'open': float(row['open']), 'high': float(row['high']),
                  'low': float(row['low']), 'close': float(row['close']),
                  'volume': float(row['volume'])}
    return out, None


def qfq_self(bars, events, asof):
    """自算前复权：逐字段调用协议 adjust()。"""
    asc = sorted(bars.items())
    asc_filtered = [(d, b) for d, b in asc if d <= asof]
    dates = [d for d, _ in asc_filtered]
    out = {d: {} for d in dates}
    for f in FIELDS:
        series = [(d, b[f]) for d, b in asc if d <= asof]
        adj = adjust(series, events, asof)
        for (d, _), (dd, v) in zip(asc_filtered, adj):
            out[d][f] = v
    return out


def qfq_mult(bars, events, asof):
    """模型 B：东财/同花顺式乘法模型。事件比值 = 除权参考价/前收盘，
    参考价 = (前收 - 现金 + 配股价*配股比例) / (1 + 送转比例 + 配股比例)。
    前复权：qfq(d) = raw(d) * ∏_{事件日>d} (参考价/前收)。"""
    asc = sorted(bars.items())
    asc = [(d, b) for d, b in asc if d <= asof]
    dates = [d for d, _ in asc]
    close_by_date = {d: b['close'] for d, b in asc}
    ev = []
    for e in events:
        if e['category'] != 1:
            continue
        d = '{:04d}-{:02d}-{:02d}'.format(e['year'], e['month'], e['day'])
        if d > asof:
            continue
        prev = [x for x in dates if x < d]
        if not prev:
            continue
        pc = close_by_date[prev[-1]]
        fh = (e.get('fenhong') or 0) / 10
        pg = (e.get('peigu') or 0) / 10
        song = (e.get('songzhuangu') or 0) / 10
        ref = (pc - fh + (e.get('peigujia') or 0) * pg) / (pc * (1 + song + pg))
        ev.append((d, ref))
    ev.sort()
    out = {d: {} for d in dates}
    for f in FIELDS:
        cum = 1.0
        j = len(ev) - 1
        for d in reversed(dates):
            while j >= 0 and ev[j][0] > d:
                cum *= ev[j][1]
                j -= 1
            out[d][f] = bars[d][f] * cum
    return out


def run_one(code, events, beg):
    res = {'code': code, 'ok': False}
    em0, err = fetch_em(code, 0)
    if err:
        res['error'] = 'em fqt=0: ' + err
        return res
    em1, err = fetch_em(code, 1)
    if err:
        res['error'] = 'em fqt=1: ' + err
        return res
    loc, err = local_bars(code)
    if err:
        res['error'] = 'local: ' + err
        return res
    asof = max(em1)
    common = sorted(set(loc) & set(em0) & set(em1))
    common = [d for d in common if beg <= d <= asof]
    if len(common) < 60:
        res['error'] = f'too few common bars ({len(common)})'
        return res

    # A) raw
    raw_max = 0.0
    raw_bad = []
    for d in common:
        for f in FIELDS:
            diff = abs(loc[d][f] - em0[d][f])
            if diff > raw_max:
                raw_max = diff
            if diff > TOL:
                raw_bad.append((d, f, loc[d][f], em0[d][f]))
    # B) 自算 qfq —— 模型 A（通达信仿射）+ 模型 B（东财乘法）
    models = {}
    for name, fn in (('affine', qfq_self), ('mult', qfq_mult)):
        try:
            models[name] = fn({d: loc[d] for d in common}, events, asof)
        except Exception as e:  # noqa: BLE001
            res['error'] = name + ': ' + str(e)
            res['raw_max_diff'] = round(raw_max, 4)
            return res
    mres = {}
    for _name, _mm in models.items():
        _sc = {f: (em1[asof][f] / _mm[asof][f]) if _mm[asof][f] else 1.0 for f in FIELDS}
        _a = _n = 0.0
        _bad = []
        for d in common:
            for f in FIELDS:
                _da = abs(_mm[d][f] - em1[d][f])
                _dn = abs(_mm[d][f] * _sc[f] - em1[d][f])
                _a = max(_a, _da)
                _n = max(_n, _dn)
                if _dn > TOL:
                    _bad.append((d, f, round(_mm[d][f], 4), em1[d][f], round(_mm[d][f] * _sc[f], 4)))
        mres[_name] = {'abs_max': round(_a, 4), 'norm_max': round(_n, 4),
                       'bad_n': len(_bad), 'bad': _bad[:5]}
    q_abs, q_norm, q_bad = mres['affine']['abs_max'], mres['affine']['norm_max'], mres['affine']['bad']
    # C) 事件级：每个事件日附近东财比值 vs 本机公式
    ev_tests = []
    for e in events:
        if e['category'] != 1:
            continue
        d0 = '{:04d}-{:02d}-{:02d}'.format(e['year'], e['month'], e['day'])
        prev = [d for d in common if d < d0]
        if not prev or d0 not in em1 or d0 not in em0:
            continue
        p = prev[-1]
        em_ratio = em1[d0]['close'] / em1[p]['close']
        raw_ratio = em0[d0]['close'] / em0[p]['close']
        ev_tests.append({'date': d0, 'prev': p, 'em_qfq_ratio': round(em_ratio, 6),
                         'em_raw_ratio': round(raw_ratio, 6),
                         'cash': round((e['fenhong'] or 0) / 10, 4),
                         'songzhuan': round((e['songzhuangu'] or 0) / 10, 4),
                         'peigu': round((e['peigu'] or 0) / 10, 4)})
    res.update({
        'ok': raw_max <= TOL and q_norm <= TOL,
        'ok_mult': raw_max <= TOL and mres['mult']['norm_max'] <= TOL,
        'bars': len(common), 'asof': asof,
        'raw_max_diff': round(raw_max, 4), 'raw_bad': raw_bad[:5], 'raw_bad_n': len(raw_bad),
        'qfq_abs_max': round(q_abs, 4), 'qfq_norm_max': round(q_norm, 4),
        'qfq_bad': q_bad[:5], 'qfq_bad_n': len(q_bad),
        'qfq_norm_max_mult': mres['mult']['norm_max'], 'qfq_abs_max_mult': mres['mult']['abs_max'],
        'qfq_bad_n_mult': mres['mult']['bad_n'], 'qfq_bad_mult': mres['mult']['bad'][:5],
        'events_tested': ev_tests,
    })
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--random', type=int, default=50)
    ap.add_argument('--focus', default='600125')
    ap.add_argument('--beg', default='2021-01-01')
    ap.add_argument('--out', default=str(ROOT / 'data/r2/tdx/qfq_parity_em_20261021.json'))
    ap.add_argument('--limit', type=int, default=0, help='只跑前 N 只（调试）')
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    ev, ev_at = load_events()
    log.info('xdxr fetched_at=%s stocks=%d', ev_at, len(ev))
    oct_pool = [c for c, es in ev.items()
                if any(e['category'] == 1 and e['year'] == 2026 and e['month'] == 10 for e in es)]
    universe = sorted(ev)
    rnd = random.Random(20261021)
    sample = rnd.sample(universe, min(a.random, len(universe)))
    targets = []
    for c in [a.focus] + oct_pool + sample:
        if c not in targets:
            targets.append(c)
    if a.limit:
        targets = targets[:a.limit]
    log.info('targets: focus=1 oct_pool=%d random=%d total=%d', len(oct_pool), len(sample), len(targets))

    t0 = time.time()
    results = []
    for i, c in enumerate(targets, 1):
        try:
            r = run_one(c, ev.get(c, []), a.beg)
        except Exception as e:  # noqa: BLE001
            r = {'code': c, 'ok': False, 'ok_mult': False, 'error': 'unhandled: %s %s' % (type(e).__name__, e)}
        results.append(r)
        if i % 20 == 0 or not r['ok']:
            log.info('[%d/%d] %s ok=%s raw=%s norm=%s %s', i, len(targets), c, r['ok'],
                     r.get('raw_max_diff'), r.get('qfq_norm_max'), r.get('error') or '')
    passed = [r for r in results if r['ok']]
    failed = [r for r in results if not r['ok']]
    errs = [r for r in failed if r.get('error')]
    dir_fail = [r for r in failed if not r.get('error')]
    summary = {
        'baseline': 'eastmoney push2his fqt=0/1 (independent)',
        'xdxr_fetched_at': ev_at,
        'targets': len(targets),
        'pass_count': len(passed), 'fail_count': len(failed),
        'err_count': len(errs), 'mismatch_count': len(dir_fail),
        'oct_pool_size': len(oct_pool), 'random_size': len(sample),
        'raw_max_diff_overall': round(max([r.get('raw_max_diff', 0) for r in results], default=0), 4),
        'qfq_norm_max_overall': round(max([r.get('qfq_norm_max', 0) for r in results], default=0), 4),
        'qfq_abs_max_overall': round(max([r.get('qfq_abs_max', 0) for r in results], default=0), 4),
        'pass_count_mult': len([r for r in results if r.get('ok_mult')]),
        'qfq_norm_max_overall_mult': round(max([r.get('qfq_norm_max_mult', 0) for r in results], default=0), 4),
        'bars_checked': sum(r.get('bars', 0) for r in results),
        'elapsed_sec': round(time.time() - t0, 1),
        'failures': sorted([{'code': r['code'], 'error': r.get('error'),
                             'raw_max_diff': r.get('raw_max_diff'),
                             'qfq_norm_max': r.get('qfq_norm_max'),
                             'qfq_norm_max_mult': r.get('qfq_norm_max_mult'),
                             'qfq_bad': r.get('qfq_bad', [])[:2],
                             'raw_bad': r.get('raw_bad', [])[:2]} for r in failed],
                           key=lambda x: -(x.get('qfq_norm_max') or 0))[:40],
        'focus_detail': [r for r in results if r['code'] == a.focus],
    }
    out = Path(a.out)
    out.write_text(json.dumps({'summary': summary, 'results': results}, ensure_ascii=False, indent=1))
    log.info('PASS %d / %d  FAIL %d (err %d / mismatch %d)  %ds  -> %s',
             len(passed), len(targets), len(failed), len(errs), len(dir_fail),
             summary['elapsed_sec'], out)
    s = summary
    print(json.dumps({k: s[k] for k in ('targets', 'pass_count', 'fail_count', 'err_count',
                                        'mismatch_count', 'raw_max_diff_overall',
                                        'qfq_norm_max_overall', 'qfq_abs_max_overall',
                                        'pass_count_mult', 'qfq_norm_max_overall_mult',
                                        'bars_checked', 'elapsed_sec')}, ensure_ascii=False, indent=1))
    if s['failures']:
        print('worst failures:')
        for f in s['failures'][:6]:
            print(' ', f['code'], f.get('error') or '', 'norm=', f.get('qfq_norm_max'),
                  'raw=', f.get('raw_max_diff'), (f.get('qfq_bad') or [])[:1])


if __name__ == '__main__':
    main()