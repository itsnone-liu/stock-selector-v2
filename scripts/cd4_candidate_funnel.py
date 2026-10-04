#!/usr/bin/env python3
"""CD-4 L3 Candidate Funnel: exclusions -> 3-timescale triggers -> compression eval -> sector metadata.
Preregistered: docs/cd/cd4_preregistration.json. Monthly checkpoints."""
import json, gzip, time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
D = ROOT/'data'/'cd'/'daily_fullmarket'
ST = ROOT/'data'/'cd'/'sector_axes'/'l2_state_table.json.gz'
OUT_R = ROOT/'docs'/'cd'/'cd4_funnel_results.json'
OUT_C = ROOT/'data'/'cd'/'l3_candidate_pool.json.gz'

def main():
    t0 = time.time()
    # load all stocks compactly
    stocks = {}
    for f in sorted(D.glob('*.json.gz')):
        c = f.name.split('.')[0]
        if c.startswith('_'): continue
        rec = json.loads(gzip.decompress(f.read_bytes()))
        if not rec['dates']: continue
        closes = [float(r[2]) for r in rec['qfq']]
        vols = [float(r[5]) for r in rec['unadj']]
        stocks[c] = (rec['dates'], closes, vols)
    print('stocks:', len(stocks), '({:.0f}s)'.format(time.time()-t0))
    # sector state index (l2,date)->base/path
    st = json.loads(gzip.decompress(ST.read_bytes()))['states']
    sec_of = {}
    csrc = json.load(open(ROOT/'data'/'cd'/'sector_seeds'/'csrc_v1.json'))['members']
    for m in csrc:
        if m.get('L2'): sec_of[m['code']] = m['L2']
    state_idx = {(s['l2'], s['date']): s for s in st if s.get('base')}
    # monthly checkpoints: last trading day of each month from union calendar
    all_dates = sorted({d for ds, _, _ in stocks.values() for d in ds})
    by_month = defaultdict(list)
    for d in all_dates: by_month[d[:7]].append(d)
    cps = [ds[-1] for m, ds in sorted(by_month.items())]
    cps = [c for c in cps if c >= '2021-06-01']  # need >=500d history for T_LONG
    print('checkpoints:', len(cps), cps[0], '..', cps[-1])
    # market 20d total volume per date + market volume percentile inputs computed per checkpoint
    # per checkpoint evaluation
    results = []
    pool_all = {}
    prev_pool = None
    for cp in cps:
        # per-stock data up to cp
        elig = {}
        vol20_all = {}
        for c, (ds, closes, vols) in stocks.items():
            # positions <= cp
            n = len(ds)
            # binary search
            lo, hi = 0, n
            while lo < hi:
                mid = (lo+hi)//2
                if ds[mid] <= cp: lo = mid+1
                else: hi = mid
            i = lo  # count of sessions <= cp
            if i == 0: continue
            info = {'i': i, 'close': closes[i-1], 'ds': ds, 'closes': closes, 'vols': vols}
            # RQ1 exclusions
            reason = None
            if i < 120: reason = 'EXCLUDED_NEW'
            elif info['close'] < 2.0: reason = 'EXCLUDED_LOW_PRICE'
            else:
                w60 = vols[max(0,i-60):i]
                act = sum(1 for v in w60 if v > 0)
                if act < 10: reason = 'EXCLUDED_SUSPENDED'
            if reason is None:
                w20 = vols[max(0,i-20):i]
                if len(w20) == 20 and sum(w20) > 0:
                    vol20_all[c] = sum(w20)/20
                    elig[c] = info
                else:
                    elig[c] = dict(info, illiq=True)
            else:
                elig[c] = dict(info, excl=reason)
        # liquidity percentile
        if vol20_all:
            vals = sorted(vol20_all.values())
            p2 = vals[max(0, int(len(vals)*0.02)-1)]
        else:
            p2 = 0
        lvl_excl = []
        excl_counts = defaultdict(int)
        for c, info in elig.items():
            if 'excl' in info: excl_counts[info['excl']] += 1
            elif info.get('illiq') or vol20_all.get(c) is None: excl_counts['EXCLUDED_ILLIQUID'] += 1
            elif vol20_all[c] < p2: excl_counts['EXCLUDED_ILLIQUID'] += 1
            else: lvl_excl.append(c)
        # triggers
        # market 20d mean total volume at cp for volume-share
        mktv20 = None
        # T_LONG / T_MID / T_SHORT
        lvl_long = []; lvl_mid = []; lvl_full = []
        volshare_now = {}; volshare_year = {}
        for c in lvl_excl:
            ds, closes, vols = elig[c]['ds'], elig[c]['closes'], elig[c]['vols']
            i = elig[c]['i']
            # T_LONG: 500-session mean & 24m return
            if i < 500: continue
            m500 = sum(closes[i-500:i])/500
            ret24 = closes[i-1]/closes[i-500]-1
            if not (closes[i-1] > m500 and ret24 > 0): continue
            lvl_long.append(c)
            # T_MID: 65-session return>0 and volume share ratio
            if i < 250: continue
            ret65 = closes[i-1]/closes[i-65]-1
            v20 = sum(vols[i-20:i])/20
            y250 = vols[i-250:i]
            # stock volume share needs market — approximated by ratio of own v20 to own 250d median v20 (self-relative participation)
            med = sorted(vols[i-250:i])[len(vols[i-250:i])//2]
            if not (ret65 > 0 and med > 0 and v20 > 1.5*med): continue
            lvl_mid.append(c)
            # T_SHORT: 60d new high on 2x volume day within trailing 20 sessions
            hit = False
            for k in range(max(60, i-20), i):
                if closes[k] >= max(closes[k-60+1:k+1]) and vols[k] > 2*(sum(vols[max(0,k-20):k])/max(1,k-max(0,k-20))):
                    hit = True; break
            if hit: lvl_full.append(c)
        # recall ground truth: forward 60d rel return top decile among lvl_excl (evaluation only)
        fwd = {}
        for c in lvl_excl:
            ds, closes = elig[c]['ds'], elig[c]['closes']
            i = elig[c]['i']
            if i+60 < len(ds):
                fwd[c] = closes[i+60]/closes[i-1]-1
        if fwd:
            mret = sum(fwd.values())/len(fwd)
            ranked = sorted(fwd.items(), key=lambda kv: -(kv[1]-mret))
            top = set(c for c, _ in ranked[:max(1, len(ranked)//10)])
            rec = {'top_decile_n': len(top),
                   'recall_excl': round(len(top & set(lvl_excl))/len(top), 4),
                   'recall_long': round(len(top & set(lvl_long))/len(top), 4),
                   'recall_mid': round(len(top & set(lvl_mid))/len(top), 4),
                   'recall_full': round(len(top & set(lvl_full))/len(top), 4)}
        else:
            rec = None
        # sector metadata for lvl_full
        pool = {}
        for c in lvl_full:
            l2 = sec_of.get(c)
            meta = None
            if l2:
                srow = state_idx.get((l2, cp))
                if srow:
                    meta = {'l2': l2, 'base': srow['base'], 'path': srow.get('path')}
                    # narrowing risk within trailing 10 sessions
                    nar = False
                    for k in range(1, 11):
                        s2 = state_idx.get((l2, elig[c]['ds'][elig[c]['i']-k] if elig[c]['i']-k >= 0 else ''))
                        if s2 and s2.get('path') == 'NARROWING': nar = True; break
                    meta['narrowing_risk'] = nar
            pool[c] = meta
        # turnover vs prev checkpoint
        if prev_pool is not None:
            a, b = set(pool), set(prev_pool)
            jac = len(a & b)/len(a | b) if (a | b) else 1.0
        else:
            jac = None
        results.append({'checkpoint': cp, 'universe': len(elig), 'excluded': dict(excl_counts),
                        'lvl_excl': len(lvl_excl), 'lvl_long': len(lvl_long), 'lvl_mid': len(lvl_mid),
                        'lvl_full': len(lvl_full), 'recall': rec, 'pool_jaccard_vs_prev': round(jac, 4) if jac is not None else None})
        pool_all[cp] = pool
        prev_pool = pool
        if len(results) % 10 == 0: print(cp, 'full pool:', len(lvl_full), '({:.0f}s)'.format(time.time()-t0))
    # summary dev/holdout
    def summ(split):
        rs = [r for r in results if (r['checkpoint'] <= '2023-12-31') == (split == 'dev')]
        if not rs: return None
        import statistics as st2
        def med(k): return st2.median([r[k] for r in rs if r[k] is not None])
        recs = [r['recall'] for r in results if (r['checkpoint'] <= '2023-12-31') == (split == 'dev') and r['recall']]
        return {'n_checkpoints': len(rs),
                'median_lvl_excl': med('lvl_excl'), 'median_lvl_long': med('lvl_long'),
                'median_lvl_mid': med('lvl_mid'), 'median_lvl_full': med('lvl_full'),
                'median_recall_full': st2.median([r['recall_full'] for r in recs]) if recs else None,
                'median_recall_mid': st2.median([r['recall_mid'] for r in recs]) if recs else None,
                'median_turnover_jaccard': med('pool_jaccard_vs_prev'),
                'median_excluded': {k: st2.median([r['excluded'].get(k, 0) for r in rs]) for k in ('EXCLUDED_NEW','EXCLUDED_LOW_PRICE','EXCLUDED_SUSPENDED','EXCLUDED_ILLIQUID')}}
    out = {'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'n_checkpoints': len(results),
           'summary': {'dev': summ('dev'), 'holdout': summ('holdout')},
           'checkpoints': results}
    json.dump(out, open(OUT_R, 'w'), indent=1)
    OUT_C.write_bytes(gzip.compress(json.dumps({'pools': {k: {c: m for c, m in v.items()} for k, v in pool_all.items()}}, separators=(',', ':')).encode(), 6))
    print('summary dev:', out['summary']['dev'])
    print('summary holdout:', out['summary']['holdout'])
    print('done ({:.0f}s)'.format(time.time()-t0))

if __name__ == '__main__':
    main()
