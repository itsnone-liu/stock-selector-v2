#!/usr/bin/env python3
"""qfq 自算对拍 —— 新浪复权因子基准（1 请求/票，独立第三方）

用途：验证 src/r2/tdx_client.py 的 xdxr 事件表 + adjust() 复权模型
基准：finance.sina.com.cn/realstock/company/{mk}{code}/qfq.js 逐事件复权因子（F 为前复权除数：qfq=raw/F）
产物：data/r2/tdx/qfq_parity_sina_YYYYMMDD.json

用法：.venv/bin/python scripts/tdx_qfq_parity_sina.py --n 150 [--delay 0.15]
"""
import argparse
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location('_p', str(ROOT / 'scripts' / 'tdx_qfq_parity_em.py'))
_m = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_m)

RDIR = ROOT / 'data/r2/tdx'
CACHE = RDIR / 'sina_qfq'
UA = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0 Safari/537.36',
      'Referer': 'https://finance.sina.com.cn/'}
TOL_REL = 0.003          # 价位级相对容差 0.3%（复权模型口径差 ~0.1%）
TOL_EV = 1e-4            # 事件级比值容差


def mk_of(code):
    if code[:3] in ('600', '601', '603', '605', '688', '689', '900') or code[0] in '69':
        return 'sh'
    if code[:2] in ('43', '83', '87', '88', '92'):
        return 'bj'
    return 'sz'


def sina_factors(code, delay=0.15, retries=3):
    """新浪前复权因子 {日期: 累计除数}；带磁盘缓存。"""
    CACHE.mkdir(parents=True, exist_ok=True)
    cf = CACHE / '{}.json'.format(code)
    if cf.exists():
        try:
            return {k: float(v) for k, v in json.loads(cf.read_text()).items()}, None
        except Exception:  # noqa: BLE001
            pass
    url = 'https://finance.sina.com.cn/realstock/company/%s%s/qfq.js' % (mk_of(code), code)
    last = None
    for i in range(retries):
        time.sleep(delay * (i + 1))
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=12) as r:
                t = r.read().decode('gbk', 'ignore')
            j = json.loads(t[t.index('{'):t.rindex('}') + 1])
            out = {x['d']: float(x['f']) for x in j['data']}
            if not out:
                return {}, 'empty'
            cf.write_text(json.dumps(out))
            return out, None
        except Exception as e:  # noqa: BLE001
            last = '%s: %s' % (type(e).__name__, e)
    return None, last


def f_of(fac, dates):
    def f(d):
        j = -1
        for i, x in enumerate(dates):
            if x <= d:
                j = i
            else:
                break
        return fac[dates[j]] if j >= 0 else None
    return f


