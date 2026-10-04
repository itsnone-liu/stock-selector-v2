#!/usr/bin/env python3
"""CSR-8 Phase I / I4B — External Market Context READOUT.

Executed strictly under frozen I4A contract (sha b1278342...) + semantic
addendum-1 (R4(d)>=5 theory gate vs >=3 output-coverage floor; LOW_COVERAGE
strata contribute signs but never theory-grade claims).

For each eligible relation (ETF 4v8, 8v9):
  overall (naive / date-dedup / leave-max-cluster-out, asserted bitwise vs
  the I3 report) + the same three calibers WITHIN UP / DOWN market-regime
  strata; deterministic context classification per the frozen rule.

Outputs: docs/phase_i/i4b_readout.json (+ report MD written separately).
"""
import json, sys, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
OUT = ROOT / 'docs/phase_i'

import phase_i_i2_unblind as frozen

LOW_COV = ('LOW_COVERAGE — output coverage only; not theory-grade evidence '
           '(R4(d)>=5 unmet in this stratum)')
BANNERS = {
    'general': 'FORBIDDEN: causal language; actor attribution on the ETF layer; '
               "'regime threshold' claims; treating the 120d-median index regime as a "
               'market model (it is a coarse modifier); capital-state labels immutable.',
    'nd_nopit': 'stock_layer ND-vs-NO_PIT: DESCRIPTIVE_ONLY, EXCLUDED from theory '
                're-upgrade by user ruling; context columns are descriptive only.',
}
RELATIONS = [
    {'id': 'ETF_4_vs_8', 'variable': 'etf_expansion_count', 'A': '4', 'B': '8'},
    {'id': 'ETF_8_vs_9', 'variable': 'etf_expansion_count', 'A': '8', 'B': '9'},
]


def readout_rows():
    frozen.ORDINALS = list(range(7, 129))
    mapping = frozen.resolve_mapping()
    frozen.mapped_codes = {m['code'] for m in mapping.values()}
    calendar, _ = frozen.load_calendar()
    rows, _ = frozen.outcomes(mapping, calendar)
    return {r['ordinal']: r for r in rows}


def cliffs(xs, ys):
    gt = lt = 0
    for x in xs:
        for y in ys:
            gt += x > y
            lt += x < y
    n = len(xs) * len(ys)
    return (gt - lt + 0.0) / n if n else None


def sgn(x):
    return None if x is None or x == 0 else ('+' if x > 0 else '-')


def calibers(mA, mB):
    """naive / date-dedup / leave-max-cluster-out for member lists of cases."""
    rA = [c['R5'] for c in mA]
    rB = [c['R5'] for c in mB]
    if not rA or not rB:
        return None
    naive_d = st.median(rA) - st.median(rB)
    naive_delta = cliffs(rA, rB)
    def dedup(ms):
        by = defaultdict(list)
        for c in ms:
            by[c['T']].append(c['R5'])
        return {d: st.median(v) for d, v in by.items()}
    dA, dB = dedup(mA), dedup(mB)
    dedup_d = st.median(dA.values()) - st.median(dB.values()) if dA and dB else None
    cnt = defaultdict(int)
    for c in mA + mB:
        cnt[c['T']] += 1
    maxT = max(cnt, key=lambda d: cnt[d]) if cnt else None
    fA = [c['R5'] for c in mA if c['T'] != maxT]
    fB = [c['R5'] for c in mB if c['T'] != maxT]
    lco_d = st.median(fA) - st.median(fB) if fA and fB else None
    fdA = [v for d, v in dA.items() if d != maxT]
    fdB = [v for d, v in dB.items() if d != maxT]
    lco_dedup = st.median(fdA) - st.median(fdB) if fdA and fdB else None
    return {'nA': len(mA), 'nB': len(mB), 'dates_A': len(dA), 'dates_B': len(dB),
            'naive_d': naive_d, 'naive_cliffs': naive_delta,
            'dedup_d': dedup_d,
            'lco': {'dropped': maxT, 'dropped_cases': cnt.get(maxT),
                    'd_case_level': lco_d, 'd_dedup': lco_dedup},
            'max_date_multiplicity': max(cnt.values()) if cnt else 0,
            'signs': {'naive': sgn(naive_d), 'dedup': sgn(dedup_d),
                      'lco_case': sgn(lco_d), 'lco_dedup': sgn(lco_dedup)}}


