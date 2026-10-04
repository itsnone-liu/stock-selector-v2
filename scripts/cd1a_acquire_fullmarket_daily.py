#!/usr/bin/env python3
"""CD-1A-DATA-1: full-market daily acquisition (EM push2his, fqt=0+1, resumable).
Preregistration: docs/cd/cd1a_preregistration.json. No market conclusions."""
import json, gzip, os, sys, time, hashlib
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT/'data'/'cd'/'daily_fullmarket'
OUT.mkdir(parents=True, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0'}
KLINE = 'https://push2his.eastmoney.com/api/qt/stock/kline/get'
BEG, END = '20210101', '20500101'
FIELDS2 = 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'  # date,open,close,high,low,volume,amount,amplitude,pct,chg,turnover

def secid(code):
    if code.startswith(('6', '9', '688')): return '1.'+code
    if code.startswith(('8', '4')): return '0.'+code  # BJ on EM m:0
    return '0.'+code

def fetch_one(sess, code):
    out = {}
    for fqt in (0, 1):
        p = {'secid': secid(code), 'fields1': 'f1,f2,f3,f4,f5,f6', 'fields2': FIELDS2,
             'klt': '101', 'fqt': str(fqt), 'beg': BEG, 'end': END, 'lmt': '1000000'}
        for attempt in range(4):
            try:
                r = sess.get(KLINE, params=p, timeout=25, headers=UA)
                j = r.json().get('data')
                if j is None: return None, 'no_data'
                rows = j['klines']
                if not rows: return None, 'empty'
                out[str(fqt)] = rows
                break
            except Exception as e:
                if attempt == 3: return None, f'err:{type(e).__name__}'
                time.sleep(2*(attempt+1))
    # derive adjust factor: close_fqt1/close_fqt0 anchored last=1
    c0 = [row.split(',')[2] for row in out['0']]
    c1 = [row.split(',')[2] for row in out['1']]
    anchor = float(c1[-1])/float(c0[-1])
    factors = [round(float(a)/float(b)/anchor, 6) for a, b in zip(c1, c0)]
    rec = {'code': code, 'name': j.get('name', ''), 'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'source': 'eastmoney_push2his_kline', 'beg': BEG,
           'dates': [row.split(',')[0] for row in out['0']],
           'unadj': out['0'], 'qfq': out['1'], 'adjust_factor_model_derived': factors}
    blob = json.dumps(rec, separators=(',', ':'), sort_keys=False).encode()
    gz = gzip.compress(blob, 6)
    (OUT/f'{code}.json.gz').write_bytes(gz)
    return len(rec['dates']), 'ok'

def build_universe():
    # priority 1: csrc snapshot stock list (seed, names only); 2: sina hs_a pages
    codes = set()
    snap = ROOT/'data'/'t4'/'sector_map'/'csrc_industry_snapshot.json'
    if snap.exists():
        sm = json.load(open(snap))
        rows = sm['rows'] if isinstance(sm, dict) and 'rows' in sm else sm
        for r in rows:
            # snapshot rows are lists: [date, 'sh.600000', name, 'J66货币金融服务', source]
            c = r[1] if isinstance(r, list) else str(r.get('stock_code') or r.get('code') or '')
            c = str(c).split('.')[-1].strip()  # 'sh.600000' -> '600000'
            if len(c) == 6 and c.isdigit(): codes.add(c)
    print(f'csrc seed codes: {len(codes)}', flush=True)
    try:
        import requests as rq
        s = rq.Session(); page = 1; seen = 0
        while True:
            r = s.get('http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData',
                      params={'node': 'hs_a', 'page': page, 'num': 100, 'sort': 'symbol', 'asc': 1, 'symbol': '', '_s_r_a': 'page'},
                      timeout=20, headers=UA)
            rows = r.json()
            if not rows: break
            for x in rows:
                c = x['symbol'].replace('sh', '').replace('sz', '')
                if len(c) == 6 and c.isdigit(): codes.add(c)
            seen += len(rows); page += 1; time.sleep(0.2)
            if page > 80: break
        print(f'after sina hs_a union: {len(codes)} (sina rows {seen})', flush=True)
    except Exception as e:
        print(f'sina list FAIL {type(e).__name__} — proceeding with crc seed only', flush=True)
    # drop Beijing exchange for v1 (EM BJ handling uncertain); keep 60/00/30/68
    keep = {c for c in codes if c[:2] in ('60', '00', '30', '68', '90', '20')}
    drop_bj = len(codes)-len(keep)
    print(f'universe final: {len(keep)} (dropped {drop_bj} BJ/other)', flush=True)
    json.dump({'universe': sorted(keep), 'dropped_bj': drop_bj, 'built_at': time.strftime('%Y-%m-%dT%H:%M:%S')},
              open(OUT/'_universe.json', 'w'), indent=1)
    return sorted(keep)

def main():
    uni_file = OUT/'_universe.json'
    if uni_file.exists():
        uni = json.load(open(uni_file))['universe']
        print(f'resume with existing universe: {len(uni)}', flush=True)
    else:
        uni = build_universe()
    sess = requests.Session()
    done = fail = 0; failures = []
    t0 = time.time()
    for i, code in enumerate(uni):
        f = OUT/f'{code}.json.gz'
        if f.exists():
            done += 1; continue
        n, status = fetch_one(sess, code)
        if status == 'ok': done += 1
        else: fail += 1; failures.append((code, status))
        time.sleep(0.25)
        if (i+1) % 100 == 0:
            print(f'[{i+1}/{len(uni)}] done={done} fail={fail} elapsed={int(time.time()-t0)}s', flush=True)
    json.dump({'fetched_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'universe_n': len(uni),
               'ok': done, 'fail': fail, 'failures': failures[:200]},
              open(OUT/'_acquisition_log.json', 'w'), indent=1)
    print(f'FINAL done={done} fail={fail} failures_head={failures[:10]}', flush=True)

if __name__ == '__main__':
    main()
