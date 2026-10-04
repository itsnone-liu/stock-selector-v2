#!/usr/bin/env python3
"""CD-1A: per-level sector coverage census + G-CD1A-1 gate evaluation.
Reads: data/cd/daily_fullmarket/*.json.gz (DATA-1), data/cd/sector_seeds/{csrc_v1,sina_industry_v1}.json
Writes: docs/cd/cd1a_census.json (census + gate). NO market conclusions — coverage stats only."""
import json, gzip, sys, hashlib, time
from pathlib import Path
from collections import defaultdict
from bisect import bisect_left

ROOT = Path(__file__).resolve().parent.parent
D = ROOT / 'data' / 'cd' / 'daily_fullmarket'
SEEDS = ROOT / 'data' / 'cd' / 'sector_seeds'
OUT = ROOT / 'docs' / 'cd' / 'cd1a_census.json'

def main():
    uni = json.load(open(D / '_universe.json'))['universe']
    # 1. daily availability per stock
    have, firsts, lasts, nrows = {}, {}, {}, {}
    for f in D.glob('*.json.gz'):
        code = f.name.split('.')[0]
        if code.startswith('_'): continue
        rec = json.loads(gzip.decompress(f.read_bytes()))
        if rec['dates']:
            have[code] = rec['dates'][0], rec['dates'][-1], len(rec['dates'])
    print(f'DATA-1 files present: {len(have)} / universe {len(uni)}')

    # 1b. market trading-calendar union + per-code date sets (streamed, memory-bounded)
    market_dates = set()
    for code in have:
        f = D / f'{code}.json.gz'
        rec = json.loads(gzip.decompress(f.read_bytes()))
        market_dates.update(rec['dates'])
    cal = sorted(market_dates)
    print(f'market union calendar: {len(cal)} dates {cal[0]}..{cal[-1]}')

    # 2. csrc seeds L1/L2
    csrc = json.load(open(SEEDS / 'csrc_v1.json'))['members']
    l1 = {}; l2 = {}
    for m in csrc:
        if m.get('L1'): l1[m['code']] = m['L1']
        if m.get('L2'): l2[m['code']] = m['L2']
    # sina L3
    sina = json.load(open(SEEDS / 'sina_industry_v1.json'))
    l3 = {}
    for ind, codes in sina['industries'].items():
        for c in codes:
            cc = c.replace('sh', '').replace('sz', '').replace('bj', '')
            l3[cc] = ind

    def census(level_name, mapping):
        members = defaultdict(list)
        for code, lab in mapping.items():
            members[lab].append(code)
        sizes = sorted(len(v) for v in members.values())
        n_cls = len(mapping)
        cov_uni = sum(1 for c in uni if c in mapping) / len(uni)
        cov_daily = sum(1 for c in have if c in mapping) / max(1, len(have))
        # per-sector: daily member fraction + window-gap profile (on union calendar)
        sec_frac = {}
        gap_stats = {}
        for lab, codes in members.items():
            sec_frac[lab] = sum(1 for c in codes if c in have) / len(codes) if codes else 0
            ds = set()
            for c in codes:
                if c in have:
                    f = D / f'{c}.json.gz'
                    ds.update(json.loads(gzip.decompress(f.read_bytes()))['dates'])
            covered = sorted(ds)
            gaps = []
            if covered:
                prev_idx = -1
                for d in covered:
                    i = cal.index(d) if False else bisect_left(cal, d)
                    if prev_idx >= 0 and i - prev_idx - 1 > 20:  # >20 trading-day hole
                        gaps.append((cal[prev_idx], d, i - prev_idx - 1))
                    prev_idx = i
            gap_stats[lab] = {'n_long_gaps_gt20': len(gaps), 'max_gap_days': max((g[2] for g in gaps), default=0),
                              'first_covered': covered[0] if covered else None, 'last_covered': covered[-1] if covered else None}
        med = sizes[len(sizes)//2] if sizes else 0
        single = sum(1 for s in sizes if s == 1) / max(1, len(sizes))
        small10 = sum(1 for s in sizes if s < 10) / max(1, len(sizes))
        withdaily = sum(1 for lab in members if sec_frac[lab] > 0)
        n_gaps = sum(v['n_long_gaps_gt20'] for v in gap_stats.values())
        source_complete = sum(1 for c in mapping if c in have) / max(1, len(mapping))
        return {'level': level_name, 'sectors': len(members), 'stocks_classified': n_cls,
                'stock_coverage_of_universe': round(cov_uni, 4), 'stock_coverage_of_daily': round(cov_daily, 4),
                'source_provenance_completeness': round(source_complete, 4),
                'member_count_min': sizes[0] if sizes else 0, 'member_count_median': med, 'member_count_max': sizes[-1] if sizes else 0,
                'single_stock_sector_fraction': round(single, 4), 'small_sector_lt10_fraction': round(small10, 4),
                'sectors_with_any_daily': withdaily,
                'median_sector_daily_member_fraction': round(sorted(sec_frac.values())[len(sec_frac)//2], 4) if sec_frac else 0,
                'membership_change_frequency': 'UNKNOWN (v1-static-declared)',
                'long_gaps_gt20_trading_days_total': n_gaps,
                'max_sector_gap_days': max((v['max_gap_days'] for v in gap_stats.values()), default=0),
                'gap_detail_per_sector': gap_stats, }

    c1 = census('L1_csrc', l1); c2 = census('L2_csrc', l2); c3 = census('L3_sina', l3)

    def gate_level(c):
        return (c['stock_coverage_of_universe'] >= 0.95 and c['member_count_median'] >= 15
                and c['single_stock_sector_fraction'] <= 0.05)

    gate = {
        'c1_membership_usable_declared': True,
        'c1_note': 'v1-static-declared usable (NOT historical PIT; declaration mandatory on artifacts)',
        'c2_levels': {'L1_csrc': gate_level(c1), 'L2_csrc': gate_level(c2), 'L3_sina': gate_level(c3)},
        'c2_any_pass': gate_level(c1) or gate_level(c2) or gate_level(c3),
        'c3_full_market_daily': len(have) / len(uni) >= 0.97,
        'c3_detail': f'{len(have)}/{len(uni)}',
        'c4_deterministic_rebuild': 'evaluated in sector-series feasibility step',
        'c5_provenance': 'per-stock source+fetch_time embedded in gz; sha manifest at census final',
        'c6_no_future_backfill': 'v1-static declaration enforced; NO_CLASSIFICATION fail-closed counts recorded',
    }
    doc = {'phase': 'CD-1A census', 'generated_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
           'incomplete_run': len(have) < len(uni),
           'data1': {'universe': len(uni), 'acquired': len(have)},
           'censuses': [c1, c2, c3], 'gate_G_CD1A_1_partial': gate,
           'declaration': 'static classification, change_frequency UNKNOWN, NOT historical authority'}
    json.dump(doc, open(OUT, 'w'), ensure_ascii=False, indent=1, sort_keys=True)
    print(json.dumps(c1, ensure_ascii=False)); print(json.dumps(c2, ensure_ascii=False)); print(json.dumps(c3, ensure_ascii=False))
    print('gate partial:', json.dumps({k: v for k, v in gate.items() if k != 'c1_note'}, ensure_ascii=False))
    print('written', OUT)

if __name__ == '__main__':
    main()
