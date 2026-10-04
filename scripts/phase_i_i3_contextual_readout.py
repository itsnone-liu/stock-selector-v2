#!/usr/bin/env python3
"""CSR-8 Phase I / I3 — Contextual Readout (cluster-robust).

Executes the FROZEN I2 preregistration checklist exactly (contract
csr8-phase-i-i2-contextual-preregistration-v1 sha e32bf614..., commit eddd1ff;
addendum-1 with the two user-authorized extensions: three-state classification
and effective-evidence-size reporting). No new variables, no gate changes, no
added context; DEFERRED tiers stay deferred; capital-state labels untouched.

Steps (frozen I2 'i3_execution_plan'):
 1. rebuild C1 sampling context from the I1 atlas (deterministic)
 2. compute C2 margin variables per case from packet evidence (PIT-safe)
 3. recompute the three preregistered relations under R2: naive (with
    consistency assertion vs the frozen third-readout numbers), date-dedup,
    leave-max-cluster-out
 4. apply the R4 hard gate -> THEORY_ELIGIBLE / SAMPLING_DEPENDENT /
    DESCRIPTIVE_ONLY (EXT-1)
 5. effective evidence size per relation (EXT-2)
 6. descriptive-only margin-stratum cross-tab with forbidden-interpretation
    banner
Outputs: docs/phase_i/i3_contextual_readout.json (+ report MD written separately)
"""
import json, sys, statistics as st
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
EVID = ROOT / 'docs/audit/evidence'
OUT = ROOT / 'docs/phase_i'
RC = ROOT / 'data/csr8_phase_c/c4d_receipts/c4-prod-0002'

import phase_i_i2_unblind as frozen
import phase_i_third_readout_128 as third

