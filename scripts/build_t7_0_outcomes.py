#!/usr/bin/env python3
"""T7.0 Step 2b — build outcomes table (reads path facts + frozen upstream
outcome semantics; NEVER imported by the features builder).

Outcome columns: cycle type / a0_day / false_recovery (frozen T6.3-R1
trigger) / bh_R0_H* (frozen T6.2) / MFE / MAE / re-REDUCE / EXIT /
terminal_failure (T6.4 semantics) / true_recovery + recovery_established_day
(judged exactly per the frozen definition registry).
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file, write_stage_outputs  # noqa: E402

T7 = T6.parent/'t7'
OUT = T7/'00_path_factlayer'
HORIZON = 40


def main():
    reg = json.loads((OUT/'t7_0_definition_registry.json').read_text())
    t6c = load_contract()
    severe = t6c['preregistered_thresholds']['severe_dd_depth_log']
    K = int(reg['true_recovery']['persistence']['days'])

    cyc = pd.read_parquet(T6/'02_recycling/t6_2_cycle_master.parquet')
    ct3 = pd.read_parquet(T6/'03_failure_anatomy/t6_3_cycle_trigger.parquet',
                          columns=['event_id', 'r0_day', 'false_recovery'])
    cyc = cyc.merge(ct3, on=['event_id', 'r0_day'], how='left')
    cyc['false_recovery'] = cyc.false_recovery.fillna(False)

    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'close_adj', 'dist_ref20',
                                  'drawdown_from_peak_log', 'resolution_state',
                                  'exposure_after_ref'])
    dm = dm[dm.exposure_after_ref.notna()].sort_values(['event_id', 'delta_day'])
    groups = {e: g for e, g in dm.groupby('event_id', sort=False)}

    rows = []
    for ev, r0, typ, a0, fr, bh5, bh10, bh20, bh40, seg, ecl in zip(
            cyc.event_id, cyc.r0_day, cyc.type, cyc.a0_day, cyc.false_recovery,
            cyc.bh_R0_H5, cyc.bh_R0_H10, cyc.bh_R0_H20, cyc.bh_R0_H40,
            cyc.segment, cyc.E_class):
        g = groups.get(ev)
        if g is None or (g.delta_day == r0).sum() == 0:
            continue
        r0row = g[g.delta_day == r0].iloc[0]
        c0 = float(r0row.close_adj)
        w = g[(g.delta_day > r0) & (g.delta_day <= r0 + HORIZON)]
        offs = w.delta_day.to_numpy()
        d20 = w.dist_ref20.to_numpy()
        dd = w.drawdown_from_peak_log.to_numpy()
        logret = np.log(w.close_adj.to_numpy()) - np.log(c0)
        st = w.resolution_state.to_numpy()
        n = len(w)

        # MFE / MAE after R0 (log close vs R0 close, within horizon)
        mfe = float(np.nanmax(logret)) if n else np.nan
        mae = float(np.nanmin(logret)) if n else np.nan

        # next REDUCE / EXIT inside the window (action diagnostics, secondary)
        red_i = np.where(st == 'RESOLVED_REDUCE')[0]
        ex_i = np.where(st == 'RESOLVED_EXIT')[0]
        re_reduce_day = int(offs[red_i[0]]) if len(red_i) else np.nan
        exit_day = int(offs[ex_i[0]]) if len(ex_i) else np.nan

        # terminal_failure: last valid day of the EPISODE (not window) dd >= severe
        last_dd = float(g.drawdown_from_peak_log.iloc[-1])
        terminal_failure = bool(np.isfinite(last_dd) and last_dd >= severe)

        # true_recovery judgment per frozen registry (achievement + persistence)
        ok = np.isfinite(d20) & np.isfinite(dd) & (d20 >= 0) & (dd < severe)
        est = np.nan
        # persistence: the K subsequent effective observations must exist, be
        # finite, and the frozen F3 failure condition must not fire in them
        for i in np.where(ok)[0]:
            if i + K < n:
                wd20 = d20[i+1:i+1+K]
                wdd = dd[i+1:i+1+K]
                if (np.all(np.isfinite(wd20)) and np.all(np.isfinite(wdd))
                        and not np.any(wd20 < 0) and not np.any(wdd >= severe)):
                    est = int(offs[i])
                    break
        rows.append({
            'event_id': ev, 'r0_day': int(r0), 'segment': seg,
            'E_class': ecl, 'type': typ,
            'a0_day': int(a0) if np.isfinite(a0) else np.nan,
            'false_recovery': bool(fr),
            'bh_R0_H5': float(bh5), 'bh_R0_H10': float(bh10),
            'bh_R0_H20': float(bh20), 'bh_R0_H40': float(bh40),
            'mfe_after_r0': mfe, 'mae_after_r0': mae,
            're_reduce_day': re_reduce_day, 'exit_day': exit_day,
            'terminal_failure': terminal_failure,
            'true_recovery': bool(np.isfinite(est)),
            'recovery_established_day': est,
            'n_obs_in_window': n,
            'censored': bool(n < HORIZON),
        })
    out = pd.DataFrame(rows)
    out['stock_code'] = out.event_id.str.split('_').str[0]
    out['T0_date'] = out.event_id.str.split('_').str[1]

    write_stage_outputs(
        OUT, 't7_0_outcomes', {'outcomes': out},
        {'inputs': [
            {'name': 't6_2_cycle_master', 'path': 'output/research/t6/02_recycling/t6_2_cycle_master.parquet',
             'sha256': sha256_file(T6/'02_recycling/t6_2_cycle_master.parquet'), 'bytes': 0},
            {'name': 't6_3_cycle_trigger', 'path': 'output/research/t6/03_failure_anatomy/t6_3_cycle_trigger.parquet',
             'sha256': sha256_file(T6/'03_failure_anatomy/t6_3_cycle_trigger.parquet'), 'bytes': 0},
            {'name': 'daily_master', 'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
            {'name': 'definition_registry', 'path': 'output/research/t7/00_path_factlayer/t7_0_definition_registry.json',
             'sha256': sha256_file(OUT/'t7_0_definition_registry.json'), 'bytes': 0}]},
        {'stage': 't7_0_outcomes',
         'true_recovery_semantics': 'judged per frozen definition registry (achievement + K=5 persistence); persistence requires K subsequent effective observations with finite values (censored tails do not establish)',
         'counts': {'rows': int(len(out)),
                    'true_recovery': int(out.true_recovery.sum()),
                    'false_recovery_inherited': int(out.false_recovery.sum()),
                    'terminal_failure': int(out.terminal_failure.sum())}})
    print('outcomes rows:', len(out), 'true_recovery:', out.true_recovery.sum(),
          'false_recovery:', out.false_recovery.sum())
    print(out.groupby(out.segment).true_recovery.agg(['mean', 'size']).round(3))


if __name__ == '__main__':
    main()
