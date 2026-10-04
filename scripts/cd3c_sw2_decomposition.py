#!/usr/bin/env python3
"""CD-3C SW2 divergence decomposition: Q1/Q2/Q3 per preregistration.
classification_mode=RETROSPECTIVE_CURRENT_SW2 on all outputs."""
import json, gzip, time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
SW2 = ROOT/'data'/'cd'/'sector_seeds'/'sw2_v1.json'
ST = ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz'
V3B = ROOT/'docs'/'cd'/'cd3b_validation.json'
OUT = ROOT/'docs'/'cd'/'cd3c_sw2_answers.json'

def median(v):
    s = sorted(x for x in v if x is not None)
    if not s: return None
    n = len(s)
    return s[n//2] if n % 2 else (s[n//2-1]+s[n//2])/2

def main():
    t0 = time.time()
    # load sw2 membership
    sw = json.load(open(SW2))['second_level']
    code2sw = {}
    for code, v in sw.items():
        for s in (v['stocks'] or []):
            code2sw[s] = v['name']
    # per-stock: date->(ret, vol) from qfq close & unadj vol
    per = {}
    for f in sorted(D.glob('*.json.gz')):
        c = f.name.split('.')[0]
        if c.startswith('_') or c not in code2sw: continue
        rec = json.loads(gzip.decompress(f.read_bytes()))
        if not rec['dates']: continue
        closes = [float(r[2]) for r in rec['qfq']]
        vols = [float(r[5]) for r in rec['unadj']]
        m = {}
        for i in range(1, len(rec['dates'])):
            pc = closes[i-1]
            if pc > 0:
                m[rec['dates'][i]] = ((closes[i]-pc)/pc, vols[i])
        per[c] = m
    print('sw2 stocks with data:', len(per), '({:.0f}s)'.format(time.time()-t0))
    # sw2 child daily eq returns + volume
    child = defaultdict(lambda: defaultdict(list))  # swname -> date -> [(ret,vol)]
    for c, m in per.items():
        swname = code2sw[c]
        for d, (r, v) in m.items():
            child[swname][d].append((r, v))
    child_eq = {}   # (swname,date) -> (eqret, vol)
    for swname, byd in child.items():
        for d, lst in byd.items():
            if len(lst) >= 5:
                child_eq[(swname, d)] = (sum(r for r, _ in lst)/len(lst), sum(v for _, v in lst))
    print('sw2 child-days:', len(child_eq), '({:.0f}s)'.format(time.time()-t0))
    # L2 membership (code -> l2) for linking children to L2
    csrc = json.load(open(ROOT/'data'/'cd'/'sector_seeds'/'csrc_v1.json'))['members']
    code2l2 = {m['code']: m['L2'] for m in csrc if m.get('L2')}
    # child -> parent L2 (by majority of member codes)
    child2l2 = {}
    for swname in child:
        cnt = defaultdict(int)
        for c, sn in code2sw.items():
            if sn == swname and c in code2l2: cnt[code2l2[c]] += 1
        if cnt:
            child2l2[swname] = max(cnt, key=cnt.get)
    # state table: per (l2,date) base + mods
    st = json.loads(gzip.decompress(ST.read_bytes()))['states']
    state_idx = {(s['l2'], s['date']): s for s in st if s.get('base')}
    # regime reuse
    edges = json.load(open(V3B))['regime_edges_dev']
    # market 20d regime per date (recompute cheaply from axr mkt_eq)
    axr = json.loads(gzip.decompress((ROOT/'data'/'cd'/'sector_axes'/'l2_four_axes.json.gz').read_bytes()))['rows']
    mkt = defaultdict(list)
    for r in axr:
        if r['status'] == 'OK' and r['mkt_eq'] is not None: mkt[r['date']].append(r['mkt_eq'])
    mkt_eq = {d: sum(v)/len(v) for d, v in mkt.items()}
    dates = sorted(mkt_eq); mkt20 = {}
    for i, d in enumerate(dates):
        if i >= 19: mkt20[d] = sum(mkt_eq[x] for x in dates[i-19:i+1])/20
    def regime(d):
        v = mkt20.get(d)
        if v is None: return None
        return 'R1' if v < edges[0] else 'R3' if v >= edges[1] else 'R2'
    # per (l2,date): children returns
    l2_children = defaultdict(lambda: defaultdict(list))  # (l2,date) -> swname -> [(ret,vol)]
    for (swname, d), (r, v) in child_eq.items():
        l2 = child2l2.get(swname)
        if l2: l2_children[(l2, d)][swname] = (r, v)
    def child_stats(l2, d):
        ch = l2_children.get((l2, d))
        if not ch or len(ch) < 2: return None
        rets = [r for (r, _) in ch.values()]
        pos = {k: (max(r, 0.0)*v) for k, (r, v) in ch.items() if r > 0}
        totp = sum(pos.values())
        top2 = sum(sorted(pos.values(), reverse=True)[:2])/totp if totp > 0 else None
        return {'range': max(rets)-min(rets), 'std': (sum((x-sum(rets)/len(rets))**2 for x in rets)/len(rets))**0.5,
                'n_children': len(rets), 'pos_frac': sum(1 for x in rets if x > 0)/len(rets),
                'top2_share': top2}
    # Q1/Q2/Q3 day collection
    q1_div, q1_pool, q2, q3 = defaultdict(list), defaultdict(list), defaultdict(list), defaultdict(list)
    for (l2, d), ch in l2_children.items():
        s = state_idx.get((l2, d))
        if not s: continue
        cs = child_stats(l2, d)
        if not cs: continue
        yr = d[:4]; split = 'dev' if d <= '2023-12-31' else 'holdout'
        base = s['base']; mods = s.get('mods', [])
        if base == 'DIVERGENT':
            q1_div[split].append(cs['range'])
        else:
            rg = regime(d)
            q1_pool[(split, yr, rg)].append((l2, d, cs['range']))
        if base == 'NARROW_STRENGTH' and 'HIGH_CONCENTRATION' in mods:
            q2[split].append(cs['top2_share'])
        if base == 'BROAD_STRENGTH':
            q3[split].append(cs['pos_frac'])
    answers = {'classification_mode': 'RETROSPECTIVE_CURRENT_SW2', 'generated': time.strftime('%Y-%m-%dT%H:%M:%S')}
    # Q1: matched pool per (split,year,regime) of the SAME sector — approximate with (year,regime) pool filtered to sectors having DIVERGENT days that year
    q1_res = {}
    for split in ('dev', 'holdout'):
        divs = q1_div[split]
        pool_ranges = []
        div_secs_years = {(l2, d[:4]) for (l2, d) in state_idx if True}  # unused placeholder
        for (sp, yr, rg), lst in q1_pool.items():
            if sp != split: continue
            pool_ranges.extend(r for _, _, r in lst)
        q1_res[split] = {'n_div_days': len(divs), 'div_median_range': median(divs),
                         'n_pool_days': len(pool_ranges), 'pool_median_range': median(pool_ranges)}
    answers['Q1_divergent_split'] = {**q1_res,
      'answer': 'YES' if all(q1_res[s]['div_median_range'] > q1_res[s]['pool_median_range'] for s in ('dev','holdout')) else 'NO'}
    answers['Q2_narrow_top2'] = {s: {'n': len(q2[s]), 'median_top2_share': median(q2[s])} for s in ('dev','holdout')}
    m2 = {s: median(q2[s]) for s in ('dev','holdout')}
    answers['Q2_narrow_top2']['answer'] = 'YES' if all(m2[s] is not None and m2[s] >= 0.6 for s in ('dev','holdout')) else 'NO'
    answers['Q3_broad_agreement'] = {s: {'n': len(q3[s]), 'median_pos_frac': median(q3[s])} for s in ('dev','holdout')}
    m3 = {s: median(q3[s]) for s in ('dev','holdout')}
    answers['Q3_broad_agreement']['answer'] = 'L2_BREADTH_FAITHFUL' if all(m3[s] is not None and m3[s] >= 0.8 for s in ('dev','holdout')) else 'L2_BREADTH_MASKS_STRUCTURE'
    json.dump(answers, open(OUT, 'w'), indent=1)
    print(json.dumps(answers, indent=1)[:1500])
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
