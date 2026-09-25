#!/usr/bin/env python3
"""T6.5 — Synthesis. NO new statistics: mechanically aggregates the five
frozen stage claims/gates/manifests into one registry, verifies the chain,
and emits the decision mapping (frozen conclusions vs open hypotheses).
Every synthesis claim must cite frozen claim_ids only.
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file, write_stage_outputs

OUT = T6/'05_synthesis'
STAGES = {
    't6_1': T6/'01_eclass',
    't6_2': T6/'02_recycling',
    't6_3': T6/'03_failure_anatomy',
    't6_4': T6/'04_regime',
}
FROZEN_COMMITS = {
    't6_0': '0f3783d', 't6_1': '50575f5', 't6_2': 'a4e8402',
    't6_3': 'bf0f44f', 't6_4': '52ea1f4',
}


def main():
    contract = load_contract()
    all_claims = []
    claim_stage = {}
    chain = []
    for stage, d in STAGES.items():
        cl = __import__('json').loads((d/f'{stage}_claims.json').read_text())['claims']
        gates = __import__('json').loads((d/f'{stage}_gates.json').read_text())
        man = __import__('json').loads((d/f'{stage}_manifest.json').read_text())
        all_claims.extend(cl)
        for c in cl:
            claim_stage[c['claim_id']] = stage
        chain.append({
            'stage': stage, 'dir': d.name, 'frozen_commit': FROZEN_COMMITS[stage],
            'gate_overall': gates.get('overall'),
            'gate_fail': [k for k, v in gates.items()
                          if k not in ('overall',) and isinstance(v, dict)
                          and v.get('verdict', 'PASS') not in ('PASS', 'SKIP')],
            'manifest_products': sorted(p['file'] for p in man['products']),
            'claims_sha256': sha256_file(d/f'{stage}_claims.json'),
            'gates_sha256': sha256_file(d/f'{stage}_gates.json'),
        })

    status_counts = {}
    for c in all_claims:
        status_counts[c['status']] = status_counts.get(c['status'], 0) + 1

    report = {
        'stage': 't6_5',
        'contract_sha256': sha256_file(T6/'t6_contract.json'),
        'aggregation_only': True,
        'no_new_statistics': True,
        'frozen_chain': chain,
        'claims_inventory': [
            {'claim_id': c['claim_id'], 'status': c['status'], 'stage': claim_stage[c['claim_id']]}
            for c in all_claims],
        'status_counts': status_counts,
        'decision_mapping': {
            'frozen_conclusions': [
                {'conclusion': 'E-class is an initial risk-budget structure, not a return score',
                 'cites': ['C102', 'C103', 'C104', 'C105', 'C110', 'C404']},
                {'conclusion': 'REDUCE is deterioration-triggered with magnitude-stratified outcomes',
                 'cites': ['C201']},
                {'conclusion': 'ADD re-enters quickly at lower prices without indicator-repair confirmation (behavioral description)',
                 'cites': ['C202', 'C207']},
                {'conclusion': 'Failure mass sits in F1 early-operator + F3 false-recovery + F6 residual; exit-missing and data-gap stages are marginal',
                 'cites': ['C301', 'C306']},
                {'conclusion': 'False-recovery signature is a HOT REDUCE day (bounce + efficiency + turnover), median dd non-separating',
                 'cites': ['C302']},
            ],
            'open_hypotheses': [
                {'hypothesis': 'The remaining separator between true and false recovery (stock-internal path vs unobserved external variables)',
                 'cites': ['C402'], 'boundary': 'NOT_FOUND_IN_TESTED_REPRESENTATION'},
                {'hypothesis': 'Mechanism producing E2 confirmation terminal-failure excess (multi-path: F6+F1+F3)',
                 'cites': ['C303', 'C304', 'C405'], 'boundary': 'DESCRIPTIVE_ONLY_NO_INTERACTION_CONTRAST'},
                {'hypothesis': 'F6 residual composition (largest failure class, undecomposed by preregistered taxonomy)',
                 'cites': ['C301', 'C303'], 'boundary': 'UNRESOLVED_RESIDUAL'},
                {'hypothesis': 'Sector interaction',
                 'cites': ['C406'], 'boundary': 'DATA_UNAVAILABLE_NON_PIT'},
            ],
        },
        'unresolved_evidence_boundaries': [
            'F6 residual: largest failure class not decomposed (preregistered taxonomy residual; decomposition deferred to avoid post-hoc refinement)',
            'True/false-recovery separator: not found in the tested breadth/new-high regime; stock-internal vs unobserved-external remains open',
            'Sector interaction: preregistered sector_metrics absent from frozen T6.0 fact layer (NON-PIT) — unavailability is not evidence of absence',
        ],
    }
    write_stage_outputs(OUT, 't6_5', {}, {'inputs': [
        {'name': f'{s}_claims', 'path': f'output/research/t6/{d.name}/{s}_claims.json',
         'sha256': sha256_file(d/f'{s}_claims.json'), 'bytes': 0}
        for s, d in STAGES.items()]}, report)
    print('chain ok:', all(c['gate_overall'] == 'PASS' for c in chain))
    print('claims:', len(all_claims), status_counts)


if __name__ == '__main__':
    main()
