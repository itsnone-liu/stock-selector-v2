#!/usr/bin/env python3
"""T7.3-R1 gates — adds:
  G29 feature-decision-clock identity (FULL population, not sampled):
      for every C1/C2-eligible cycle, the observation cutoff of
      max_bounce_R5 (last effective day with delta_day in (R0, R0+5],
      replayed from the daily fact layer) must be <= the policy decision
      day, and when R+5 itself trades the decision day IS R+5.
      Proves the confirmation feature is fully observable at ADD time.
  G26 upgraded: stratified replay per policy (100 each) + C1 clock-relation
      strata (add_day vs A's a0_day).
  est distribution persisted for the missed-recovery interpretation.
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

    # G2b upstream immutability
    ok, n_prod = True, 0
    for mf in ('t7_0_features_manifest.json', 't7_0_outcomes_manifest.json'):
        for pr in json.loads((IN0/mf).read_text())['products']:
            n_prod += 1
            if sha256_file(IN0/pr['file']) != pr['sha256']:
                ok = False
    log.gate('G2b_upstream_immutable', ok, products_verified=n_prod)

    # G25 counterfactual conservation
    keys = {p: set(zip(replay[replay.policy == p].event_id,
                       replay[replay.policy == p].r0_day.astype(int)))
            for p in POLICIES}
    k0 = keys['A']
    ok25 = (len(replay) == 31260 * len(POLICIES)
            and all(keys[p] == k0 for p in POLICIES)
            and len(k0) == 31260
            and set(replay.segment) == {'validation', 'confirmation',
                                        'development'}
            and set(summ.policy) == set(POLICIES)
            and int(summ.n_cycles.sum() / len(POLICIES)) == 17150)
    log.gate('G25_counterfactual_conservation', ok25,
             cycles=len(k0), rows=int(len(replay)),
             c1_addless=int((~replay[(replay.policy == 'C1')].has_add).sum()))

    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'close_adj'])
    dm = dm[dm.exposure_after_ref.notna()]
    dclose = {}
    for ev, g in dm.groupby('event_id', sort=False):
        g = g.sort_values('delta_day')
        dclose[ev] = (g.delta_day.to_numpy(int), g.close_adj.to_numpy(float))

    # G29 feature-decision-clock identity — FULL population over C1/C2 rows
    c_rows = replay[replay.policy.isin(('C1', 'C2')) & replay.has_add]
    viol_cut = viol_day = viol_off = n_checked = 0
    for r in c_rows.itertuples():
        offs, _ = dclose[r.event_id]
        wmask = (offs > r.r0_day) & (offs <= r.r0_day + 5)
        if not wmask.any():
            viol_cut += 1
            continue
        cutoff = int(offs[wmask][-1])
        n_checked += 1
        # decision day must not precede the feature observation cutoff
        if r.add_day < cutoff:
            viol_cut += 1
        # when R+5 itself trades, the decision day IS R+5 (same-close
        # decision: feature uses the R+5 close, ADD executes on that close)
        if cutoff == r.r0_day + 5 and r.add_day != r.r0_day + 5:
            viol_day += 1
        # maxbounce_day_offset sanity via stored feature
    feat = pd.read_parquet(IN0/'t7_0_features_anchor_features.parquet',
                           columns=['event_id', 'r0_day', 'maxbounce_day_offset'])
    mg = c_rows.merge(feat, on=['event_id', 'r0_day'])
    viol_off = int((mg.maxbounce_day_offset > 5).sum())
    log.gate('G29_feature_decision_clock_identity',
             viol_cut == 0 and viol_day == 0 and viol_off == 0
             and n_checked == len(c_rows),
             c_policies_rows=len(c_rows), cutoff_violations=viol_cut,
             r5_trading_day_mismatches=viol_day,
             maxbounce_offset_gt5=viol_off,
             semantics='feature window: delta_day in (R0, R0+5] (market-day '
                       'advance, halts NOT compressed) per frozen '
                       'build_t7_0_features.py line 85; decision day = first '
                       'effective row with delta_day >= R0+5 (same close '
                       'basis). B family keeps its contract wording '
                       '"N effective trading days" — two distinct frozen '
                       'clock words, both honoured.')

    # est distribution (persisted for missed-recovery interpretation)
    out0 = pd.read_parquet(IN0/'t7_0_outcomes_outcomes.parquet',
                           columns=['event_id', 'r0_day', 'segment',
                                    'recovery_established_day'])
    v0 = out0[out0.segment == 'validation']
    est_off = v0.recovery_established_day - v0.r0_day
    est_off = est_off[est_off.notna()]
    est_stats = {
        'n_tr_established': int(len(est_off)),
        'median': float(est_off.median()), 'p25': float(est_off.quantile(.25)),
        'p75': float(est_off.quantile(.75)),
        'P_est_le_R1': float((est_off <= 1).mean()),
        'P_est_le_R2': float((est_off <= 2).mean()),
        'P_est_le_R3': float((est_off <= 3).mean()),
        'P_est_le_R5': float((est_off <= 5).mean()),
    }
    rep['recovery_established_offset_distribution_val'] = est_stats
    (OUT/'t7_3_report_data.json').write_text(
        json.dumps(rep, ensure_ascii=False, indent=2))

    # G26 dual-clock stratified replay
    severe = load_contract()['preregistered_thresholds']['severe_dd_depth_log']
    W = int(t7c['error_cost']['false_add']['horizon'])
    est_map = {(e, int(r)): (float(s) if np.isfinite(s) else np.nan)
               for e, r, s in zip(out0.event_id, out0.r0_day,
                                  out0.recovery_established_day)}
    mism_fa = mism_mr = 0
    strat = {}
    for p in POLICIES:
        pool = replay[(replay.policy == p) & replay.has_add]
        strat[p] = pool.sample(min(100, len(pool)), random_state=7)
    c1 = replay[(replay.policy == 'C1') & replay.has_add]
    a0map = {(e, int(r)): (float(a) if np.isfinite(a) else np.nan)
             for e, r, a in zip(replay[replay.policy == 'A'].event_id,
                                replay[replay.policy == 'A'].r0_day,
                                replay[replay.policy == 'A'].add_day)}
    for rel, m in (('earlier', c1[c1.apply(
                        lambda x: (np.isfinite(a0map[(x.event_id, x.r0_day)])
                                   and x.add_day <
                                   a0map[(x.event_id, x.r0_day)]), axis=1)]),
                   ('same', c1[c1.apply(
                        lambda x: (np.isfinite(a0map[(x.event_id, x.r0_day)])
                                   and x.add_day ==
                                   a0map[(x.event_id, x.r0_day)]), axis=1)]),
                   ('later', c1[c1.apply(
                        lambda x: (np.isfinite(a0map[(x.event_id, x.r0_day)])
                                   and x.add_day >
                                   a0map[(x.event_id, x.r0_day)]), axis=1)])):
        if len(m):
            strat[f'C1_add_{rel}_than_A'] = m.sample(
                min(30, len(m)), random_state=7)
    n_samp = 0
    for name, samp in strat.items():
        for r in samp.itertuples():
            n_samp += 1
            offs, close = dclose[r.event_id]
            iw = (offs > r.add_day) & (offs <= r.add_day + W)
            cp = close[iw]
            run_dd = np.log(cp / np.maximum.accumulate(cp))
            est = est_map[(r.event_id, int(r.r0_day))]
            est_in = np.isfinite(est) and r.add_day < est <= r.add_day + W
            fa = (not est_in) and bool(np.any(run_dd <= -severe))
            if fa != r.false_add:
                mism_fa += 1
            if r.true_recovery and np.isfinite(est):
                mr = (not r.has_add) or (r.add_day > est)
                if mr != r.missed_recovery:
                    mism_mr += 1
    log.gate('G26_dual_clock_replay', mism_fa == 0 and mism_mr == 0,
             false_add_mismatches=mism_fa, missed_mismatches=mism_mr,
             stratified_sampled=n_samp, strata=sorted(strat))

    # G27 sizing inheritance + no literals
    ok27 = bool(replay.inheritance_ok.all())
    src = (ROOT/'scripts/run_t7_3.py').read_text()
    code = '\n'.join(re.sub(r'#.*$', '', ln) for ln in src.splitlines())
    code = re.sub(r"'[^'\n]*'", "''", re.sub(r'"[^"\n]*"', '""', code))
    for lit in (repr(q1), repr(q2), '-0.0187', '0.0180'):
        if lit in code:
            ok27 = False
    log.gate('G27_sizing_inheritance_no_literals', ok27,
             violations=int((~replay.inheritance_ok).sum()))

    ok28 = ('CONF deliberately NOT computed' in rep['identity']
            and rep['thresholds_from_contract']['C1'] == q1
            and summ.n_cycles.nunique() == 1
            and int(summ.n_cycles.iloc[0]) == 17150)
    log.gate('G28_val_only_reporting', ok28)

    sys.exit(log.finish(OUT/'t7_3_gates.json'))


if __name__ == '__main__':
    main()