def main():
    rows = readout_rows()
    atlas = json.loads((OUT / 'i1_structural_atlas.json').read_text())
    cards = atlas['cards']
    cov = json.loads((OUT / 'i4a_coverage_matrix.json').read_text())
    regime = {int(k): v['regime'] for k, v in cov['per_case_regime'].items()}
    i3 = json.loads((OUT / 'i3_contextual_readout.json').read_text())
    i3_by_rel = {r['relation']: r for r in i3['relation_results']}

    cases = []
    for c in cards.values():
        if c['ordinal'] < 7 or not isinstance(c.get('capital_state'), dict):
            continue
        cell = str(c['capital_state']['etf']['expansion'])
        sl = c['capital_state']['stock_layer_summary']
        cases.append({'ordinal': c['ordinal'], 'T': c['T'], 'R5': rows[c['ordinal']]['R5'],
                      'cell': cell, 'regime': regime[c['ordinal']], 'sl': sl})

    results = []
    for rel in RELATIONS:
        a, b = rel['A'], rel['B']
        mem = [c for c in cases if c['cell'] in (a, b)]
        mA_all = [c for c in mem if c['cell'] == a]
        mB_all = [c for c in mem if c['cell'] == b]
        overall = calibers(mA_all, mB_all)
        # consistency assertion vs I3 (overall numbers identical machinery)
        i3r = i3_by_rel[rel['id']]
        assert overall['nA'] == i3r['naive_case_level']['nA']
        assert overall['nB'] == i3r['naive_case_level']['nB']
        assert abs(overall['naive_d'] - i3r['naive_case_level']['dR5']) < 1e-12
        assert abs(overall['dedup_d'] - i3r['date_dedup_R3']['dR5_dedup']) < 1e-12
        strata = {}
        for strat in ('UP', 'DOWN'):
            sA = [c for c in mA_all if c['regime'] == strat]
            sB = [c for c in mB_all if c['regime'] == strat]
            cc = calibers(sA, sB)
            if cc is None:
                strata[strat] = {'status': 'INSUFFICIENT_CONTEXT_COVERAGE (empty side)'}
                continue
            low = cc['dates_A'] < 5 or cc['dates_B'] < 5
            out_floor = cc['dates_A'] >= 3 and cc['dates_B'] >= 3
            strata[strat] = {
                **cc,
                'output_coverage_floor_met': out_floor,
                'low_coverage': low,
                'low_coverage_banner': LOW_COV if low else None,
                'stratum_r4_theory_grade': (not low) and (
                    sgn(cc['naive_d']) == sgn(cc['dedup_d']) == sgn(cc['lco']['d_case_level'])
                    == sgn(cc['lco']['d_dedup']) is not None)}
        # deterministic context classification (frozen rule)
        d_all = sgn(overall['dedup_d'])
        i3_dir = sgn(i3r['naive_case_level']['dR5'])
        sU = strata.get('UP', {}).get('signs', {}).get('dedup')
        sD = strata.get('DOWN', {}).get('signs', {}).get('dedup')
        if sU is not None and sD is not None and sU == sD == d_all:
            ctx = 'CONTEXT_ROBUST'
        elif d_all == i3_dir and ((sU == d_all) != (sD == d_all)):
            ctx = 'CONDITIONAL'
        elif sU is not None and sD is not None and sU != i3_dir and sD != i3_dir:
            ctx = 'MARKET_COMPOSITION_DEPENDENT'
        else:
            ctx = 'NOT_CLASSIFIABLE (zero-delta or missing stratum)'
        any_low = strata.get('UP', {}).get('low_coverage') or strata.get('DOWN', {}).get('low_coverage')
        results.append({
            'relation': rel['id'], 'cells': {'A': a, 'B': b},
            'overall': overall,
            'consistent_with_I3': True,
            'strata': strata,
            'context_classification': ctx,
            'context_classification_semantics': (
                'CONTEXT_ROBUST · LOW_COVERAGE: no observed contextual sign reversal in '
                'available evidence; DOWN stratum does NOT independently satisfy R4'
                if ctx == 'CONTEXT_ROBUST' and any_low else None),
            'i3_standing': i3r['classification_EXT1']})
    nd = {}
    for strat in ('ALL', 'UP', 'DOWN'):
        sub = [c for c in cases if c['sl'] in
               ('NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10', 'NO_PIT_VISIBLE_REPORT')
               and (strat == 'ALL' or c['regime'] == strat)]
        a = [c['R5'] for c in sub if c['sl'] == 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10']
        b = [c['R5'] for c in sub if c['sl'] == 'NO_PIT_VISIBLE_REPORT']
        key = strat or 'ALL'
        nd[key] = ({'n_ND': len(a), 'n_NO_PIT': len(b),
                    'median_R5_ND': st.median(a) if a else None,
                    'median_R5_NO_PIT': st.median(b) if b else None,
                    'd': (st.median(a) - st.median(b)) if a and b else None}
                   if a or b else {'note': 'empty'})
    report = {
        'phase': 'CSR-8 Phase I / I4B', 'mode': 'frozen-contract execution',
        'contract': 'i4a sha b1278342... + addendum-semantic-1 (two-tier evidence semantics)',
        'relation_results': results,
        'nd_vs_nopit_descriptive_only': nd,
        'banners': BANNERS,
    }
    (OUT / 'i4b_readout.json').write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    for r in results:
        print(json.dumps({'relation': r['relation'],
                          'overall_signs': r['overall']['signs'],
                          'UP': r['strata'].get('UP', {}).get('signs'),
                          'UP_dates': [r['strata'].get('UP', {}).get('dates_A'),
                                       r['strata'].get('UP', {}).get('dates_B')],
                          'DOWN': r['strata'].get('DOWN', {}).get('signs'),
                          'DOWN_dates': [r['strata'].get('DOWN', {}).get('dates_A'),
                                         r['strata'].get('DOWN', {}).get('dates_B')],
                          'context': r['context_classification']}, ensure_ascii=False))
    print('ND/NO_PIT descriptive:', json.dumps(nd, ensure_ascii=False))


if __name__ == '__main__':
    main()
