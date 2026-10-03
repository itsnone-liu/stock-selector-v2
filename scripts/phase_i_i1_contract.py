#!/usr/bin/env python3
"""Build the Phase-I I1 canonical readout contract (outcome-free).

Deterministically assembles the machine contract from the frozen I0.2
lineage vocabulary facts and pinned input hashes. It reads NO outcome
values, NO selector secret contents (hash only), and NO per-case forward
prices. Output: docs/audit/evidence/phase_i_i1_contract.json with its
canonical SHA-256 embedded for the unlock gate.
"""
import hashlib, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/audit/evidence' / 'phase_i_i1_contract.json'
CONTRACT_VERSION = 'phase-i-i1-readout-contract-v1'


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def build():
    lineage = json.loads((ROOT / 'docs/audit/evidence/phase_i_i0_2_evidence_derived_lineage.json').read_text())
    ordinals = [r['ordinal'] for r in lineage['rows'] if r['ordinary_pilot_eligible']]
    assert ordinals == list(range(7, 39))

    contract = {
        'contract_version': CONTRACT_VERSION,
        'status': 'FROZEN_CANDIDATE_PENDING_I2_UNLOCK_GATE',
        'corpus': {
            'ordinary_pilot_ordinals': ordinals,
            'ordinary_pilot_case_count': len(ordinals),
            'unit': 'one sealed ordinal = one case',
            'historical_prefix_ordinals': [1, 2, 3, 4, 5, 6],
            'historical_prefix_policy': 'descriptive only; separate stratum; never pooled with ordinary pilot',
            'lineage_binding': 'docs/audit/evidence/phase_i_i0_2_evidence_derived_lineage.json',
        },
        'origin': {
            'T_source_path': '/sealed/as_of/T',
            'T_semantics': 'blinded anchor date carried in the sealed packet; decision clock CLOSE_AFTER_T',
            'P0': 'hfq_adjusted close of the mapped instrument on T',
            'P0_identity_cross_check': 'unadjusted close on T in the frozen price store must equal the packet price_panel last value on T (machine check at unlock)',
            'origin_unresolved_rule': 'if T row missing or cross-check fails -> origin_unresolved, excluded from endpoint numerators, kept in denominator ledger',
        },
        'price_source': {
            'provider': 'baostock',
            'dataset': 'data/adjustment_baostock/per_stock/<code>.json.gz',
            'adjustment': 'hfq (adjustflag=1, backward/hou-fu-quan adjusted close)',
            'fields': 'date,open,high,low,close,volume,amount,turn,pctChg',
            'coverage': '2021-01-04 .. 2026-09-18 (fetch window 2021-01-01 .. 2026-09-19)',
            'fetch_manifest_sha256': sha_file(ROOT / 'data/adjustment_baostock/fetch_manifest.json'),
            'closed_world_commitment': {
                'manifest_path': 'docs/audit/evidence/phase_i_price_store_manifest.json',
                'manifest_sha256': 'filled_at_build',
                'file_count': 5240,
                'per_entry': ['relative_path', 'bytes', 'sha256'],
                'i2_unlock_verification': 're-hash every declared file and require exact equality of bytes and sha256 per entry and of the closed-world file set before any outcome value is read',
            },
            'selector_mapping_secret': {
                'path': 'data/csr8_phase_c/secret/packet_plan.json',
                'sha256': sha_file(ROOT / 'data/csr8_phase_c/secret/packet_plan.json'),
                'policy': 'secret bytes hashed only during I1; not parsed, decoded, mapped, or semantically inspected; consulted only inside the logged I2 unlock ceremony',
            },
        },
        'eligible_observation_clock': {
            'clock': 'exchange trading sessions of the mapped instrument',
            'eligible_observation': 'a session date d with d > T, present in the instrument hfq series, with finite positive hfq close',
            'H_k': 'k-th eligible observation after T, k in {1,3,5,10}',
            'skip_rule': 'session present for the exchange but absent/invalid for the instrument -> skipped, logged with reason; never counted as zero return',
            'trading_calendar_proxy': 'union of session dates across the frozen baostock store universe (5,240 files pinned by the closed-world price-store manifest); materialized and hashed at I2 unlock',
            'right_censor_rule': 'if fewer than k eligible observations within 60 exchange sessions after T -> endpoint status right_censored for that k',
            'max_look_forward_sessions': 60,
        },
        'endpoints': {
            'primary': {
                'name': 'R5',
                'formula': 'ln(P5_hfq / P0_hfq)',
                'horizon': 5,
                'status_domain': ['complete', 'right_censored', 'origin_unresolved', 'data_error'],
            },
            'secondary': {
                'R1': 'ln(P1_hfq / P0_hfq)',
                'R3': 'ln(P3_hfq / P0_hfq)',
                'R10': 'ln(P10_hfq / P0_hfq)',
                'MFE5': 'max over eligible i in 1..5 of (P_i/P0 - 1), simple return',
                'MAE5': 'min over eligible i in 1..5 of (P_i/P0 - 1), simple return',
                'MFE10': 'max over eligible i in 1..10 of (P_i/P0 - 1), simple return',
                'MAE10': 'min over eligible i in 1..10 of (P_i/P0 - 1), simple return',
                'first_hit_band_5_10': 'first eligible i in 1..10 reaching (P_i/P0-1) >= +0.05 or <= -0.05; ties by earliest session; band = up/down/none, session index recorded',
                'return_convention': 'R* are natural-log gross ratios; MFE/MAE and band thresholds are simple returns; never mixed in one endpoint',
            },
            'missing_data': {
                'imputation': 'none',
                'winsorization': 'none',
                'outlier_deletion': 'none',
                'duplicate_session_rule': 'duplicate session rows -> data_error for that case, quarantine before unlock-phase computation completes',
                'censoring_denominator': 'censored cases stay in the corpus ledger and are excluded only from the affected endpoint summary with both counts reported',
            },
        },
        'explanatory_variables': {
            'primary': [
                {
                    'name': 'stock_layer_summary',
                    'json_path': '/sealed/stock_layer_summary',
                    'vocabulary': ['NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10', 'NO_PIT_VISIBLE_REPORT', 'NATIONAL_ACTORS_PRESENT'],
                    'i0_distribution': {'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10': 25, 'NO_PIT_VISIBLE_REPORT': 5, 'NATIONAL_ACTORS_PRESENT': 2},
                    'missing_handling': 'none expected; any unseen value at unlock -> coverage incident, not pooled',
                },
                {
                    'name': 'etf_expansion_count',
                    'definition': 'count of /sealed/market_etf_records/*/state == EXPANSION',
                    'range': '0..9',
                    'derived_from_sealed_context_only': True,
                },
                {
                    'name': 'etf_contraction_count',
                    'definition': 'count of /sealed/market_etf_records/*/state == CONTRACTION',
                    'range': '0..9',
                    'derived_from_sealed_context_only': True,
                },
            ],
            'prespecified_blocking': [
                {
                    'name': 'era',
                    'definition': 'calendar year of /sealed/as_of/T in {2021,2022,2023,2024,2025,2026}',
                    'role': 'blocking/stratification only; never an interpretive variable',
                },
            ],
            'descriptive_only': [
                {'name': 'etf_state_vector', 'json_path': '/sealed/market_etf_records/*/state', 'reason': 'per-slot cells too sparse for a 32-case pilot'},
                {'name': 'stock_layer_report_period_recency', 'json_path': '/sealed/stock_layer_summary_report_period', 'reason': 'empty string tied to NO_PIT_VISIBLE_REPORT; redundant, descriptive'},
                {'name': 'annotation_rt_support', 'json_path': '/annotation/rt_judgments/*/support', 'i0_distribution': {'NOT_OBSERVED': 190, 'SUPPORTED_PARTIAL': 2}, 'reason': 'near-zero variation: coverage diagnostic only'},
                {'name': 'annotation_rt_observability', 'json_path': '/annotation/rt_judgments/*/observability', 'i0_distribution': {'OBSERVABLE': 192}, 'reason': 'constant'},
                {'name': 'support_reference_count', 'i0_distribution': {'2': 32}, 'reason': 'constant, zero discrimination'},
                {'name': 'provenance_fields', 'json_paths': ['/sealed/packet_id', '/sealed/packet_sha256', '/sealed/production_head', '/sealed/reveal_count', '/sealed/seal_count'], 'reason': 'audit lineage only'},
            ],
            'selection_basis': 'chosen from I0/I0.1/I0.2 outcome-free cross-case distributions before any outcome read; near-zero-variation annotation fields are frozen as descriptive diagnostics',
        },
        'decision_rubric': {
            'evaluated_on': 'primary endpoint R5 across primary explanatory variables; descriptive, non-confirmatory',
            'cell_definition': 'each distinct raw value of a primary variable is one cell; outcome-driven binning, collapsing, or pair selection after unlock is forbidden',
            'minimum_interpretable_cell_n': 5,
            'qualifying_variable': 'at least two distinct value cells each with n >= 5 cases that are common-complete for R3/R5/R10',
            'pair_enumeration': 'all unordered cell pairs of each qualifying variable, each pair evaluated on that pair\'s common-complete case intersection across R3/R5/R10',
            'consistent_pair_definition': 'for pair (A,B): dH = median(cellA,H) - median(cellB,H) for H in {R3,R5,R10}; CONSISTENT(pair) iff all three dH are nonzero and share the same sign',
            'decision_tree': [
                {'priority': 1, 'condition': 'complete_R5_fraction < 0.80', 'outcome': 'B'},
                {'priority': 2, 'condition': 'no qualifying variable exists', 'outcome': 'C'},
                {'priority': 3, 'condition': 'at least one CONSISTENT(pair) exists across any qualifying variable', 'outcome': 'A'},
                {'priority': 4, 'condition': 'otherwise', 'outcome': 'B'},
            ],
            'complete_R5_fraction_definition': 'cases with R5 status complete divided by 32 ordinary pilot cases',
            'taxonomy_v2_diagnostic': 'reported separately from the A/B/C decision: true iff every annotation-derived descriptive_only variable is constant or near-constant (non-dominant share <= 2/32) in the sealed corpus; never feeds the decision tree',
            'effect_size_reporting': 'per-cell median and MAD of R5 on common-complete intersections; Cliff\'s delta for every enumerated pair; no significance-threshold gate',
            'binding': 'decision tree evaluated top-down yields exactly one of A/B/C; pilot is not confirmatory',
        },
        'unlock_gate': {
            'i1_contract_sha256': 'embedded_at_build',
            'requirements_for_I2': [
                'this contract committed and its canonical sha256 frozen',
                'PHASE-I SEALED INPUT ARCHIVE completed with closed-world manifest, archive sha256, hash-pinned durable release asset, and round-trip replay PASS, covering the I0.2 runtime read manifest files plus sealing_log plus batch completion bindings plus the price-source closed-world manifest',
                'price store closed-world re-verification PASS: every one of the 5,240 pinned per-stock files re-hashed and equal to the manifest entries',
                'price source and selector-mapping secret hashes still match the pins above at unlock time',
                'unlock ceremony reads only through a logged runtime read manifest',
            ],
        },
        'interpretation_limits': [
            '32 cases are a pilot; no stable probabilities, thresholds, or trading rules',
            'association is not causation; annotation variables are descriptive strata',
            'sparse cells are reported as sparse, never as null or strong evidence',
        ],
        'pinned_input_hashes': {
            'phase_i_i0_2_evidence_derived_lineage.json': sha_file(ROOT / 'docs/audit/evidence/phase_i_i0_2_evidence_derived_lineage.json'),
            'phase_i_i0_1_sealed_case_lineage.json': sha_file(ROOT / 'docs/audit/evidence/phase_i_i0_1_sealed_case_lineage.json'),
            'phase_i_i0_corpus_inventory.json': sha_file(ROOT / 'docs/audit/evidence/phase_i_i0_corpus_inventory.json'),
            'scripts/csr8_phase_h_review_envelope.py': sha_file(ROOT / 'scripts/csr8_phase_h_review_envelope.py'),
            'scripts/csr8_phase_h_runner.py': sha_file(ROOT / 'scripts/csr8_phase_h_runner.py'),
        },
    }
    ps_manifest = json.loads((ROOT / 'docs/audit/evidence/phase_i_price_store_manifest.json').read_text())
    contract['price_source']['closed_world_commitment']['manifest_sha256'] = ps_manifest['manifest_sha256']
    if ps_manifest.get('file_count') != 5240 or not ps_manifest.get('closed_world'):
        raise RuntimeError('price store manifest is not closed-world over 5,240 files')
    contract['unlock_gate']['i1_contract_sha256'] = ''
    digest = hashlib.sha256(canon(contract).encode()).hexdigest()
    contract['unlock_gate']['i1_contract_sha256'] = digest
    outer = {
        'report_type': 'PHASE_I_I1_CANONICAL_READOUT_CONTRACT',
        'contract_sha256': digest,
        'canonicalization': 'sha256 of json.dumps(contract, ensure_ascii=False, sort_keys=True, separators=(",",":")) evaluated with unlock_gate.i1_contract_sha256 set to the empty string; verification replaces that field with "" and recomputes',
        'outcome_unlock': 'NOT_AUTHORIZED',
        'i2_ready': False,
        'contract': contract,
    }
    OUT.write_text(json.dumps(outer, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    print(json.dumps({'contract_sha256': digest, 'path': OUT.relative_to(ROOT).as_posix(), 'outcome_unlock': 'NOT_AUTHORIZED'}))


if __name__ == '__main__':
    build()
