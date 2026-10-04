#!/usr/bin/env python3
"""CD-3B forward validation of CD-2C path episodes vs matched baselines.
Preregistered: docs/cd/cd3b_preregistration.json."""
import json, gzip, hashlib, time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
AX = ROOT/'data'/'cd'/'sector_axes'/'l2_four_axes.json.gz'
ST = ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz'
OUT = ROOT/'docs'/'cd'/'cd3b_validation.json'
HORIZONS = [5, 20, 60]
LABELS = ['FADING', 'EXPANSION', 'NARROWING', 'BUILDING']

def qs(v, ps):
    v = sorted(x for x in v if x is not None)
    if not v: return None
    out = []
    for p in ps:
        k = (len(v)-1)*p; f = int(k); c = min(f+1, len(v)-1)
        out.append(round(v[f]+(v[c]-v[f])*(k-f), 6))
    return out

def dstats(v, pool_q10=None):
    if not v: return None
    s = sorted(v); n = len(s)
    med = s[n//2] if n % 2 else (s[n//2-1]+s[n//2])/2
    def p(q):
        k = (n-1)*q; f = int(k); c = min(f+1, n-1)
        return s[f]+(s[c]-s[f])*(k-f)
    m = sum(s)/n
    sd = (sum((x-m)**2 for x in s)/n)**0.5
    return {'n': n, 'mean': round(m, 6), 'median': round(med, 6),
            'q25': round(p(0.25), 6), 'q75': round(p(0.75), 6), 'std': round(sd, 6),
            'p_gt0': round(sum(1 for x in s if x > 0)/n, 4),
            **({'p_lt_poolq10': round(sum(1 for x in s if x < pool_q10)/n, 4)} if pool_q10 is not None else {})}

def main():
    t0 = time.time()
    axr = json.loads(gzip.decompress(AX.read_bytes()))['rows']
    str_ = json.loads(gzip.decompress(ST.read_bytes()))['states']
    axidx = {(r['l2'], r['date']): r for r in axr if r['status'] == 'OK'}
    # per-sector OK sequence
    per = defaultdict(list)
    for s in str_:
        if s.get('base'): per[s['l2']].append(s)
    for k in per: per[k].sort(key=lambda r: r['date'])
    # market 20d eq return per date (for regime terciles)
    mkt = {}
    for r in axr:
        if r['status'] == 'OK' and r['mkt_eq'] is not None:
            mkt.setdefault(r['date'], []).append(r['mkt_eq'])
    mkt_eq = {d: sum(v)/len(v) for d, v in mkt.items()}
    dates = sorted(mkt_eq)
    mkt20 = {}
    for i, d in enumerate(dates):
        if i >= 19:
            w = [mkt_eq[x] for x in dates[i-19:i+1]]
            mkt20[d] = sum(w)/20
    dev_edges = qs([mkt20[d] for d in mkt20 if d <= "2023-12-31"], (1/3, 2/3))
    def regime(d):
        v = mkt20.get(d)
        if v is None: return None
        return 'R1' if v < dev_edges[0] else 'R3' if v >= dev_edges[1] else 'R2'
    # episodes
    episodes = []
    for sec, rs in per.items():
        for lab in LABELS:
            i = 0
            n = len(rs)
            while i < n:
                if rs[i].get('path') == lab:
                    j = i
                    while j+1 < n and rs[j+1].get('path') == lab: j += 1
                    episodes.append({'l2': sec, 'label': lab, 'T_e': rs[i]['date'], 'event_days': j-i+1})
                    i = j+1
                else: i += 1
    print('episodes:', len(episodes), 'by label:', {l: sum(1 for e in episodes if e['label']==l) for l in LABELS})
    # per-sector date index for forward windows
    sec_dates = {sec: [r['date'] for r in rs] for sec, rs in per.items()}
    sec_pos = {sec: {d: i for i, d in enumerate(ds)} for sec, ds in sec_dates.items()}
    def outcome(sec, T_e, H, lab):
        ds = sec_dates[sec]; pos = sec_pos[sec].get(T_e)
        if pos is None: return None
        win = ds[pos+1:pos+1+H]
        avail = len(win)
        if avail == 0: return None
        cum_s = 1.0; cum_m = 1.0; rel_path = [0.0]; breadth = []; part = []
        cont_days = 0; sub_label_seen = False
        sub_label = {'NARROWING': 'FADING', 'BUILDING': 'EXPANSION'}.get(lab)
        cont_base = {'EXPANSION': 'BROAD_STRENGTH', 'FADING': 'BROAD_WEAKNESS'}.get(lab)
        state_rows = per[sec]
        pos_in_state = pos  # aligned: axidx/st same dates
        for k, d in enumerate(win):
            a = axidx.get((sec, d))
            if a is None: break
            cum_s *= (1+(a['sector_eq'] or 0)); cum_m *= (1+(a['mkt_eq'] or 0))
            rel_path.append(cum_s/cum_m-1)
            breadth.append(a['advance_frac'])
            part.append((a['vol_share']-a['vol_share_20d']) if a['vol_share_20d'] is not None else None)
            sr = state_rows[pos_in_state+1+k] if pos_in_state+1+k < len(state_rows) else None
            if sr is not None:
                if cont_base and sr['base'] == cont_base: cont_days += 1
                if sub_label and sr.get('path') == sub_label: sub_label_seen = True
        rel_ret = cum_s/cum_m-1
        mdd = min(rel_path)
        return {'rel_ret': round(rel_ret, 6), 'breadth_mean': round(sum(breadth)/len(breadth), 4) if breadth else None,
                'part_mean': round(sum(x for x in part if x is not None)/max(1, sum(1 for x in part if x is not None)), 8),
                'mdd': round(mdd, 6), 'cont_share': round(cont_days/avail, 4),
                'sub_seen': sub_label_seen, 'avail': avail, 'truncated': avail < H}
    # baseline pools: per (sec, year, regime) of eligible non-event days
    event_days = {(e['l2'], d) for e in episodes for d in [e['T_e']]}
    # expand contamination exclusion: any path-label day + 5 sessions after any episode start
    label_days = defaultdict(set)
    for sec, rs in per.items():
        for r in rs:
            if r.get('path'): label_days[sec].add(r['date'])
    excl = defaultdict(set)
    for sec, rs in per.items():
        ds = [r['date'] for r in rs]
        posmap = {d: i for i, d in enumerate(ds)}
        bad = set()
        for r in rs:
            if r.get('path'):
                i = posmap[r['date']]
                for k in range(0, 6):
                    if i+k < len(ds): bad.add(ds[i+k])
        excl[sec] = bad
    pools = defaultdict(list)
    for sec, rs in per.items():
        for r in rs:
            d = r['date']
            if d in excl[sec]: continue
            rg = regime(d)
            if rg is None: continue
            pools[(sec, d[:4], rg)].append(d)
    # compute episode outcomes + matched comparisons
    results = {}
    ep_rows = []
    for e in episodes:
        rg = regime(e['T_e'])
        if rg is None: continue
        for H in HORIZONS:
            o = outcome(e['l2'], e['T_e'], H, e['label'])
            if o is None or o['truncated']: continue
            ep_rows.append({'l2': e['l2'], 'label': e['label'], 'T_e': e['T_e'], 'year': e['T_e'][:4], 'regime': rg,
                            'H': H, **{k: o[k] for k in ('rel_ret','breadth_mean','part_mean','mdd','cont_share','sub_seen')}})
    for lab in LABELS:
        for H in HORIZONS:
            for split in ('dev', 'holdout'):
                rows = [r for r in ep_rows if r['label'] == lab and r['H'] == H and
                        ((split == 'dev') == (r['T_e'] <= '2023-12-31'))]
                if not rows: continue
                # matched pool rows (same sec-year-regime, outcomes same way)
                key = f"{lab}|H{H}|{split}"
                pool_rets = []
                secs = {r['l2'] for r in rows}
                for sec in secs:
                    yrs = {r['year'] for r in rows if r['l2'] == sec}
                    for yr in yrs:
                        rgs = {r['regime'] for r in rows if r['l2'] == sec and r['year'] == yr}
                        for rgm in rgs:
                            for d in pools.get((sec, yr, rgm), []):
                                o = outcome(sec, d, H, lab)
                                if o is None or o['truncated']: continue
                                pool_rets.append(o['rel_ret'])
                q10 = qs(pool_rets, (0.1,))[0] if pool_rets else None
                results[key] = {
                  'episodes': len(rows), 'sectors': len(secs), 'years': sorted({r['year'] for r in rows}),
                  'rel_ret': dstats([r['rel_ret'] for r in rows], q10),
                  'mdd': dstats([r['mdd'] for r in rows]),
                  'cont_share': dstats([r['cont_share'] for r in rows]),
                  'sub_label_seen_frac': round(sum(1 for r in rows if r['sub_seen'])/len(rows), 4),
                  'pool_n': len(pool_rets),
                  'pool_rel_ret': dstats(pool_rets)}
                print(key, 'eps=', len(rows), 'ep_ret_med=', results[key]['rel_ret']['median'],
                      'pool_med=', results[key]['pool_rel_ret']['median'] if results[key]['pool_rel_ret'] else None,
                      'cont=', results[key]['cont_share']['median'], 'sub=', results[key]['sub_label_seen_frac'])
    json.dump({'generated': time.strftime('%Y-%m-%dT%H:%M:%S'), 'regime_edges_dev': dev_edges,
               'episode_summary': {l: {'n': sum(1 for e in episodes if e['label']==l),
                                       'event_days': sum(e['event_days'] for e in episodes if e['label']==l),
                                       'sectors': len({e['l2'] for e in episodes if e['label']==l}),
                                       'years': sorted({e['T_e'][:4] for e in episodes if e['label']==l})} for l in LABELS},
               'results': results}, open(OUT, 'w'), indent=1)
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
