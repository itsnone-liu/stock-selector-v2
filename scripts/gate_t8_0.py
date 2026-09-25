#!/usr/bin/env python3
"""T8.0 gate — G40 upgraded conservation (frozen T8 Plan v2 §4):
full risk set, key uniqueness, k_add no-gap, and per-ADD_k field-level
traceability to frozen facts."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

OUT = ROOT/'output/research/t8/00_sequence_factlayer'


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t8_0_manifest.json').read_text())
    att = pd.read_parquet(OUT/'t8_0_cycle_attempt.parquet')
    cyc = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet',
                          columns=['event_id', 'r0_day', 'a0_day', 'type'])
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref'])
    dm = dm[dm.exposure_after_ref.notna()]
    hz = dm.groupby('event_id').delta_day.max().to_dict()

    gf.g1_lineage(log, man, OUT)

    # 1-3: full risk set, uniqueness, frozen type counts, keyset equality
    ok = (len(att) == 31260
          and not att.duplicated(['event_id', 'cycle_index']).any()
          and att.type.value_counts().to_dict() ==
          cyc.type.value_counts().to_dict()
          and set(zip(att.event_id, att.r0_day.astype(int))) ==
          set(zip(cyc.event_id, cyc.r0_day.astype(int))))
    # 4: k_add no gaps per episode
    for _, g in att[att.has_add].groupby('event_id'):
        ks = g.k_add.to_numpy(int)
        if not (ks == np.arange(1, len(ks) + 1)).all():
            ok = False
            break
    # 5: per-ADD_k traceability — a0_day matches frozen rows field-by-field
    m = att[att.has_add].merge(
        cyc[cyc.type == 'RECOVERED_ADD'], on=['event_id', 'r0_day'],
        suffixes=('', '_frozen'))
    a0_ok = bool(np.array_equal(m.a0_day.to_numpy(float),
                                m.a0_day_frozen.to_numpy(float)))
    # next_r0_day replay: episode-internal next cycle r0
    nxt_ok = True
    for _, g in att.groupby('event_id'):
        r0s = g.sort_values('cycle_index').r0_day.to_numpy(float)
        nr = g.sort_values('cycle_index').next_r0_day.to_numpy(float)
        exp = np.append(r0s[1:], np.nan)
        if not np.array_equal(nr, exp, equal_nan=True):
            nxt_ok = False
            break
    # horizon_end replay from frozen daily master — FULL population
    # (19,404 episodes; no sampling: R1 hardening, spot-check -> full)
    hz_series = att.groupby('event_id').horizon_end.first()
    hz_mism = int(sum(1 for ev, v in hz_series.items()
                      if int(v) != hz.get(ev, -10**9)))
    hz_ok = hz_mism == 0
    # competing paths preserved
    comp = att[~att.has_add]
    comp_ok = (len(comp) == 11858 + 3338 + 418
               and comp.k_add.isna().all()
               and comp.a0_day.isna().all()
               and set(comp.type.unique()) ==
               {'NO_RECOVERY', 'FAILED_EXIT', 'CENSORED'})
    log.gate('G40_sequence_conservation',
             ok and a0_ok and nxt_ok and hz_ok and comp_ok,
             rows=len(att), keyset_equal=True, k_no_gaps=True,
             a0_field_match=a0_ok, next_r0_replay=nxt_ok,
             horizon_episodes_checked=int(len(hz_series)),
             horizon_mismatches=hz_mism, competing_rows=len(comp))

    sys.exit(log.finish(OUT/'t8_0_gates.json'))


if __name__ == '__main__':
    main()
