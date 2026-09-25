#!/usr/bin/env python3
"""T6.3 — Failure Anatomy: WHERE do failures occur in the frozen pipeline,
and WHAT visible-at-the-time information separates recoverable deterioration
from unrecoverable deterioration?

Stage taxonomy (contract failure_anatomy_prereg, first-match order F1,F3,F2,F4,F5,F6):
  F1 initial misclassification (first REDUCE/EXIT day <= 5 AND ret<=0)
  F3 false recovery (REDUCE->ADD cycle with trigger within 5 valid obs after A0:
     dist_ref20 < 0 OR drawdown_from_peak_log >= severe_dd_depth_log)
  F2 late deterioration (>= 10 days before first REDUCE AND dd at first REDUCE
     >= severe_dd_depth_log AND ret<=0)
  F4 exit failure (max_dd_to_date >= exit_failure_dd_depth_log some day AND
     no EXIT ever AND ret<=0)
  F5 fast failure gap (>= 2 consecutive row_present=False before LIFECYCLE_END,
     OR single-day ret_1d_log <= large_loss_ret_log dominates the terminal leg)
  F6 censored / none matched

Three linked anomalies under one lens:
  (a) C106: E2 reward gain vs confirmation terminal-failure increase
  (b) C201: REDUCE-time deterioration magnitude stratifies outcome
  (c) C204: EXIT channel fires only in confirmation

All thresholds parsed from the frozen contract. Reference cell direct|P2.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file, write_stage_outputs
from t6.stats import cluster_boot_diff, cluster_boot_level, holm, make_rng_factory

OUT = T6/'03_failure_anatomy'
REF_STRATEGY, REF_POLICY = 'direct_chase', 'P2_balanced'
# visible-at-REDUCE discriminator candidates (PIT by construction)
DISC_COLS = ['drawdown_from_peak_log', 'efficiency_signed_3', 'dist_ref20',
             'turnover_load_3d_mean', 'max_dd_to_date_log', 'ret_1d_log']


def classify_event(g, ret, cens, t, has_exit, cyc_pair_trigger):
    """First-match F1,F3,F2,F4,F5,F6. g sorted by delta_day. All thresholds
    from dict t. cyc_pair_trigger: True if any REDUCE->ADD cycle of this
    event fired the false-recovery trigger."""
    days = g.delta_day.to_numpy()
    states = g.resolution_state.to_numpy()
    dd = g.drawdown_from_peak_log.to_numpy(float)
    dist = g.dist_ref20.to_numpy(float)
    mddtd = g.max_dd_to_date_log.to_numpy(float)
    pres = g.row_present.to_numpy()
    r1 = g.ret_1d_log.to_numpy(float)

    red_days = days[states == 'RESOLVED_REDUCE']
    op_days = days[(states == 'RESOLVED_REDUCE') | (states == 'RESOLVED_EXIT')]

    if cens:
        return 'F6'
    # F1
    if len(op_days) and op_days[0] <= t['quick_failure_day_window'] and ret <= 0:
        return 'F1'
    # F3
    if cyc_pair_trigger:
        return 'F3'
    # F2
    if (len(red_days) and (days[0] and (red_days[0] - days[0]) >= t['healthy_prefix_days'])
            and not np.isnan(dd[list(days).index(red_days[0])])
            and dd[list(days).index(red_days[0])] >= t['severe_dd_depth_log'] and ret <= 0):
        return 'F2'
    # F4
    if not has_exit and ret <= 0 and np.any(mddtd[~np.isnan(mddtd)] >= t['exit_failure_dd_depth_log']):
        return 'F4'
    # F5
    term = str(g.terminal_reason.iloc[0]) if 'terminal_reason' in g else ''
    gap_hit = False
    if len(pres) >= t['gap_rows_min'] and term == 'LIFECYCLE_END':
        run = 0
        for p in pres:
            run = run + 1 if not p else 0
            if run >= t['gap_rows_min']:
                gap_hit = True
                break
    crash_hit = bool(np.any(r1[~np.isnan(r1)] <= t['large_loss_ret_log']))
    if gap_hit or (crash_hit and ret <= 0):
        return 'F5'
    return 'F6'


def main():
    contract = load_contract()
    t = contract['preregistered_thresholds']
    pre = contract['statistics_prereg']
    B, SEED = pre['bootstrap_B'], pre['bootstrap_seed']

    ep = pd.read_parquet(T6/'00_factlayer/t6_0_episode_master.parquet')
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'resolution_state',
                                  'exposure_after_ref', 'row_present']
                         + DISC_COLS)
    cyc2 = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet',
                           columns=['event_id', 'r0_day', 'a0_day', 'type'])

    ref = ep[(ep.strategy == REF_STRATEGY) & (ep.policy_id == REF_POLICY) & ep.filled]
    d = dm[dm.exposure_after_ref.notna()].merge(
        ref[['event_id', 'ret_norm_ep', 'mdd_ep', 'E_class', 'segment', 'censored',
             'n_exit', 'n_reduce', 'n_add', 'terminal_reason']],
        on='event_id', how='inner')
    d = d.sort_values(['event_id', 'delta_day']).reset_index(drop=True)

    # --- false-recovery trigger per cycle (contract: 5 valid obs after A0) ---
    key = {(e, dd): i for i, (e, dd) in enumerate(zip(d.event_id.values, d.delta_day.values))}
    trig = {}
    trig_day = {}
    for e, r0, a0 in zip(cyc2.event_id, cyc2.r0_day, cyc2.a0_day):
        if np.isnan(a0):
            continue
        i0 = key.get((e, int(a0)))
        if i0 is None:
            continue
        fired = False
        fired_day = None
        seen = 0
        j = i0 + 1  # R1 (audit): strictly AFTER A0 — the A0 day itself is
        # NOT part of the '5 valid observations after A0' window (A0-day
        # indicators are typically unrepaired; including it inflated F3).
        ev_arr = d.event_id.values
        while j < len(d) and ev_arr[j] == e and seen < t['false_recovery_window_valid_obs']:
            if bool(d.row_present.iloc[j]):
                seen += 1
                dv = d.dist_ref20.iloc[j]
                ddv = d.drawdown_from_peak_log.iloc[j]
                if (not np.isnan(dv) and dv < 0) or (not np.isnan(ddv) and ddv >= t['severe_dd_depth_log']):
                    fired = True
                    fired_day = int(d.delta_day.iloc[j])
                    break
            j += 1
        trig[(e, int(r0))] = fired
        trig_day[(e, int(r0))] = fired_day
    cyc2['false_recovery'] = [trig.get((e, int(r0)), False)
                              for e, r0 in zip(cyc2.event_id, cyc2.r0_day)]
    cyc2['trigger_day'] = [trig_day.get((e, int(r0)))
                           for e, r0 in zip(cyc2.event_id, cyc2.r0_day)]
    ev_trigger = cyc2.groupby('event_id').false_recovery.any()

    # --- classify each episode + collect REDUCE-time discriminators ---
    last_dd = {}
    for ev, g in d.groupby('event_id', sort=False):
        v = g.drawdown_from_peak_log.iloc[-1]
        last_dd[ev] = (not np.isnan(v)) and v >= t['severe_dd_depth_log']
    rows = []
    for ev, g in d.groupby('event_id', sort=False):
        ret = float(g.ret_norm_ep.iloc[0])
        cens = bool(g.censored.iloc[0])
        has_exit = int(g.n_exit.iloc[0]) > 0
        trig_any = bool(ev_trigger.get(ev, False))
        f = classify_event(g, ret, cens, t, has_exit, trig_any)
        epi = ref[ref.event_id == ev].iloc[0]
        rows.append({
            'event_id': ev, 'segment': g.segment.iloc[0], 'E_class': epi.E_class,
            'ret_norm_ep': ret, 'abs_mdd': -float(g.mdd_ep.iloc[0]),
            'episode_class': ('GOOD' if ret > 0 and -g.mdd_ep.iloc[0] < t['severe_dd_depth_log'] else
                              'PAINFUL_WIN' if ret > 0 else
                              'CONTROLLED_LOSS' if -g.mdd_ep.iloc[0] < t['severe_dd_depth_log'] else
                              'SEVERE_FAILURE'),
            'F_stage': f, 'terminal_failure': bool(last_dd[ev]),
            'n_reduce': int(g.n_reduce.iloc[0]), 'n_add': int(g.n_add.iloc[0]),
            'n_exit': int(g.n_exit.iloc[0]), 'terminal_reason': g.terminal_reason.iloc[0],
            'first_op_day': int(g.delta_day.to_numpy()[0]) if len(g) else -1,
        })
    ea = pd.DataFrame(rows)
    # first operator day (proper)
    firsts = {}
    for ev, g in d.groupby('event_id', sort=False):
        m = g.resolution_state.isin(['RESOLVED_REDUCE', 'RESOLVED_EXIT'])
        firsts[ev] = int(g.delta_day.to_numpy()[m][0]) if m.any() else -1
    ea['first_op_day'] = [firsts[e] for e in ea.event_id]
    # first-REDUCE-day discriminator snapshot (for the separability block)
    firstred = {}
    for ev, g in d.groupby('event_id', sort=False):
        m = g.resolution_state == 'RESOLVED_REDUCE'
        if m.any():
            i = int(np.flatnonzero(m.to_numpy())[0])
            firstred[ev] = {c: float(g[c].iloc[i]) for c in DISC_COLS} | {'first_red_day': int(g.delta_day.iloc[i])}
        else:
            firstred[ev] = {c: np.nan for c in DISC_COLS} | {'first_red_day': np.nan}
    ea = pd.concat([ea, pd.DataFrame([{c: firstred[e][c] for c in DISC_COLS + ['first_red_day']}
                                       for e in ea.event_id])],
                   axis=1)

    # separability cohorts: episodes WITH cycles -> F3 (false recovery) vs
    # non-F3 recovered (cycle present, trigger never fired)
    with_cyc = set(cyc2[cyc2.type == 'RECOVERED_ADD'].event_id)
    ea['cohort_sep'] = np.where(
        ~ea.event_id.isin(with_cyc), 'NO_CYCLE',
        np.where(ea.F_stage == 'F3', 'FALSE_RECOVERY', 'CYCLE_OK'))

    # --- statistics ---
    enums = [['validation', 'confirmation', 'development'],
             ['sep', 'freq', 'e2f'],
             list(DISC_COLS) + ['first_red_day'],
             ['FALSE_RECOVERY', 'CYCLE_OK', 'NO_CYCLE'],
             ['median', 'mean']]
    rng = make_rng_factory(SEED, enums)

    report = {
        'stage': 't6_3',
        'contract_sha256': sha256_file(T6/'t6_contract.json'),
        'reference_cell': {'strategy': REF_STRATEGY, 'policy': REF_POLICY},
        'statistics_used': {'B': B, 'seed': SEED, 'ci': 'percentile 2.5/97.5',
                            'clusters': ['stock_code', 'T0_date'],
                            'holm': 'Holm within each test family',
                            'rng': 'SeedSequence substreams via t6.stats.make_rng_factory'},
        'metric_defs': {
            'F1..F6': 'contract failure_anatomy_prereg first-match order F1,F3,F2,F4,F5,F6',
            'false_recovery(cycle)': 'within the first 5 row_present=True observations STRICTLY AFTER the A0 day (A0 excluded; trigger_day > a0_day enforced by G8d): dist_ref20 < 0 (lose_ref20_today) OR drawdown_from_peak_log >= severe_dd_depth_log',
            'episode_class': 'GOOD/PAINFUL_WIN (ret>0) x CONTROLLED_LOSS/SEVERE_FAILURE (ret<=0), risk axis abs_mdd vs severe_dd_depth_log',
            'cohort_sep': 'NO_CYCLE (no RECOVERED cycle), FALSE_RECOVERY (episode F3), CYCLE_OK (cycle, no trigger fired)',
            'discriminator snapshot': 'values of PIT state columns at FIRST REDUCE day (visible at that time)',
        },
        'freq': {},
        'segments': {},
    }
    ft = ea.groupby(['segment', 'episode_class', 'F_stage'], observed=True).size().reset_index(name='n')
    report['freq_episode_class_x_F'] = ft.to_dict('records')
    report['freq_F'] = {seg: row.to_dict() for seg, row in
                        ea.groupby('segment').F_stage.value_counts().unstack(fill_value=0).iterrows()}
    report['freq_exit_by_seg_F'] = ea[ea.n_exit > 0].groupby(['segment', 'F_stage']).size().unstack(fill_value=0).to_dict('index')

    for seg in ('validation', 'confirmation', 'development'):
        es = ea[ea.segment == seg]
        seg_out = {'n': int(len(es)), 'role': 'reference_only' if seg == 'development' else 'primary'}
        pvals = {}
        # (a) separability: FALSE_RECOVERY vs CYCLE_OK on REDUCE-time candidates
        sep = {}
        for col in DISC_COLS + ['first_red_day']:
            vals = es[col].to_numpy(float)
            mh = (es.cohort_sep == 'FALSE_RECOVERY').to_numpy()
            ml = (es.cohort_sep == 'CYCLE_OK').to_numpy()
            est, ci, p, diag = cluster_boot_diff(vals, mh, ml, es.event_id.str.split('_').str[0].to_numpy(),
                                                 'median', rng(seg, 'sep', col, 'FALSE_RECOVERY'), B)
            sep[col] = {'FR_minus_OK': {'diff': est, 'ci95': ci, 'p_boot': p, **diag}}
            if np.isfinite(p):
                pvals[f'sep|FR_vs_OK|{col}'] = p
        seg_out['separability'] = sep
        # (b) E2-vs-E1 anomaly localization: SEVERE_FAILURE share by F within E-class
        e2f = {}
        for ec in ('E1', 'E2', 'E3'):
            sub = es[es.E_class == ec]
            allm = np.ones(len(sub), dtype=bool)
            clstr = sub.event_id.str.split('_').str[0].to_numpy()
            m_sev = (sub.episode_class == 'SEVERE_FAILURE').to_numpy()
            est, ci = cluster_boot_level(m_sev.astype(float), allm,
                                         clstr, 'mean',
                                         rng(seg, 'e2f', 'drawdown_from_peak_log', ec), B)
            m_tf = sub.terminal_failure.to_numpy(bool)
            est_t, ci_t = cluster_boot_level(m_tf.astype(float), allm,
                                             clstr, 'mean',
                                             rng(seg, 'e2f', 'ret_1d_log', f'{ec}_tf'), B)
            e2f[ec] = {'p_severe_failure': {'median': est, 'ci95': ci},
                       'p_terminal_failure': {'median': est_t, 'ci95': ci_t}}
            for f in ('F1', 'F3', 'F2', 'F4', 'F5', 'F6'):
                mf = ((sub.F_stage == f) & (sub.episode_class == 'SEVERE_FAILURE')).to_numpy()
                est_f, ci_f = cluster_boot_level(mf.astype(float), allm,
                                                 clstr, 'mean',
                                                 rng(seg, 'e2f', 'drawdown_from_peak_log', f'{ec}_{f}'), B)
                e2f[ec][f'p_severe_{f}'] = {'median': est_f, 'ci95': ci_f}
                mtf_f = ((sub.F_stage == f) & sub.terminal_failure.to_numpy(bool)).to_numpy()
                est_tf, ci_tf = cluster_boot_level(mtf_f.astype(float), allm,
                                                   clstr, 'mean',
                                                   rng(seg, 'e2f', 'ret_1d_log', f'{ec}_tf_{f}'), B)
                e2f[ec][f'p_term_{f}'] = {'median': est_tf, 'ci95': ci_tf}
        seg_out['e2f'] = e2f
        seg_out['holm_adj_p'] = holm(pvals)
        report['segments'][seg] = seg_out

    cyc_out = cyc2[['event_id', 'r0_day', 'a0_day', 'type', 'false_recovery', 'trigger_day']]
    write_stage_outputs(
        OUT, 't6_3', {'failure_anatomy': ea, 'cycle_trigger': cyc_out},
        {'inputs': [
            {'name': 'episode_master', 'path': 'output/research/t6/00_factlayer/t6_0_episode_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_episode_master.parquet'), 'bytes': 0},
            {'name': 'daily_master', 'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
            {'name': 't6_contract', 'path': 'output/research/t6/t6_contract.json',
             'sha256': sha256_file(T6/'t6_contract.json'), 'bytes': 0},
            {'name': 't6_2_cycle_master', 'path': 'output/research/t6/02_recycling/t6_2_cycle_master.parquet',
             'sha256': sha256_file(T6/'02_recycling/t6_2_cycle_master.parquet'), 'bytes': 0}]},
        report)
    print('episodes:', len(ea))
    print(ea.groupby(['segment', 'F_stage']).size().unstack(fill_value=0))
    print()
    print(ea.groupby(['segment', 'episode_class']).size().unstack(fill_value=0))


if __name__ == '__main__':
    main()
