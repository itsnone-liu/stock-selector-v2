#!/usr/bin/env python3
"""CD-7D Absolute Risk Budget: E-class monotonicity + portfolio replay + D0-D5 ablations.
Preregistered: docs/cd/cd7d_preregistration.json. ENTER from frozen policy (L1+PRIMARY_ZONE); sizing never bypasses eligibility."""
import json, gzip, time, bisect
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
OUT = ROOT/'docs'/'cd'/'cd7d_results.json'
NBUCKETS = 50

def wq(hist, lo, hi, vsum, tf):
    target = vsum*tf; acc = 0.0; span = hi-lo
    for bi in range(NBUCKETS):
        if hist[bi] > 0 and acc+hist[bi] >= target:
            return lo+(bi+(target-acc)/hist[bi])/NBUCKETS*span
        acc += hist[bi]
    return hi

def med(v):
    s = sorted(x for x in v if x is not None)
    return round(s[len(s)//2], 5) if s else None
def mean(v):
    vv = [x for x in v if x is not None]
    return round(sum(vv)/len(vv), 5) if vv else None
def p10(v):
    s = sorted(x for x in v if x is not None)
    return round(s[max(0, len(s)//10)], 5) if s else None

def main():
    t0 = time.time()
    bands = json.load(open(ROOT/'docs'/'cd'/'cd5bd_results.json'))['frozen_bands']
    eps = json.loads(gzip.decompress((ROOT/'data'/'cd'/'l4_episodes.json.gz').read_bytes()))['episodes']
    sec_of = {}
    for m in json.load(open(ROOT/'data'/'cd'/'sector_seeds'/'csrc_v1.json'))['members']:
        if m.get('L2'): sec_of[m['code']] = m['L2']
    ax = json.loads(gzip.decompress((ROOT/'data'/'cd'/'sector_axes'/'l2_four_axes.json.gz').read_bytes()))['rows']
    mkt_by_date = defaultdict(list); sec_by_date = defaultdict(dict)
    for r in ax:
        if r['status'] == 'OK':
            if r['mkt_eq'] is not None: mkt_by_date[r['date']].append(r['mkt_eq'])
            if r['sector_eq'] is not None: sec_by_date[r['l2']][r['date']] = r['sector_eq']
    mkt_hist = []; c = 1.0
    for d in sorted(mkt_by_date):
        c *= 1+sum(mkt_by_date[d])/len(mkt_by_date[d]); mkt_hist.append((d, c))
    mkt_ret20 = {mkt_hist[i][0]: mkt_hist[i][1]/mkt_hist[i-20][1]-1 for i in range(20, len(mkt_hist))}
    sec_ret20 = {}
    for l2, byd in sec_by_date.items():
        hist = []; c = 1.0
        for d in sorted(byd):
            c *= 1+byd[d]; hist.append((d, c))
        for i in range(20, len(hist)):
            sec_ret20[(l2, hist[i][0])] = hist[i][1]/hist[i-20][1]-1
    l1 = json.loads(gzip.decompress((ROOT/'data'/'cd'/'sector_axes'/'l1_market_axes.json.gz').read_bytes()))['rows']
    reg_daily = {r['date']: r['regime'] for r in l1}
    rd = [r['date'] for r in l1]; reg_mode = {}
    for i in range(19, len(rd)):
        reg_mode[rd[i]] = Counter(reg_daily[x] for x in rd[i-19:i+1]).most_common(1)[0][0]
    GROSS = {'R_RISK_ON_BROAD': 8.0, 'R_RISK_ON_NARROW': 6.0, 'R_REBOUND_MIXED': 6.0, 'R_DEPRESSED': 2.0, 'R_RISK_OFF': 2.0}
    SUP = {'R_RISK_ON_BROAD'}
    NORM = {'R_RISK_ON_NARROW', 'R_REBOUND_MIXED'}
    st_tbl = json.loads(gzip.decompress((ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz').read_bytes()))['states']
    sector_risk = {}
    for s in st_tbl:
        if s.get('path') in ('FADING', 'NARROWING'):
            sector_risk[(s['l2'], s['date'])] = True
    print('ctx {:.0f}s'.format(time.time()-t0))
    by_stock = defaultdict(list)
    for e in eps: by_stock[e['stock']].append(e)
    for k in by_stock: by_stock[k].sort(key=lambda e: e['start'])
    def band(ax_, v):
        if v is None: return None
        lo, hi = bands[ax_]
        return 'LOW' if v < lo else 'HIGH' if v >= hi else 'MID'
    # per-episode trade plans (PRIMARY_ZONE entries from frozen policy) + entry-day E-class
    plans = []  # dicts: ep, sector, entry_d, entry_px, exit_d, exit_px, exit_reason, reduce_d(reduce_px), eclass, fwd series for MAE
    for code, elist in by_stock.items():
        f = D/(code+'.json.gz')
        if not f.exists(): continue
        rec = json.loads(gzip.decompress(f.read_bytes()))
        ds = rec['dates']
        if not ds: continue
        closes = [float(r[2]) for r in rec['qfq']]
        highs = [float(r[3]) for r in rec['qfq']]
        lows = [float(r[4]) for r in rec['qfq']]
        vols = [float(r[5]) for r in rec['unadj']]
        n = len(ds)
        vs = [0.0]*(n+1)
        for i in range(n): vs[i+1] = vs[i]+vols[i]
        l2 = sec_of.get(code)
        for e in elist:
            s_i = bisect.bisect_left(ds, e['start'])
            if s_i >= n: continue
            rows = []
            hist = [0.0]*NBUCKETS; vsum = 0.0; tp_lo = tp_hi = None
            baseline = (vs[s_i]-vs[max(0,s_i-20)])/max(1, min(20, s_i)) if s_i >= 1 else None
            for i in range(s_i, n):
                if ds[i] > e['end']: break
                cl = closes[i]
                if not (cl > 0 and highs[i] > 0 and lows[i] > 0): continue
                tp = (highs[i]+lows[i]+cl)/3; v = vols[i]
                if tp_lo is None: tp_lo = tp_hi = tp
                tp_lo = min(tp_lo, tp); tp_hi = max(tp_hi, tp)
                span = tp_hi-tp_lo
                b_ = 0 if span <= 0 else min(NBUCKETS-1, int((tp-tp_lo)/span*NBUCKETS))
                hist[b_] += v; vsum += v
                p25 = wq(hist, tp_lo, tp_hi, vsum, 0.25); p75 = wq(hist, tp_lo, tp_hi, vsum, 0.75)
                center = wq(hist, tp_lo, tp_hi, vsum, 0.5)
                r20s = r20m = None
                if i >= 20 and closes[i-20] > 0:
                    r20 = cl/closes[i-20]-1
                    sr = sec_ret20.get((l2, ds[i])); mr = mkt_ret20.get(ds[i])
                    r20s = r20-sr if sr is not None else None
                    r20m = r20-mr if mr is not None else None
                v20 = (vs[i+1]-vs[max(0,i-19)])/max(1, min(20, i+1))
                part = v20/baseline if baseline and baseline > 0 else None
                rps = band('rps', r20s); rpm = band('rpm', r20m); pb = band('part', part)
                if rps == 'LOW' and rpm == 'LOW' and (cl < p25 or pb == 'LOW'): st = 'DECAYING'
                elif (rps == 'HIGH' or rpm == 'HIGH') and pb != 'LOW': st = 'STRENGTHENING'
                else: st = 'HOLDING'
                rows.append((ds[i], st, cl, p25, p75, center, pb))
            if not rows: continue

            ever_str = False; entered = False
            entry_k = None; eclass = None
            reduce_k = None
            for k, (d, st, cl, p25, p75, center, pb) in enumerate(rows):
                if st == 'STRENGTHENING': ever_str = True
                age = k+1
                if not entered:
                    elig = age >= 10 and ever_str and st in ('HOLDING', 'STRENGTHENING')
                    g = reg_mode.get(d) or reg_daily.get(d)
                    if elig and p25 <= cl <= center*1.05 and pb != 'LOW' and g not in ('R_DEPRESSED', 'R_RISK_OFF'):
                        # E-class (frozen rule table v1)
                        inside = p25 <= cl <= p75
                        sec_risk = sector_risk.get((l2, d), False)
                        if g in SUP and st == 'STRENGTHENING' and inside and not sec_risk: eclass = 'E3'
                        elif g in SUP and st == 'STRENGTHENING' and inside: eclass = 'E2'
                        else: eclass = 'E1'
                        entered = True; entry_k = k
                        plans.append({'ep': e['episode_id'], 'sector': l2, 'k0': k, 'entry_d': d,
                                      'entry_px': cl, 'eclass': eclass, 'cost_inside': inside, 'rows_ref': rows, 'terminal': e['terminal'], 'end': e['end']})
                        continue
                else:
                    if reduce_k is None and st == 'DECAYING' and cl < p25:
                        reduce_k = k
                        plans[-1]['reduce_k'] = k
            if entered:
                p = plans[-1]
                term_idx = None
                for k, r in enumerate(rows):
                    if r[0] == e['end'] and e['terminal'] in ('STRUCTURAL_FAILURE', 'INACTIVE_TERMINATION'):
                        term_idx = k; break
                p['exit_k'] = term_idx if term_idx is not None else len(rows)-1
                p['rows'] = rows
                p['exit_px'] = rows[p['exit_k']][2]
    print('plans:', len(plans), '({:.0f}s)'.format(time.time()-t0))
    # entry-day E-class monotonicity (per trade forward metrics, group by eclass)
    mono = {}
    for ec in ('E1', 'E2', 'E3'):
        grp = [p for p in plans if p['eclass'] == ec]
        if not grp: mono[ec] = {'n': 0}; continue
        maes = []; rets = []; adv = []; valid = []
        for p in grp:
            seg = p['rows'][p['k0']:p['exit_k']+1]
            if not seg: continue
            valid.append(p)
            maes.append(min(r[2] for r in seg)/p['entry_px']-1)
            rets.append(p['exit_px']/p['entry_px']-1)
            adv.append(1.0 if any(r[1] == 'DECAYING' for r in seg) else 0.0)
        dev_m = [m for m, p in zip(maes, valid) if p['entry_d'] <= '2023-12-31']
        hol_m = [m for m, p in zip(maes, valid) if p['entry_d'] > '2023-12-31']
        dev_r = [r for r, p in zip(rets, valid) if p['entry_d'] <= '2023-12-31']
        hol_r = [r for r, p in zip(rets, valid) if p['entry_d'] > '2023-12-31']
        dev_adv = [a for a, p in zip(adv, valid) if p['entry_d'] <= '2023-12-31']
        hol_adv = [a for a, p in zip(adv, valid) if p['entry_d'] > '2023-12-31']
        mono[ec] = {'n': len(valid),
                    'dev': {'median_mae': med(dev_m), 'p10_ret': p10(dev_r), 'adverse': mean(dev_adv)},
                    'holdout': {'median_mae': med(hol_m), 'p10_ret': p10(hol_r), 'adverse': mean(hol_adv)}}
    # portfolio replay per ablation
    E_CEIL = {'E1': 0.5, 'E2': 1.0, 'E3': 1.5}
    def replay(layer):
        caps = layer >= 'D5'
        gross_on = layer >= 'D1'
        lifecycle_on = layer >= 'D2'
        cost_on = layer >= 'D3'
        sector_on = layer >= 'D4'
        by_d = defaultdict(list)
        for idx, p in enumerate(plans):
            by_d[p['entry_d']].append(idx)
        all_dates = sorted(set(d for d in by_d) | {r[0] for p in plans for r in p['rows']})
        positions = {}  # idx -> dict(size, entry_px, sector)
        capital0 = 10.0
        equity = capital0; peak = capital0; maxdd = 0.0
        missed = 0
        entered_count = 0
        util_sum = 0.0; util_n = 0
        ret_contrib = 0.0
        closes_by_d = {}
        for p in plans:
            for r in p['rows']:
                closes_by_d[(p['ep'], r[0])] = r[2]
        for d in all_dates:
            g = reg_mode.get(d) or reg_daily.get(d) or 'R_RISK_ON_BROAD'
            gross_cap = GROSS[g] if gross_on else 10.0
            # exits
            for idx in list(positions):
                p = plans[idx]
                if p['rows'][p['exit_k']][0] <= d:
                    px = closes_by_d.get((p['ep'], d), p['exit_px'])
                    equity_change = positions[idx]['size']*(px/positions[idx]['entry_px']-1)
                    ret_contrib += equity_change
                    equity += equity_change
                    del positions[idx]
            # reduces
            if lifecycle_on:
                for idx, pos in positions.items():
                    p = plans[idx]
                    rk = p.get('reduce_k')
                    if rk is not None and p['rows'][rk][0] == d and pos['size'] > 0.25:
                        px = p['rows'][rk][2]
                        half = pos['size']/2
                        equity_change = half*(px/pos['entry_px']-1)
                        ret_contrib += equity_change
                        equity += equity_change
                        pos['size'] -= half
            # entries
            for idx in by_d.get(d, []):
                p = plans[idx]
                ec = p['eclass']
                ceil = E_CEIL[ec]
                if cost_on and ec in ('E2', 'E3') and not p.get('cost_inside', False):
                    # D3: cost-position ceiling; an out-of-band E2/E3 entry is capped to E1.
                    ceil = E_CEIL['E1']
                if sector_on and ec == 'E3':
                    if sector_risk.get((p['sector'], d), False): ceil = E_CEIL['E2']
                if lifecycle_on:
                    pass  # DECAYING entries never happen (ZONE condition)
                # caps
                if caps:
                    used = sum(pos['size'] for pos in positions.values())
                    sec_used = sum(pos['size'] for pos in positions.values() if pos['sector'] == p['sector'])
                    if len(positions) >= 10: ceil = 0.0
                    ceil = min(ceil, max(0.0, gross_cap-used), max(0.0, 3.0-sec_used))
                if ceil < 0.25:
                    missed += 1
                    continue
                positions[idx] = {'size': ceil, 'entry_px': p['entry_px'], 'sector': p['sector']}
                entered_count += 1
            # mark to market
            used = sum(pos['size'] for pos in positions.values())
            util_sum += used/10.0; util_n += 1
            mtm = equity
            for idx, pos in positions.items():
                p = plans[idx]
                dd = None
                for r in p['rows']:
                    if r[0] == d: dd = r[2]; break
                if dd is not None: mtm += pos['size']*(dd/pos['entry_px']-1)
            peak = max(peak, mtm); maxdd = min(maxdd, mtm/peak-1)
        return {'total_pnl_pct': round(ret_contrib/capital0, 4), 'maxdd': round(maxdd, 4),
                'avg_util': round(util_sum/max(1, util_n), 4), 'n_entered': entered_count, 'missed_by_budget': missed,
                'final_open': len(positions)}
    out = {'generated': time.strftime('%Y-%m-%dT%H:%M:%S'), 'eclass_monotonicity': mono, 'ablations': {}}
    for layer in ('D0', 'D1', 'D2', 'D3', 'D4', 'D5'):
        r = replay(layer)
        out['ablations'][layer] = r
        print(layer, r)
    json.dump(out, open(OUT, 'w'), indent=1)
    print('mono:', json.dumps(mono, indent=1))
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
