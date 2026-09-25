#!/usr/bin/env python3
"""T7.3 gates — counterfactual conservation, dual-clock audit, sizing
inheritance, VAL-only reporting discipline."""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

T7 = T6.parent/'t7'
IN0 = T7/'00_path_factlayer'
OUT = T7/'03_policy_validation'
POLICIES = ('A', 'B1', 'B2', 'B3', 'B5', 'C1', 'C2')


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t7_3_manifest.json').read_text())
    rep = json.loads((OUT/'t7_3_report_data.json').read_text())
    replay = pd.read_parquet(OUT/'t7_3_replay.parquet')
    summ = pd.read_parquet(OUT/'t7_3_summary_val.parquet')
    t7c = json.loads((T7/'t7_contract.json').read_text())
    q1 = t7c['policy_amendments']['primary_amendment_candidate']['threshold']
    q2 = t7c['policy_amendments']['secondary_sensitivity']['threshold']

    gf.g1_lineage(log, man, OUT)

    # G2b: upstream immutability (T7.0 manifests)
    ok = True
    n_prod = 0
    for mf in ('t7_0_features_manifest.json', 't7_0_outcomes_manifest.json'):
        for pr in json.loads((IN0/mf).read_text())['products']:
            n_prod += 1
            if sha256_file(IN0/pr['file']) != pr['sha256']:
                ok = False
    log.gate('G2b_upstream_immutable', ok, products_verified=n_prod)

    # G25 counterfactual conservation: every policy covers the SAME cycle
    # universe; C1's ADD-less cycles stay in the evaluation set
    keys = {p: set(zip(replay[replay.policy == p].event_id,
                       replay[replay.policy == p].r0_day.astype(int)))
            for p in POLICIES}
    k0 = keys['A']
    ok25 = (len(replay) == 31260 * len(POLICIES)
            and all(keys[p] == k0 for p in POLICIES)
            and len(k0) == 31260
            # cycles where C1 vetoes ADD remain present with has_add=False
            and replay[(replay.policy == 'C1') & (~replay.has_add)].shape[0]
            + replay[(replay.policy == 'C1') & (replay.has_add)].shape[0]
            == 31260
            # replay rows carry every segment (universe integrity), while
            # summaries are VAL only
            and set(replay.segment) == {'validation', 'confirmation',
                                        'development'}
            and set(summ.policy) == set(POLICIES)
            and int(summ.n_cycles.sum() / len(POLICIES)) == 17150)
    log.gate('G25_counterfactual_conservation', ok25,
             cycles=len(k0), rows=int(len(replay)),
             c1_addless=int((~replay[(replay.policy == 'C1')].has_add).sum()))

    # G26 dual-clock audit: False ADD recomputed from each policy's OWN
    # add_day; Missed Recovery from the common cycle est clock
    severe = load_contract()['preregistered_thresholds']['severe_dd_depth_log']
    W = int(t7c['error_cost']['false_add']['horizon'])
    out0 = pd.read_parquet(IN0/'t7_0_outcomes_outcomes.parquet',
                           columns=['event_id', 'r0_day',
                                    'recovery_established_day'])
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'close_adj'])
    dm = dm[dm.exposure_after_ref.notna()]
    dclose = {}
    for ev, g in dm.groupby('event_id', sort=False):
        g = g.sort_values('delta_day')
        dclose[ev] = (g.delta_day.to_numpy(int), g.close_adj.to_numpy(float))
    samp = replay[replay.has_add].sample(120, random_state=5)
    mism_fa = mism_mr = 0
    for r in samp.itertuples():
        offs, close = dclose[r.event_id]
        iw = (offs > r.add_day) & (offs <= r.add_day + W)
        cp = close[iw]
        run_dd = np.log(cp / np.maximum.accumulate(cp))
        est = out0[(out0.event_id == r.event_id)
                   & (out0.r0_day == r.r0_day)].recovery_established_day
        est = float(est.iloc[0]) if len(est) else np.nan
        est_in = np.isfinite(est) and r.add_day < est <= r.add_day + W
        fa = (not est_in) and bool(np.any(run_dd <= -severe))
        if fa != r.false_add:
            mism_fa += 1
        # common-clock missed: only meaningful for TR cycles
        if r.true_recovery and np.isfinite(est):
            mr = (not r.has_add) or (r.add_day > est)
            if mr != r.missed_recovery:
                mism_mr += 1
    log.gate('G26_dual_clock_replay', mism_fa == 0 and mism_mr == 0,
             false_add_mismatches=mism_fa, missed_mismatches=mism_mr,
             sampled=len(samp))

    # G27 sizing inheritance + no threshold literals in source
    ok27 = bool(replay.inheritance_ok.all())
    src = (ROOT/'scripts/run_t7_3.py').read_text()
    code = '\n'.join(re.sub(r'#.*$', '', ln) for ln in src.splitlines())
    code = re.sub(r"'[^'\n]*'", "''", re.sub(r'"[^"\n]*"', '""', code))
    for lit in (repr(q1), repr(q2), '-0.0187', '0.0180'):
        if lit in code:
            ok27 = False
    log.gate('G27_sizing_inheritance_no_literals', ok27,
             violations=int((~replay.inheritance_ok).sum()))

    # G28 VAL-only reporting: summary is VAL; report carries no CONF numbers
    ok28 = ('CONF deliberately NOT computed' in rep['identity']
            and rep['thresholds_from_contract']['C1'] == q1
            and summ.n_cycles.nunique() == 1
            and int(summ.n_cycles.iloc[0]) == 17150)
    log.gate('G28_val_only_reporting', ok28)

    sys.exit(log.finish(OUT/'t7_3_gates.json'))


if __name__ == '__main__':
    main()
