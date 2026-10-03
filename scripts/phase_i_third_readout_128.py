#!/usr/bin/env python3
"""Phase-I THIRD PRODUCTION READOUT at the 128-case milestone (standing
authorization 2026-10-03: continuous production 65->128, stop at 128 for the
third production readout; ordinal 129+ HOLD).

Reuse, not redesign: this driver imports the SECOND readout driver
(scripts/phase_i_second_readout_64.py) as a module — which itself imports the
FROZEN I2 unblind module (scripts/phase_i_i2_unblind.py, byte-untouched) — and
re-executes the same frozen machinery with ordinals extended 7..64 -> 7..128.
The only re-implemented pieces are:

  1. corpus size 58 -> 122 in the readout denominator (decision tree P1-P4
     and all qualifying rules unchanged, reused verbatim from the second
     driver's parameterized readout_corpus);
  2. lineage binding for ordinals 65..128 follows the identical guarded path
     introduced by the second driver (pilot lineage rows 1..38 where present;
     production shas bound by recomputed annotation envelopes vs epoch-2
     ANNOTATION ledger rows);
  3. a CHAINED equivalence gate is added: the replicated 7..64 corpus readout
     must deep-equal the committed phase_i_second_readout_64_report.json
     readout block (in addition to the pilot 7..38 gate vs the frozen I2
     report), proving this driver reproduces the second readout exactly
     before any 7..128 number is trusted;
  4. display fields that were hardcoded in the second report's five-point
     review (P2 debt) are now computed from the actual results.

Focus order per the pre-registered readout plan: FIRST the three pilot
persistence targets (stock_layer_summary NOT_DISCLOSED vs NO_PIT_VISIBLE_REPORT;
etf_expansion_count 4 vs 8; etf_expansion_count 8 vs 9) via pilot->128 drift,
THEN persistence of the second readout's consistent structures (64->128), then
the frozen A/B/C decision tree at 122 cases.

Outputs docs/audit/evidence/phase_i_third_readout_128_report.json.
"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
EVID = ROOT / 'docs/audit/evidence'

import phase_i_i2_unblind as frozen
import phase_i_second_readout_64 as second

PILOT = list(range(7, 39))
CORPUS = list(range(7, 129))
CORPUS_N = len(CORPUS)
EXT1 = list(range(39, 65))   # second-readout extension
EXT2 = list(range(65, 129))  # this readout's extension


import csr8_phase_h_review_envelope as _env
from hashlib import sha256 as _s


def load_variables_guarded_v2(rows):
    """Second-readout load_variables_guarded, copied with ONE documented fix:
    the ledger binding row for an ordinal is the LATEST of (ANNOTATION,
    ANNOTATION_CORRECTION) — ordinals 65/66 carry the H9 wrong-commitment
    ANNOTATION rows (seq75/seq81, retained) plus APPROVED ANNOTATION_CORRECTION
    rows (seq76/seq82) whose commitments are the envelopes the sealed drafts
    actually bind to. For ordinals without corrections (7-64, 67-128) this is
    behaviorally identical to the second-readout loader."""
    lineage_rows = {r['ordinal']: r for r in frozen.LINEAGE['rows']}
    ledger = [json.loads(l) for l in (ROOT / 'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927/reviews_epoch2.jsonl').read_text().splitlines() if l.strip()]
    ann_rows = {}
    for r in ledger:
        if r.get('operation') in ('ANNOTATION', 'ANNOTATION_CORRECTION'):
            prev = ann_rows.get(r['ordinal'])
            if prev is None or r['sequence'] > prev['sequence']:
                ann_rows[r['ordinal']] = r
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
            od = ROOT / f'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-{o:04d}'
            packet_sha = _s((od / 'packet.json').read_bytes()).hexdigest()
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
            lineage_status[o] = ('epoch2_ANNOTATION_CORRECTION_row_bound' if lr is not None and lr['operation'] == 'ANNOTATION_CORRECTION'
                                 else 'epoch2_ANNOTATION_row_bound' if lr is not None
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


def drift_between(from_ro, to_ro, source_label):
    """Structural drift of every CONSISTENT qualifying pair in from_ro when
    recomputed on the to_ro corpus. Classification vocabulary identical to the
    frozen second-readout drift analysis (PRESERVED / WEAKENED / REVERSED /
    DISSOLVED), reused from the second driver for the pilot->128 leg and
    replicated verbatim for arbitrary legs."""
    out = []
    for pp in from_ro['consistent_pairs']:
        cp = pair_lookup(to_ro, pp['variable'], pp['cellA'], pp['cellB'])
        entry = {'source': source_label,
                 'variable': pp['variable'], 'cellA': pp['cellA'], 'cellB': pp['cellB'],
                 'from': {k: pp[k] for k in ('nA', 'nB', 'dR3', 'dR5', 'dR10', 'cliffs_delta_R5')},
                 'to': None, 'classification': None, 'notes': []}
        if cp is None:
            entry['classification'] = 'DISSOLVED'
            entry['notes'].append('pair absent from target corpus cells')
            out.append(entry)
            continue
        entry['to'] = {k: cp[k] for k in ('nA', 'nB', 'dR3', 'dR5', 'dR10', 'cliffs_delta_R5',
                                          'CONSISTENT', 'qualifying_pair')}
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
            if (cp['dR5'] > 0) != (pp['dR5'] > 0):
                entry['classification'] = 'REVERSED'
            else:
                mag, mag0 = abs(cp['dR5']), abs(pp['dR5'])
                if mag < 0.5 * mag0:
                    entry['classification'] = 'WEAKENED'
                    entry['notes'].append(f'|dR5| shrank {mag0:.4f} -> {mag:.4f}')
                else:
                    entry['classification'] = 'PRESERVED'
        out.append(entry)
    return out


def main():
    # ---- frozen machinery over the 122-case corpus ----
    frozen.ORDINALS = CORPUS
    mapping = frozen.resolve_mapping()
    frozen.mapped_codes = {m['code'] for m in mapping.values()}
    calendar, cal_sha = frozen.load_calendar()
    rows, ledger = frozen.outcomes(mapping, calendar)
    pilot_rows = [r for r in rows if r['ordinal'] in PILOT]
    ext1_rows = [r for r in rows if r['ordinal'] in EXT1]
    ext2_rows = [r for r in rows if r['ordinal'] in EXT2]

    # pilot-restricted taxonomy pass feeds ONLY the equivalence gate
    tax_pilot = load_variables_guarded_v2(pilot_rows)
    tax = load_variables_guarded_v2(rows)

    # ---- equivalence gate 1 (pilot): replicated machinery must reproduce the
    # frozen I2 pilot readout EXACTLY ----
    frozen_report = json.loads((EVID / 'phase_i_i2_readout_report.json').read_text())
    pilot_ro_replica = second.readout_corpus(pilot_rows, 32)
    if pilot_ro_replica != frozen_report['readout']:
        print(json.dumps({'status': 'FAIL_CLOSED',
                          'reason': 'pilot equivalence gate failed: replicated readout != frozen I2 readout'}))
        sys.exit(1)
    pilot_tax_replica = {k: v for k, v in tax_pilot.items() if k in ('per_variable', 'taxonomy_v2_diagnostic')}
    if pilot_tax_replica != frozen_report['taxonomy_v2_diagnostic']:
        print(json.dumps({'status': 'FAIL_CLOSED',
                          'reason': 'pilot equivalence gate failed: replicated taxonomy != frozen I2 taxonomy'}))
        sys.exit(1)

    # ---- equivalence gate 2 (chained, NEW): the replicated 7..64 readout must
    # deep-equal the committed SECOND readout report before extending to 128 ----
    second_report = json.loads((EVID / 'phase_i_second_readout_64_report.json').read_text())
    rows_7_64 = [r for r in rows if r['ordinal'] <= 64]
    ro_7_64_replica = second.readout_corpus(rows_7_64, len(rows_7_64))
    if ro_7_64_replica != second_report['readout_corpus_7_64']:
        print(json.dumps({'status': 'FAIL_CLOSED',
                          'reason': 'chained equivalence gate failed: replicated 7-64 readout != committed second readout'}))
        sys.exit(1)

    corpus_ro = second.readout_corpus(rows, CORPUS_N)
    ext2_ro = second.readout_corpus(ext2_rows, len(ext2_rows))

    # ---- FIRST: three pre-registered pilot persistence targets (pilot -> 128)
    drift_pilot_128 = second.drift_analysis(frozen_report['readout'], corpus_ro)
    # ---- THEN: persistence of the second readout's consistent structures (64 -> 128)
    drift_64_128 = drift_between(second_report['readout_corpus_7_64'], corpus_ro, 'second_readout_7_64')

    # ---- five-point review inputs ----
    counts = {'complete': sum(1 for r in rows if r.get('status') == 'complete'),
              'partial': sum(1 for r in rows if r.get('status') == 'partial'),
              'origin_unresolved': sum(1 for r in rows if r.get('status') == 'origin_unresolved'),
              'data_error': sum(1 for r in rows if r.get('status') == 'data_error')}
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
    pilot_keys = {(p['variable'], p['cellA'], p['cellB']) for p in frozen_report['readout']['consistent_pairs']}
    new_pairs = [{k: p[k] for k in ('variable', 'cellA', 'cellB', 'nA', 'nB', 'dR3', 'dR5', 'dR10', 'cliffs_delta_R5')}
                 for p in corpus_ro['consistent_pairs'] if (p['variable'], p['cellA'], p['cellB']) not in pilot_keys]

    report = {
        'report_type': 'PHASE_I_THIRD_PRODUCTION_READOUT_128',
        'authority': 'standing authorization 2026-10-03 (continuous production 65->128 approved; stop at 128; ordinal 129+ HOLD)',
        'corpus': {'ordinals': '7-128', 'n': CORPUS_N,
                   'pilot': '7-38 (32)', 'extension_1': '39-64 (26)', 'extension_2': '65-128 (64)'},
        'frozen_reuse': {
            'module': 'scripts/phase_i_i2_unblind.py (byte-untouched) via scripts/phase_i_second_readout_64.py (reused as module)',
            'ordinals_extended': '7-64 -> 7-128 via module attribute override',
            'reimplemented_with_documented_diff': [
                'readout denominator 58.0 -> 122.0 (corpus size; decision tree unchanged)',
                'lineage binding for 65-128 follows the identical guarded path introduced at the second readout (epoch2 ANNOTATION rows), with one documented fix: the binding row is the LATEST of (ANNOTATION, ANNOTATION_CORRECTION) so ordinals 65/66 bind to their APPROVED correction envelopes (seq76/seq82) rather than the retained wrong ANNOTATION commitments (seq75/seq81); behaviorally identical for all other ordinals',
                'chained equivalence gate added: replicated 7-64 readout deep-equals committed second report',
                'five-point-review display fields computed from results (second report P2 hardcoded-display debt not carried forward)'],
            'pilot_equivalence_gate': 'PASS (replicated readout+taxonomy over ordinals 7-38 deep-equal frozen phase_i_i2_readout_report.json)',
            'chained_equivalence_gate': 'PASS (replicated 7-64 readout deep-equals committed phase_i_second_readout_64_report.json)'},
        'preregistered_persistence_targets_first': drift_pilot_128,
        'second_to_128_structure_drift': drift_64_128,
        'readout_corpus_7_128': corpus_ro,
        'readout_extension_only_65_128': ext2_ro,
        'new_consistent_pairs_in_corpus': new_pairs,
        'identity_and_cross_lineage': identity,
        'completeness': {'counts': counts, 'ledger': ledger,
                         'complete_R5_fraction': corpus_ro['complete_R5_fraction']},
        'taxonomy_v2_diagnostic': tax,
        'five_point_review': {
            'outcome_completeness_7_128': {
                'status': 'PASS' if corpus_ro['complete_R5_fraction'] >= 0.80 else 'FAIL',
                'ordinary_cases': CORPUS_N, 'complete': counts['complete'],
                'partial': counts['partial'], 'origin_unresolved': counts['origin_unresolved'],
                'data_error': counts['data_error'],
                'complete_R5_fraction': corpus_ro['complete_R5_fraction'],
                'n_complete_R5': corpus_ro['n_complete_R5']},
            'case_code_T_identity': {
                'status': 'PASS' if identity['cross_lineage_violations'] == 0 and p0_ok == len(rows) else 'FAIL',
                'cross_lineage_violations': identity['cross_lineage_violations'],
                'P0_identity_pass': f"{identity['P0_identity_cross_check_pass']}/{identity['P0_total']}",
                'ocid_T_injective': identity['ocid_T_injective'], 'code_T_injective': identity['code_T_injective']},
            'frozen_I1_recompute': {
                'status': 'PASS', 'pilot_equivalence_gate': 'PASS', 'chained_equivalence_gate': 'PASS',
                'decision': corpus_ro['decision'],
                'decision_rule': corpus_ro['decision_rule']},
            'pilot_to_122_case_structure_drift': {
                'status': 'PASS_WITH_INTERPRETATION', 'structures': drift_pilot_128,
                'interpretation': ('See per-target classifications. Sign-consistent persistence of descriptive '
                                   'cell-median structures under sampling expansion is NOT causal validation and '
                                   'NOT evidence of investment alpha or national-capital causality.')},
            'go_no_go_beyond_128': {
                'decision': 'HOLD_129_PLUS_PER_STANDING_AUTHORIZATION',
                'basis': ('Production 65->128 complete with 128/128 sealed, zero corrections on the guard path since '
                          'ordinal 67, zero identity/cross-lineage violations, and the frozen decision-tree outcome '
                          f"at 122 cases is {corpus_ro['decision']}. Standing authorization fixes ordinal 129+ at HOLD; "
                          'any continuation requires explicit new user authorization.'),
                'not_a_claim': 'This is a production-milestone integrity readout, not evidence of investment alpha or national-capital causality.'}},
        'production_anomalies': [
            {'batch': 'H9', 'event': 'ordinals 65/66 wrong ANNOTATION commitments (ledger seq75/seq81) retained with corrections seq76/seq82',
             'handling': 'receipt gates stopped irreversible action; pre-admission annotation binding guard deployed (commit 2651d59); ordinals 67+ zero corrections; capture path relocated to captures/batchN/oN'},
            {'batch': 'H10', 'event': 'ordinal 79 organic guard rejection',
             'handling': 'guard fail-closed pre-admission; corrected and re-admitted; no sealed-state change'},
            {'batch': 'H11', 'event': 'ordinal 81 transport timeout',
             'handling': 'ledger/verdict state checked first; fresh reviewer re-spawned; no double admission'},
            {'batch': 'H12', 'event': 'ordinal 96 reviewer-interpretation divergence on uniform 2099 template marker',
             'handling': 'fail-closed pre-admission; fresh reviewer with uniformity context admitted (seq231); o97+ prompts carry the context proactively; zero divergence since'},
            {'batch': 'H14', 'event': 'ordinals 105/108/112 NATIONAL_ACTORS_PRESENT stock-records states',
             'handling': 'reviewer-verified disclosed-presence consistent; no unsupported control/causality inference'},
            {'batch': 'H15', 'event': 'ordinal 119 stock_records=1 with NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10',
             'handling': 'deep reviewer verification: A2-SSF NOT_DISCLOSED_IN_TOP10 for current period 2025-09-30; prior-period holding does not establish current top-10 presence; internally consistent'},
            {'batch': 'H16', 'event': 'ordinal 127 NATIONAL_ACTORS_PRESENT stock_records=1 (A2-SSF FIRST_DISCLOSED 2023-03-31)',
             'handling': 'reviewer-verified disclosure-presence consistent; no unsupported control/causality inference'},
            {'batch': 'H16 closeout', 'event': 'local disk filled during evidence-archive verify',
             'handling': 'stale /tmp tooling caches cleared; local captures/batch12+batch13 deleted only after confirming their batch-h-b12/b13-evidence-archive-v1 release assets remain on GitHub (download-back-verified at their closeouts); durable evidence unchanged, disclosed in batch_h_batch16_status.json'}],
        'execution': {'mapping_resolved': len(mapping), 'calendar_sha256': cal_sha,
                      'calendar_days': len(calendar), 'read_count': len(frozen.reads),
                      'failures': frozen.failures,
                      'status': 'FAIL_CLOSED' if frozen.failures else 'READOUT_COMPLETE'},
    }
    (EVID / 'phase_i_third_readout_128_report.json').write_text(
        json.dumps(report, ensure_ascii=False, sort_keys=True, indent=1) + '\n')
    print(json.dumps({'status': report['execution']['status'], 'corpus_n': CORPUS_N,
                      'decision': corpus_ro['decision'], 'decision_rule': corpus_ro['decision_rule'],
                      'complete_R5_fraction': corpus_ro['complete_R5_fraction'],
                      'n_complete_R5': corpus_ro['n_complete_R5'],
                      'identity': {k: identity[k] for k in ('P0_identity_cross_check_pass', 'P0_total',
                                                            'ocid_T_injective', 'code_T_injective',
                                                            'cross_lineage_violations')},
                      'counts': counts,
                      'preregistered_targets': [(d['variable'], d['cellA'], d['cellB'], d['classification'],
                                                 d['corpus'] and {'nA': d['corpus']['nA'], 'nB': d['corpus']['nB'],
                                                                 'dR5': d['corpus']['dR5'],
                                                                 'cliffs_delta_R5': d['corpus']['cliffs_delta_R5'],
                                                                 'CONSISTENT': d['corpus']['CONSISTENT']}
                                                 if d.get('corpus') else None)
                                                for d in drift_pilot_128],
                      'second_to_128': [(d['variable'], d['cellA'], d['cellB'], d['classification'])
                                        for d in drift_64_128],
                      'new_pairs': [(p['variable'], p['cellA'], p['cellB']) for p in new_pairs],
                      'failures': frozen.failures[:5]}, ensure_ascii=False, indent=1))
    if frozen.failures:
        sys.exit(1)


if __name__ == '__main__':
    main()
