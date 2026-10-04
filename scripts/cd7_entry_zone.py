#!/usr/bin/env python3
"""CD-7 Entry-Zone & Participation Timing: position axis + two-stage ENTER + three-arm validation.
Preregistered: docs/cd/cd7_preregistration.json. L1 permissions frozen carry-forward from CD-6 layer B."""
import json, gzip, time, bisect
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
OUT = ROOT/'docs'/'cd'/'cd7_results.json'
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
    mkt_cum = dict(mkt_hist)
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
    def l1_ok(d):
        g = reg_mode.get(d) or reg_daily.get(d)
        return g not in ('R_DEPRESSED', 'R_RISK_OFF')
    print('context loaded ({:.0f}s)'.format(time.time()-t0))
    by_stock = defaultdict(list)
    for e in eps: by_stock[e['stock']].append(e)
    for k in by_stock: by_stock[k].sort(key=lambda e: e['start'])
    def band(ax_, v):
        if v is None: return None
        lo, hi = bands[ax_]
        return 'LOW' if v < lo else 'HIGH' if v >= hi else 'MID'
    # per-episode as-of rows (state, cost band, zones) + arms replay in one pass
    trades = {'CHASE': [], 'ZONE': []}
    pullback_events = []
    never_trig = {'ZONE': 0}; never_elig = 0; l1_denied_zone = 0
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
        cs = [0.0]*(n+1); vs = [0.0]*(n+1)
        for i in range(n):
            cs[i+1] = cs[i]+closes[i]; vs[i+1] = vs[i]+vols[i]
        l2 = sec_of.get(code)
        fwd60 = {}
        dpos = {d: i for i, d in enumerate(ds)}
        for e in elist:
            s_i = bisect.bisect_left(ds, e['start'])
            if s_i >= n: continue
            # build as-of rows
            rows = []
            hist = [0.0]*NBUCKETS; vsum = 0.0; tp_lo = tp_hi = None
            run_high = None
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
                if rps == 'LOW' and rpm == 'LOW' and (cl < p25 or pb == 'LOW'): state = 'DECAYING'
                elif (rps == 'HIGH' or rpm == 'HIGH') and pb != 'LOW': state = 'STRENGTHENING'
                else: state = 'HOLDING'
                run_high = cl if run_high is None else max(run_high, cl)
                epdd = cl/run_high-1
                rows.append({'i': i, 'd': ds[i], 'st': state, 'cl': cl, 'p25': p25, 'p75': p75, 'c': center, 'pb': pb, 'epdd': epdd})
            if not rows: continue
            # forward 60d abs ret from any index (for cohort top-decile)
            def fwd60_at(i):
                j = rows[i]['i']
                if j+60 < n and closes[j-0] > 0 and closes[j-60] >= 0:
                    pass
                if j+60 < n and closes[j] > 0:
                    return closes[j+60]/closes[j]-1
                return None
            # --- CD-7B pullback events: first close<=p75 after a STRENGTHENING day while previously above p75
            was_above = False; had_str = False
            for k, r in enumerate(rows):
                if r['st'] == 'STRENGTHENING': had_str = True
                if had_str and r['cl'] > r['p75']: was_above = True
                if was_above and r['cl'] <= r['p75']:
                    # pullback day: classify as-of
                    intact = r['st'] in ('HOLDING', 'STRENGTHENING') and r['epdd'] > -0.25 and r['pb'] != 'LOW'
                    # forward: recovery = within 20 sessions close > p75 again; break = close < p25 or CD-5 failure within 20
                    recov = False; brk = False
                    for k2 in range(k+1, min(len(rows), k+21)):
                        if rows[k2]['cl'] > rows[k2]['p75']: recov = True; break
                        if rows[k2]['cl'] < rows[k2]['p25']: brk = True; break
                    if e['terminal'] == 'STRUCTURAL_FAILURE': brk = brk or True
                    pullback_events.append({'intact_asof': intact, 'recovered': recov, 'broke': brk,
                                            'pb': r['pb'], 'st': r['st'], 'epdd': round(r['epdd'], 3)})
                    was_above = False  # only first
            # --- arm CHASE (control): first STRENGTHENING day with L1 ok -> ENTER; exits per B-layer
            def run_arm(arm):
                nonlocal never_elig
                pos = 0; entries = []; entry_k = None; entry_d = None
                decided = False
                ever_str = False
                tr = None
                def close_trade(k_exit, reason):
                    nonlocal pos, entries, tr
                    if pos <= 0: return
                    epx = sum(entries)/len(entries); xpx = rows[k_exit]['cl']
                    ret = xpx/epx-1
                    mc0 = mkt_cum.get(rows[entry_k]['d']); mc1 = mkt_cum.get(rows[k_exit]['d'])
                    rr = (1+ret)/(mc1/mc0)-1 if (mc0 and mc1) else None
                    seg = rows[entry_k:k_exit+1]
                    tr = {'ep': e['episode_id'], 'origin': e['origin'], 'l2': l2, 'entry': entry_d,
                          'ret': round(ret, 5), 'ret_rel': round(rr, 5) if rr is not None else None,
                          'mae': round(min(r['cl'] for r in seg)/epx-1, 5), 'mfe': round(max(r['cl'] for r in seg)/epx-1, 5),
                          'dur': k_exit-entry_k, 'adverse': any(r['st'] == 'DECAYING' for r in seg),
                          'reason': reason}
                    pos = 0; entries = []
                for k, r in enumerate(rows):
                    term_today = ds[rows[k]['i']] == e['end'] and e['terminal'] in ('STRUCTURAL_FAILURE', 'INACTIVE_TERMINATION')
                    if pos > 0:
                        if term_today:
                            close_trade(k, 'TERM'); break
                        if r['st'] == 'DECAYING' and (r['cl'] < r['p25']):
                            pos = max(0, pos-1)
                            continue
                    else:
                        if arm == 'CHASE':
                            if r['st'] == 'STRENGTHENING' and l1_ok(r['d']) and not decided:
                                pos = 1; entries = [r['cl']]; entry_k = k; entry_d = r['d']; decided = True
                        else:  # ZONE two-stage
                            if r['st'] == 'STRENGTHENING': ever_str = True
                            age = k+1
                            elig = age >= 10 and ever_str and r['st'] in ('HOLDING', 'STRENGTHENING')
                            if elig:
                                zone = r['p25'] <= r['cl'] <= r['c']*1.05 and r['pb'] != 'LOW'
                                if zone and l1_ok(r['d']) and not decided:
                                    pos = 1; entries = [r['cl']]; entry_k = k; entry_d = r['d']; decided = True
                if pos > 0:
                    close_trade(len(rows)-1, 'CENSORED')
                if tr: trades[arm].append(tr)
                if arm == 'ZONE' and not decided:
                    # never entered: eligible-but-no-trigger vs never-eligible vs L1-denied
                    any_elig = False
                    ever_str2 = False
                    for k, r in enumerate(rows):
                        if r['st'] == 'STRENGTHENING': ever_str2 = True
                        if k+1 >= 10 and ever_str2 and r['st'] in ('HOLDING', 'STRENGTHENING'):
                            any_elig = True
                            if r['p25'] <= r['cl'] <= r['c']*1.05 and r['pb'] != 'LOW' and l1_ok(r['d']):
                                break
                    if not any_elig: never_elig += 1
                    else: never_trig['ZONE'] += 1
            run_arm('CHASE'); run_arm('ZONE')
    print('arms done: CHASE', len(trades['CHASE']), 'ZONE', len(trades['ZONE']), '({:.0f}s)'.format(time.time()-t0))
    # pullback discrimination summary
    pb = {'n': len(pullback_events)}
    for label, sel in (('intact', lambda p: p['intact_asof']), ('not_intact', lambda p: not p['intact_asof'])):
        grp = [p for p in pullback_events if sel(p)]
        pb[label] = {'n': len(grp), 'P_recovered': mean([1.0 if p['recovered'] else 0.0 for p in grp]),
                     'P_broke': mean([1.0 if p['broke'] else 0.0 for p in grp])}
    # summarize arms dev/holdout
    def agg(ts):
        if not ts: return None
        return {'n_trades': len(ts), 'n_stocks': len({t['ep'].split('#')[0] for t in ts}),
                'median_ret': med([t['ret'] for t in ts]), 'median_ret_rel': med([t['ret_rel'] for t in ts]),
                'mean_ret_rel': mean([t['ret_rel'] for t in ts]),
                'median_mae': med([t['mae'] for t in ts]), 'median_mfe': med([t['mfe'] for t in ts]),
                'adverse_rate': mean([1.0 if t['adverse'] else 0.0 for t in ts]), 'median_dur': med([t['dur'] for t in ts])}
    out = {'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'pullback_discrimination': pb,
           'zone_never_entered': {'never_eligible': never_elig, 'eligible_no_trigger': never_trig['ZONE']},
           'arms': {}}
    # missed-upside: ZONE-entered vs never-entered episodes, 60d fwd top-decile of entry-month cohort (from episode start)
    fwd_by_ep = {}
    for code, elist in by_stock.items():
        f = D/(code+'.json.gz')
        if not f.exists(): continue
        rec = json.loads(gzip.decompress(f.read_bytes()))
        ds2 = rec['dates']
        if not ds2: continue
        cl2 = [float(r[2]) for r in rec['qfq']]
        for e in elist:
            i = bisect.bisect_left(ds2, e['start'])
            if 0 <= i and i+60 < len(ds2) and cl2[i] > 0:
                fwd_by_ep[e['episode_id']] = cl2[i+60]/cl2[i]-1
    month = defaultdict(list)
    for e in eps:
        if e['episode_id'] in fwd_by_ep: month[e['start'][:7]].append(e['episode_id'])
    top = set()
    for m, lst in month.items():
        lst.sort(key=lambda x: -fwd_by_ep[x])
        top.update(lst[:max(1, len(lst)//10)])
    entered = {t['ep'] for t in trades['ZONE']}
    never = [e['episode_id'] for e in eps if e['episode_id'] in fwd_by_ep and e['episode_id'] not in entered]
    out['missed_upside'] = {
        'zone_entered': len(entered), 'zone_entered_topdecile': mean([1.0 if x in top else 0.0 for x in entered]),
        'never_entered': len(never), 'never_entered_topdecile': mean([1.0 if x in top else 0.0 for x in never]),
        'topdecile_lost_share': (lambda a, b: round(a/max(1, a+b), 4))(sum(1 for x in never if x in top), sum(1 for x in entered if x in top))}
    for arm in ('CHASE', 'ZONE'):
        dev = [t for t in trades[arm] if t['entry'] <= '2023-12-31']; hol = [t for t in trades[arm] if t['entry'] > '2023-12-31']
        out['arms'][arm] = {'dev': agg(dev), 'holdout': agg(hol)}
    json.dump(out, open(OUT, 'w'), indent=1)
    for arm in ('CHASE', 'ZONE'):
        for s in ('dev', 'holdout'):
            a = out['arms'][arm][s]
            if a: print(arm, s, 'n=', a['n_trades'], 'ret_rel_med=', a['median_ret_rel'], 'MAE=', a['median_mae'], 'adv=', a['adverse_rate'], 'dur=', a['median_dur'])
    print('pullback:', pb)
    print('zone never entered:', out['zone_never_entered'])
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
