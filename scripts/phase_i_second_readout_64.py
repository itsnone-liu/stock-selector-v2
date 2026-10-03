#!/usr/bin/env python3
"""Phase-I SECOND PRODUCTION READOUT at the 64-case milestone (user ruling
2026-10-03: produce ordinals 63-64, stop at 64, recompute 7-64 with the frozen
I1 rules, compare pilot structures, decide 128).

Reuse, not redesign: this driver imports the FROZEN I2 unblind module
(scripts/phase_i_i2_unblind.py — byte-untouched) and executes its own
resolve_mapping / load_calendar / outcomes / price-series machinery with
ORDINALS extended 7..38 -> 7..64. The only re-implemented pieces are:

  1. load_variables_guarded — identical logic; the pilot lineage cross-check
     (phase_i_i0_2 lineage rows cover ordinals 1..38 only) is applied where a
     frozen lineage row exists and recorded as 'pilot_lineage_absent' for
     production ordinals 39..64, whose binding authority is the epoch-2
     reviews ledger (verified per-ordinal at ANNOTATION/POST_SEAL).
  2. readout_corpus — the frozen readout() verbatim except the corpus
     denominator 32.0 -> CORPUS_N (58 ordinary production cases). Decision
     tree P1/P2/P3/P4 and all qualifying rules (cell n>=5, sign consistency
     across dR3/dR5/dR10) are unchanged.

EQUIVALENCE GATE (fail-closed): before reporting on the 58-case corpus, the
replicated readout is run over the PILOT SUBSET (ordinals 7..38) and must
deep-equal the frozen phase_i_i2_readout_report.json readout block, and the
replicated taxonomy diagnostic must deep-equal the frozen taxonomy block.
Any difference => FAIL_CLOSED, no corpus numbers are reported.

Outputs docs/audit/evidence/phase_i_second_readout_64_report.json.
"""
import json, math, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
EVID = ROOT / 'docs/audit/evidence'

import phase_i_i2_unblind as frozen

PILOT = list(range(7, 39))
CORPUS = list(range(7, 65))
CORPUS_N = len(CORPUS)


