#!/usr/bin/env python3
"""CD-5B+5D: lifecycle axes -> frozen bands -> states -> sampled forward validation by origin.
Preregistered: docs/cd/cd5_preregistration.json."""
import json, gzip, time, bisect
from pathlib import Path
from collections import defaultdict, Counter

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
EPS = ROOT/'data'/'cd'/'l4_episodes.json.gz'
OUT = ROOT/'docs'/'cd'/'cd5bd_results.json'
NBUCKETS = 50

def qs(v, ps):
    s = sorted(v); out = []
    for p in ps:
        k = (len(s)-1)*p; f = int(k); c = min(f+1, len(s)-1)
        out.append(round(s[f]+(s[c]-s[f])*(k-f), 8))
    return out

def wq(hist, lo, hi, vsum, target_frac):
    target = vsum*target_frac; acc = 0.0
    span = hi-lo
    for bi in range(NBUCKETS):
        if acc+hist[bi] >= target and hist[bi] > 0:
            frac = (target-acc)/hist[bi]
            return lo+(bi+frac)/NBUCKETS*span
        acc += hist[bi]
    return hi

def main():
    t0 = time.time()
    eps = json.loads(gzip.decompress(EPS.read_bytes()))['episodes']
    print('episodes:', len(eps), '({:.0f}s)'.format(time.time()-t0))
    sec_of = {}
    for m in json.load(open(ROOT/'data'/'cd'/'sector_seeds'/'csrc_v1.json'))['members']:
        if m.get('L2'): sec_of[m['code']] = m['L2']
    ax = json.loads(gzip.decompress((ROOT/'data'/'cd'/'sector_axes'/'l2_four_axes.json.gz').read_bytes()))['rows']
    mkt_by_date = defaultdict(list); sec_by_date = defaultdict(dict)
    for r in ax:
        if r['status'] == 'OK':
            if r['mkt_eq'] is not None: mkt_by_date[r['date']].append(r['mkt_eq'])
            if r['sector_eq'] is not None: sec_by_date[r['l2']][r['date']] = r['sector_eq']
    def ret20(series_dates, cum, d):
        i = cum[0].get(d)
        return None
    # market ret20 per date
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
    # group episodes by stock
    by_stock = defaultdict(list)
    for e in eps: by_stock[e['stock']].append(e)
    for k in by_stock: by_stock[k].sort(key=lambda e: e['start'])
    # pass 1: compute per-episode-day continuous axes (store minimal tuples)
    # axis tuple: (ep_idx_global, day_idx_in_stock, rp_sec, rp_mkt, struct_ratio, part_ratio, cost_pos_code(0/1/2), dist_center)
    # state computed in pass 2 after bands frozen. Keep raw values + day indices.
    ep_days = []          # list per episode: list of (i, dict of raw axis values)
    raw_dev = defaultdict(list)
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
            e_end = e['end']
            days = []
            hist = [0.0]*NBUCKETS; vsum = 0.0; tp_lo = None; tp_hi = None
            run_high = None
            baseline = (vs[s_i]-vs[max(0,s_i-20)])/max(1, min(20, s_i)) if s_i >= 1 else None
            for i in range(s_i, n):
                if ds[i] > e_end: break
                cl = closes[i]
                if not (cl > 0 and highs[i] > 0 and lows[i] > 0): continue
                # cost running
                tp = (highs[i]+lows[i]+cl)/3; v = vols[i]
                if tp_lo is None: tp_lo = tp_hi = tp
                tp_lo = min(tp_lo, tp); tp_hi = max(tp_hi, tp)
                span = tp_hi-tp_lo
                b = 0 if span <= 0 else min(NBUCKETS-1, int((tp-tp_lo)/span*NBUCKETS))
                hist[b] += v; vsum += v
                p25 = wq(hist, tp_lo, tp_hi, vsum, 0.25); p75 = wq(hist, tp_lo, tp_hi, vsum, 0.75); med = wq(hist, tp_lo, tp_hi, vsum, 0.5)
                cost_pos = 0 if cl < p25 else (2 if cl > p75 else 1)
                dist_c = cl/med-1 if med > 0 else None
                # axes
                r20s = None; r20m = None
                if i >= 20 and closes[i-20] > 0:
                    r20 = cl/closes[i-20]-1
                    sr = sec_ret20.get((l2, ds[i])) if l2 else None
                    mr = mkt_ret20.get(ds[i])
                    r20s = r20-sr if sr is not None else None
                    r20m = r20-mr if mr is not None else None
                struct = cl/((cs[i+1]-cs[max(0,i-59)])/max(1,min(60,i+1)))-1 if i >= 1 else None
                run_high = cl if run_high is None else max(run_high, cl)
                epdd = cl/run_high-1 if run_high > 0 else None
                v20 = (vs[i+1]-vs[max(0,i-19)])/max(1, min(20, i+1))
                part = v20/baseline if baseline and baseline > 0 else None
                row = {'i': i, 'd': ds[i], 'rps': r20s, 'rpm': r20m, 'struct': struct, 'epdd': epdd, 'part': part, 'cost': cost_pos, 'dist': dist_c}
                days.append(row)
                if e['start'] <= '2023-12-31':
                    for k in ('rps', 'rpm', 'struct', 'epdd', 'part'):
                        if row[k] is not None: raw_dev[k].append(row[k])
            ep_days.append((e, days))
    print('episode-day axes computed ({:.0f}s)'.format(time.time()-t0))
    bands = {k: qs(v, (1/3, 2/3)) for k, v in raw_dev.items()}
    print('frozen bands:', bands)
    def band(ax, v):
        if v is None: return None
        lo, hi = bands[ax]
        return 'LOW' if v < lo else 'HIGH' if v >= hi else 'MID'
    # pass 2: states + sampling + forward
    HORIZONS = (5, 20, 60)
    def state_of(row):
        rps = band('rps', row['rps']); rpm = band('rpm', row['rpm']); part = band('part', row['part'])
        if rps == 'LOW' and rpm == 'LOW' and (row['cost'] == 0 or part == 'LOW'):
            return 'DECAYING'
        if (rps == 'HIGH' or rpm == 'HIGH') and part != 'LOW':
            return 'STRENGTHENING'
        return 'HOLDING'
    # per episode: state seq, samples
    results = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))  # origin->split->metric->list
    state_census = Counter(); state_days = Counter()
    seq_census = Counter()
    for e, days in ep_days:
        if not days: continue
        states = [state_of(r) for r in days]
        for s in states: state_days[s] += 1
        # state sequence (compressed)
        comp = []
        for s in states:
            if not comp or comp[-1] != s: comp.append(s)
        seq_census['->'.join(comp[:6])] += 1
        first_entry = {}
        for j, s in enumerate(states):
            if s not in first_entry: first_entry[s] = j
        # weekly first sessions
        week_first = set()
        last_w = None
        for j, r in enumerate(days):
            w = r['d'][:10]
            iso = r['d']
            wk = iso
            if wk != last_w and (last_w is None or wk[:7] != last_w[:7] or True):
                pass
        # simpler: first trading day of each ISO week within episode
        seen_week = set()
        for j, r in enumerate(days):
            wk = r['d']
            import datetime
            dt = datetime.date(*map(int, wk.split('-')))
            isowk = dt.isocalendar()[:2]
            if isowk not in seen_week:
                seen_week.add(isowk); week_first.add(j)
        samples = sorted(set([0]) | week_first | set(first_entry.values()))
        closes_needed = days
        e_dev = e['start'] <= '2023-12-31'
        split = 'dev' if e_dev else 'holdout'
        org = e['origin']
        for j in samples:
            if j >= len(days): continue
            s_now = states[j]
            for H in HORIZONS:
                endj = min(len(days), j+H+1)
                if j+H >= len(days) and e['terminal'] == 'CENSORED' and j+H >= len(days):
                    pass  # still record with truncation flag
                if endj <= j+1: continue
                fut = states[j+1:endj]
                dd = min(r['epdd'] if r['epdd'] is not None else 0 for r in days[j+1:endj]) if len(fut) else None
                still_str = fut[-1] == 'STRENGTHENING' if fut else None
                entered_decay = 'DECAYING' in fut
                failed_within = e['terminal'] == 'STRUCTURAL_FAILURE' and days[-1]['i'] <= days[min(j+H, len(days)-1)]['i']
                alive = not (e['terminal'] == 'STRUCTURAL_FAILURE' and len(fut) > 0 and j+H < len(days))
                rs_chg = None
                if days[min(j+H, len(days)-1)]['rps'] is not None and days[j]['rps'] is not None:
                    rs_chg = days[min(j+H, len(days)-1)]['rps']-days[j]['rps']
                key_metrics = {
                    'P_still_STR_at_H': 1.0 if still_str else (0.0 if still_str is not None else None),
                    'P_decay_within_H': 1.0 if entered_decay else 0.0,
                    'P_fail_within_H': 1.0 if failed_within else 0.0,
                    'fwd_dd': dd, 'rs_chg': rs_chg}
                for mk, mv in key_metrics.items():
                    if mv is not None:
                        results[org][split][f'{s_now}|{mk}|H{H}'].append(mv)
                        results['ALL'][split][f'{s_now}|{mk}|H{H}'].append(mv)
    def med(v):
        s = sorted(x for x in v if x is not None)
        return round(s[len(s)//2], 4) if s else None
    def mean(v):
        vv = [x for x in v if x is not None]
        return round(sum(vv)/len(vv), 4) if vv else None
    out = {'generated': time.strftime('%Y-%m-%dT%H:%M:%S'), 'frozen_bands': bands,
           'state_day_census': dict(state_days),
           'state_sequence_top': dict(seq_census.most_common(10)),
           'validation': {org: {split: {k: {'n': len(v), 'mean': mean(v) if '|P_' in k else None, 'median': med(v)}
                                for k, v in d.items()}
                                for split, d in splits.items()} for org, splits in results.items()}}
    json.dump(out, open(OUT, 'w'), indent=1)
    print('state days:', dict(state_days))
    print('top state seqs:', dict(seq_census.most_common(6)))
    # print key validation medians
    for org in ('ALL', 'L', 'M', 'S'):
        for split in ('dev', 'holdout'):
            d = out['validation'].get(org, {}).get(split, {})
            for h in ('H5','H20','H60'):
                for k in sorted(d):
                    if ('STRENGTHENING|P_still_STR_at_H|'+h) in k or ('DECAYING|P_fail_within_H|'+h) in k or ('HOLDING|P_decay_within_H|'+h) in k or ('STRENGTHENING|P_decay_within_H|'+h) in k:
                        print(org, split, k, 'n=', d[k]['n'], 'P=', d[k]['mean'])
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
