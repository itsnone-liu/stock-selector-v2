#!/usr/bin/env python3
"""T8.1 gates — G41/G42/G43/G44 (frozen T8 Plan v2 §6)."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

T7 = T6.parent/'t7'
T8 = T6.parent/'t8'
OUT = T8/'01_order_anatomy'
W = 10


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t8_1_manifest.json').read_text())
    rep = json.loads((OUT/'t8_1_report_data.json').read_text())
    an = pd.read_parquet(OUT/'t8_1_order_anatomy.parquet')
    att = pd.read_parquet(T8/'00_sequence_factlayer/t8_0_cycle_attempt.parquet')
    out0 = pd.read_parquet(T7/'00_path_factlayer/t7_0_outcomes_outcomes.parquet',
                           columns=['event_id', 'r0_day', 'false_recovery',
                                    'true_recovery', 're_reduce_day'])

    gf.g1_lineage(log, man, OUT)

    # G41 segmentation discipline: full-population rows carry segment,
    # grouping fixed k1/k2/k3+, no freeze-era rule fields
    adds = att[att.has_add]
    ok41 = (len(an) == 15646
            and set(an.k_group.unique()) == {'k1', 'k2', 'k3+'}
            and an.k_group.isin(['k1', 'k2', 'k3+']).all()
            and ((an.k_add == 1) == (an.k_group == 'k1')).all()
            and ((an.k_add == 2) == (an.k_group == 'k2')).all()
            and ((an.k_add >= 3) == (an.k_group == 'k3+')).all()
            and set(an.segment.unique()) <= {'development', 'validation',
                                             'confirmation'})
    log.gate('G41_segmentation_fixed_grouping', ok41, rows=len(an))

    # G42 dual clock: W10 endpoint replay + frozen-flag passthrough
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'close_adj'])
    dm = dm[dm.exposure_after_ref.notna()].sort_values(['event_id', 'delta_day'])
    agg = {ev: (g.delta_day.to_numpy(int), g.exposure_after_ref.to_numpy(float),
                g.close_adj.to_numpy(float))
           for ev, g in dm.groupby('event_id', sort=False)}
    m = adds.merge(out0, on=['event_id', 'r0_day'])
    key = {(r.event_id, int(r.a0_day)): (bool(r.false_recovery),
                                         bool(r.true_recovery))
           for r in m.itertuples()}
    mism = n_s = 0
    for r in an.sample(150, random_state=21).itertuples():
        n_s += 1
        offs, expo, close = agg[r.event_id]
        ia = int(np.searchsorted(offs, int(r.a0_day)))
        ie = min(ia + W, len(offs))
        win = np.log(close[ia:ie] / close[ia])
        ok = (int(r.n_obs_w10) == ie - ia
              and abs(r.dd_w10 - win.min()) < 1e-12
              and abs(r.mfe_w10 - win.max()) < 1e-12
              and abs(r.ret_w10 - win[-1]) < 1e-12
              and abs(r.occ_w10 - expo[ia:ie].mean()) < 1e-12)
        fa, tr = key[(r.event_id, int(r.a0_day))]
        ok = ok and r.false_add == fa and r.recovery == tr
        if not ok:
            mism += 1
    log.gate('G42_dual_clock_replay', mism == 0, sampled=n_s, mismatches=mism)

    # G43 descriptive discipline: no p-values, no thresholds, no rule words
    txt = json.dumps(rep, ensure_ascii=False)
    ok43 = (not re.search(r'"p_?(val|value)|holm|significan|threshold'
                          r'|cut_?off|rule"', txt, re.I)
            and 'false_add_rate' in str(rep['by_k_group']['k1']))
    log.gate('G43_descriptive_only', ok43)

    # G44 estimand naming: no causal wording anywhere in report identity
    ok44 = not re.search(r'导致|造成|因果|causes?|due to|effect of k',
                         json.dumps(rep, ensure_ascii=False), re.I)
    log.gate('G44_estimand_naming', ok44,
             estimand=rep.get('estimand', ''))

    sys.exit(log.finish(OUT/'t8_1_gates.json'))


if __name__ == '__main__':
    main()
