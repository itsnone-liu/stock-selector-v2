#!/usr/bin/env python3
"""CD-1A-DATA-1 v2: full-market daily acquisition via Tencent fqkline (EM throttled).
Segments of 640 rows, raw + qfq, resumable per-stock gz.
Declared GAPs (source cannot provide): amount, turnover_rate, free_float_market_cap,
st_flag — recorded in preregistration; EM backfill may be attempted after throttle clears."""
import json, gzip, os, sys, time, datetime as dt
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'cd' / 'daily_fullmarket'
OUT.mkdir(parents=True, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0'}
URL = 'http://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
WIN_START = '2021-01-01'

def tx_code(c):
    if c.startswith(('6', '9')): return 'sh' + c
    return 'sz' + c

def fetch_segments(sess, full, fq):
    """page backward from window end until WIN_START covered; returns rows oldest-first"""
    field = (fq or 'day')
    seg_end = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    collected = {}
    for _ in range(12):  # safety cap
        for attempt in range(4):
            try:
                r = sess.get(URL, params={'param': f'{full},day,{WIN_START},{seg_end},640,{fq}'}, timeout=25, headers=UA)
                j = r.json()['data'][full]
                rows = j.get('qfqday') if fq == 'qfq' else j.get('day')
                if fq == 'qfq' and rows is None:  # some stocks return only day
                    rows = j.get('day')
                break
            except Exception:
                if attempt == 3: return None
                time.sleep(2 * (attempt + 1))
        if not rows: break
        for row in rows:
            collected[row[0]] = row
        earliest = rows[0][0]
        if earliest <= WIN_START or len(rows) < 640: break
        y, m, d = map(int, earliest.split('-'))
        seg_end = (dt.date(y, m, d) - dt.timedelta(days=1)).isoformat()
        time.sleep(0.15)
    return [collected[k] for k in sorted(collected)] if collected else None

def fetch_one(sess, code):
    full = tx_code(code)
    raw = fetch_segments(sess, full, '')
    if raw is None or not raw: return None, 'no_data'
    qfq = fetch_segments(sess, full, 'qfq')
    if qfq is None or not qfq: return None, 'no_qfq'
    # align on dates present in both
    rmap = {r[0]: r for r in raw}; qmap = {r[0]: r for r in qfq}
    dates = sorted(set(rmap) & set(qmap))
    if not dates: return None, 'no_overlap'
    # adjust factor from qfq/raw close ratio, anchored at latest=1
    anchor = float(qmap[dates[-1]][2]) / float(rmap[dates[-1]][2]) if float(rmap[dates[-1]][2]) else 1.0
    factors = []
    for d in dates:
        rc = float(rmap[d][2]); qc = float(qmap[d][2])
        factors.append(round(qc / rc / anchor, 6) if rc else 1.0)
    rec = {'code': code, 'source': 'tencent_fqkline', 'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'window_start': WIN_START,
           'declared_gaps': ['amount', 'turnover_rate', 'free_float_market_cap', 'st_flag'],
           'dates': dates,
           'unadj': [rmap[d][:6] for d in dates],      # [d,o,c,h,l,volume]
           'qfq': [qmap[d][:6] for d in dates],
           'adjust_factor_model_derived': factors}
    (OUT / f'{code}.json.gz').write_bytes(gzip.compress(json.dumps(rec, separators=(',', ':')).encode(), 6))
    return len(dates), 'ok'

def main():
    uni = json.load(open(OUT / '_universe.json'))['universe']
    print(f'universe: {len(uni)}', flush=True)
    sess = requests.Session()
    done = fail = 0; failures = []
    t0 = time.time()
    for i, code in enumerate(uni):
        if (OUT / f'{code}.json.gz').exists():
            done += 1; continue
        n, status = fetch_one(sess, code)
        if status == 'ok': done += 1
        else: fail += 1; failures.append((code, status))
        time.sleep(0.12)
        if (i + 1) % 100 == 0:
            print(f'[{i+1}/{len(uni)}] done={done} fail={fail} elapsed={int(time.time()-t0)}s', flush=True)
    json.dump({'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'universe_n': len(uni),
               'ok': done, 'fail': fail, 'failures': failures[:300]},
              open(OUT / '_acquisition_log.json', 'w'), indent=1)
    print(f'FINAL done={done} fail={fail} head={failures[:10]}', flush=True)

if __name__ == '__main__':
    main()
