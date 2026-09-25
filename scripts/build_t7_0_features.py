#!/usr/bin/env python3
"""T7.0 Step 2a — build path_fact + anchor_features (PHYSICALLY ISOLATED).

This builder NEVER reads t7_0_outcomes (or any outcome-semantic column of
upstream frozen products): the T6.2 cycle master is read with a strict
column whitelist (event_id / segment / E_class / r0_day only — no type,
no a0_day, no bh_*). Path facts are pure PIT daily rows; anchor features
are decision-time trajectory summaries at checkpoints R+1/2/3/5.
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
OUT = T7/'00_path_factlayer'
CKPTS = (1, 2, 3, 5)
HORIZON = 40

DAILY_COLS = ['event_id', 'delta_day', 'close_adj', 'ret_1d_log',
              'volume_load_vs_prebreak', 'turnover_load_3d_mean',
              'efficiency_signed_3', 'drawdown_from_peak_log', 'dist_ref20',
              'mkt_breadth_5d', 'mkt_new_high_20d', 'resolution_state',
              'exposure_after_ref']
CYCLE_COLS = ['event_id', 'segment', 'E_class', 'r0_day']  # strict whitelist


def build_group(g, r0):
    """g: daily rows of one event sorted by delta_day. Returns (path rows, features)."""
    w = g[(g.delta_day > r0) & (g.delta_day <= r0 + HORIZON)]
    if len(w) == 0:
        return None, None
    r0row = g.loc[g.delta_day == r0]
    c0 = float(r0row['close_adj'].iloc[0])
    dd0 = float(r0row['drawdown_from_peak_log'].iloc[0])
    offs = w.delta_day.to_numpy()
    close = w.close_adj.to_numpy()
    ret1 = w.ret_1d_log.to_numpy()
    vol = w.volume_load_vs_prebreak.to_numpy()
    tur = w.turnover_load_3d_mean.to_numpy()
    eff = w.efficiency_signed_3.to_numpy()
    dd = w.drawdown_from_peak_log.to_numpy()
    d20 = w.dist_ref20.to_numpy()

    # ---- path_fact rows (pure PIT) ----
    n = len(w)
    path = pd.DataFrame({
        'event_id': w.event_id, 'r0_day': int(r0), 'delta_day': offs, 'day_offset': offs - r0,
        'close_adj': close, 'ret_1d_log': ret1, 'volume_load_vs_prebreak': vol,
        'turnover_load_3d_mean': tur, 'efficiency_signed_3': eff,
        'drawdown_from_peak_log': dd, 'dist_ref20': d20,
        'mkt_breadth_5d': w.mkt_breadth_5d.to_numpy(),
        'mkt_new_high_20d': w.mkt_new_high_20d.to_numpy(),
        'resolution_state': w.resolution_state.to_numpy(),
        'r0_close_log': np.log(c0),
    })

    # ---- anchor features (decision-time only, checkpoints 1/2/3/5) ----
    logc = np.log(close)
    bounce = logc - np.log(c0)
    f = {}
    cum_up = 0
    consec_up = np.zeros(n, dtype=int)
    for i in range(n):
        cum_up = cum_up + 1 if ret1[i] > 0 else 0
        consec_up[i] = cum_up
    cum_sh = 0
    consec_sh = np.zeros(n, dtype=int)
    for i in range(n):
        cum_sh = cum_sh + 1 if (np.isfinite(vol[i]) and vol[i] < 1) else 0
        consec_sh[i] = cum_sh
    pos_share = np.cumsum(np.where(np.isfinite(eff) & (eff > 0), 1, 0)) / np.arange(1, n + 1)

    def at(k, arr):
        m = offs <= r0 + k
        return float(arr[m][-1]) if m.any() else np.nan

    repair = np.clip((dd0 - dd) / dd0, 0.0, 1.0) if dd0 > 0 else np.full(n, np.nan)
    for k in CKPTS:
        f[f'max_bounce_R{k}'] = float(np.nanmax(bounce[offs <= r0 + k]))
        f[f'consec_up_days_R{k}'] = at(k, consec_up)
        f[f'consec_shrink_days_R{k}'] = at(k, consec_sh)
        f[f'eff_pos_share_R{k}'] = at(k, pos_share)
        f[f'ref20_repair_R{k}'] = at(k, d20)
        f[f'dd_repair_ratio_R{k}'] = at(k, repair)
    m5 = offs <= r0 + 5
    mb_i = int(np.nanargmax(np.where(m5, bounce, -np.inf)))
    f['maxbounce_day_offset'] = int(offs[mb_i] - r0)
    f['vol_load@maxbounce_R5'] = float(vol[mb_i])
    f['turnover@maxbounce_R5'] = float(tur[mb_i])
    f['vol_decay_R5'] = (at(5, vol) / at(1, vol)) if (np.isfinite(at(1, vol)) and at(1, vol) > 0) else np.nan
    f['turnover_level_R1'] = at(1, tur)
    f['turnover_level_R5'] = at(5, tur)
    f['turnover_traj_slope'] = at(5, tur) - at(1, tur)
    f['new_high_after_R0_R5'] = int(np.any(np.isfinite(dd[m5]) & (dd[m5] <= 0)))
    f['mkt_breadth_5d@R5'] = at(5, w.mkt_breadth_5d.to_numpy())
    f['mkt_new_high_20d@R5'] = at(5, w.mkt_new_high_20d.to_numpy())
    return path, f


def main():
    cyc = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet',
                          columns=CYCLE_COLS)
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=DAILY_COLS)
    dm = dm[dm.exposure_after_ref.notna()].sort_values(['event_id', 'delta_day'])
    groups = {e: g for e, g in dm.groupby('event_id', sort=False)}

    meta = cyc[['event_id', 'segment', 'E_class', 'r0_day']].copy()
    meta['stock_code'] = meta.event_id.str.split('_').str[0]
    meta['T0_date'] = meta.event_id.str.split('_').str[1]

    path_rows, feat_rows, dropped = [], [], 0
    for ev, r0 in zip(cyc.event_id, cyc.r0_day):
        g = groups.get(ev)
        if g is None or (g.delta_day == r0).sum() == 0:
            dropped += 1
            continue
        p, f = build_group(g, int(r0))
        if p is None:
            dropped += 1
            continue
        path_rows.append(p)
        feat_rows.append({'event_id': ev, 'r0_day': int(r0), **f})

    path = pd.concat(path_rows, ignore_index=True)
    feat = pd.DataFrame(feat_rows).merge(
        meta.drop_duplicates(['event_id', 'r0_day']), on=['event_id', 'r0_day'])
    feat['decision_checkpoint_set'] = '|'.join(map(str, CKPTS))

    man_inputs = [
        {'name': 'daily_master', 'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
         'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
        {'name': 't6_2_cycle_master', 'path': 'output/research/t6/02_recycling/t6_2_cycle_master.parquet',
         'sha256': sha256_file(T6/'02_recycling/t6_2_cycle_master.parquet'), 'bytes': 0},
        {'name': 't6_contract', 'path': 'output/research/t6/t6_contract.json',
         'sha256': sha256_file(T6/'t7_contract.json'.replace('t7_', 't6_')), 'bytes': 0},
        {'name': 'definition_registry', 'path': 'output/research/t7/00_path_factlayer/t7_0_definition_registry.json',
         'sha256': sha256_file(OUT/'t7_0_definition_registry.json'), 'bytes': 0}]
    write_stage_outputs(
        OUT, 't7_0_features', {'path_fact': path, 'anchor_features': feat},
        {'inputs': man_inputs,
         'isolation': 'this builder reads no outcome-semantic column; cycle master whitelist = '
                      + ','.join(CYCLE_COLS),
         'dropped_anchors_no_window': dropped},
        {'stage': 't7_0_features',
         'isolation_statement': {
             'tables_written': ['t7_0_features_path_fact.parquet',
                                't7_0_features_anchor_features.parquet'],
             'outcome_tables_read': [],
             'cycle_master_column_whitelist': CYCLE_COLS,
             'note': 'path_fact rows are pure PIT daily facts within R+1..R+40; anchor_features '
                     'carry decision-time trajectory summaries at checkpoints R+1/2/3/5 only'},
         'counts': {'anchors': int(len(feat)), 'path_rows': int(len(path)),
                    'dropped_anchors_no_window': int(dropped)},
         'checkpoints': list(CKPTS), 'horizon': HORIZON})
    print('anchors:', len(feat), 'path rows:', len(path), 'dropped:', dropped)
    print(feat[['max_bounce_R5', 'dd_repair_ratio_R5', 'vol_load@maxbounce_R5',
                'turnover@maxbounce_R5']].describe().loc[['mean', '50%', 'max']].round(4))


if __name__ == '__main__':
    main()
