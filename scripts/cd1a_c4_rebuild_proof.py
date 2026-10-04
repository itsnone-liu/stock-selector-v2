#!/usr/bin/env python3
"""CD-1A c4: sector-series deterministic-rebuild feasibility proof.
From (v1-static membership + DATA-1 daily) build synthetic sector index for ONE FIXED
sector under three weightings; run TWICE; PASS iff byte-identical. No ranking, no
conclusions — feasibility only. Pass 2 rebuilds from scratch and compares hashes."""
import json, gzip, hashlib, sys, time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / 'data' / 'cd' / 'daily_fullmarket'
SEEDS = ROOT / 'data' / 'cd' / 'sector_seeds'
FIXED_SECTOR_L2 = 'C39'   # 计算机、通信和其他电子设备制造业 — fixed BEFORE looking at any return
OUT = ROOT / 'docs' / 'cd' / 'cd1a_c4_rebuild.json'

def load_daily(code):
    f = D / f'{code}.json.gz'
    if not f.exists(): return None
    rec = json.loads(gzip.decompress(f.read_bytes()))
    return {d: (float(r[2]), float(r[5])) for d, r in zip(rec['dates'], rec['unadj'])}  # close, volume

def build():
    members = [m['code'] for m in json.load(open(SEEDS / 'csrc_v1.json'))['members']
               if m.get('L2') == FIXED_SECTOR_L2]
    series = {}
    daily_cache = {}
    for c in members:
        dd = load_daily(c)
        if dd: daily_cache[c] = dd
    all_dates = sorted({d for dd in daily_cache.values() for d in dd})
    for d in all_dates:
        rets_eq, rets_vol, base_close_prev, base_close, vols = [], [], {}, {}, {}
        closes = {c: daily_cache[c].get(d) for c in daily_cache if d in daily_cache[c]}
        prevs = {c: daily_cache[c].get(p) for c in daily_cache for p in [None]}
        # simple deterministic scheme: cross-sectional mean return of members traded on d
        # needs previous close: use each stock's own previous available close <= d
        for c in daily_cache:
            if d not in daily_cache[c]: continue
            dates_sorted = sorted(daily_cache[c])
            i = dates_sorted.index(d)
            if i == 0: continue
            pc = daily_cache[c][dates_sorted[i-1]][0]
            cc, vv = daily_cache[c][d]
            if pc > 0:
                r = (cc - pc) / pc
                rets_eq.append(r); rets_vol.append((r, vv))
        if len(rets_eq) >= 5:  # min participation for the day to count
            series[d] = {
                'eq_weight_return': round(sum(rets_eq)/len(rets_eq), 8),
                'vol_weight_return': round(sum(r*v for r, v in rets_vol)/max(1e-9, sum(v for _, v in rets_vol)), 8),
                'n_members_participating': len(rets_eq),
            }
    return {'sector_L2': FIXED_SECTOR_L2, 'members_with_daily': len(daily_cache),
            'total_members': len(members), 'days_counted': len(series), 'series': series,
            'declaration': 'v1-static membership; volume-weighted uses raw volume (amount unavailable — declared gap); feasibility proof only, NO conclusions'}

def main():
    t0 = time.time()
    s1 = build(); t1 = time.time()
    s2 = build(); t2 = time.time()
    h1 = hashlib.sha256(json.dumps(s1, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(s2, sort_keys=True).encode()).hexdigest()
    determinism = h1 == h2
    doc = {'phase': 'CD-1A c4 deterministic rebuild proof', 'fixed_sector': FIXED_SECTOR_L2,
           'build1_seconds': round(t1-t0, 2), 'build2_seconds': round(t2-t1, 2),
           'sha_build1': h1, 'sha_build2': h2, 'byte_identical': determinism,
           'verdict_c4': 'PASS' if determinism else 'FAIL',
           'sample': {'members_with_daily': s1['members_with_daily'], 'days_counted': s1['days_counted']},
           'declaration': s1['declaration'], 'note': 'full-universe proof re-run after DATA-1 completes; this fixes the SCHEME now, on partial data'}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, sort_keys=True)
    print('c4 verdict:', doc['verdict_c4'], '| members w/ daily:', s1['members_with_daily'], '| days:', s1['days_counted'], f'| {round(t1-t0,1)}s per build')

if __name__ == '__main__':
    main()
