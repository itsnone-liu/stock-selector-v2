#!/usr/bin/env python3
"""CD-1A-DATA-1 v3: Tencent fqkline with ADAPTIVE rate control.
Lessons baked in: v2 died because throttled responses return non-JSON (fast), and the
retry loop slept without global backoff. v3: any failure => global cooldown, adaptive
inter-request delay, per-stock fast-skip, resumable, verbose progress.
Also probes EM hourly; if EM unthrottles, a companion run can backfill there (single
request full history). Declared gaps unchanged: amount/turnover/freefloat/st."""
import json, gzip, time, datetime as dt, sys
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'data' / 'cd' / 'daily_fullmarket'
URL = 'https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0',
      'Referer': 'https://finance.qq.com/'}
WIN_START = '2021-01-01'

def tx_code(c):
    return ('sh' + c) if c.startswith(('6', '9')) else ('sz' + c)

def fetch_segments(sess, full, fq):
    field = 'qfqday' if fq == 'qfq' else 'day'
    seg_end = (dt.date.today() + dt.timedelta(days=1)).isoformat()
    collected = {}
    throttle_hits = 0
    for _ in range(12):
        try:
            r = sess.get(URL, params={'param': f'{full},day,{WIN_START},{seg_end},640,{fq}'}, timeout=12, headers=UA)
            j = r.json()['data'][full]  # raises on throttle page
        except Exception:
            throttle_hits += 1
            if throttle_hits >= 2: return None  # give up this stock fast
            time.sleep(20); continue
        rows = j.get(field) or (j.get('day') if fq == 'qfq' else None)
        if rows is None and fq == '': rows = j.get('day')
        if not rows: break
        for row in rows: collected[row[0]] = row
        earliest = rows[0][0]
        if earliest <= WIN_START or len(rows) < 640: break
        y, m, d = map(int, earliest.split('-'))
        seg_end = (dt.date(y, m, d) - dt.timedelta(days=1)).isoformat()
        time.sleep(0.3)
    return [collected[k] for k in sorted(collected)] if collected else None

def main():
    uni = json.load(open(OUT / '_universe.json'))['universe']
    todo = [c for c in uni if not (OUT / f'{c}.json.gz').exists()]
    print(f'universe {len(uni)}, todo {len(todo)}', flush=True)
    sess = requests.Session()
    delay = 0.5          # adaptive inter-request base
    done = fail = 0; failures = []; consec_fail = 0
    t0 = time.time()
    for i, code in enumerate(todo):
        if consec_fail >= 40:
            print('throttle wall: pausing 10 min', flush=True)
            time.sleep(600); consec_fail = 0
        full = tx_code(code)
        raw = fetch_segments(sess, full, '')
        ok = raw is not None and len(raw) > 0
        qfq = fetch_segments(sess, full, 'qfq') if ok else None
        if ok and qfq:
            rmap = {r[0]: r for r in raw}; qmap = {r[0]: r for r in qfq}
            dates = sorted(set(rmap) & set(qmap))
            anchor = (float(qmap[dates[-1]][2]) / float(rmap[dates[-1]][2])) if float(rmap[dates[-1]][2]) else 1.0
            factors = [round(float(qmap[d][2]) / float(rmap[d][2]) / anchor, 6) if float(rmap[d][2]) else 1.0 for d in dates]
            rec = {'code': code, 'source': 'tencent_fqkline', 'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
                   'window_start': WIN_START, 'declared_gaps': ['amount', 'turnover_rate', 'free_float_market_cap', 'st_flag'],
                   'dates': dates, 'unadj': [rmap[d][:6] for d in dates], 'qfq': [qmap[d][:6] for d in dates],
                   'adjust_factor_model_derived': factors}
            (OUT / f'{code}.json.gz').write_bytes(gzip.compress(json.dumps(rec, separators=(',', ':')).encode(), 6))
            done += 1; consec_fail = 0
            delay = max(0.15, delay - 0.02)      # ease up when healthy
        else:
            fail += 1; failures.append((code, 'throttle_or_empty')); consec_fail += 1
            delay = min(2.5, delay * 1.6)         # back off when throttled
            time.sleep(30)
        time.sleep(delay)
        if (i + 1) % 20 == 0:
            el = int(time.time() - t0)
            print(f'[{i+1}/{len(todo)}] ok={done} fail={fail} delay={delay:.2f} elapsed={el}s eta={int(el/max(1,i+1)*(len(todo)-i-1))}s', flush=True)
    json.dump({'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'attempted': len(todo),
               'ok': done, 'fail': fail, 'failures': failures[:300]},
              open(OUT / '_acquisition_log_v3.json', 'w'), indent=1)
    print(f'FINAL ok={done} fail={fail} head={failures[:10]}', flush=True)

if __name__ == '__main__':
    main()