RELATIONS = [
    {'id': 'SL_ND_vs_NOPIT', 'variable': 'stock_layer_summary',
     'A': 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10', 'B': 'NO_PIT_VISIBLE_REPORT'},
    {'id': 'ETF_4_vs_8', 'variable': 'etf_expansion_count', 'A': '4', 'B': '8'},
    {'id': 'ETF_8_vs_9', 'variable': 'etf_expansion_count', 'A': '8', 'B': '9'},
]
FORBIDDEN_BANNER = ('FORBIDDEN interpretations: margin variables are '
                    'leverage-participation temperature only (mixed participants, CSR-4 '
                    'MULTI scope) — never 大盘趋势 / 国家队态度 / 主力加减仓 / 行业资金流入 / '
                    'market-wide risk-appetite proxy / causal language; context is a '
                    'modifier, capital-state labels are immutable.')


def readout_rows():
    frozen.ORDINALS = list(range(7, 129))
    mapping = frozen.resolve_mapping()
    frozen.mapped_codes = {m['code'] for m in mapping.values()}
    calendar, _ = frozen.load_calendar()
    rows, _ = frozen.outcomes(mapping, calendar)
    return {r['ordinal']: r for r in rows}


def cliffs_delta(xs, ys):
    """Classic Cliff's delta = (|x>y| - |x<y|) / n; ties count in neither side.
    Matches the frozen third-readout implementation (verified: 8v9 -> 114/238
    = 0.4789915966386555 exactly)."""
    gt = lt = 0
    for x in xs:
        for y in ys:
            gt += x > y
            lt += x < y
    n = len(xs) * len(ys)
    return (gt - lt + 0.0) / n if n else None


def margin_ctx(o):
    """C2: packet-internal, PIT-safe by construction (obs<=T-1, avail<=T)."""
    try:
        pj = json.loads((RC / f'ordinal-{o:04d}' / 'packet.json').read_bytes())
    except FileNotFoundError:
        return None
    ev = [e for e in (pj.get('evidence') or []) if '融资余额' in (e.get('payload') or {})]
    if not ev:
        return None
    ev.sort(key=lambda e: e['observation_date'])          # earliest -> latest
    bal = [float(e['payload']['融资余额']) for e in ev]
    buy = [float(e['payload'].get('融资买入额') or 0) for e in ev]
    latest_bal, first_bal = bal[-1], bal[0]
    sign = '+' if latest_bal > first_bal else ('-' if latest_bal < first_bal else '0')
    srt = sorted(buy)
    pos = srt.index(buy[-1]) if buy[-1] in srt else 0     # position of latest buy value
    tercile = 'LOW' if pos < len(srt) / 3 else ('MID' if pos < 2 * len(srt) / 3 else 'HIGH')
    return {'endpoint': ev[0]['endpoint'], 'n_records': len(ev),
            'window_first_obs': ev[0]['observation_date'], 'window_last_obs': ev[-1]['observation_date'],
            'balance_regime_20d': sign, 'buy_intensity_latest': tercile}


def side_of(card, rel):
    cap = card.get('capital_state')
    if not isinstance(cap, dict):
        return None
    if rel['variable'] == 'stock_layer_summary':
        v = cap['stock_layer_summary']
    else:
        v = str(cap['etf']['expansion'])
    return 'A' if v == rel['A'] else ('B' if v == rel['B'] else None)


def analyze(rel, cases, third_target):
    """R2 paired statistics + R4 gate + EXT-1/EXT-2 for one relation."""
    mA = [c for c in cases if c['side'] == 'A']
    mB = [c for c in cases if c['side'] == 'B']
    rA = [c['R5'] for c in mA]
    rB = [c['R5'] for c in mB]
    naive_d = st.median(rA) - st.median(rB)
    naive_delta = cliffs_delta(rA, rB)
    # consistency assertion vs frozen third readout
    ok = (len(mA) == third_target['corpus']['nA'] and len(mB) == third_target['corpus']['nB']
          and abs(naive_d - third_target['corpus']['dR5']) < 1e-9
          and abs(naive_delta - third_target['corpus']['cliffs_delta_R5']) < 1e-9)
    # R3 date-dedup: per (T, side) median -> statistics over dates
    def dedup(members):
        byd = defaultdict(list)
        for c in members:
            byd[c['T']].append(c['R5'])
        return {d: st.median(v) for d, v in byd.items()}
    dA, dB = dedup(mA), dedup(mB)
    dedup_d = st.median(dA.values()) - st.median(dB.values())
    dedup_delta = cliffs_delta(list(dA.values()), list(dB.values()))
    # R4(c) leave-max-cluster-out: drop the largest date (by case count) among
    # this relation's members, recompute BOTH case-level and dedup direction
    cnt = defaultdict(int)
    for c in mA + mB:
        cnt[c['T']] += 1
    maxT = max(cnt, key=lambda d: cnt[d]) if cnt else None
    fA = [c['R5'] for c in mA if c['T'] != maxT]
    fB = [c['R5'] for c in mB if c['T'] != maxT]
    lco_d = st.median(fA) - st.median(fB) if fA and fB else None
    fdA = [v for d, v in dA.items() if d != maxT]
    fdB = [v for d, v in dB.items() if d != maxT]
    lco_dedup_d = st.median(fdA) - st.median(fdB) if fdA and fdB else None
    sgn = lambda x: None if x is None or x == 0 else ('+' if x > 0 else '-')
    # R4 gate
    cl = {'a_naive': sgn(naive_d), 'b_dedup_same': sgn(dedup_d) == sgn(naive_d),
          'c_lco_same': sgn(lco_d) == sgn(naive_d) and sgn(lco_dedup_d) == sgn(naive_d),
          'd_dates_ge5': len(dA) >= 5 and len(dB) >= 5}
    if not cl['d_dates_ge5']:
        cls = 'DESCRIPTIVE_ONLY'
    elif sgn(naive_d) and cl['b_dedup_same'] and cl['c_lco_same']:
        cls = 'THEORY_ELIGIBLE'
    else:
        cls = 'SAMPLING_DEPENDENT'
    effA = {d: len([c for c in mA if c['T'] == d]) for d in dA}
    effB = {d: len([c for c in mB if c['T'] == d]) for d in dB}
    return {
        'relation': rel['id'], 'variable': rel['variable'],
        'cells': {'A': rel['A'], 'B': rel['B']},
        'naive_case_level': {'nA': len(mA), 'nB': len(mB), 'dR5': naive_d,
                             'cliffs_delta_R5': naive_delta,
                             'consistent_with_frozen_third_readout': ok},
        'date_dedup_R3': {'dates_A': len(dA), 'dates_B': len(dB),
                          'dR5_dedup': dedup_d, 'cliffs_delta_dedup': dedup_delta},
        'leave_max_cluster_out_R4c': {
            'dropped_date': maxT, 'dropped_cases': cnt.get(maxT),
            'dR5_case_level': lco_d, 'dR5_dedup': lco_dedup_d},
        'r4_gate': cl, 'classification_EXT1': cls,
        'effective_evidence_size_EXT2': {
            'raw_cases': {'A': len(mA), 'B': len(mB)},
            'distinct_observation_dates': {'A': len(dA), 'B': len(dB)},
            'max_date_multiplicity_in_relation': max(cnt.values()) if cnt else 0,
            'date_dedup_effective_N': {'A': len(dA), 'B': len(dB)},
            'per_date_case_counts': {'A': effA, 'B': effB}}}


def margin_crosstab(cases):
    """Descriptive-only: relation direction within margin-balance strata."""
    rows = []
    for rel in RELATIONS:
        for strat in ('+', '-', '0'):
            sub = [c for c in cases if c['relation'] == rel['id']
                   and c['margin'] and c['margin']['balance_regime_20d'] == strat]
            mA = [c['R5'] for c in sub if c['side'] == 'A']
            mB = [c['R5'] for c in sub if c['side'] == 'B']
            if not mA or not mB:
                rows.append({'relation': rel['id'], 'margin_regime': strat,
                             'nA': len(mA), 'nB': len(mB), 'dR5': None,
                             'note': 'empty side — not reportable'})
                continue
            d = st.median(mA) - st.median(mB)
            rows.append({'relation': rel['id'], 'margin_regime': strat,
                         'nA': len(mA), 'nB': len(mB), 'dR5': d,
                         'sign': '+' if d > 0 else ('-' if d < 0 else '0'),
                         'small_n_warning': len(mA) < 5 or len(mB) < 5})
    return rows


def main():
    rows = readout_rows()
    atlas = json.loads((OUT / 'i1_structural_atlas.json').read_text())
    cards = atlas['cards']
    third_report = json.loads((EVID / 'phase_i_third_readout_128_report.json').read_text())
    targets = {t['variable'] + '|' + str(t['cellA']): t
               for t in third_report['preregistered_persistence_targets_first']}

    # C1 + C2 per case
    c1c2, relcases = {}, defaultdict(list)
    for o in range(7, 129):
        c = cards[str(o)]
        if not isinstance(c.get('capital_state'), dict):
            continue
        m = margin_ctx(o)
        c1c2[o] = {'C1': {'obs_date': c['T'], 'epoch': c['epoch'],
                          'paired_ordinal': c['paired_ordinal'],
                          'date_multiplicity': sum(
                              1 for x in cards.values()
                              if x.get('T') == c['T'] and x['ordinal'] >= 7)},
                   'C2': m}
        for rel in RELATIONS:
            s = side_of(c, rel)
            if s:
                case = {'ordinal': o, 'T': c['T'], 'R5': rows[o]['R5'], 'side': s,
                        'relation': rel['id'], 'margin': m}
                relcases[rel['id']].append(case)

    tgt_map = {'SL_ND_vs_NOPIT': targets['stock_layer_summary|NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10'],
               'ETF_4_vs_8': targets['etf_expansion_count|4'],
               'ETF_8_vs_9': targets['etf_expansion_count|8']}
    results = [analyze(rel, relcases[rel['id']], tgt_map[rel['id']]) for rel in RELATIONS]

    report = {
        'phase': 'CSR-8 Phase I / I3', 'mode': 'frozen-checklist execution',
        'contract': 'i2_contextual_preregistration-v1 sha e32bf614... + addendum-1 (EXT-1 three-state, EXT-2 effective evidence size)',
        'guarantees': ['no new variables', 'no gate changes', 'no added context',
                       'DEFERRED tiers stayed deferred', 'capital-state labels untouched'],
        'C1C2_computed': {str(k): v for k, v in c1c2.items()},
        'relation_results': results,
        'margin_crosstab_descriptive_only': margin_crosstab(
            [c for v in relcases.values() for c in v]),
        'forbidden_interpretation_banner': FORBIDDEN_BANNER,
    }
    (OUT / 'i3_contextual_readout.json').write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    for r in results:
        print(json.dumps({'relation': r['relation'], 'naive': r['naive_case_level'],
                          'dedup': {k: r['date_dedup_R3'][k] for k in ('dates_A', 'dates_B', 'dR5_dedup')},
                          'lco': r['leave_max_cluster_out_R4c'],
                          'gate': r['r4_gate'], 'class': r['classification_EXT1']},
                         ensure_ascii=False))


if __name__ == '__main__':
    main()