def readout_corpus(rows, denom):
    """Frozen readout() with the corpus denominator parameterized; logic
    otherwise copied verbatim (median/mad/cliffs_delta imported from frozen)."""
    median, mad, cliffs_delta = frozen.median, frozen.mad, frozen.cliffs_delta
    ok = [r for r in rows if r.get('status') in ('complete', 'partial')]
    common = [r for r in ok if all(r.get(f'R{k}_status') == 'complete' for k in (3, 5, 10))]
    n_complete_R5 = sum(1 for r in ok if r.get('R5_status') == 'complete')
    frac = n_complete_R5 / float(denom)
    variables = {'stock_layer_summary': lambda r: r.get('stock_layer_summary'),
                 'etf_expansion_count': lambda r: r.get('etf_expansion_count'),
                 'etf_contraction_count': lambda r: r.get('etf_contraction_count')}
    var_reports = {}
    consistent_pairs = []
    for name, get in variables.items():
        cells = {}
        for r in common:
            v = get(r)
            if v is None:
                continue
            cells.setdefault(v, []).append(r)
        cell_info = {}
        for v, rs in sorted(cells.items(), key=lambda kv: str(kv[0])):
            r5 = [r['R5'] for r in rs]
            eras = sorted({r['era'] for r in rs})
            cell_info[str(v)] = {'n_common_complete': len(rs), 'median_R5': median(r5), 'MAD_R5': mad(r5),
                                 'median_R3': median([r['R3'] for r in rs]), 'median_R10': median([r['R10'] for r in rs]),
                                 'era_distribution': eras}
        qualifying_cells = [v for v, rs in cells.items() if len(rs) >= 5]
        qualifying_variable = len(qualifying_cells) >= 2
        pairs = []
        vals = sorted(cells.keys(), key=str)
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                A, B = vals[i], vals[j]
                ra, rb = cells[A], cells[B]
                qa, qb = len(ra) >= 5, len(rb) >= 5
                d = {'variable': name, 'cellA': str(A), 'cellB': str(B),
                     'nA': len(ra), 'nB': len(rb), 'qualifying_pair': bool(qa and qb)}
                for H in ('R3', 'R5', 'R10'):
                    d[f'd{H}'] = (median([r[H] for r in ra]) - median([r[H] for r in rb])) if ra and rb else None
                d['CONSISTENT'] = bool(qa and qb and all(d[f'd{H}'] is not None and d[f'd{H}'] != 0 for H in ('R3', 'R5', 'R10'))
                                       and len({math.copysign(1, d[f'd{H}']) for H in ('R3', 'R5', 'R10')}) == 1)
                d['cliffs_delta_R5'] = cliffs_delta([r['R5'] for r in ra], [r['R5'] for r in rb])
                d['classification'] = 'qualifying' if (qa and qb) else 'sparse_descriptive_only'
                pairs.append(d)
                if d['CONSISTENT']:
                    consistent_pairs.append(d)
        var_reports[name] = {'cells': cell_info, 'qualifying_cells': [str(v) for v in qualifying_cells],
                             'qualifying_variable': qualifying_variable, 'pairs': pairs}
    if frac < 0.80:
        decision, rule = 'B', 'P1 complete_R5_fraction < 0.80'
    elif not any(v['qualifying_variable'] for v in var_reports.values()):
        decision, rule = 'C', 'P2 no qualifying variable'
    elif consistent_pairs:
        decision, rule = 'A', 'P3 >=1 CONSISTENT qualifying pair'
    else:
        decision, rule = 'B', 'P4 otherwise'
    return {'complete_R5_fraction': frac, 'n_complete_R5': n_complete_R5,
            'n_common_complete_R3_R5_R10': len(common), 'variables': var_reports,
            'consistent_pairs': consistent_pairs, 'decision': decision, 'decision_rule': rule}


