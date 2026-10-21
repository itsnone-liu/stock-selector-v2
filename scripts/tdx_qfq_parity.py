#!/usr/bin/env python3
"""qfq 自算对拍：TDX 本地裸价 + TDX 除权事件 → adjust() 自算前复权
对照存量腾讯 qfqkline 档案（data/cd/daily_fullmarket/*.json.gz）。

口径：
- 每只票 asof = 该档案文件最后一根 bar 日期（腾讯 qfq 以前复权锚定 asof）
- 事件只用 date <= asof 的 cat1（adjust 内部已过滤）
- 逐 bar 逐字段比 open/high/low/close，门槛 |diff| <= 0.01
- 额外报 raw 裸价一致性（TDX .day vs 腾讯 unadj）

用法: .venv/bin/python scripts/tdx_qfq_parity.py [--limit N] [--random N] [--out PATH]
"""
import argparse
import gzip
import json
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from pytdx.reader import TdxDailyBarReader

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
from r2.tdx_client import adjust  # noqa: E402

log = logging.getLogger('qfq_parity')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

TDX_DIR = '/root/tdx_data'
ARCHIVE = ROOT / 'data' / 'cd' / 'daily_fullmarket'
WINDOW_START = '2021-01-01'
TOL = 0.01


def load_events(path):
    with gzip.open(path, 'rt', encoding='utf8') as f:
        data = json.load(f)
    ev = {}
    for r in data['events']:
        mkt = {0: 'sz', 1: 'sh', 2: 'bj'}[r['market']]
        out = []
        for e in r['events']:
            d = e['date']
            out.append(dict(year=d // 10000, month=d // 100 % 100, day=d % 100, category=e['category'],
                            fenhong=e['f1'], peigujia=e['f2'], songzhuangu=e['f3'], peigu=e['f4']))
        ev[r['code']] = out
    return ev


def local_bars(reader, code, base):
    try:
        ex = 'sh' if code.startswith(('6', '9')) else ('sz' if code.startswith(('0', '3', '2')) else 'bj')
        df = reader.get_df_by_code(code, ex)
    except Exception as e:
        return None, str(e)
    if df is None or df.empty:
        return None, 'empty'
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep='last')].sort_index()
    if base:
        df = df[df.index <= base]
    if df.empty:
        return None, 'no bars in window'
    bars = []
    for ts, row in df.iterrows():
        bars.append(dict(date=ts.strftime('%Y-%m-%d'), open=float(row['open']), high=float(row['high']),
                         low=float(row['low']), close=float(row['close']), volume=float(row['volume'])))
    return bars, None


