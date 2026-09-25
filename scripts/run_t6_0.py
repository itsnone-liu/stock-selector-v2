#!/usr/bin/env python3
"""T6.0 — contract + common fact layer (Episode Master & Daily Master).

Freezes the unified research fact tables every T6 stage reads. Baseline
80e934c (T5.8R-2). Read-only upstream. All numbers in the report come from
t6_0_report_data.json (machine aggregation of the frozen masters).
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import (T6, build_episode_master, build_daily_master,
                       write_stage_outputs, sha256_file, UPSTREAM_PRODUCTS,
                       canonical_frame_hash)

OUT = T6/'00_factlayer'

INPUTS = [
    ('t4_6_assignment', ROOT/'output/research/t4/entry_policy/t4_6_assignment.parquet'),
    ('t5_daily_state', ROOT/'output/research/t5/facts/t5_daily_state.parquet'),
    ('t5_candidate_state_daily', ROOT/'output/research/t5/state/t5_candidate_state_daily.parquet'),
    ('t5_operational_state_daily_v2', ROOT/'output/research/t5/transition/t5_operational_state_daily_v2.parquet'),
    ('t5_7_exposure_trajectory', ROOT/'output/research/t5/exposure_adjustment/t5_7_exposure_trajectory.parquet'),
    ('t5_8_episode_results', ROOT/'output/research/t5/full_lifecycle/t5_8_episode_results.parquet'),
    ('t5_8_daily_exposure_pnl', ROOT/'output/research/t5/full_lifecycle/t5_8_daily_exposure_pnl.parquet'),
]


def main():
    ep = build_episode_master()
    dm = build_daily_master()

    # ---- integrity checks the builders assert before writing ----
    assert len(ep) == 283088, f'episode master rows {len(ep)} != frozen 283,088'
    assert len(dm) == 492900, f'daily master rows {len(dm)} != frozen 492,900'
    assert set(ep.segment.unique()) == {'development', 'validation', 'confirmation'}

    # ---- report data: every reported number machine-derived ----
    rep = {
        'episode_master': {
            'rows': int(len(ep)),
            'by_policy': ep.policy_id.value_counts().to_dict(),
            'by_E_class': {str(k): int(v) for k, v in
                           ep[ep.policy_id != 'CONTROL'].E_class.value_counts().items()},
            'filled_rate': float(ep[ep.policy_id != 'CONTROL'].filled.mean()),
            'not_filled_no_position': int(((ep.policy_id != 'CONTROL') & (~ep.filled)).sum()),
            'censored': int(ep.censored.sum()),
        },
        'daily_master': {
            'rows': int(len(dm)),
            'events': int(dm.event_id.nunique()),
            'median_lifecycle_days': float(ep.lifecycle_days.median()),
            'row_present_rate': float(dm.row_present.mean()),
            'resolution_state_top': dm.resolution_state.value_counts().head(8).to_dict(),
            'operational_state_top': dm.operational_state.value_counts().head(8).to_dict(),
            'ref_exec_rows': int(dm.exposure_after_ref.notna().sum()),
        },
        'join_integrity': {
            'episode_event_set_equals_daily': bool(
                set(ep.event_id.unique()) == set(dm.event_id.unique())),
            'E_class_values': sorted(ep.E_class.dropna().unique().tolist()),
            'initial_state_values': sorted(ep.initial_state.dropna().unique().tolist())[:12],
        },
    }

    inputs = [{'name': n, 'path': str(p.relative_to(ROOT)), 'sha256': sha256_file(p),
               'bytes': p.stat().st_size} for n, p in INPUTS]
    upstream_hashes = [{'path': str(p.relative_to(ROOT)), 'sha256': sha256_file(p)}
                       for p in UPSTREAM_PRODUCTS]
    man = write_stage_outputs(
        OUT, 't6_0',
        {'episode_master': ep, 'daily_master': dm},
        {'inputs': inputs, 'upstream_hashes': upstream_hashes},
        rep)
    # canonical hashes for G10 (rebuild path uses the same builders)
    (OUT/'t6_0_canonical.json').write_text(
        __import__('json').dumps({
            'episode_master': canonical_frame_hash(ep),
            'daily_master': canonical_frame_hash(dm)}, indent=2))
    man['products'].append({'file': 't6_0_canonical.json',
                            'sha256': sha256_file(OUT/'t6_0_canonical.json'),
                            'bytes': (OUT/'t6_0_canonical.json').stat().st_size})
    (OUT/'t6_0_manifest.json').write_text(__import__('json').dumps(man, indent=2, ensure_ascii=False))
    print('episode_master', ep.shape, 'daily_master', dm.shape)
    print({k: v for k, v in rep['join_integrity'].items()})


if __name__ == '__main__':
    main()
