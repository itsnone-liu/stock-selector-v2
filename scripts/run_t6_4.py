#!/usr/bin/env python3
"""T6.4 — Market/Sector Regime Interaction.

Core question (post-T6.3): the SAME bounce-day + hot signature sometimes
becomes a true recovery and sometimes a false recovery — does the external
market regime provide the separating condition?

Preregistered (contract regime_prereg):
  M_STRONG  mkt_breadth_5d > 0.55 AND mkt_new_high_20d > 0.10
  M_WEAK    mkt_breadth_5d < 0.45 OR  mkt_new_high_20d < 0.04
  M_NEUTRAL otherwise
  Sector metrics are NON-PIT (retrospective 2026 snapshot) -> EXPLORATORY
  ONLY, quarantined from primary conclusions (gate-enforced).

Analyses (all PIT unless marked EXPLORATORY):
  A1 cycle-outcome x R0-regime (REDUCE_to_ADD x MarketRegime)
  A2 false-recovery vs clean-recovery x regime, and within the hot-REDUCE
     subset (the T6.3 signature) — does regime separate true from false?
  A3 E_class x MarketRegime on T6.1 headline outcomes (terminal_failure,
     abs_mdd median) — is the E3 risk advantage regime-uniform?
  A4 EXIT conf-concentration descriptive regime profile (C204 follow-up)
  X  sector blocks (EXPLORATORY ONLY)
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

OUT = T6/'04_regime'
REF_STRATEGY, REF_POLICY = 'direct_chase', 'P2_balanced'
HOT_SIG = ['ret_1d_log', 'efficiency_signed_3', 'dist_ref20', 'turnover_load_3d_mean']


def mkt_regime(b, nh):
    if np.isnan(b) or np.isnan(nh):
        return 'NA'
    if b > 0.55 and nh > 0.10:
        return 'M_STRONG'
    if b < 0.45 or nh < 0.04:
        return 'M_WEAK'
    return 'M_NEUTRAL'


def main():
    contract = load_contract()
    t = contract['preregistered_thresholds']
    pre = contract['statistics_prereg']
    B, SEED = pre['bootstrap_B'], pre['bootstrap_seed']

    ep = pd.read_parquet(T6/'00_factlayer/t6_0_episode_master.parquet',
                         columns=['event_id', 'strategy', 'policy_id', 'filled', 'E_class',
                                  'segment', 'ret_norm_ep', 'mdd_ep'])
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'resolution_state',
                                  'exposure_after_ref', 'mkt_breadth_5d', 'mkt_new_high_20d',
                                  'drawdown_from_peak_log']
                         + HOT_SIG)
    cyc2 = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet',
                           columns=['event_id', 'r0_day', 'a0_day', 'type', 'segment'])
    ct3 = pd.read_parquet(T6/'03_failure_anatomy/t6_3_cycle_trigger.parquet',
                          columns=['event_id', 'r0_day', 'a0_day', 'false_recovery'])

    ref = ep[(ep.strategy == REF_STRATEGY) & (ep.policy_id == REF_POLICY) & ep.filled]
    d = dm[dm.exposure_after_ref.notna()].merge(
        ref[['event_id', 'E_class', 'segment']], on='event_id', how='inner')
    d = d.sort_values(['event_id', 'delta_day']).reset_index(drop=True)
    key = {(e, int(dd)): i for i, (e, dd) in enumerate(zip(d.event_id.values, d.delta_day.values))}

    cyc = cyc2.merge(ct3[['event_id', 'r0_day', 'false_recovery']],
                     on=['event_id', 'r0_day'], how='left')
    cyc['false_recovery'] = cyc.false_recovery.fillna(False)

    def row(e, day):
        i = key.get((e, int(day))) if not np.isnan(day) else None
        return d.iloc[i] if i is not None else None

    rows = []
    for e, r0, a0, typ, fr in zip(cyc.event_id, cyc.r0_day, cyc.a0_day, cyc.type, cyc.false_recovery):
        g0 = row(e, r0)
        if g0 is None:
            continue
        rows.append({
            'event_id': e, 'r0_day': int(r0),
            'a0_day': int(a0) if not np.isnan(a0) else np.nan,
            'type': typ, 'false_recovery': bool(fr),
            'R0_regime': mkt_regime(g0.mkt_breadth_5d, g0.mkt_new_high_20d),
            **{f'{c}@R0': float(g0[c]) for c in HOT_SIG},
        })
    rg = pd.DataFrame(rows)
    rg = rg.merge(cyc[['event_id', 'segment']].drop_duplicates('event_id'), on='event_id')
    rg['hot'] = (rg['ret_1d_log@R0'] > 0) & (rg['efficiency_signed_3@R0'] > 0)
    rg['stock_code'] = rg.event_id.str.split('_').str[0]
    rg['T0_date'] = rg.event_id.str.split('_').str[1]

    # episode-level frame for A3
    last_dd = {}
    ep_abs_mdd = {}
    e_seg, e_ec = {}, {}
    for ev, g in d.groupby('event_id', sort=False):
        last_dd[ev] = float(g.drawdown_from_peak_log.iloc[-1]) if 'drawdown_from_peak_log' in g else np.nan
    epi = ref.set_index('event_id')
    epf = pd.DataFrame({
        'event_id': epi.index,
        'segment': epi.segment.values, 'E_class': epi.E_class.values,
        'abs_mdd': -epi.mdd_ep.values,
        'terminal_failure': np.array([ (not np.isnan(v)) and v >= t['severe_dd_depth_log']
                                       for v in d.groupby('event_id', sort=False).drawdown_from_peak_log.last() ]),
        'r0_regime': [rg[rg.event_id == e].R0_regime.iloc[0] if (rg.event_id == e).any() else 'NA'
                      for e in epi.index],
    })
    epf['stock_code'] = epf.event_id.str.split('_').str[0]

    enums = [['validation', 'confirmation', 'development'],
             ['A1', 'A2', 'A3', 'X'],
             ['RECOVERED_ADD', 'NO_RECOVERY', 'FAILED_EXIT'],
             ['M_STRONG', 'M_NEUTRAL', 'M_WEAK', 'NA'],
             ['median', 'mean']]
    rng = make_rng_factory(SEED, enums)

    report = {
        'stage': 't6_4',
        'contract_sha256': sha256_file(T6/'t6_contract.json'),
        'reference_cell': {'strategy': REF_STRATEGY, 'policy': REF_POLICY},
        'statistics_used': {'B': B, 'seed': SEED, 'ci': 'percentile 2.5/97.5',
                            'clusters': ['stock_code', 'T0_date'],
                            'holm': 'Holm within each test family',
                            'rng': 'SeedSequence substreams via t6.stats.make_rng_factory'},
        'metric_defs': {
            'R0_regime': 'preregistered M_STRONG/M_WEAK/M_NEUTRAL from mkt_breadth_5d and mkt_new_high_20d at the R0 day (PIT daily-market columns)',
            'hot': 'R0-day bounce signature subset: ret_1d_log@R0 > 0 AND efficiency_signed_3@R0 > 0 (T6.3 C302 signature carriers)',
            'FR_rate': 'share of false_recovery among RECOVERED_ADD cycles within the stated stratum',
            'sec_*': 'EXPLORATORY ONLY — NON-PIT retrospective 2026 sector snapshot, quarantined',
        },
        'freq': {
            'cycle_outcome_x_regime': [
                {'segment': k[0], 'R0_regime': k[1], 'type': k[2], 'n': int(v)}
                for k, v in rg.groupby(['segment', 'R0_regime', 'type'], observed=True).size().items()],
            'regime_totals': [
                {'segment': k[0], 'R0_regime': k[1], 'n': int(v)}
                for k, v in rg.groupby(['segment', 'R0_regime'], observed=True).size().items()],
        },
        'segments': {},
        'EXPLORATORY_sector': {},
    }

    for seg in ('validation', 'confirmation', 'development'):
        cs = rg[rg.segment == seg]
        seg_out = {'n': int(len(cs)), 'role': 'reference_only' if seg == 'development' else 'primary'}
        pvals = {}
        # A1: NO_RECOVERY share by regime (recycling outcome x regime)
        a1 = {}
        for reg in ('M_STRONG', 'M_NEUTRAL', 'M_WEAK'):
            sub = cs[cs.R0_regime == reg]
            if len(sub) < 10:
                a1[reg] = {'n': int(len(sub)), 'skipped': 'insufficient cycles'}
                continue
            m_no = (sub.type == 'NO_RECOVERY').to_numpy()
            est, ci = cluster_boot_level(m_no.astype(float), np.ones(len(sub), bool),
                                         sub.stock_code.to_numpy(), 'mean',
                                         rng(seg, 'A1', 'NO_RECOVERY', reg), B)
            a1[reg] = {'p_no_recovery': {'mean': est, 'ci95': ci}, 'n': int(len(sub))}
        seg_out['A1_no_recovery_by_regime'] = a1
        # A2: FR rate by regime, overall and within hot subset
        rec = cs[cs.type == 'RECOVERED_ADD']
        a2 = {'all_recovered': {}, 'hot_subset': {}}
        for label, frame in (('all_recovered', rec), ('hot_subset', rec[rec.hot])):
            for reg in ('M_STRONG', 'M_NEUTRAL', 'M_WEAK'):
                sub = frame[frame.R0_regime == reg]
                if len(sub) < 10:
                    a2[label][reg] = {'n': int(len(sub)), 'skipped': 'insufficient cycles'}
                    continue
                m_fr = sub.false_recovery.to_numpy()
                est, ci = cluster_boot_level(m_fr.astype(float), np.ones(len(sub), bool),
                                             sub.stock_code.to_numpy(), 'mean',
                                             rng(seg, 'A2', 'NO_RECOVERY', f'{label}_{reg}'), B)
                a2[label][reg] = {'FR_rate': {'mean': est, 'ci95': ci}, 'n': int(len(sub))}
        # regime contrast on FR rate (M_STRONG minus M_WEAK), all + hot
        for label, frame in (('all_recovered', rec), ('hot_subset', rec[rec.hot])):
            hs = frame[frame.R0_regime == 'M_STRONG']
            wl = frame[frame.R0_regime == 'M_WEAK']
            if len(hs) >= 10 and len(wl) >= 10:
                est, ci, p, diag = cluster_boot_diff(
                    frame.false_recovery.to_numpy(float),
                    (frame.R0_regime == 'M_STRONG').to_numpy(),
                    (frame.R0_regime == 'M_WEAK').to_numpy(),
                    frame.stock_code.to_numpy(), 'mean',
                    rng(seg, 'A2', 'NO_RECOVERY', f'{label}_SvW'), B)
                a2[label]['M_STRONG_minus_M_WEAK'] = {'diff': est, 'ci95': ci, 'p_boot': p, **diag}
                if np.isfinite(p):
                    pvals[f'A2|{label}|STRONG_vs_WEAK'] = p
        seg_out['A2_FR_rate_by_regime'] = a2
        # A3: E3-vs-E1/E2 abs_mdd and terminal_failure by regime (episode level)
        es = epf[epf.segment == seg]
        a3 = {}
        for reg in ('M_STRONG', 'M_NEUTRAL', 'M_WEAK'):
            sub = es[es.r0_regime == reg]
            entry = {'n': int(len(sub))}
            for ec in ('E1', 'E2', 'E3'):
                m = (sub.E_class == ec).to_numpy()
                if m.sum() < 10:
                    entry[ec] = {'n': int(m.sum()), 'skipped': True}
                    continue
                est, ci = cluster_boot_level(sub.abs_mdd.to_numpy(float), m,
                                             sub.stock_code.to_numpy(), 'median',
                                             rng(seg, 'A3', ec, reg), B)
                est_tf, ci_tf = cluster_boot_level(sub.terminal_failure.to_numpy(float), m,
                                                   sub.stock_code.to_numpy(), 'mean',
                                                   rng(seg, 'A3', ec, f'{reg}_tf'), B)
                entry[ec] = {'abs_mdd_median': {'median': est, 'ci95': ci},
                             'p_terminal_failure': {'mean': est_tf, 'ci95': ci_tf},
                             'n': int(m.sum())}
            a3[reg] = entry
        seg_out['A3_eclass_by_regime'] = a3
        seg_out['holm_adj_p'] = holm(pvals)
        report['segments'][seg] = seg_out
        # X: sector exploratory — UNAVAILABLE: the four preregistered
        # sector_metrics are not present in the frozen T6.0 fact layer
        # (contract regime_prereg lists them; t6_0_daily_master carries no
        # sector columns). Reported as a data boundary, not silently dropped.
        report['EXPLORATORY_sector'][seg] = {
            'status': 'UNAVAILABLE',
            'reason': 'sector_metrics not present in frozen t6_0 daily_master fact layer',
        }

    rg_out = rg.drop(columns=[c for c in rg.columns if '@' not in c and c not in
                              ('event_id', 'r0_day', 'a0_day', 'type', 'false_recovery',
                               'R0_regime', 'hot', 'stock_code', 'T0_date', 'segment')], errors='ignore')
    write_stage_outputs(
        OUT, 't6_4', {'regime_cycle': rg_out, 'regime_episode': epf},
        {'inputs': [
            {'name': 'episode_master', 'path': 'output/research/t6/00_factlayer/t6_0_episode_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_episode_master.parquet'), 'bytes': 0},
            {'name': 'daily_master', 'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
            {'name': 't6_contract', 'path': 'output/research/t6/t6_contract.json',
             'sha256': sha256_file(T6/'t6_contract.json'), 'bytes': 0},
            {'name': 't6_2_cycle_master', 'path': 'output/research/t6/02_recycling/t6_2_cycle_master.parquet',
             'sha256': sha256_file(T6/'02_recycling/t6_2_cycle_master.parquet'), 'bytes': 0},
            {'name': 't6_3_cycle_trigger', 'path': 'output/research/t6/03_failure_anatomy/t6_3_cycle_trigger.parquet',
             'sha256': sha256_file(T6/'03_failure_anatomy/t6_3_cycle_trigger.parquet'), 'bytes': 0}]},
        report)
    print('cycles:', len(rg), 'episodes:', len(epf))
    print(rg.groupby(['segment', 'R0_regime'], observed=True).size().unstack(fill_value=0))
    for seg in ('validation', 'confirmation'):
        rec = rg[(rg.segment == seg) & (rg.type == 'RECOVERED_ADD')]
        for label, fr_ in (('all', rec), ('hot', rec[rec.hot])):
            line = {r: (round(rec[rec.R0_regime == r].false_recovery.mean(), 3) if (rec.R0_regime == r).sum() > 10 else None,
                      int((rec.R0_regime == r).sum())) for r in ('M_STRONG', 'M_NEUTRAL', 'M_WEAK')}
            print(f'{seg} FR_rate {label}:', line, 'hot_n=', int(fr_.hot.sum()))


if __name__ == '__main__':
    main()
