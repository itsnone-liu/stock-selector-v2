#!/usr/bin/env python3
"""T6.0 gates — first application of the frozen unified gate framework."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import (T6, load_contract, UPSTREAM_PRODUCTS, canonical_frame_hash)  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

OUT = T6/'00_factlayer'


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t6_0_manifest.json').read_text())
    contract = load_contract()
    ep = pd.read_parquet(OUT/'t6_0_episode_master.parquet')
    dm = pd.read_parquet(OUT/'t6_0_daily_master.parquet')

    gf.g1_lineage(log, man, OUT)
    gf.g2_upstream_immutability(log, man)
    gf.g3_pit_truncation_replay(log, dm, n_events=40, seed=7)

    build_src = (ROOT/'src/t6/common.py').read_text()
    gf.g4_outcome_separation(log, {'episode_master': ep, 'daily_master': dm}, [build_src])
    gf.g5_segment_isolation(log, {'episode_master': ep, 'daily_master': dm})

    run_src = (ROOT/'scripts/run_t6_0.py').read_text()
    gf.contract_symbol_asserts(log, contract)
    gf.contract_reference_integrity(log, contract,
                                    legal_identifiers=set(dm.columns) | set(ep.columns))
    gf.g6_preregistration(log, [run_src, build_src], contract)
    gf.g7_no_tuning(log, [run_src, build_src])

    # G8: conservation — episode cells by policy decompose the total; ref-exec
    # daily rows equal the frozen T5.8R-2 daily count of the reference cell.
    parts = ep.policy_id.value_counts().to_dict()
    total = len(ep)
    dd_ref = pd.read_parquet(ROOT/'output/research/t5/full_lifecycle/t5_8_daily_exposure_pnl.parquet',
                             columns=['strategy', 'policy_id'])
    n_ref_frozen = int(((dd_ref.strategy == 'direct_chase') & (dd_ref.policy_id == 'P2_balanced')).sum())
    ref_cell_rows = int(dm.exposure_after_ref.notna().sum())
    gf.g8_conservation(log, {
        'episode_by_policy': (total, parts),
        'ref_exec_daily_rows': (n_ref_frozen, {'filled_ref_rows': ref_cell_rows}),
    })

    log.skip('G9_statistical_integrity',
             'T6.0 builds fact tables only; no inference/bootstrap is run at this stage')

    def rebuild(key):
        from t6.common import build_episode_master, build_daily_master
        return (build_episode_master() if key.endswith('episode_master')
                else build_daily_master())
    gf.g10_determinism(log, man, OUT, rebuild)

    report = ROOT/'docs/reports/T6_0_FACT_LAYER.md'
    claim_registry = T6/'05_synthesis/t6_claim_registry.json'
    gf.g11_anti_story(log, report, claim_registry if claim_registry.exists() else None)

    sys.exit(log.finish(OUT/'t6_0_gates.json'))


if __name__ == '__main__':
    main()
