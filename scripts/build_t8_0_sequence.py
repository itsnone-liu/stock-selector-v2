#!/usr/bin/env python3
"""T8.0 — Sequence Fact Layer: full REDUCE-cycle risk set + ADD order
reconstruction (frozen T8 Plan v2 §4).

Mechanical only, zero new variable definitions:
  - every frozen T6.2 cycle maps to exactly one cycle_attempt row
    (RECOVERED_ADD / NO_RECOVERY / FAILED_EXIT / CENSORED — the competing
    paths never disappear);
  - cycle_index = within-episode cycle ordinal (ALL types);
  - k_add = ADD order (only RECOVERED_ADD rows carry it, 1..n_add,
    no gaps);
  - per ADD_k traceability: a0_day / preceding r0_day / next reduce-or-exit
    (next cycle's r0_day in the episode, else the cycle's own end state) /
    horizon_end (episode last effective day).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, sha256_file, write_stage_outputs  # noqa: E402

T7 = T6.parent/'t7'
OUT = T7.parent/'t8'/'00_sequence_factlayer'


def main():
    cyc = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet',
                          columns=['event_id', 'segment', 'E_class', 'r0_day',
                                   'a0_day', 'type', 'stock_code', 'T0_date'])
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref'])
    dm = dm[dm.exposure_after_ref.notna()]
    horizon_end = dm.groupby('event_id').delta_day.max().to_dict()

    rows = []
    for ev, g in cyc.groupby('event_id', sort=False):
        g = g.sort_values('r0_day')
        n = len(g)
        k_add = 0
        r0s = g.r0_day.to_numpy(float)
        types = g.type.to_numpy()
        for i in range(n):
            has_add = types[i] == 'RECOVERED_ADD'
            if has_add:
                k_add += 1
            next_r0 = r0s[i + 1] if i + 1 < n else np.nan
            rows.append({
                'event_id': ev,
                'segment': g.segment.iloc[i],
                'E_class': g.E_class.iloc[i],
                'cycle_index': i + 1,
                'k_add': (k_add if has_add else np.nan),
                'type': types[i],
                'has_add': bool(has_add),
                'r0_day': int(r0s[i]),
                'a0_day': (float(g.a0_day.iloc[i]) if has_add else np.nan),
                'next_r0_day': (float(next_r0) if np.isfinite(next_r0)
                                else np.nan),
                'horizon_end': int(horizon_end.get(ev, np.nan)),
            })
    att = pd.DataFrame(rows)

    # conservation assertions (fail loudly before writing anything)
    assert len(att) == 31260, len(att)
    assert att.type.value_counts().to_dict() == \
        {'RECOVERED_ADD': 15646, 'NO_RECOVERY': 11858,
         'FAILED_EXIT': 3338, 'CENSORED': 418}
    assert not att.duplicated(['event_id', 'cycle_index']).any()
    key0 = set(zip(cyc.event_id, cyc.r0_day.astype(int)))
    assert set(zip(att.event_id, att.r0_day.astype(int))) == key0
    for ev, g in att[att.has_add].groupby('event_id'):
        ks = g.k_add.to_numpy(int)
        assert (ks == np.arange(1, len(ks) + 1)).all(), ev

    report = {
        'stage': 't8_0',
        'identity': 'sequence fact layer: full REDUCE-cycle risk set with '
                    'ADD order reconstruction; competing paths (no-ADD '
                    'cycles) preserved; mechanical, zero new variables',
        'n_rows': int(len(att)),
        'type_counts': att.type.value_counts().to_dict(),
        'n_episodes': int(att.event_id.nunique()),
        'k_add_distribution': att[att.has_add].k_add.value_counts().sort_index().to_dict(),
        'conservation': 'rows=31260; (event_id,cycle_index) unique; keyset '
                        'equals frozen T6.2; k_add 1..n_add no gaps',
        'inputs': [
            {'name': 't6_2_cycle_master',
             'path': 'output/research/t6/02_recycling/t6_2_cycle_master.parquet',
             'sha256': sha256_file(T6/'02_recycling/t6_2_cycle_master.parquet'),
             'bytes': 0},
            {'name': 't6_0_daily_master',
             'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'),
             'bytes': 0},
            {'name': 't8_plan_v2',
             'path': 'docs/plans/T8_RERISK_MARGINAL_VALUE_PLAN.md',
             'sha256': sha256_file(ROOT/'docs/plans/T8_RERISK_MARGINAL_VALUE_PLAN.md'),
             'bytes': 0},
        ],
    }
    write_stage_outputs(OUT, 't8_0', {'cycle_attempt': att},
                        {'inputs': report['inputs']}, report)
    print('rows', len(att), '| k_add dist:',
          report['k_add_distribution'])
    print('episodes', report['n_episodes'])


if __name__ == '__main__':
    main()
