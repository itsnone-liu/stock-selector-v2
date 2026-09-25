#!/usr/bin/env python3
"""T8.1 — Order Anatomy (frozen T8 Plan v2 §3): descriptive only.

Estimand A (observed order profile): within the risk set that actually
reaches ADD_k, how do five outcome dimensions vary with k?

Frozen-reuse contract (zero new definitions):
  - False ADD_k  = frozen T7.0 false_recovery (a0-anchored, W10+adverse)
  - Recovery_k   = frozen T7.0 true_recovery
  - windowed dims replayed from frozen daily master at the preregistered
    W10 clock: endpoint = 10th effective observation after a0 (truncated
    to available; n_obs_w10 recorded). next_r0_day is NOT an outcome
    endpoint (user warning, T8.0 audit) — it is reported only as the
    mechanical cycle-lifetime descriptor and reconciled against frozen
    re_reduce_day.
No p-values, no thresholds, no rule words (G43). Grouping fixed:
k=1 / k=2 / k>=3 (G-plan §2); per-k appendix from raw cycle_index dist.
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
T8 = T6.parent/'t8'
OUT = T8/'01_order_anatomy'
W = 10  # preregistered: same clock family as frozen False-ADD W10


def main():
    att = pd.read_parquet(T8/'00_sequence_factlayer/t8_0_cycle_attempt.parquet')
    adds = att[att.has_add].copy()
    out0 = pd.read_parquet(T7/'00_path_factlayer/t7_0_outcomes_outcomes.parquet',
                           columns=['event_id', 'r0_day', 'false_recovery',
                                    'true_recovery', 'recovery_established_day',
                                    're_reduce_day', 'exit_day', 'censored',
                                    'segment', 'stock_code', 'T0_date'])
    m = adds.merge(out0, on=['event_id', 'r0_day'], suffixes=('', '_o'))
    assert len(m) == len(adds) == 15646, (len(m), len(adds))
    assert (m.type == 'RECOVERED_ADD').all()
    # cycle-lifetime clock semantics (discovered in reconciliation):
    # re_reduce_day = the reduce ACTION day of this ADD's position (frozen);
    # next_r0_day  = R0 anchor of the NEXT cycle (confirmation, later).
    # Same nan-pattern, re_reduce_day <= next_r0_day always. Lifetime uses
    # the frozen action day; next_r0 stays topology-only (user warning).
    nr = m.next_r0_day.to_numpy(float)
    rr = m.re_reduce_day.to_numpy(float)
    assert np.array_equal(np.isnan(nr), np.isnan(rr))
    both = ~np.isnan(nr) & ~np.isnan(rr)
    assert (rr[both] <= nr[both]).all(), 're_reduce after next R0'
    r2n_gap = {'n': int(both.sum()),
               'gap_wmedian': float(np.nanmedian(nr[both] - rr[both])),
               'gap_max': float((nr[both] - rr[both]).max())}

    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'close_adj'])
    dm = dm[dm.exposure_after_ref.notna()].sort_values(['event_id', 'delta_day'])
    agg = {ev: (g.delta_day.to_numpy(int), g.exposure_after_ref.to_numpy(float),
                g.close_adj.to_numpy(float))
           for ev, g in dm.groupby('event_id', sort=False)}

    rows = []
    for r in m.itertuples():
        offs, expo, close = agg[r.event_id]
        ia = int(np.searchsorted(offs, int(r.a0_day)))     # a0 row
        ie = min(ia + W, len(offs))                          # W10 endpoint
        n_obs = ie - ia
        win = close[ia:ie] / close[ia]
        expo_w = expo[ia:ie]
        rows.append({
            'event_id': r.event_id, 'segment': r.segment,
            'stock_code': r.stock_code, 'T0_date': r.T0_date,
            'k_add': int(r.k_add), 'k_group': ('k1' if r.k_add == 1 else
                                               'k2' if r.k_add == 2 else 'k3+'),
            'a0_day': int(r.a0_day), 'n_obs_w10': n_obs,
            'false_add': bool(r.false_recovery),
            'recovery': bool(r.true_recovery),
            'dd_w10': float(np.log(win).min()) if n_obs else np.nan,
            'mfe_w10': float(np.log(win).max()) if n_obs else np.nan,
            'ret_w10': float(np.log(win[-1])) if n_obs else np.nan,
            'occ_w10': float(expo_w.mean()) if n_obs else np.nan,
            'expo_days_w10': float(expo_w.sum()) if n_obs else np.nan,
            'cycle_life': (float(r.re_reduce_day) - float(r.a0_day)
                           if np.isfinite(r.re_reduce_day) else np.nan),
        })
    an = pd.DataFrame(rows)
    an['contrib_w10'] = an.occ_w10 * an.ret_w10

    def grp(df, key):
        g = {'n': int(len(df))}
        for c in ('false_add', 'recovery'):
            g[c + '_rate'] = round(float(df[c].mean()), 4)
        for c in ('dd_w10', 'mfe_w10', 'ret_w10', 'occ_w10', 'expo_days_w10',
                  'contrib_w10', 'cycle_life'):
            g[c + '_median'] = round(float(np.nanmedian(df[c].to_numpy(float))), 4)
        g['n_obs_w10_median'] = float(df.n_obs_w10.median())
        return g

    order = ['k1', 'k2', 'k3+']
    by_group = {k: grp(an[an.k_group == k], k) for k in order}
    by_segment = {f'{k}_{seg}': grp(an[(an.k_group == k) &
                                       (an.segment == seg)], k)
                  for k in order for seg in ('development', 'validation',
                                             'confirmation')}
    appendix_per_k = {int(k): grp(an[an.k_add == k], k)
                      for k in sorted(an.k_add.unique())}

    report = {
        'stage': 't8_1',
        'identity': 'order anatomy: estimand A observed order profile, '
                    'descriptive only, no inference, no policy',
        'estimand': 'A_observed_order_profile (risk-set conditional on '
                    'reaching ADD_k; NOT causal marginal value)',
        'w10_clock': 'endpoint = 10th effective observation after a0 '
                     '(truncated to available); same window family as '
                     'frozen False-ADD W10',
        'frozen_reuse': {'false_add': 't7_0 false_recovery',
                         'recovery': 't7_0 true_recovery',
                         'cycle_life': 'frozen re_reduce_day - a0_day '
                                       '(reduce ACTION clock; next_r0_day is '
                                       'topology-only)',
                         'reduce_action_to_next_R0': r2n_gap},
        'n_adds': int(len(an)),
        'by_k_group': by_group,
        'by_segment': by_segment,
        'appendix_per_k': appendix_per_k,
        'inputs': [
            {'name': 't8_0_cycle_attempt',
             'path': 'output/research/t8/00_sequence_factlayer/t8_0_cycle_attempt.parquet',
             'sha256': sha256_file(T8/'00_sequence_factlayer/t8_0_cycle_attempt.parquet'),
             'bytes': 0},
            {'name': 't7_0_outcomes',
             'path': 'output/research/t7/00_path_factlayer/t7_0_outcomes_outcomes.parquet',
             'sha256': sha256_file(T7/'00_path_factlayer/t7_0_outcomes_outcomes.parquet'),
             'bytes': 0},
            {'name': 't6_0_daily_master',
             'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'),
             'bytes': 0},
        ],
    }
    write_stage_outputs(OUT, 't8_1', {'order_anatomy': an},
                        {'inputs': report['inputs']}, report)
    for k in order:
        print(k, by_group[k])


if __name__ == '__main__':
    main()
