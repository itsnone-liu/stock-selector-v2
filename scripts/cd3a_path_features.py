#!/usr/bin/env python3
"""CD-3A path features per (l2, T, W) for W in {20,40,60}. Preregistered: docs/cd/cd3a_preregistration.json."""
import json, gzip, hashlib, time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
AX = ROOT/'data'/'cd'/'sector_axes'/'l2_four_axes.json.gz'
ST = ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz'
OUT = ROOT/'data'/'cd'/'sector_axes'/'l2_path_features.json.gz'
CEN = ROOT/'docs'/'cd'/'cd3a_path_census.json'
WINDOWS = [20, 40, 60]
BASES6 = ['BROAD_STRENGTH','NARROW_STRENGTH','BROAD_WEAKNESS','NARROW_WEAKNESS','DIVERGENT','NEUTRAL_ANY']
STRENGTH = ('BROAD_STRENGTH','NARROW_STRENGTH')
WEAKNESS = ('BROAD_WEAKNESS','NARROW_WEAKNESS')

def ols_slope_xw(ys):
    n = len(ys)
    if n < 3: return None
    xm = (n-1)/2.0; ym = sum(ys)/n
    den = sum((i-xm)**2 for i in range(n))
    if den == 0: return None
    b = sum((i-xm)*(y-ym) for i, y in enumerate(ys))/den
    return b*n

