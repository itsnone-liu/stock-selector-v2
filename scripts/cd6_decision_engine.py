#!/usr/bin/env python3
"""CD-6 Integrated Capital Decision Engine: three-layer rule table, replay + layer ablations.
Preregistered: docs/cd/cd6_preregistration.json. As-of-T lifecycle states recomputed (never back-stamped)."""
import json, gzip, time, bisect, datetime
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
OUT = ROOT/'docs'/'cd'/'cd6_results.json'
NBUCKETS = 50
HORIZONS = (5, 20, 60)

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
    bands_doc = json.load(open(ROOT/'docs'/'cd'/'cd5bd_results.json'))
    bands = bands_doc['frozen_bands']
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
    rd = [r['date'] for r in l1]
    reg_mode = {}
    for i in range(19, len(rd)):
        cnt = Counter(reg_daily[x] for x in rd[i-19:i+1])
        reg_mode[rd[i]] = cnt.most_common(1)[0][0]
    st = json.loads(gzip.decompress((ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz').read_bytes()))['states']
    state_idx = {(s['l2'], s['date']): (s['base'], s.get('path')) for s in st if s.get('base')}
    # narrowing trailing-10d per (l2,date)
    nar_days = defaultdict(set)
    for s in st:
        if s.get('path') == 'NARROWING':
            l2 = s['l2']; d = s['date']
            nar_days[l2].add(d)
    print('context loaded ({:.0f}s)'.format(time.time()-t0))
    by_stock = defaultdict(list)
    for e in eps: by_stock[e['stock']].append(e)
    for k in by_stock: by_stock[k].sort(key=lambda e: e['start'])
    def band(ax_, v):
        if v is None: return None
        lo, hi = bands[ax_]
        return 'LOW' if v < lo else 'HIGH' if v >= hi else 'MID'
    # build as-of state sequences per episode (once, shared by all ablations)
    epseq = []  # (episode, [(d, state, cost_pos, ...)])
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
        for e in elist:
            s_i = bisect.bisect_left(ds, e['start'])
            rows = []
            hist = [0.0]*NBUCKETS; vsum = 0.0; tp_lo = tp_hi = None
            run_high = None
            baseline = (vs[s_i]-vs[max(0,s_i-20)])/max(1, min(20, s_i)) if s_i >= 1 else None
            streak = 0
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
                cost_pos = 0 if cl < p25 else (2 if cl > p75 else 1)
                r20s = r20m = None
                if i >= 20 and closes[i-20] > 0:
                    r20 = cl/closes[i-20]-1
                    sr = sec_ret20.get((l2, ds[i])); mr = mkt_ret20.get(ds[i])
                    r20s = r20-sr if sr is not None else None
                    r20m = r20-mr if mr is not None else None
                v20 = (vs[i+1]-vs[max(0,i-19)])/max(1, min(20, i+1))
                part = v20/baseline if baseline and baseline > 0 else None
                rps = band('rps', r20s); rpm = band('rpm', r20m); pb = band('part', part)
                if rps == 'LOW' and rpm == 'LOW' and (cost_pos == 0 or pb == 'LOW'): state = 'DECAYING'
                elif (rps == 'HIGH' or rpm == 'HIGH') and pb != 'LOW': state = 'STRENGTHENING'
                else: state = 'HOLDING'
                rows.append((ds[i], state, cost_pos, cl))
            epseq.append((e, rows, closes, ds))
    print('as-of sequences built: episodes', len(epseq), '({:.0f}s)'.format(time.time()-t0))
    # risk context as-of
    def risk_ctx(d, l2, layer):
        if layer < 'B': return 'NEUTRAL'
        g = reg_mode.get(d) or reg_daily.get(d)
        base = {'R_RISK_ON_BROAD': 'SUPPORTIVE', 'R_RISK_ON_NARROW': 'NEUTRAL', 'R_REBOUND_MIXED': 'NEUTRAL', 'R_DEPRESSED': 'RESTRICTIVE', 'R_RISK_OFF': 'RISK_OFF'}.get(g, 'NEUTRAL')
        if layer >= 'C' and l2:
            sp = state_idx.get((l2, d))
            path = sp[1] if sp else None
            if path == 'FADING':
                order = ['SUPPORTIVE', 'NEUTRAL', 'RESTRICTIVE', 'RISK_OFF']
                base = order[min(len(order)-1, order.index(base)+1)]
        if layer >= 'D' and l2:
            ndays = nar_days.get(l2, set())
            if any(d2 in ndays for d2 in [d] if d in ndays) or d in ndays:
                order = ['SUPPORTIVE', 'NEUTRAL', 'RESTRICTIVE', 'RISK_OFF']
                base = order[min(len(order)-1, order.index(base)+1)]
        return base
    # replay one configuration
    def replay(layer, narrowing_mode='ADD_VETO'):
        trades = []; avoids = 0; add_events = 0; reduce_events = 0
        false_exit = 0; false_reduce = 0; exits_fail = 0
        miss = 0; miss_elig = 0
        for e, rows, closes, ds in epseq:
            if not rows: continue
            l2 = e['l2']; org = e['origin']
            pos = 0; entry_i = None; entries = []  # entry prices
            entry_d = None
            decided_enter = False
            # baseline handles BASE separately
            def close_trade(exit_i, reason):
                nonlocal pos, entries, false_exit
                if pos <= 0: return None
                entry_px = sum(entries)/len(entries)
                exit_px = rows[exit_i][3]
                ret = exit_px/entry_px-1
                # market rel
                mc0 = mkt_cum.get(rows[0][0]); mc1 = mkt_cum.get(rows[exit_i][0])
                ret_rel = None
                if mc0 and mc1 and mc0 > 0: ret_rel = (1+ret)/(mc1/mc0)-1
                # MFE/MAE/drawdown from entry index
                hi = max(r[3] for r in rows[entry_i:exit_i+1]); lo = min(r[3] for r in rows[entry_i:exit_i+1])
                mfe = hi/entry_px-1; mae = lo/entry_px-1
                adverse = any(rows[k][1] != 'STRENGTHENING' and rows[k][1] in ('DECAYING',) for k in range(entry_i, exit_i+1))
                t = {'ep': e['episode_id'], 'origin': org, 'l2': l2, 'entry': entry_d, 'exit': rows[exit_i][0],
                     'ret': round(ret, 5), 'ret_rel': round(ret_rel, 5) if ret_rel is not None else None,
                     'mfe': round(mfe, 5), 'mae': round(mae, 5), 'dur': exit_i-entry_i,
                     'adverse': adverse, 'reason': reason, 'regime_entry': reg_mode.get(entry_d)}
                trades.append(t)
                # false-exit: within 20 sessions after exit, re-STRENGTHENING
                if reason in ('FAILURE', 'INACTIVE'):
                    if any(rows[k][1] == 'STRENGTHENING' for k in range(exit_i+1, min(len(rows), exit_i+21))):
                        false_exit += 1
                pos = 0; entries = []
            if layer == 'BASE':
                entry_px = rows[0][3]; exit_px = rows[-1][3]
                ret = exit_px/entry_px-1
                mc0 = mkt_cum.get(rows[0][0]); mc1 = mkt_cum.get(rows[-1][0])
                ret_rel = (1+ret)/(mc1/mc0)-1 if (mc0 and mc1) else None
                hi = max(r[3] for r in rows); lo = min(r[3] for r in rows)
                trades.append({'ep': e['episode_id'], 'origin': org, 'l2': l2, 'entry': e['start'], 'exit': rows[-1][0],
                               'ret': round(ret, 5), 'ret_rel': round(ret_rel, 5) if ret_rel is not None else None,
                               'mfe': round(hi/entry_px-1, 5), 'mae': round(lo/entry_px-1, 5),
                               'dur': len(rows)-1, 'adverse': any(r[1] == 'DECAYING' for r in rows),
                               'reason': e['terminal'], 'regime_entry': reg_mode.get(e['start'])})
                continue
            last_reduced_state = None
            for i, (d, state, cost_pos, cl) in enumerate(rows):
                rc = risk_ctx(d, l2, layer)
                nar = layer >= 'D' and l2 and d in nar_days.get(l2, set())
                term_today = (e['terminal'] == 'STRUCTURAL_FAILURE' and d == e['end']) or (e['terminal'] == 'INACTIVE_TERMINATION' and d == e['end'])
                if pos > 0:
                    if term_today or state == 'FAILED':
                        close_trade(i, 'FAILURE' if e['terminal'] == 'STRUCTURAL_FAILURE' else 'INACTIVE'); exits_fail += 1
                        continue
                    if state == 'DECAYING' and layer >= 'B' and (rc in ('RESTRICTIVE', 'RISK_OFF') or cost_pos == 0):
                        pos = max(0, pos-1); reduce_events += 1
                        last_reduced_state = i
                        if any(rows[k][1] == 'STRENGTHENING' for k in range(i+1, min(len(rows), i+21))):
                            false_reduce += 1
                        continue
                    if state == 'STRENGTHENING' and rc == 'SUPPORTIVE' and cost_pos == 1 and not nar and pos < 2 and (layer < 'F' or org != 'M'):
                        pos += 1; entries.append(cl); add_events += 1
                        continue
                else:
                    if state == 'STRENGTHENING':
                        ok = True
                        if layer >= 'B' and rc in ('RESTRICTIVE', 'RISK_OFF'): ok = False
                        if layer >= 'E' and cost_pos == 0: ok = False
                        if layer >= 'D' and narrowing_mode == 'ENTER_PLUS_ADD' and nar: ok = False
                        if ok and not decided_enter:
                            pos = 1; entries = [cl]; entry_i = i; entry_d = d; decided_enter = True
                        elif not ok:
                            avoids += 1
                            # missed upside: episode reaches top-decile by 60d abs ret among same-month episodes
                            miss_elig += 1
            if pos > 0:
                close_trade(len(rows)-1, 'CENSORED')
        return {'trades': trades, 'avoids': avoids, 'adds': add_events, 'reduces': reduce_events,
                'false_exit': false_exit, 'false_reduce': false_reduce, 'exits_fail': exits_fail}
    def summarize(res, layer):
        tr = res['trades']
        dev = [t for t in tr if t['entry'] <= '2023-12-31']; hol = [t for t in tr if t['entry'] > '2023-12-31']
        def agg(ts):
            if not ts: return None
            return {'n_trades': len(ts), 'n_eps': len({t['ep'] for t in ts}), 'n_stocks': len({t['ep'].split('#')[0] for t in ts}),
                    'n_sectors': len({t['l2'] for t in ts}),
                    'median_ret': med([t['ret'] for t in ts]), 'mean_ret_rel': mean([t['ret_rel'] for t in ts]),
                    'median_ret_rel': med([t['ret_rel'] for t in ts]),
                    'median_mae': med([t['mae'] for t in ts]), 'median_mfe': med([t['mfe'] for t in ts]),
                    'adverse_rate': mean([1.0 if t['adverse'] else 0.0 for t in ts]),
                    'median_dur': med([t['dur'] for t in ts])}
        return {'layer': layer, 'avoids': res['avoids'], 'adds': res['adds'], 'reduces': res['reduces'],
                'false_exit_rate': round(res['false_exit']/max(1, res['exits_fail']), 4),
                'false_reduce': res['false_reduce'],
                'dev': agg(dev), 'holdout': agg(hol)}
    out = {'generated': time.strftime('%Y-%m-%dT%H:%M:%S'), 'layers': {}}
    for layer in ('BASE', 'A', 'B', 'C', 'D', 'E', 'F'):
        res = replay(layer)
        out['layers'][layer] = summarize(res, layer)
        d = out['layers'][layer]
        print(layer, 'dev:', (d['dev'] or {}).get('median_ret_rel'), 'holdout:', (d['holdout'] or {}).get('median_ret_rel'),
              'MAE dev:', (d['dev'] or {}).get('median_mae'), 'adverse dev:', (d['dev'] or {}).get('adverse_rate'),
              'adds:', res['adds'], 'avoids:', res['avoids'])
    # NARROWING usage ablation at layer E: OFF vs ADD_VETO vs ENTER_PLUS_ADD
    out['narrowing_ablation'] = {}
    for mode, layer in (('OFF', 'C'), ('ADD_VETO', 'D'), ('ENTER_PLUS_ADD', 'D')):
        res = replay('E', narrowing_mode=('ENTER_PLUS_ADD' if mode == 'ENTER_PLUS_ADD' else 'ADD_VETO')) if layer == 'D' else replay('C')
        out['narrowing_ablation'][mode] = summarize(res, 'E_'+mode)
    json.dump(out, open(OUT, 'w'), indent=1)
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
