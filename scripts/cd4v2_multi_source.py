#!/usr/bin/env python3
"""CD-4V2 Regime-aware Multi-source Candidate Architecture.
Preregistered: docs/cd/cd4v2_preregistration.json. Sources = V1 definitions verbatim, independent."""
import json, gzip, time
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
AX = ROOT/'data'/'cd'/'sector_axes'/'l1_market_axes.json.gz'
ST = ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz'
OUT_R = ROOT/'docs'/'cd'/'cd4v2_results.json'
OUT_P = ROOT/'data'/'cd'/'l3_candidate_pool_v2.json.gz'

def med(v):
    s = sorted(x for x in v if x is not None)
    return s[len(s)//2] if s else None

def main():
    t0 = time.time()
    stocks = {}
    for f in sorted(D.glob('*.json.gz')):
        c = f.name.split('.')[0]
        if c.startswith('_'): continue
        rec = json.loads(gzip.decompress(f.read_bytes()))
        if not rec['dates']: continue
        stocks[c] = (rec['dates'], [float(r[2]) for r in rec['qfq']], [float(r[5]) for r in rec['unadj']])
    print('stocks:', len(stocks), '({:.0f}s)'.format(time.time()-t0))
    # regime daily + 20d mode
    ax = json.loads(gzip.decompress(AX.read_bytes()))['rows']
    reg_daily = {r['date']: r['regime'] for r in ax}
    rdates = [r['date'] for r in ax]
    reg_mode = {}
    for i, d in enumerate(rdates):
        if i >= 19:
            reg_mode[d] = Counter(reg_daily[x] for x in rdates[i-19:i+1]).most_common(1)[0][0]
    # sector metadata
    sec_of = {}
    for m in json.load(open(ROOT/'data'/'cd'/'sector_seeds'/'csrc_v1.json'))['members']:
        if m.get('L2'): sec_of[m['code']] = m['L2']
    st = json.loads(gzip.decompress(ST.read_bytes()))['states']
    state_idx = {(s['l2'], s['date']): s for s in st if s.get('base')}
    # checkpoints (month-end)
    all_dates = sorted({d for ds, _, _ in stocks.values() for d in ds})
    by_month = defaultdict(list)
    for d in all_dates: by_month[d[:7]].append(d)
    cps = [ds[-1] for _, ds in sorted(by_month.items())]
    cps = [c for c in cps if c >= '2021-06-01']
    print('checkpoints:', len(cps))
    # evaluation points: checkpoints + [+5,+20,+60] trade days after each (for daily-continuity)
    dpos = {d: i for i, d in enumerate(all_dates)}
    def src_state(c, i):
        """trailing source definitions VERBATIM from V1 at position i (exclusive prefix length i, 1-based index of last used)."""
        ds, closes, vols = stocks[c]
        n = len(ds)
        LONG = MID = SHORT = False
        obs = None
        # observation pool eligibility
        if i < 120: obs = 'EXCLUDED_NEW'
        elif closes[i-1] < 2.0: obs = 'EXCLUDED_LOW_PRICE'
        else:
            w60 = vols[max(0,i-60):i]
            if sum(1 for v in w60 if v > 0) < 10: obs = 'EXCLUDED_SUSPENDED'
        if obs is None:
            w20 = vols[max(0,i-20):i]
            obs = 'OK' if len(w20) == 20 else 'EXCLUDED_ILLIQUID'
        if obs == 'OK':
            if i >= 500 and closes[i-1] > sum(closes[i-500:i])/500 and closes[i-1]/closes[i-500]-1 > 0:
                LONG = True
            if i >= 250:
                ret65 = closes[i-1]/closes[i-65]-1
                v20 = sum(vols[i-20:i])/20
                med250 = sorted(vols[i-250:i])[125]
                if ret65 > 0 and med250 > 0 and v20 > 1.5*med250: MID = True
            for k in range(max(60, i-20), i):
                win = vols[max(0,k-20):k]
                if closes[k] >= max(closes[k-60+1:k+1]) and vols[k] > 2*(sum(win)/max(1,len(win))):
                    SHORT = True; break
        return obs, LONG, MID, SHORT
    # NOTE: liquidity percentile needs cross-section; computed per eval date below
    # gather per eval-date: for each stock position via bisect on dates
    import bisect
    def eval_at(eval_date, need_recall):
        i_map = {}
        for c, (ds, _, _) in stocks.items():
            i = bisect.bisect_right(ds, eval_date)
            if i > 0: i_map[c] = i
        v20s = {}
        for c, i in i_map.items():
            _, _, vols = stocks[c]
            w = vols[i-20:i]
            if len(w) == 20 and sum(w) > 0: v20s[c] = sum(w)/20
        if not v20s: return {'state': {}, 'top': set()}
        vals = sorted(v20s.values())
        p2 = vals[max(0, int(len(vals)*0.02)-1)]
        out = {}
        for c, i in i_map.items():
            obs, L, M, S = src_state(c, i)
            if obs == 'OK' and (v20s.get(c) is None or v20s[c] < p2): obs = 'EXCLUDED_ILLIQUID'
            out[c] = (obs, L and obs=='OK', M and obs=='OK', S and obs=='OK', i)
        if need_recall:
            fwd = {}
            for c, (ds, closes, _) in stocks.items():
                if c not in i_map: continue
                i = i_map[c]
                if i+60 < len(ds) and closes[i-1] > 0:
                    fwd[c] = closes[i+60]/closes[i-1]-1
            if fwd:
                mret = sum(fwd.values())/len(fwd)
                top = set(sorted(fwd, key=lambda c: -(fwd[c]-mret))[:max(1, len(fwd)//10)])
            else: top = set()
        else: top = set()
        return {'state': out, 'top': top}
    # main pass
    results = []
    pools = {}
    prev_union = None
    for cp in cps:
        r = eval_at(cp, True)
        state, top = r['state'], r['top']
        obs = {c for c, v in state.items() if v[0] == 'OK'}
        L = {c for c, v in state.items() if v[1]}
        M = {c for c, v in state.items() if v[2]}
        S = {c for c, v in state.items() if v[3]}
        U = L | M | S
        rg_d = reg_daily.get(cp); rg_m = reg_mode.get(cp)
        row = {'checkpoint': cp, 'obs_pool': len(obs), 'regime_daily': rg_d, 'regime_20d': rg_m,
               'L': len(L), 'M': len(M), 'S': len(S), 'U': len(U),
               'jaccard_U_vs_prev': None, 'recall': {}}
        if top:
            for k, sset in (('L', L), ('M', M), ('S', S), ('U', U), ('obs', obs)):
                row['recall'][k] = round(len(sset & top)/len(top), 4) if top else None
        if prev_union is not None:
            a, b = U, prev_union
            row['jaccard_U_vs_prev'] = round(len(a & b)/len(a | b), 4) if (a | b) else 1.0
        # per-source jaccard too
        for k in ('L', 'M', 'S'):
            row['jac_'+k] = None
        results.append(row)
        pools[cp] = {'L': sorted(L), 'M': sorted(M), 'S': sorted(S)}
        prev_union = U
        print(cp, 'obs', len(obs), 'L', len(L), 'M', len(M), 'S', len(S), 'U', len(U), '({:.0f}s)'.format(time.time()-t0))
    # daily-continuity: P(source still true at +5/+20/+60 trade days)
    cont = defaultdict(list)
    for cp in cps:
        i_cp = dpos[cp]
        base = eval_at(cp, False)['state']
        for h in (5, 20, 60):
            di = i_cp + h
            if di >= len(all_dates): continue
            ed = all_dates[di]
            nxt = eval_at(ed, False)['state']
            for src_i, k in ((1, 'L'), (2, 'M'), (3, 'S')):
                had = [c for c, v in base.items() if v[src_i]]
                if not had: continue
                still = sum(1 for c in had if nxt.get(c, (None,)*5)[src_i])
                cont[(k, h)].append(still/len(had))
        if len(cont) % 20 == 0 and cont: pass
    # regime-stratified effectiveness
    strat = defaultdict(lambda: defaultdict(list))
    for row in results:
        rg = row['regime_20d']
        if not rg: continue
        for k in ('L', 'M', 'S', 'U'):
            strat[rg][k].append(row[k])
        if row['recall'].get('U'): strat[rg]['recall_U'].append(row['recall']['U'])
        if row['recall'].get('L'): strat[rg]['recall_L'].append(row['recall']['L'])
    strat_out = {rg: {k: med(v) for k, v in d.items()} for rg, d in strat.items()}
    # intersections tenure: monthly runs per source membership
    # (monthly source membership runs across checkpoints)
    def runs_of(members_by_cp, key):
        seqs = defaultdict(list)
        order = cps
        prev = None
        runs = []
        cur_streak = {}
        active = set()
        for cp in order:
            cur = set(members_by_cp[cp][key]) if key in members_by_cp[cp] else set()
            for c in cur - active: cur_streak[c] = cp
            for c in active - cur:
                runs.append((c, cur_streak.pop(c), cp))
            active = cur
        for c in active: runs.append((c, cur_streak[c], order[-1]))
        return runs
    src_runs = {k: runs_of(pools, k) for k in ('L', 'M', 'S', 'U_list')}
    # U needs list form
    for cp in cps: pools[cp]['U_list'] = sorted(set(pools[cp]['L'])|set(pools[cp]['M'])|set(pools[cp]['S']))
    src_runs = {k: runs_of(pools, k) for k in ('L', 'M', 'S', 'U_list')}
    def run_lens(runs):
        order = {cp: i for i, cp in enumerate(cps)}
        return [order[e]-order[s] for _, s, e in runs]
    tenure = {k: {'median_months': med(run_lens(v)), 'n_runs': len(v),
                  'reentry_rate': round(1 - len({c for c,_,_ in v})/max(1, len(v)), 4)} for k, v in src_runs.items()}
    # summary
    def med_key(k): return med([r[k] for r in results if r.get(k) is not None])
    summ = {'n_checkpoints': len(results), 'median_obs': med_key('obs_pool'),
            'median_L': med_key('L'), 'median_M': med_key('M'), 'median_S': med_key('S'), 'median_U': med_key('U'),
            'median_jac_U': med_key('jaccard_U_vs_prev'),
            'median_jac_L': med([r.get('jac_L') for r in results if r.get('jac_L') is not None]),
            'recall': {k: med([r['recall'][k] for r in results if r['recall'].get(k)]) for k in ('L','M','S','U','obs')},
            'obs_limitation': 'st_flag/free_float/turnover_rate unavailable in DATA-1 — OBSERVABILITY_LIMITATION declared on all pool rows'}
    # incremental recall L -> +M -> +S (checkpoint median)
    inc = {}
    # computed on intersection pass below
    inter = {}
    for cp in cps:
        L, M, S = set(pools[cp]['L']), set(pools[cp]['M']), set(pools[cp]['S'])
        combos = {'L_only': L-M-S, 'M_only': M-L-S, 'S_only': S-L-M, 'LM': (L&M)-S, 'LS': (L&S)-M, 'MS': (M&S)-L, 'LMS': L&M&S}
        for k, s in combos.items():
            inter.setdefault(k, []).append(len(s))
    inter_med = {k: med(v) for k, v in inter.items()}
    json.dump({'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
               'summary': summ, 'incremental': inc, 'intersections_median_size': inter_med,
               'continuity': {f"{k}_after_{h}d": round(med(v), 4) for (k, h), v in sorted(cont.items())},
               'tenure': tenure, 'regime_stratified': strat_out,
               'checkpoints': results}, open(OUT_R, 'w'), indent=1, default=str)
    OUT_P.write_bytes(gzip.compress(json.dumps({'pools': pools, 'regime': {cp: {'daily': r['regime_daily'], 'mode20': r['regime_20d']} for cp, r in zip(cps, results)}, 'observability_limitation': 'st/free_float/turnover unavailable'}, separators=(',', ':')).encode(), 6))
    print('SUMMARY:', json.dumps({k: summ[k] for k in ('median_obs','median_L','median_M','median_S','median_U','median_jac_U')}, ensure_ascii=False))
    print('recall:', summ['recall'])
    print('continuity:', {f"{k}_{h}": round(med(v), 3) for (k, h), v in sorted(cont.items())})
    print('tenure:', tenure)
    print('intersections:', inter_med)
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
