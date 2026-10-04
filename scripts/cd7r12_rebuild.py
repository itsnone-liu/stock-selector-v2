#!/usr/bin/env python3
"""CD-7 R1/R2 REBUILD: full-coverage three-arm validation (CHASE control / PRIMARY_ZONE / PRIMARY+SECONDARY)
Fixes coverage bug in cd7_entry_zone.py+cd7r2_secondary.py (only 2,813/25,164 triggered episodes covered).
rows construction inherited verbatim from cd7d_risk_budget.py (independently verified: 30,066 non-empty,
per-episode trigger formula matches manual recomputation)."""
import json, gzip, time, bisect
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
OUT = ROOT/'docs'/'cd'/'cd7_rebuild_results.json'
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
    CLS = {}
    DBG = []
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
    fwd60_pool = {}
    by_stock = defaultdict(list)
    for e in eps: by_stock[e['stock']].append(e)
    for k in by_stock: by_stock[k].sort(key=lambda e: e['start'])
    def band(ax_, v):
        if v is None: return None
        lo, hi = bands[ax_]
        return 'LOW' if v < lo else 'HIGH' if v >= hi else 'MID'
    trades = {'CHASE': [], 'ZONE': [], 'C': []}
    p0_events = []
    never_cls = Counter()
    fwd_by_ep = {}
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
            if closes[s_i] > 0 and s_i+60 < n:
                fwd_by_ep[e['episode_id']] = closes[s_i+60]/closes[s_i]-1
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
            def run_arm(arm):
                pos = 0; entry_px = None; entry_k = None; entry_d = None
                decided = False; ever_str = False; kind = None; reduce_done = False
                tr = None
                def close_trade(k_exit, reason):
                    nonlocal pos, tr
                    if pos <= 0: return
                    xpx = rows[k_exit][2]; ret = xpx/entry_px-1
                    mc0 = mkt_cum.get(rows[entry_k][0]); mc1 = mkt_cum.get(rows[k_exit][0])
                    rr = (1+ret)/(mc1/mc0)-1 if (mc0 and mc1) else None
                    seg = rows[entry_k:k_exit+1]
                    tr = {'ep': e['episode_id'], 'kind': kind, 'entry': entry_d,
                          'ret': round(ret, 5), 'ret_rel': round(rr, 5) if rr is not None else None,
                          'mae': round(min(r[2] for r in seg)/entry_px-1, 5),
                          'mfe': round(max(r[2] for r in seg)/entry_px-1, 5),
                          'dur': k_exit-entry_k, 'delay': entry_k,
                          'adverse': any(r[1] == 'DECAYING' for r in seg), 'reason': reason}
                    pos = 0
                for k, (d, st, cl, p25, p75, center, pb) in enumerate(rows):
                    term_today = d == e['end'] and e['terminal'] in ('STRUCTURAL_FAILURE', 'INACTIVE_TERMINATION')
                    if arm == 'ZONE' and e['episode_id'] == '002594#0001' and k < 62:
                        DBG.append((k, d, st, 'pos='+str(pos), 'dec='+str(decided), 'term='+str(term_today), 'tr='+('Y' if tr else 'N')))
                    if pos > 0:
                        if term_today: close_trade(k, 'TERM'); break
                        if not reduce_done and st == 'DECAYING' and cl < p25:
                            # P0 fix: reducing a 1-unit position to zero IS an exit -> must record the trade.
                            # close_trade guards on pos>0, so close BEFORE decrementing (the original engines
                            # decremented first, so the guard rejected every reduce-exit and the trade vanished).
                            position_before = pos
                            close_trade(k, 'REDUCED_OUT')
                            pos = 0; reduce_done = True
                            if arm == 'ZONE':
                                p0_events.append({'trade_id': f"{e['episode_id']}@{rows[k][0]}", 'episode_id': e['episode_id'], 'stock': e['stock'], 'decision_date': rows[k][0], 'decision': 'REDUCE', 'position_before': position_before, 'remaining_position': pos, 'terminal_reason': 'REDUCED_OUT', 'entry_date': entry_d, 'entry_price': entry_px, 'reduction_price': cl, 'lifecycle_state': st, 'ordering': ['close_record_created', 'position_discarded']})
                            break
                    else:
                        if arm == 'CHASE':
                            if st == 'STRENGTHENING' and l1_ok(d) and not decided:
                                pos = 1; entry_px = cl; entry_k = k; entry_d = d; decided = True; kind = 'CHASE'
                        else:
                            if st == 'STRENGTHENING': ever_str = True
                            elig = (k+1) >= 10 and ever_str and st in ('HOLDING', 'STRENGTHENING')
                            if elig:
                                primary = p25 <= cl <= center*1.05 and pb != 'LOW' and l1_ok(d)
                                secondary = False
                                if arm == 'C' and not decided and k >= 20:
                                    dh = [rows[k2][2]/rows[k2][4]-1 if rows[k2][4] > 0 else None for k2 in range(k-20, k+1)]
                                    dh = [x for x in dh if x is not None]
                                    if dh:
                                        d_t = dh[-1]; d_max20 = max(dh)
                                        band_rising = rows[k][4] >= rows[k-20][4] if rows[k-20][4] > 0 else False
                                        hi20 = max(rows[k2][2] for k2 in range(k-20, k+1))
                                        secondary = (d_t <= 0.5*d_max20 and d_t <= 0.03 and band_rising and pb != 'LOW' and cl >= 0.93*hi20 and l1_ok(d))
                                if primary and not decided:
                                    pos = 1; entry_px = cl; entry_k = k; entry_d = d; decided = True; kind = 'PRIMARY'
                                elif secondary and not decided:
                                    pos = 1; entry_px = cl; entry_k = k; entry_d = d; decided = True; kind = 'SECONDARY'
                if pos > 0: close_trade(len(rows)-1, 'CENSORED')
                if tr: trades[arm].append(tr)
                return decided
            d_chase = run_arm('CHASE'); d_zone = run_arm('ZONE'); d_c = run_arm('C')
            if e['episode_id'] == '002594#0001':
                for x in DBG: print('DBG', x)
            CLS['eps'] = CLS.get('eps',0)+1
            if d_zone and not trades['ZONE'] or (trades['ZONE'] and trades['ZONE'][-1]['ep'] != e['episode_id'] and d_zone):
                CLS['decided_no_trade'] = CLS.get('decided_no_trade',0)+1
            if d_zone: CLS['decided'] = CLS.get('decided',0)+1
            if not d_zone:
                any_elig = False; ever2 = False
                for k, (d, st, cl, p25, p75, center, pb) in enumerate(rows):
                    if st == 'STRENGTHENING': ever2 = True
                    if k+1 >= 10 and ever2 and st in ('HOLDING', 'STRENGTHENING'):
                        any_elig = True
                        if p25 <= cl <= center*1.05 and pb != 'LOW' and l1_ok(d): break
                never_cls['never_eligible' if not any_elig else 'eligible_no_trigger'] += 1
            elif not d_c:
                never_cls['C_lost'] += 1
    print('CLS:', CLS)
    print('trades CHASE', len(trades['CHASE']), 'ZONE', len(trades['ZONE']), 'C', len(trades['C']), '({:.0f}s)'.format(time.time()-t0))
    print('never:', dict(never_cls))
    json.dump(p0_events, open(ROOT/'docs/cd'/'cd7_p0_reduced_out_events.json','w'), indent=1)
    month = defaultdict(list)
    for e in eps:
        if e['episode_id'] in fwd_by_ep: month[e['start'][:7]].append(e['episode_id'])
    top = set()
    for m, lst in month.items():
        lst.sort(key=lambda x: -fwd_by_ep[x])
        top.update(lst[:max(1, len(lst)//10)])
    def agg(ts):
        if not ts: return None
        return {'n': len(ts),
                'topdecile_rate': mean([1.0 if t['ep'] in top else 0.0 for t in ts]),
                'median_ret_rel': med([t['ret_rel'] for t in ts]), 'median_mae': med([t['mae'] for t in ts]),
                'median_mfe': med([t['mfe'] for t in ts]),
                'adverse_rate': mean([1.0 if t['adverse'] else 0.0 for t in ts]),
                'median_delay': med([t['delay'] for t in ts]), 'median_dur': med([t['dur'] for t in ts])}
    out = {'generated': time.strftime('%Y-%m-%dT%H:%M:%S'), 'coverage_fix': 'P0 REDUCED_OUT fix: prior cd7/cd7r2 engines silently dropped trades closed by DECAYING-reduce (survivorship 2813/25164); all CD-7 R1/R2 numbers superseded',
           'never': dict(never_cls), 'arms': {}, 'strata': {}}
    for arm in ('CHASE', 'ZONE', 'C'):
        dev = [t for t in trades[arm] if t['entry'] <= '2023-12-31']; hol = [t for t in trades[arm] if t['entry'] > '2023-12-31']
        out['arms'][arm] = {'dev': agg(dev), 'holdout': agg(hol)}
    out['strata'] = {
        'primary_only_C': agg([t for t in trades['C'] if t['kind'] == 'PRIMARY']),
        'secondary_only_C': agg([t for t in trades['C'] if t['kind'] == 'SECONDARY']),
        'incremental_C_minus_ZONE': len(trades['C'])-len(trades['ZONE']),
        'never_entered_all': {'n': sum(never_cls.values()), 'topdecile_rate': None}}
    never_ids = [e['episode_id'] for e in eps if e['episode_id'] in fwd_by_ep and e['episode_id'] not in {t['ep'] for t in trades['C']}]
    out['strata']['never_entered_all'] = {'n': len(never_ids), 'topdecile_rate': mean([1.0 if i in top else 0.0 for i in never_ids])}
    json.dump(out, open(OUT, 'w'), indent=1)
    for arm in ('CHASE', 'ZONE', 'C'):
        for s in ('dev', 'holdout'):
            a = out['arms'][arm][s]
            if a: print(arm, s, 'n=', a['n'], 'ret_rel=', a['median_ret_rel'], 'MAE=', a['median_mae'], 'adv=', a['adverse_rate'], 'topdec=', a['topdecile_rate'], 'delay=', a['median_delay'])
    print('SECONDARY-only:', out['strata']['secondary_only_C'])
    print('never_all:', out['strata']['never_entered_all'])
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