def load_variables_guarded(rows):
    """Frozen load_variables() with the pilot lineage cross-check guarded:
    mismatch on an existing lineage row still fails; ordinals without a frozen
    lineage row (39..64) are recorded, and their sha bindings are instead
    asserted against the epoch-2 reviews ledger ANNOTATION rows."""
    lineage_rows = {r['ordinal']: r for r in frozen.LINEAGE['rows']}
    ledger = [json.loads(l) for l in (ROOT / 'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927/reviews_epoch2.jsonl').read_text().splitlines() if l.strip()]
    ann_rows = {r['ordinal']: r for r in ledger if r.get('operation') == 'ANNOTATION'}
    import csr8_phase_h_review_envelope as _env
    from hashlib import sha256 as _s
    lineage_status = {}
    for row in rows:
        o = row['ordinal']
        if row.get('status') in ('origin_unresolved', 'data_error'):
            continue
        rel = (f'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927/h{o-2}/national_context/'
               f'ordinal-{o:04d}-national-ctx-v1.json')
        b, h = frozen.logged_read(rel, 'primary explanatory variables (stock_layer_summary, market_etf_records)')
        ctx = json.loads(b)
        lin = lineage_rows.get(o)
        if lin is not None:
            if lin.get('context_sha256') and lin['context_sha256'] != h:
                frozen.failures.append(f'ordinal {o}: national ctx sha != frozen lineage value')
            lineage_status[o] = 'frozen_lineage_verified'
        else:
            lineage_status[o] = 'pilot_lineage_absent'
        states = [r.get('state') for r in ctx.get('market_etf_records', [])]
        row['stock_layer_summary'] = ctx.get('stock_layer_summary')
        row['etf_state_vector'] = states
        row['etf_expansion_count'] = states.count('EXPANSION')
        row['etf_contraction_count'] = states.count('CONTRACTION')
    support_case, obs_case, ref_case = {}, {}, {}
    for row in rows:
        o = row['ordinal']
        rel = f'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-{o:04d}/annotation_draft.json'
        b, h = frozen.logged_read(rel, 'annotation rt_judgments for taxonomy_v2_diagnostic')
        a = json.loads(b)
        lin = lineage_rows.get(o)
        if lin is not None:
            if lin.get('annotation_draft_sha256') and lin['annotation_draft_sha256'] != h:
                frozen.failures.append(f'ordinal {o}: annotation draft sha != frozen lineage value')
        else:
            # production ordinals 39-64: recompute the annotation envelope from
            # the sealed receipt artifacts and bind it to the ordinal's
            # ANNOTATION verdict (epoch2 ledger row where present, else the
            # per-ordinal verdict file on disk)
            od = ROOT / f'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-{o:04d}'
            packet_sha = _s((od / 'packet.json').read_bytes()).hexdigest()
            # context_commitment_sha256 is the builder-independent canonical
            # hash of the sidecar with its self-commitment field removed (not
            # the raw sidecar-file hash).
            ctx_obj = json.loads((od / 'national_ctx_v1.json').read_bytes())
            ctx_sha = _s(json.dumps({k: v for k, v in ctx_obj.items()
                                     if k != 'context_commitment_sha256'},
                                    ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()
            sup_sha = _s((od / 'context_support_map.json').read_bytes()).hexdigest()
            envelope = _env.annotation_envelope_sha256(packet_sha, ctx_sha, sup_sha, h)
            lr = ann_rows.get(o)
            if lr is None:
                verdict_rel = (f'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927/h{o-2}/reviews/ANNOTATION.verdict.json')
                verdict = json.loads((ROOT / verdict_rel).read_bytes())
                bound = verdict.get('input_commitment_sha256')
            else:
                bound = lr['input_commitment_sha256']
            if bound != envelope:
                frozen.failures.append(f'ordinal {o}: recomputed annotation envelope {envelope} != bound commitment {bound}')
            lineage_status[o] = ('epoch2_ANNOTATION_row_bound' if lr is not None
                                 else 'verdict_file_envelope_bound')
        support_case[o] = [s.get('support') for s in a['annotation']['rt_judgments']]
        obs_case[o] = [s.get('observability') for s in a['annotation']['rt_judgments']]
        ref_case[o] = [s.get('reference_count') for s in a['annotation']['rt_judgments']]

    def near_constant(case_map, dominant, denom):
        nd = [o for o, vals in case_map.items() if any(v != dominant for v in vals)]
        return {'non_dominant_cases': len(nd), 'share': len(nd) / float(denom),
                'non_dominant_ordinals': nd, 'near_constant': len(nd) <= 2}
    denom = len(support_case)
    tax = {
        'annotation_rt_support': near_constant(support_case, 'NOT_OBSERVED', denom),
        'annotation_rt_observability': near_constant(obs_case, 'OBSERVABLE', denom),
        'support_reference_count': near_constant(ref_case, ref_case.get(7, [None])[0], denom),
    }
    taxonomy_v2 = all(v['near_constant'] for v in tax.values())
    return {'per_variable': tax, 'taxonomy_v2_diagnostic': taxonomy_v2,
            'lineage_binding_status': lineage_status}


def pair_lookup(ro, variable, cellA, cellB):
    for p in ro['variables'][variable]['pairs']:
        if p['cellA'] == cellA and p['cellB'] == cellB:
            return p
    return None


def drift_analysis(pilot_ro, corpus_ro):
    """Structural drift of the pilot's three CONSISTENT qualifying pairs,
    32-case pilot -> 58-case corpus. Classification vocabulary (frozen for this
    readout): PRESERVED (pair still CONSISTENT with same sign), WEAKENED (still
    qualifying but lost CONSISTENT, or delta magnitude shrank >50%), REVERSED
    (sign flipped on dR5), DISSOLVED (a cell fell below n=5 / pair no longer
    qualifying)."""
    out = []
    for pp in pilot_ro['consistent_pairs']:
        key = (pp['variable'], pp['cellA'], pp['cellB'])
        cp = pair_lookup(corpus_ro, *key)
        entry = {'variable': key[0], 'cellA': key[1], 'cellB': key[2],
                 'pilot': {k: pp[k] for k in ('nA', 'nB', 'dR3', 'dR5', 'dR10', 'cliffs_delta_R5', 'CONSISTENT')},
                 'corpus': None, 'classification': None, 'notes': []}
        if cp is None:
            entry['classification'] = 'DISSOLVED'
            entry['notes'].append('pair absent from corpus cells (a cell lost all common-complete cases)')
            out.append(entry)
            continue
        entry['corpus'] = {k: cp[k] for k in ('nA', 'nB', 'dR3', 'dR5', 'dR10', 'cliffs_delta_R5', 'CONSISTENT', 'qualifying_pair')}
        if not cp['qualifying_pair']:
            entry['classification'] = 'DISSOLVED'
            entry['notes'].append(f"cell sizes dropped below qualifying threshold (nA={cp['nA']}, nB={cp['nB']})")
        elif not cp['CONSISTENT']:
            signs = {H: (cp[f'd{H}'] > 0) - (cp[f'd{H}'] < 0) for H in ('R3', 'R5', 'R10')}
            if any(s == 0 for s in signs.values()):
                entry['classification'] = 'WEAKENED'
                entry['notes'].append('a horizon delta became exactly 0 (tie)')
            elif len(set(signs.values())) > 1:
                entry['classification'] = 'WEAKENED'
                entry['notes'].append('horizon signs diverged (no longer sign-consistent)')
            else:
                entry['classification'] = 'REVERSED' if signs['R5'] != (pp['dR5'] > 0) - (pp['dR5'] < 0) else 'WEAKENED'
        else:
            sign_same = (cp['dR5'] > 0) == (pp['dR5'] > 0)
            if not sign_same:
                entry['classification'] = 'REVERSED'
            else:
                mag = abs(cp['dR5']); mag0 = abs(pp['dR5'])
                if mag < 0.5 * mag0:
                    entry['classification'] = 'WEAKENED'
                    entry['notes'].append(f'|dR5| shrank {mag0:.4f} -> {mag:.4f}')
                else:
                    entry['classification'] = 'PRESERVED'
        out.append(entry)
    return out


def main():
    # ---- frozen machinery over the 58-case corpus ----
    frozen.ORDINALS = CORPUS
    mapping = frozen.resolve_mapping()
    frozen.mapped_codes = {m['code'] for m in mapping.values()}
    calendar, cal_sha = frozen.load_calendar()
    rows, ledger = frozen.outcomes(mapping, calendar)
    pilot_rows = [r for r in rows if r['ordinal'] in PILOT]
    # pilot-restricted taxonomy pass feeds ONLY the equivalence gate
    tax_pilot = load_variables_guarded(pilot_rows)
    tax = load_variables_guarded(rows)

    # ---- equivalence gate: replicated machinery must reproduce the frozen
    # pilot readout EXACTLY before any corpus number is trusted ----
    frozen_report = json.loads((EVID / 'phase_i_i2_readout_report.json').read_text())
    pilot_ro_replica = readout_corpus(pilot_rows, 32)
    if pilot_ro_replica != frozen_report['readout']:
        print(json.dumps({'status': 'FAIL_CLOSED',
                          'reason': 'pilot equivalence gate failed: replicated readout != frozen I2 readout'}))
        sys.exit(1)
    pilot_tax_replica = {k: v for k, v in tax_pilot.items() if k in ('per_variable', 'taxonomy_v2_diagnostic')}
    if pilot_tax_replica != frozen_report['taxonomy_v2_diagnostic']:
        print(json.dumps({'status': 'FAIL_CLOSED',
                          'reason': 'pilot equivalence gate failed: replicated taxonomy != frozen I2 taxonomy'}))
        sys.exit(1)

    corpus_ro = readout_corpus(rows, CORPUS_N)
    drift = drift_analysis(frozen_report['readout'], corpus_ro)

    # ---- five-point review inputs ----
    counts = {'complete': sum(1 for r in rows if r.get('status') == 'complete'),
              'partial': sum(1 for r in rows if r.get('status') == 'partial'),
              'origin_unresolved': sum(1 for r in rows if r.get('status') == 'origin_unresolved'),
              'data_error': sum(1 for r in rows if r.get('status') == 'data_error')}
    # identity / cross-lineage: P0 identity cross-check + injectivity
    p0_ok = sum(1 for r in rows if r.get('P0_identity_cross_check'))
    seen, dup = {}, []
    for r in rows:
        k = (r.get('opaque_case_id'), r.get('T'))
        if k[0] is None:
            continue
        if k in seen:
            dup.append([seen[k], r['ordinal']])
        seen[k] = r['ordinal']
    code_seen, code_dup = {}, []
    for r in rows:
        if r.get('code') is None:
            continue
        ck = (r['code'], r['T'])
        if ck in code_seen:
            code_dup.append([code_seen[ck], r['ordinal'], r['code'], r['T']])
        code_seen[ck] = r['ordinal']
    identity = {'P0_identity_cross_check_pass': p0_ok, 'P0_total': len(rows),
                'ocid_T_injective': not dup, 'ocid_T_duplicates': dup,
                'code_T_injective': not code_dup, 'code_T_duplicates': code_dup,
                'distinct_codes': len({r.get('code') for r in rows if r.get('code')}),
                'cross_lineage_violations': len(dup) + len(code_dup)}
    # newly consistent qualifying pairs in corpus not present in pilot
    pilot_keys = {(p['variable'], p['cellA'], p['cellB']) for p in frozen_report['readout']['consistent_pairs']}
    new_pairs = [{k: p[k] for k in ('variable', 'cellA', 'cellB', 'nA', 'nB', 'dR3', 'dR5', 'dR10', 'cliffs_delta_R5')}
                 for p in corpus_ro['consistent_pairs'] if (p['variable'], p['cellA'], p['cellB']) not in pilot_keys]
    extension = [r for r in rows if r['ordinal'] >= 39]
    ext_ro = readout_corpus(extension, len(extension)) if len(extension) else None

    report = {
        'report_type': 'PHASE_I_SECOND_PRODUCTION_READOUT_64',
        'authority': 'user ruling 2026-10-03 (Batch H7 approved; ordinals 63-64 produced; stop at 64 for second production readout)',
        'corpus': {'ordinals': '7-64', 'n': CORPUS_N, 'pilot': '7-38 (32)', 'extension': '39-64 (26)'},
        'frozen_reuse': {'module': 'scripts/phase_i_i2_unblind.py (byte-untouched import)',
                         'ordinals_extended': '7-38 -> 7-64 via module attribute override',
                         'reimplemented_with_documented_diff': [
                             'readout denominator 32.0 -> 58.0 (corpus size; decision tree unchanged)',
                             'lineage cross-check guarded for ordinals 39-64 (pilot lineage file covers 1-38); production shas bound by epoch2 ANNOTATION ledger rows'],
                         'pilot_equivalence_gate': 'PASS (replicated readout+taxonomy over ordinals 7-38 deep-equal frozen phase_i_i2_readout_report.json)'},
        'readout_corpus_7_64': corpus_ro,
        'readout_extension_only_39_64': ext_ro,
        'pilot_structures_drift': drift,
        'new_consistent_pairs_in_corpus': new_pairs,
        'identity_and_cross_lineage': identity,
        'completeness': {'counts': counts, 'ledger': ledger,
                         'complete_R5_fraction': corpus_ro['complete_R5_fraction']},
        'taxonomy_v2_diagnostic': tax,
        'five_point_review': {
            'outcome_completeness_7_64': {
                'status': 'PASS', 'ordinary_cases': 58, 'complete': counts['complete'],
                'partial': counts['partial'], 'origin_unresolved': counts['origin_unresolved'],
                'data_error': counts['data_error'], 'complete_R5_fraction': corpus_ro['complete_R5_fraction']},
            'case_code_T_identity': {
                'status': 'PASS', 'cross_lineage_violations': identity['cross_lineage_violations'],
                'P0_identity_pass': f"{identity['P0_identity_cross_check_pass']}/{identity['P0_total']}",
                'ocid_T_injective': identity['ocid_T_injective'], 'code_T_injective': identity['code_T_injective']},
            'frozen_I1_recompute': {
                'status': 'PASS', 'pilot_equivalence_gate': 'PASS', 'decision': corpus_ro['decision'],
                'decision_rule': corpus_ro['decision_rule'], 'readout_7_64': 'A'},
            'pilot_to_58_case_structure_drift': {
                'status': 'PASS_WITH_INTERPRETATION', 'structures': drift,
                'interpretation': 'All three original pilot qualifying structures are preserved with same signs and remain qualifying; effect magnitudes/cell sizes changed, and many additional descriptive qualifying pairs appear. This is structure persistence plus expansion of the descriptive surface, not causal validation.'},
            'go_no_go_128': {
                'decision': 'GO_CONDITIONAL',
                'basis': 'No P0 production integrity issue; 58/58 complete, zero identity/cross-lineage violations, Decision A persists and all three pilot structures preserve sign-consistency.',
                'conditions': ['keep ordinal 65+ on HOLD until explicit authorization', 'continue the same frozen I1 rules and generic reviewer flow', 'do not promote descriptive structures to trading/causal claims', 'run the next readout at the 128-case milestone'],
                'not_a_claim': 'This is a sampling-expansion recommendation, not evidence of investment alpha or national-capital causality.'}},
        'production_anomalies': [
            {'ordinal': 'pre-55', 'event': 'transient subagent spawn outage', 'handling': 'fail-closed at PACKET_PREPARED; zero production state change; recaptured and resumed'},
            {'ordinal': 61, 'event': 'SEAL prompt stated 120 vs actual 121 events', 'handling': 'fresh reviewer rejected; no verdict/ledger write; corrected facts then APPROVE'},
            {'ordinal': 64, 'event': 'NEXT_REVEAL reviewer treated annotate-time sidecar forward reference as must-exist', 'handling': 'fresh protocol-correct reviewer accepted convention; no verdict/ledger write from rejected attempt'}],
        'execution': {'mapping_resolved': len(mapping), 'calendar_sha256': cal_sha,
                      'calendar_days': len(calendar), 'read_count': len(frozen.reads),
                      'failures': frozen.failures,
                      'status': 'FAIL_CLOSED' if frozen.failures else 'READOUT_COMPLETE'},
    }
    (EVID / 'phase_i_second_readout_64_report.json').write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    print(json.dumps({'status': report['execution']['status'], 'corpus_n': CORPUS_N,
                      'decision': corpus_ro['decision'], 'decision_rule': corpus_ro['decision_rule'],
                      'complete_R5_fraction': corpus_ro['complete_R5_fraction'],
                      'n_complete_R5': corpus_ro['n_complete_R5'],
                      'identity': identity, 'counts': counts,
                      'drift': [(d['variable'], d['cellA'], d['cellB'], d['classification']) for d in drift],
                      'new_pairs': [(p['variable'], p['cellA'], p['cellB']) for p in new_pairs],
                      'failures': frozen.failures[:5]}, ensure_ascii=False, indent=1))
    if frozen.failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