def main():
    t0 = time.time()
    ax = {r['date']: r for r in json.loads(gzip.decompress(AX.read_bytes()))['rows'] if r['status']=='OK'}
    st = json.loads(gzip.decompress(ST.read_bytes()))['states']
    per_sec = defaultdict(list)
    for s in st: per_sec[s['l2']].append(s)
    # build aligned series per sector: only OK days, ordered
    series = {}
    for sec, rs in per_sec.items():
        rs = [r for r in rs if r.get('base')]  # OK days only
        rs.sort(key=lambda r: r['date'])
        recs = []
        for r in rs:
            a = ax.get((r['date'], sec))  # placeholder; ax keyed by date only wrong — rebuild below
        series[sec] = rs
    # proper ax index: (l2,date) -> axis row
    axidx = {}
    for r in json.loads(gzip.decompress(AX.read_bytes()))['rows']:
        if r['status']=='OK': axidx[(r['l2'], r['date'])] = r
    feats = []
    for sec, rs in series.items():
        n = len(rs)
        for W in WINDOWS:
            for i in range(W-1, n):
                w = rs[i-W+1:i+1]
                # continuity: all dates distinct OK days (already consecutive OK by construction); no INSUFFICIENT inside
                T = w[-1]
                bases = []
                for r in w:
                    b = r['base']
                    bases.append('NEUTRAL_ANY' if b in ('NEUTRAL','NEUTRAL_WIDE_UP','NEUTRAL_WIDE_DOWN') else b)
                occ = {k: bases.count(k)/W for k in BASES6}
                a_rows = [axidx[(sec, r['date'])] for r in w]
                def series_of(f):
                    return [x[f] for x in a_rows]
                sl = {}
                for f, key in [('rel_eq_mkt','sl_rp'), ('advance_frac','sl_breadth'),
                               ('ret_contrib_top5','sl_conc'), ('ret_gap_calc','sl_gap')]:
                    pass
                # d_share and ret_gap computed inline
                d_sh = [(x['vol_share']-x['vol_share_20d']) for x in a_rows]
                gap = [(x['top5_mean_ret']-x['rest_mean_ret']) if x['top5_mean_ret'] is not None else None for x in a_rows]
                def fit(vals):
                    nn = [v for v in vals if v is not None]
                    if len(nn) < W/2: return None
                    # OLS on non-null positions
                    idx = [i for i, v in enumerate(vals) if v is not None]
                    xm = sum(idx)/len(idx); ym = sum(vals[i] for i in idx)/len(idx)
                    den = sum((i-xm)**2 for i in idx)
                    if den == 0: return None
                    b = sum((i-xm)*(vals[i]-ym) for i in idx)/den
                    return b*W
                f_sl = {
                 'sl_rp': fit(series_of('rel_eq_mkt')),
                 'sl_breadth': fit(series_of('advance_frac')),
                 'sl_part': fit(d_sh),
                 'sl_conc': fit(series_of('ret_contrib_top5')),
                 'sl_gap': fit(gap)}
                # persistence
                def longest(members):
                    best = cur = 0
                    for b in bases:
                        cur = cur+1 if b in members else 0
                        best = max(best, cur)
                    return best
                sw = 0
                for j in range(1, W):
                    if bases[j] != bases[j-1]: sw += 1
                # structure deltas
                def delta(f):
                    a, b = a_rows[0].get(f), a_rows[-1].get(f)
                    return (b-a) if (a is not None and b is not None) else None
                feats.append({'l2': sec, 'date': T['date'], 'W': W,
                    **{f'occ_{k}': round(v, 6) for k, v in occ.items()},
                    **{k: (round(v, 8) if v is not None else None) for k, v in f_sl.items()},
                    'run_str': longest(STRENGTH), 'run_wk': longest(WEAKNESS), 'switches': sw,
                    'start': bases[0], 'end': bases[-1],
                    'd_breadth': (lambda d: round(d, 6) if d is not None else None)(delta('advance_frac')),
                    'd_conc': (lambda d: round(d, 6) if d is not None else None)(delta('ret_contrib_top5')),
                    'd_gap': (lambda d: round(d, 6) if d is not None else None)(delta('top5_mean_ret'))})
    sha = hashlib.sha256(json.dumps(feats, separators=(',',':')).encode()).hexdigest()
    OUT.write_bytes(gzip.compress(json.dumps({'n': len(feats), 'features': feats}, separators=(',', ':')).encode(), 6))
    # census on dev window
    dev = [f for f in feats if f['date'] <= '2023-12-31']
    def qs(vals, ps=(0.1,0.25,0.5,0.75,0.9)):
        v = sorted(x for x in vals if x is not None)
        if not v: return None
        out = []
        for p in ps:
            k = (len(v)-1)*p; floc = int(k); c = min(floc+1, len(v)-1)
            out.append(round(v[floc]+(v[c]-v[floc])*(k-floc), 6))
        return out
    census = {'n_rows': len(feats), 'n_dev': len(dev), 'per_window': {}}
    for W in WINDOWS:
        dw = [f for f in dev if f['W'] == W]
        cw = {'n': len(dw)}
        for k in ['occ_BROAD_STRENGTH','occ_BROAD_WEAKNESS','occ_DIVERGENT','sl_rp','sl_part','run_str','switches','d_breadth']:
            cw[k] = qs([f.get(k) for f in dw])
        census['per_window'][W] = cw
    # multimodality check on primary occupancy features (40-bin histogram, dev, W=40)
    mm = {}
    for k in ['occ_BROAD_STRENGTH','occ_DIVERGENT','occ_BROAD_WEAKNESS']:
        vals = [f[k] for f in dev if f['W'] == 40]
        h = [0]*40
        for v in vals:
            b = min(39, int(v*40)); h[b] += 1
        # find two tallest non-adjacent local maxima and the valley between
        peaks = sorted(range(40), key=lambda i: -h[i])
        p1 = peaks[0]
        p2 = next((p for p in peaks if abs(p-p1) > 3 and h[p] > 0), None)
        verdict = 'NO'
        if p2 is not None:
            lo, hi = min(p1, p2), max(p1, p2)
            valley = min(h[lo:hi+1])
            if valley < 0.25*min(h[p1], h[p2]) and valley < max(h)*0.5:
                verdict = 'YES'
        mm[k] = {'hist_40bins': h, 'peak1_bin': p1, 'peak2_bin': p2, 'verdict': verdict}
    census['multimodality_W40_dev'] = mm
    census['cluster_decision'] = 'CLUSTER' if any(v['verdict']=='YES' for v in mm.values()) else 'NO_CLUSTER'
    census['feature_table_sha256'] = sha
    json.dump(census, open(CEN, 'w'), indent=1)
    print('path rows:', len(feats), 'sha:', sha[:16], '({:.0f}s)'.format(time.time()-t0))
    print('cluster decision:', census['cluster_decision'])
    for k, v in mm.items(): print(' ', k, v['verdict'], 'peaks', v['peak1_bin'], v['peak2_bin'])

if __name__ == '__main__':
    main()
