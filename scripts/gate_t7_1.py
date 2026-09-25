#!/usr/bin/env python3
"""T7.1 gates — descriptive-identity enforcement + lineage + replay.

T7.1 is a descriptive path map: the gates here additionally enforce that NO
hypothesis-testing machinery was used (no p-values, no diff bootstrap, no
Holm) and that the trajectory aggregates replay correctly from the frozen
T7.0 fact layer.
"""
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
IN = T7/'00_path_factlayer'
OUT = T7/'01_path_anatomy'


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t7_1_manifest.json').read_text())
    rep = json.loads((OUT/'t7_1_report_data.json').read_text())
    traj = pd.read_parquet(OUT/'t7_1_trajectory_map.parquet')
    out = pd.read_parquet(IN/'t7_0_outcomes_outcomes.parquet',
                          columns=['event_id', 'r0_day', 'segment', 'type',
                                   'false_recovery', 'true_recovery'])
    path = pd.read_parquet(IN/'t7_0_features_path_fact.parquet')

    # G1 lineage
    gf.g1_lineage(log, man, OUT)

    # G2b: frozen T7.0 products unchanged vs their own manifests
    t70mans = [(IN, 't7_0_features_manifest.json'),
               (IN, 't7_0_outcomes_manifest.json')]
    ok = True
    n_prod = 0
    for d, mf in t70mans:
        for pr in json.loads((d/mf).read_text())['products']:
            n_prod += 1
            if sha256_file(d/pr['file']) != pr['sha256']:
                ok = False
    log.gate('G2b_t7_0_immutable', ok, products_verified=n_prod)

    # G8 group coverage conservation
    recov = (out.type == 'RECOVERED_ADD').to_numpy()
    part = (recov.astype(int) + (out.type == 'NO_RECOVERY').to_numpy().astype(int)
            + (out.type == 'FAILED_EXIT').to_numpy().astype(int)
            + (out.type == 'CENSORED').to_numpy().astype(int))
    ok8 = bool((part == 1).all()) and rep['group_coverage']['by_type_partitions_anchors']
    exp_rows = 0
    for gname, ngroups in (('by_type', 4), ('by_false_recovery', 2), ('by_true_recovery', 2)):
        exp_rows += 3 * ngroups * 7 * 7
    ok8 = ok8 and len(traj) == exp_rows
    log.gate('G8_group_coverage', ok8, anchors=int(len(out)),
             traj_rows=int(len(traj)), expected_rows=exp_rows)

    # G20 descriptive discipline: no testing machinery anywhere
    src = (ROOT/'scripts/run_t7_1.py').read_text()
    viol = []
    # call/identifier shapes only — negated prose ("no p-values") is compliant
    shapes = [r'cluster_boot_diff\s*\(', r'\bholm\s*\(', r"['\"]holm['\"]",
              r"['\"]p_value['\"]", r"\.p_value\b", r'\bttest\s*\(',
              r'\bmannwhitney\w*\s*\(', r'\bwilcoxon\s*\(']
    for pat in shapes:
        if re.search(pat, src, re.I):
            viol.append(f'src contains {pat}')
    flat = json.dumps(rep)
    for pat in ("['p_value'", '"p_value"', "['holm'", '"holm"', 'diff_ci'):
        if pat in flat:
            viol.append(f'report_data contains {pat}')
    if 'p_value' in traj.columns or 'holm' in traj.columns:
        viol.append('trajectory parquet has testing columns')
    ok20 = not viol and 'DESCRIPTIVE' in rep['identity']
    log.gate('G20_descriptive_discipline', ok20, violations=viol)

    # G21 median replay: 60 random cells recomputed naively from fact layer
    rng = np.random.default_rng(11)
    cells = traj.dropna(subset=['median']).sample(60, random_state=11)
    groups = {
        ('by_type', 'RECOVERED_ADD'): (out.type == 'RECOVERED_ADD').to_numpy(),
        ('by_type', 'NO_RECOVERY'): (out.type == 'NO_RECOVERY').to_numpy(),
        ('by_type', 'FAILED_EXIT'): (out.type == 'FAILED_EXIT').to_numpy(),
        ('by_type', 'CENSORED'): (out.type == 'CENSORED').to_numpy(),
    }
    rec = (out.type == 'RECOVERED_ADD').to_numpy()
    groups[('by_false_recovery', 'FR')] = rec & out.false_recovery.to_numpy(bool)
    groups[('by_false_recovery', 'clean')] = rec & ~out.false_recovery.to_numpy(bool)
    groups[('by_true_recovery', 'TR')] = out.true_recovery.to_numpy(bool)
    groups[('by_true_recovery', 'no_TR')] = ~out.true_recovery.to_numpy(bool)
    VARS = ['ret_vs_r0', 'drawdown_from_peak_log', 'dist_ref20',
            'volume_load_vs_prebreak', 'turnover_load_3d_mean',
            'efficiency_signed_3', 'exposure_after_ref']
    mism = 0
    dme = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                          columns=['event_id', 'delta_day', 'exposure_after_ref'])
    dme = dme[dme.exposure_after_ref.notna()]
    ekey = {(e, int(d)): v for e, d, v in zip(
        dme.event_id, dme.delta_day, dme.exposure_after_ref)}
    p2 = path.copy()
    p2['ret_vs_r0'] = np.log(p2.close_adj) - p2.r0_close_log
    # exposure lookup + per-anchor window index (built once, O(1) lookups)
    pidx = {(e, int(r)): g for (e, r), g in p2.groupby(['event_id', 'r0_day'])}
    for _, cell in cells.iterrows():
        gm = groups[(cell.grouping, cell.group)]
        m = gm & (out.segment.to_numpy() == cell.segment)
        k = int(cell.checkpoint.split('+')[1])
        sel = out.iloc[np.where(m)[0]]
        vals = []
        for ev, r0 in zip(sel.event_id, sel.r0_day):
            w = pidx.get((ev, int(r0)))
            if w is None:
                continue
            w = w[w.delta_day <= int(r0) + k]
            if len(w) == 0:
                continue
            last = w.iloc[-1]
            v = last[cell.variable] if cell.variable != 'exposure_after_ref' \
                else ekey.get((ev, int(last.delta_day)), np.nan)
            vals.append(float(v))
        vals = np.array(vals)
        vals = vals[np.isfinite(vals)]
        # replay uses the SAME frozen point-estimate definition as the build
        # (STATS['median'] = wmedian on repeat-expanded weights, NOT np.median)
        from t6.stats import STATS
        sv = np.sort(vals)
        est = float(STATS['median'](sv, np.ones(len(sv))))
        if len(vals) != int(cell.n) or abs(est - float(cell['median'])) > 1e-12:
            mism += 1
    # dual-cluster CI lineage: both CI families exist and are labeled
    ok_ci = ('ci95' in traj.columns and 'ci95_t0date' in traj.columns
             and traj.ci95.notna().sum() == traj.ci95_t0date.notna().sum()
             and rep['statistics_used']['clusters'] == ['stock_code', 'T0_date']
             and 'ci95_t0date' in rep['statistics_used'].get('cluster_implementation', ''))
    log.gate('G21b_dual_cluster_ci', bool(ok_ci),
             ci95_nonnull=int(traj.ci95.notna().sum()),
             ci95_t0date_nonnull=int(traj.ci95_t0date.notna().sum()))
    log.gate('G21_median_replay', mism == 0, cells=len(cells), mismatches=mism,
             variables=VARS)

    sys.exit(log.finish(OUT/'t7_1_gates.json'))


if __name__ == '__main__':
    main()