def compare(code, reader, events, archive_path):
    with gzip.open(archive_path, 'rt', encoding='utf8') as f:
        arch = json.load(f)
    unadj = {r[0]: [float(x) for x in r[1:5]] for r in arch['unadj']}
    qfq = {r[0]: [float(x) for x in r[1:5]] for r in arch['qfq']}
    asof = max(qfq)
    bars, err = local_bars(reader, code, asof)
    if err:
        return dict(code=code, ok=False, error=err, asof=asof)
    ev = events.get(code)
    if ev is None:
        return dict(code=code, ok=False, error='no xdxr events', asof=asof)
    # raw 对拍（只用两边都有、且在窗口内的日期）
    raw_diffs = []
    common = [b['date'] for b in bars if b['date'] in unadj and b['date'] >= WINDOW_START]
    for b in bars:
        if b['date'] not in unadj or b['date'] < WINDOW_START:
            continue
        for i, f in enumerate(('open', 'high', 'low', 'close')):
            raw_diffs.append(abs(b[f] - unadj[b['date']][i]))
    # qfq 自算
    try:
        computed = {}
        for f in ('open', 'high', 'low', 'close'):
            computed[f] = dict(adjust([(b['date'], b[f]) for b in bars], ev, asof))
    except ValueError as e:
        return dict(code=code, ok=False, error='adjust fail-closed: ' + str(e), asof=asof,
                    raw_max_diff=max(raw_diffs) if raw_diffs else None)
    qfq_diffs = []
    worst = None
    for b in bars:
        d = b['date']
        if d not in qfq or d < WINDOW_START:
            continue
        for i, f in enumerate(('open', 'high', 'low', 'close')):
            diff = abs(round(computed[f][d], 3) - qfq[d][i])
            qfq_diffs.append(diff)
            if worst is None or diff > worst[0]:
                worst = (diff, d, f, round(computed[f][d], 3), qfq[d][i], b[f])
    return dict(code=code, asof=asof, bars=len(bars), common_bars=len(common),
                raw_max_diff=max(raw_diffs) if raw_diffs else None,
                qfq_max_diff=max(qfq_diffs) if qfq_diffs else None,
                qfq_bars=len(qfq_diffs) // 4, worst=worst,
                ok=bool(qfq_diffs) and max(qfq_diffs) <= TOL and (not raw_diffs or max(raw_diffs) <= 0.011))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xdxr', default=None)
    ap.add_argument('--universe', default=None, help='对拍池文件（每行 code）；缺省=全市场前 N')
    ap.add_argument('--limit', type=int, default=0, help='按 -% 抽取比例上限（0=全部）')
    ap.add_argument('--random', type=int, default=50, help='随机抽样只数')
    ap.add_argument('--seed', type=int, default=20261021)
    ap.add_argument('--focus', default='600125', help='重点票（逗号分隔）')
    ap.add_argument('--october', action='store_true', default=True, help='含 2026-10 除权池')
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    xdxr_path = Path(args.xdxr) if args.xdxr else sorted((ROOT / 'data' / 'r2' / 'tdx').glob('xdxr_fullmarket_*.json.gz'))[-1]
    log.info('xdxr=%s', xdxr_path)
    events = load_events(xdxr_path)
    log.info('events loaded for %d stocks', len(events))

    codes_all = sorted(p.name.split('.')[0] for p in ARCHIVE.glob('*.json.gz') if not p.name.startswith('_'))
    # 2026-10 cat1 除权池（最近除权，最考验因子链）
    oct_pool = []
    for code, evs in events.items():
        for e in evs:
            d = '{:04d}-{:02d}-{:02d}'.format(e['year'], e['month'], e['day'])
            if e['category'] == 1 and '2026-10-01' <= d <= '2026-10-21':
                oct_pool.append(code)
                break
    oct_pool = sorted(set(c for c in oct_pool if (ARCHIVE / (c + '.json.gz')).exists()))
    focus = [c.strip() for c in args.focus.split(',') if c.strip()]
    rnd = random.Random(args.seed)
    rand = rnd.sample(codes_all, min(args.random, len(codes_all)))
    targets = []
    for group in (focus, oct_pool, rand):
        for c in group:
            if c not in targets:
                targets.append(c)
    log.info('targets: focus=%s oct_pool=%d random=%d total=%d', focus, len(oct_pool), len(rand), len(targets))

    reader = TdxDailyBarReader(vipdoc_path=str(Path(TDX_DIR) / 'vipdoc'))
    t0 = time.time()
    results = []
    for i, c in enumerate(targets, 1):
        p = ARCHIVE / (c + '.json.gz')
        if not p.exists():
            results.append(dict(code=c, ok=False, error='no archive'))
            continue
        try:
            results.append(compare(c, reader, events, p))
        except Exception as e:
            results.append(dict(code=c, ok=False, error=type(e).__name__ + ': ' + str(e)))
        if i % 50 == 0:
            log.info('progress %d/%d elapsed=%.1fs', i, len(targets), time.time() - t0)

    ok = [r for r in results if r.get('ok')]
    bad = [r for r in results if not r.get('ok')]
    qfq_d = [r['qfq_max_diff'] for r in ok if r.get('qfq_max_diff') is not None]
    raw_d = [r['raw_max_diff'] for r in ok if r.get('raw_max_diff') is not None]
    summary = dict(
        generated_at=datetime.now().strftime('%Y-%m-%dT%H:%M:%S+08:00'),
        xdxr_source=str(xdxr_path.name),
        targets=len(targets), pass_count=len(ok), fail_count=len(bad),
        oct_pool_size=len(oct_pool), random_size=len(rand), focus=focus,
        qfq_max_diff_overall=max(qfq_d) if qfq_d else None,
        qfq_bars_checked=sum(r.get('qfq_bars', 0) for r in ok),
        raw_max_diff_overall=max(raw_d) if raw_d else None,
        tolerance=TOL, elapsed_sec=round(time.time() - t0, 1),
        failures=bad[:50],
        worst_cases=sorted([r for r in ok if r.get('qfq_max_diff')],
                           key=lambda r: -r['qfq_max_diff'])[:15],
    )
    out = Path(args.out) if args.out else ROOT / 'data' / 'r2' / 'tdx' / f"qfq_parity_{datetime.now():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dict(summary=summary, results=results), ensure_ascii=False, indent=2, allow_nan=False))
    log.info('SUMMARY pass=%d/%d qfq_max=%.4f raw_max=%.4f bars=%d elapsed=%.1fs -> %s',
             len(ok), len(targets), summary['qfq_max_diff_overall'] or -1,
             summary['raw_max_diff_overall'] or -1, summary['qfq_bars_checked'], summary['elapsed_sec'], out)
    if bad:
        log.warning('FAILURES: %s', json.dumps(bad[:10], ensure_ascii=False))


if __name__ == '__main__':
    main()