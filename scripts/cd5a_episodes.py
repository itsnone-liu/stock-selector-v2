#!/usr/bin/env python3
"""CD-5A+5C: daily source states -> persistent episodes with running cost-proxy bands and termination.
Preregistered: docs/cd/cd5_preregistration.json. Sources VERBATIM from V2. Prefix-sum/monotonic-queue optimized."""
import json, gzip, time
from pathlib import Path
from collections import defaultdict, Counter, deque

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
AX = ROOT/'data'/'cd'/'sector_axes'/'l2_four_axes.json.gz'
OUT = ROOT/'data'/'cd'/'l4_episodes.json.gz'
OUT_C = ROOT/'docs'/'cd'/'cd5a_episode_census.json'
NBUCKETS = 50  # cost histogram buckets (weighted-quantile approximation, preregistered implementation)

def main():
    t0 = time.time()
    sec_of = {}
    for m in json.load(open(ROOT/'data'/'cd'/'sector_seeds'/'csrc_v1.json'))['members']:
        if m.get('L2'): sec_of[m['code']] = m['L2']
    # context at start: sector state/path per (l2,date)
    st = json.loads(gzip.decompress((ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz').read_bytes()))['states']
    state_idx = {(s['l2'], s['date']): (s['base'], s.get('path')) for s in st if s.get('base')}
    ax = json.loads(gzip.decompress(AX.read_bytes()))['rows']
    mkt_ret20 = {}
    sec_ret20 = {}
    # build market eq cumulative per date
    mkt_by_date = {}
    for r in ax:
        if r['status'] == 'OK' and r['mkt_eq'] is not None:
            mkt_by_date.setdefault(r['date'], []).append(r['mkt_eq'])
    mkt_hist = []
    c = 1.0
    for d in sorted(mkt_by_date):
        r_bar = sum(mkt_by_date[d])/len(mkt_by_date[d])
        c *= (1.0 + r_bar)
        mkt_hist.append((d, c))
    for i, (d, cv) in enumerate(mkt_hist):
        if i >= 20:
            mkt_ret20[d] = mkt_hist[i][1]/mkt_hist[i-20][1]-1
    # sector cumulative per l2
    sec_by_date = defaultdict(dict)
    for r in ax:
        if r['status'] == 'OK' and r['sector_eq'] is not None:
            sec_by_date[r['l2']][r['date']] = r['sector_eq']
    sec_hist = {}
    sec_ret20 = {}
    for l2, byd in sec_by_date.items():
        hist = []; c = 1.0
        for d in sorted(byd):
            c *= (1+byd[d]); hist.append((d, c))
        sec_hist[l2] = hist
        for i in range(20, len(hist)):
            sec_ret20[(l2, hist[i][0])] = hist[i][1]/hist[i-20][1]-1
    # regime daily + mode
    l1 = json.loads(gzip.decompress((ROOT/'data'/'cd'/'sector_axes'/'l1_market_axes.json.gz').read_bytes()))['rows']
    reg_daily = {r['date']: r['regime'] for r in l1}
    print('context loaded ({:.0f}s)'.format(time.time()-t0))
    # main pass per stock
    episodes = []
    ep_of_stock = {}
    n_src_days = Counter()
    for f in sorted(D.glob('*.json.gz')):
        code = f.name.split('.')[0]
        if code.startswith('_'): continue
        rec = json.loads(gzip.decompress(f.read_bytes()))
        ds = rec['dates']
        if len(ds) < 130: continue
        closes = [float(r[2]) for r in rec['qfq']]
        highs = [float(r[3]) for r in rec['qfq']]
        lows = [float(r[4]) for r in rec['qfq']]
        vols = [float(r[5]) for r in rec['unadj']]
        n = len(ds)
        # prefix sums
        cs = [0.0]*(n+1); vs = [0.0]*(n+1)
        for i in range(n):
            cs[i+1] = cs[i]+closes[i]; vs[i+1] = vs[i]+vols[i]
        # rolling max of closes over 60 (inclusive) via deque
        is60high = [False]*n
        dq = deque()
        for i in range(n):
            while dq and dq[0] < i-59: dq.popleft()
            while dq and closes[dq[-1]] <= closes[i]: dq.pop()
            dq.append(i)
            is60high[i] = dq[0] == i
        # 2x volume day
        is2x = [False]*n
        for i in range(n):
            w = vs[i]-vs[max(0,i-20)]
            k = i-max(0,i-20)
            if k > 0 and vols[i] > 2*(w/k): is2x[i] = True
        evday = [is60high[i] and is2x[i] for i in range(n)]
        evpre = [0]*(n+1)
        for i in range(n): evpre[i+1] = evpre[i]+(1 if evday[i] else 0)
        # daily source booleans
        src = []
        for i in range(n):
            L = M = S = False
            if i >= 500 and closes[i] > 0 and closes[i-500] > 0 and closes[i] > (cs[i]-cs[i-500])/500 and closes[i]/closes[i-500]-1 > 0: L = True
            if i >= 250:
                v20 = (vs[i]-vs[i-20])/20
                med = sorted(vols[i-250:i])[125]
                if closes[i-65] > 0 and closes[i]/closes[i-65]-1 > 0 and med > 0 and v20 > 1.5*med: M = True
            if i >= 60 and evpre[i+1]-evpre[max(0,i-19)] > 0: S = True
            src.append((L, M, S))
            if L: n_src_days['L'] += 1
            if M: n_src_days['M'] += 1
            if S: n_src_days['S'] += 1
        # episode walk
        active = None  # dict
        last_any_true = -1
        l2 = sec_of.get(code)
        for i in range(n):
            L, M, S = src[i]
            any_true = L or M or S
            if active is None:
                if any_true:
                    org = 'L' if L else 'M' if M else 'S'
                    active = {'stock': code, 'ord': ep_of_stock.get(code, 0)+1, 'start': ds[i],
                              'origin': org, 'events': {}, 'seq': [],
                              'baseline_v20': (vs[i]-vs[i-20])/20 if i >= 20 else None,
                              'last_src_true': i}
                    ep_of_stock[code] = active['ord']
                    for k, nm in ((0,'L'),(1,'M'),(2,'S')):
                        if (L,M,S)[k]: active['events'][nm] = ds[i]; active['seq'].append(nm)
            else:
                if any_true: active['last_src_true'] = i
                for k, nm in ((0,'L'),(1,'M'),(2,'S')):
                    if (L,M,S)[k] and nm not in active['events']:
                        active['events'][nm] = ds[i]; active['seq'].append(nm)
                # INACTIVE_TERMINATION: 40 consecutive sessions no source true
                if i - active['last_src_true'] >= 40:
                    active['terminal'] = 'INACTIVE_TERMINATION'; active['end'] = ds[i]
                    episodes.append(active); active = None; continue
            if active is None: continue
            # running histogram (bucketed weighted quantiles) — fail-closed: skip invalid rows
            if not (highs[i] > 0 and lows[i] > 0 and closes[i] > 0 and vols[i] >= 0):
                continue
            tp = (highs[i]+lows[i]+closes[i])/3
            v = vols[i]
            active.setdefault('tp_lo', None)
            if active.get('tp_lo') is None:
                active['tp_lo'] = tp; active['tp_hi'] = tp
            active['tp_lo'] = min(active['tp_lo'], tp); active['tp_hi'] = max(active['tp_hi'], tp)
            active.setdefault('hist', [0.0]*NBUCKETS)
            active.setdefault('vw_sum', 0.0); active.setdefault('v_sum', 0.0)
            span = active['tp_hi']-active['tp_lo']
            b = 0 if span <= 0 else min(NBUCKETS-1, int((tp-active['tp_lo'])/span*NBUCKETS))
            active['hist'][b] += v; active['vw_sum'] += tp*v; active['v_sum'] += v
            # STRUCTURAL_FAILURE check: close < P25 proxy for 15 consecutive AND participation<0.5
            if active['v_sum'] > 0 and span >= 0:
                # weighted P25
                target = active['v_sum']*0.25; acc = 0.0; p25 = active['tp_lo']
                for bi in range(NBUCKETS):
                    if acc+active['hist'][bi] >= target:
                        frac = (target-acc)/max(1e-9, active['hist'][bi])
                        p25 = active['tp_lo']+(bi+frac)/NBUCKETS*span
                        break
                    acc += active['hist'][bi]
                active['p25'] = p25
                v20now = (vs[i]-vs[max(0,i-19)])/max(1,min(20,i))
                baseline = active['baseline_v20'] or 0
                if baseline > 0:
                    part_ratio = v20now/baseline
                    if closes[i] < p25 and part_ratio < 0.5:
                        active['fail_streak'] = active.get('fail_streak', 0)+1
                    else:
                        active['fail_streak'] = 0
                    if active.get('fail_streak', 0) >= 15:
                        active['terminal'] = 'STRUCTURAL_FAILURE'; active['end'] = ds[i]
                        episodes.append(active); active = None; continue
                else:
                    active['fail_streak'] = 0
            else:
                active['fail_streak'] = 0
        if active is not None:
            active['terminal'] = 'CENSORED'; active['end'] = ds[-1]
            episodes.append(active)
        # strip working fields
        for e in episodes:
            if e.get('stock') == code:
                e.pop('hist', None); e.pop('tp_lo', None); e.pop('tp_hi', None); e.pop('vw_sum', None); e.pop('v_sum', None); e.pop('fail_streak', None); e.pop('p25', None); e.pop('last_src_true', None); e.pop('baseline_v20', None)
    # attach start context
    for e in episodes:
        l2 = sec_of.get(e['stock'])
        e['l2'] = l2
        bs = state_idx.get((l2, e['start'])) if l2 else None
        e['sector_state_at_start'] = bs[0] if bs else None
        e['sector_path_at_start'] = bs[1] if bs else None
        e['regime_daily_at_start'] = reg_daily.get(e['start'])
        e['episode_id'] = f"{e['stock']}#{e['ord']:04d}"
    # census
    cnt = Counter(e['terminal'] for e in episodes)
    org = Counter(e['origin'] for e in episodes)
    seqc = Counter('->'.join(e['seq']) for e in episodes)
    lens = sorted((e['end'] >= e['start']) for e in episodes)
    import statistics as st2
    durations = []
    for e in episodes:
        # duration in sessions approximated by date diff in days/1.45 — recompute exactly later in 5B; here calendar days
        from datetime import date
        d0 = date(*map(int, e['start'].split('-'))); d1 = date(*map(int, e['end'].split('-')))
        durations.append((d1-d0).days)
    census = {'n_episodes': len(episodes), 'terminal': dict(cnt), 'origin': dict(org),
              'source_sequence_top': dict(seqc.most_common(12)),
              'median_calendar_duration_days': st2.median(durations),
              'source_true_days_total': dict(n_src_days)}
    OUT.write_bytes(gzip.compress(json.dumps({'episodes': episodes}, separators=(',', ':')).encode(), 6))
    json.dump(census, open(OUT_C, 'w'), indent=1)
    print(json.dumps(census, indent=1, ensure_ascii=False))
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
