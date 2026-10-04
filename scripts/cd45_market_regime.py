#!/usr/bin/env python3
"""CD-4.5 L1 Market Observable Regime: market-level daily axes -> census -> frozen bands -> regimes -> Q1-Q5.
Preregistered: docs/cd/cd45_preregistration.json."""
import json, gzip, time
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
FUN = ROOT/'docs'/'cd'/'cd4_funnel_results.json'
OUT_A = ROOT/'data'/'cd'/'sector_axes'/'l1_market_axes.json.gz'
OUT_R = ROOT/'docs'/'cd'/'cd45_regime_results.json'

def q(sorted_v, p):
    if not sorted_v: return None
    k = (len(sorted_v)-1)*p; f = int(k); c = min(f+1, len(sorted_v)-1)
    return sorted_v[f]+(sorted_v[c]-sorted_v[f])*(k-f)

def main():
    t0 = time.time()
    # cross-section per date
    xs = defaultdict(lambda: {'rets': [], 'pos_contrib': [], 'vol': 0.0})
    for f in sorted(D.glob('*.json.gz')):
        c = f.name.split('.')[0]
        if c.startswith('_'): continue
        rec = json.loads(gzip.decompress(f.read_bytes()))
        closes = [float(r[2]) for r in rec['qfq']]
        vols = [float(r[5]) for r in rec['unadj']]
        ds = rec['dates']
        for i in range(1, len(ds)):
            pc = closes[i-1]
            if pc <= 0: continue
            r = closes[i]/pc-1
            x = xs[ds[i]]
            x['rets'].append(r)
            x['pos_contrib'].append(max(r, 0.0)*vols[i])
            x['vol'] += vols[i]
    dates = sorted(xs)
    print('dates:', len(dates), '({:.0f}s)'.format(time.time()-t0))
    # daily axes
    rows = []
    idx_cum = 1.0; cum_series = []
    for d in dates:
        x = xs[d]
        rets = x['rets']; adv = sum(1 for r in rets if r > 0)/len(rets)
        m = sum(rets)/len(rets)
        idx_cum *= (1+m); cum_series.append(idx_cum)
        pos = sorted(x['pos_contrib'], reverse=True)
        tot = sum(pos)
        conc = sum(pos[:50])/tot if tot > 0 else None
        disp = (sum((r-m)**2 for r in rets)/len(rets))**0.5
        rows.append({'date': d, 'eq_ret': round(m, 8), 'breadth': round(adv, 6),
                     'vol': x['vol'], 'conc50': round(conc, 6) if conc is not None else None,
                     'disp': round(disp, 6)})
    # derived: ret20d, participation ratio, trend vs MA500
    out = []
    for i, r in enumerate(rows):
        if i >= 20:
            r['ret20d'] = round(sum(x['eq_ret'] for x in rows[i-19:i+1]), 6)
        if i >= 20:
            v20 = [x['vol'] for x in rows[i-19:i+1]]
            r['part'] = round(r['vol']/(sum(v20)/20), 6)
        if i >= 249:
            ma = sum(cum_series[i-249:i+1])/250
            r['trend'] = 'ABOVE' if cum_series[i] >= ma else 'BELOW'
        out.append(r)
    full = [r for r in out if 'ret20d' in r and 'part' in r and 'trend' in r]
    print('full-axis days:', len(full), full[0]['date'], '..', full[-1]['date'], '({:.0f}s)'.format(time.time()-t0))
    # census + frozen bands (dev window)
    dev = [r for r in full if r['date'] <= '2023-12-31']
    bands = {}
    for ax in ('ret20d', 'breadth', 'part', 'conc50', 'disp'):
        vals = sorted(r[ax] for r in dev if r[ax] is not None)
        bands[ax] = [round(q(vals, 1/3), 6), round(q(vals, 2/3), 6)]
    print('frozen bands:', bands)
    def b(ax, v):
        if v is None: return None
        lo, hi = bands[ax]
        return 'LOW' if v < lo else 'HIGH' if v >= hi else 'MID'
    # regime assignment
    def regime(r):
        t = r['trend']; br = b('breadth', r['breadth']); rt = b('ret20d', r['ret20d'])
        if t == 'ABOVE':
            return 'R_RISK_ON_BROAD' if (br != 'LOW' and rt != 'LOW') else 'R_RISK_ON_NARROW'
        else:
            if rt == 'LOW' and br == 'LOW': return 'R_RISK_OFF'
            if rt == 'LOW' and br == 'MID': return 'R_DEPRESSED'
            if br == 'LOW' and rt == 'MID': return 'R_DEPRESSED'
            return 'R_REBOUND_MIXED'
    for r in full:
        r['regime'] = regime(r)
        r['b_conc'] = b('conc50', r['conc50']); r['b_disp'] = b('disp', r['disp']); r['b_part'] = b('part', r['part'])
    # Q1 counts
    cnt = Counter(r['regime'] for r in full)
    # Q2 persistence: runs
    runs = defaultdict(list); trans = Counter()
    cur = None; run = 0
    for r in full:
        g = r['regime']
        if g == cur: run += 1
        else:
            if cur: runs[cur].append(run)
            if cur: trans[(cur, g)] += 1
            cur = g; run = 1
    runs[cur].append(run)
    def med(v):
        s = sorted(v); return s[len(s)//2] if s else None
    pers = {k: {'n_runs': len(v), 'median_days': med(v), 'mean_days': round(sum(v)/len(v), 1), 'max_days': max(v)} for k, v in runs.items()}
    # Q3 by year
    by_year = defaultdict(Counter)
    for r in full: by_year[r['date'][:4]][r['regime']] += 1
    yr_share = {y: {k: round(c/sum(cnt2.values()), 3) for k, c in cnt2.items()} for y, cnt2 in sorted(by_year.items())}
    # Q4 funnel x regime (checkpoint month regime = regime of checkpoint date if in full)
    fun = json.load(open(FUN))
    reg_by_date = {r['date']: r['regime'] for r in full}
    strat = defaultdict(lambda: {'n': 0, 'long': [], 'mid': [], 'full': [], 'recall': []})
    for cp in fun['checkpoints']:
        g = reg_by_date.get(cp['checkpoint'])
        if not g: continue
        s = strat[g]
        s['n'] += 1; s['long'].append(cp['lvl_long']); s['mid'].append(cp['lvl_mid']); s['full'].append(cp['lvl_full'])
        if cp['recall']: s['recall'].append(cp['recall']['recall_full'])
    strat_out = {g: {'n_checkpoints': s['n'],
                     'median_long': med(s['long']), 'median_mid': med(s['mid']), 'median_full': med(s['full']),
                     'median_recall_full': med(s['recall']) if s['recall'] else None}
                 for g, s in strat.items()}
    # Q5 multimodality on continuous axes (dev)
    mm = {}
    for ax in ('ret20d', 'breadth', 'part', 'conc50', 'disp'):
        vals = [r[ax] for r in dev if r[ax] is not None]
        lo, hi = min(vals), max(vals)
        h = [0]*40
        for v in vals:
            k = min(39, int((v-lo)/(hi-lo+1e-12)*40)); h[k] += 1
        peaks = sorted(range(40), key=lambda i: -h[i])
        p1 = peaks[0]; p2 = next((p for p in peaks if abs(p-p1) > 3 and h[p] > 0), None)
        verdict = 'NO'
        if p2 is not None:
            a, bb = min(p1, p2), max(p1, p2)
            valley = min(h[a:bb+1])
            if valley < 0.25*min(h[p1], h[p2]) and valley < max(h)*0.5: verdict = 'YES'
        mm[ax] = {'verdict': verdict}
    OUT_A.write_bytes(gzip.compress(json.dumps({'n': len(full), 'rows': full}, separators=(',', ':')).encode(), 6))
    json.dump({'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'frozen_bands_dev': bands, 'regime_counts': dict(cnt),
               'regime_share': {k: round(v/len(full), 4) for k, v in cnt.items()},
               'low_support_regimes': [k for k, v in cnt.items() if v/len(full) < 0.02],
               'persistence': pers, 'transitions_top': {f"{a}->{bb}": c for (a, bb), c in trans.most_common(12)},
               'year_share': yr_share, 'funnel_by_regime': strat_out,
               'multimodality': mm},
              open(OUT_R, 'w'), indent=1)
    print('regime share:', {k: round(v/len(full), 3) for k, v in cnt.items()})
    print('persistence:', {k: v['median_days'] for k, v in pers.items()})
    print('funnel by regime:', {k: (v['median_full'], v['median_recall_full']) for k, v in strat_out.items()})
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