def run_one(code, evs, delay):
    res = {'code': code, 'ok': False}
    fac, err = sina_factors(code, delay)
    if err or not fac:
        res['error'] = 'sina: %s' % err
        return res
    loc, lerr = _m.local_bars(code)
    if lerr or not loc:
        res['error'] = 'local: %s' % lerr
        return res
    dates = sorted(fac)
    F = f_of(fac, dates)
    asof = max(loc)
    common = [d for d in sorted(loc) if d >= dates[0] and d <= asof]
    if len(common) < 100:
        res['error'] = 'too few common bars %d' % len(common)
        return res
    base = {d: loc[d] for d in common}
    A = _m.qfq_self(dict(base), evs, asof)
    B = _m.qfq_mult(dict(base), evs, asof)
    # 事件级：新浪 F 步比 vs 本机乘法预测比
    ev_rows, ev_bad = [], []
    for i in range(1, len(dates)):
        d, dprev = dates[i], dates[i - 1]
        step = fac[dprev] / fac[d]
        prev = [x for x in common if x < d]
        if not prev:
            continue
        pc = loc[prev[-1]]['close']
        row = [e for e in evs
               if '%04d-%02d-%02d' % (e['year'], e['month'], e['day']) == d and e['category'] == 1]
        if not row:
            ev_bad.append((d, 'no local event', round(step, 6), None))
            continue
        e = row[0]
        fh = (e.get('fenhong') or 0) / 10
        song = (e.get('songzhuangu') or 0) / 10
        pg = (e.get('peigu') or 0) / 10
        pj = e.get('peigujia') or 0
        pred = (pc * (1 + song + pg)) / (pc - fh + pj * pg)
        if abs(pred / step - 1) > TOL_EV:
            ev_bad.append((d, 'ratio %.6f vs %.6f' % (pred, step), round(pc, 2),
                           round((pred / step - 1) * 100, 4)))
        ev_rows.append(d)
    # 价位级（两模型都锚定 asof）
    relA = relB = 0.0
    diffA = diffB = 0.0
    for d in common:
        s = loc[d]['close'] / F(d)
        if not s:
            continue
        for name, ser in (('A', A), ('B', B)):
            v = ser[d]['close']
            r = abs(v / s - 1)
            if name == 'A':
                relA = max(relA, r); diffA = max(diffA, abs(v - s))
            else:
                relB = max(relB, r); diffB = max(diffB, abs(v - s))
    res.update({
        'ok': relA <= TOL_REL and not ev_bad,
        'bars': len(common), 'events_checked': len(ev_rows), 'ev_bad_n': len(ev_bad),
        'ev_bad': ev_bad[:4],
        'rel_max_A': round(relA * 100, 4), 'rel_max_B': round(relB * 100, 4),
        'yuan_max_A': round(diffA, 4), 'yuan_max_B': round(diffB, 4),
        'asof': asof,
    })
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=150)
    ap.add_argument('--delay', type=float, default=0.15)
    ap.add_argument('--out', default='')
    a = ap.parse_args()
    ev, at = _m.load_events()
    oct_pool = [c for c, es in ev.items()
                if any(e['category'] == 1 and e['year'] == 2026 and e['month'] == 10 for e in es)]
    rnd = random.Random(20261021)
    targets = ['600125'] + oct_pool + rnd.sample(sorted(ev), 60)
    targets = list(dict.fromkeys(targets))[:a.n]
    print('xdxr_at=%s 事件池=%d  target=%d  delay=%.2f' % (at, len(oct_pool), len(targets), a.delay))
    t0 = time.time()
    out = []
    for i, c in enumerate(targets, 1):
        try:
            r = run_one(c, ev.get(c, []), a.delay)
        except Exception as e:  # noqa: BLE001
            r = {'code': c, 'ok': False, 'error': 'unhandled %s: %s' % (type(e).__name__, e)}
        out.append(r)
        if i % 25 == 0 or not r.get('ok'):
            print('[%d/%d] %s ok=%s relA=%s%% ev_bad=%s %s' % (
                i, len(targets), c, r.get('ok'), r.get('rel_max_A'), r.get('ev_bad_n'),
                r.get('error') or ''))
    ok = [r for r in out if r.get('ok')]
    errs = [r for r in out if r.get('error')]
    mism = [r for r in out if not r.get('ok') and not r.get('error')]
    worst = sorted([r for r in out if r.get('rel_max_A') is not None],
                   key=lambda x: -x['rel_max_A'])[:12]
    summary = {
        'baseline': 'sina qfq.js per-event factors (independent)',
        'xdxr_fetched_at': at, 'targets': len(targets),
        'pass': len(ok), 'mismatch': len(mism), 'error': len(errs),
        'tol_rel_pct': TOL_REL * 100,
        'rel_max_A_overall_pct': max([r.get('rel_max_A', 0) for r in out], default=0),
        'rel_max_B_overall_pct': max([r.get('rel_max_B', 0) for r in out], default=0),
        'events_checked': sum(r.get('events_checked', 0) for r in out),
        'event_bad_total': sum(r.get('ev_bad_n', 0) for r in out),
        'bars_checked': sum(r.get('bars', 0) for r in out),
        'elapsed_sec': round(time.time() - t0, 1),
        'worst': [{'code': r['code'], 'relA': r['rel_max_A'], 'relB': r['rel_max_B'],
                   'yuanA': r['yuan_max_A'], 'ev_bad': r.get('ev_bad', [])[:1]} for r in worst],
        'fail_detail': [{'code': r['code'], 'error': r.get('error'), 'ev_bad': r.get('ev_bad', [])[:2],
                         'relA': r.get('rel_max_A')} for r in (mism + errs)][:40],
    }
    outfile = Path(a.out) if a.out else RDIR / 'qfq_parity_sina_20261021.json'
    outfile.write_text(json.dumps({'summary': summary, 'results': out}, ensure_ascii=False, indent=1))
    print(json.dumps({k: summary[k] for k in ('targets', 'pass', 'mismatch', 'error', 'tol_rel_pct',
                                             'rel_max_A_overall_pct', 'rel_max_B_overall_pct',
                                             'events_checked', 'event_bad_total', 'bars_checked',
                                             'elapsed_sec')}, ensure_ascii=False, indent=1))
    print('-> %s' % outfile)
    for w in summary['worst']:
        print('  worst', w['code'], 'relA=%s%% relB=%s%% yuanA=%s' % (w['relA'], w['relB'], w['yuanA']),
              (w['ev_bad'] or [])[:1])


if __name__ == '__main__':
    main()
