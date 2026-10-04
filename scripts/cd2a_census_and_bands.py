#!/usr/bin/env python3
"""CD-2A axis census (Support-First) + frozen threshold derivation + band table build.
Preregistered: docs/cd/cd2a_preregistration.json. Dev window 2021-01..2023-12 only."""
import json, gzip, hashlib, time, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT/'data'/'cd'/'sector_axes'/'l2_four_axes.json.gz'
OUT_T = ROOT/'docs'/'cd'/'cd2a_thresholds.json'
OUT_B = ROOT/'data'/'cd'/'sector_axes'/'l2_axis_bands.json.gz'
DEV_END = '2023-12-31'
AXES = ['rp','part','breadth','conc','disp']

def q(sorted_v, p):
    if not sorted_v: return None
    k = (len(sorted_v)-1)*p; f = int(k); c = min(f+1, len(sorted_v)-1)
    return sorted_v[f] + (sorted_v[c]-sorted_v[f])*(k-f)

def main():
    rec = json.loads(gzip.decompress(SRC.read_bytes()))
    rows = rec['rows']
    dev = [r for r in rows if r['status']=='OK' and r['date'] <= DEV_END]
    print(f'OK rows total={sum(1 for r in rows if r["status"]=="OK")} dev-window={len(dev)}')
    # derived variables per row
    def vars_of(r):
        return {'rp': r['rel_eq_mkt'],
                'part': (r['vol_share'] - r['vol_share_20d']) if (r['vol_share'] is not None and r['vol_share_20d'] is not None) else None,
                'breadth': r['advance_frac'],
                'conc': r['ret_contrib_top5'],
                'disp': (r['top5_mean_ret'] - r['rest_mean_ret']) if (r['top5_mean_ret'] is not None and r['rest_mean_ret'] is not None) else None}
    # size strata by median participating n per sector over dev window
    med_n = {}
    by_sec = defaultdict(list)
    for r in dev: by_sec[r['l2']].append(r['n'])
    for s, ns in by_sec.items():
        ns = sorted(ns); med_n[s] = ns[len(ns)//2]
    stratum = {s: ('SMALL' if m < 15 else 'MID' if m < 50 else 'LARGE') for s, m in med_n.items()}
    from collections import Counter
    print('strata:', Counter(stratum.values()))
    # per-axis pooled + stratum quantiles (dev window)
    thr = {}
    for ax in AXES:
        pooled = sorted(v[ax] for v in (vars_of(r) for r in dev) if v[ax] is not None)
        by_str = defaultdict(list)
        for r in dev:
            v = vars_of(r)[ax]
            if v is not None: by_str[stratum[r['l2']]].append(v)
        t_pooled = (q(pooled, 1/3), q(pooled, 2/3))
        t_str = {k: (q(sorted(v), 1/3), q(sorted(v), 2/3)) for k, v in by_str.items()}
        # drift measure: fraction of stratum rows falling in pooled MID band vs stratum-MID band
        drift = {}
        for k, v in by_str.items():
            def midfrac(rows, thr_):
                lo, hi = thr_
                return sum(1 for x in rows if lo <= x < hi)/len(rows)
            drift[k] = round(abs(midfrac(v, t_pooled) - midfrac(v, t_str[k])), 4)
        adopt_stratified = any(d > 0.10 for d in drift.values())
        # annual stability (pooled dev years)
        ann = {}
        for yr in ('2021','2022','2023'):
            sv = sorted(x for r in dev if r['date'].startswith(yr) for x in [vars_of(r)[ax]] if x is not None)
            ann[yr] = [round(q(sv, 1/3), 6), round(q(sv, 2/3), 6)]
        thr[ax] = {'variable': {'rp':'rel_eq_mkt','part':'vol_share - vol_share_20d','breadth':'advance_frac','conc':'ret_contrib_top5','disp':'top5_mean_ret - rest_mean_ret'}[ax],
                   'n_dev_nonnull': len(pooled), 'pooled_q33_q67': [round(t_pooled[0], 8), round(t_pooled[1], 8)],
                   'stratum_q33_q67': {k: [round(a, 8), round(b, 8)] for k, (a, b) in t_str.items()},
                   'stratum_midband_drift_abs': drift, 'annual_pooled_q33_q67': ann,
                   'adopted': 'SIZE_STRATIFIED' if adopt_stratified else 'POOLED'}
        print(ax, thr[ax]['adopted'], 'pooled=', thr[ax]['pooled_q33_q67'], 'drift=', drift)
    # freeze + build band table over ALL OK rows
    def band(ax, val, l2):
        if val is None: return None
        lo, hi = thr[ax]['stratum_q33_q67'][stratum[l2]] if thr[ax]['adopted']=='SIZE_STRATIFIED' else thr[ax]['pooled_q33_q67']
        return 'LOW' if val < lo else 'HIGH' if val >= hi else 'MID'
    bands = []
    for r in rows:
        if r['status'] != 'OK':
            bands.append({'l2': r['l2'], 'date': r['date'], 'state': 'INSUFFICIENT_SUPPORT', 'n': r.get('n', 0)})
            continue
        v = vars_of(r)
        bands.append({'l2': r['l2'], 'date': r['date'], 'n': r['n'],
            'rp': band('rp', v['rp'], r['l2']), 'part': band('part', v['part'], r['l2']),
            'breadth': band('breadth', v['breadth'], r['l2']), 'conc': band('conc', v['conc'], r['l2']),
            'disp': band('disp', v['disp'], r['l2'])})
    sha = hashlib.sha256(json.dumps(bands, separators=(',',':')).encode()).hexdigest()
    OUT_B.write_bytes(gzip.compress(json.dumps({'n': len(bands), 'bands': bands}, separators=(',',':')).encode(), 6))
    json.dump({'frozen_at': time.strftime('%Y-%m-%dT%H:%M:%S'), 'source_sha_rows': '0f747662efa35818…',
               'dev_window_end': DEV_END, 'thresholds': thr,
               'band_table_sha256': sha, 'n_rows': len(bands),
               'null_counts': {ax: sum(1 for b in bands if b.get(ax) is None) for ax in AXES}},
              open(OUT_T, 'w'), indent=1)
    print('band table rows=', len(bands), 'sha=', sha[:16])
    # dual-run determinism: recompute bands purely to compare
    bands2 = []
    for r in rows:
        if r['status'] != 'OK':
            bands2.append({'l2': r['l2'], 'date': r['date'], 'state': 'INSUFFICIENT_SUPPORT', 'n': r.get('n', 0)}); continue
        v = vars_of(r)
        bands2.append({'l2': r['l2'], 'date': r['date'], 'n': r['n'],
            'rp': band('rp', v['rp'], r['l2']), 'part': band('part', v['part'], r['l2']),
            'breadth': band('breadth', v['breadth'], r['l2']), 'conc': band('conc', v['conc'], r['l2']),
            'disp': band('disp', v['disp'], r['l2'])})
    sha2 = hashlib.sha256(json.dumps(bands2, separators=(',',':')).encode()).hexdigest()
    print('determinism recompute:', 'PASS' if sha2==sha else 'FAIL')

if __name__ == '__main__':
    main()
