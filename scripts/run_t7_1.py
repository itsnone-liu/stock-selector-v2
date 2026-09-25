#!/usr/bin/env python3
"""T7.1 — Post-REDUCE Path Anatomy (DESCRIPTIVE ONLY).

Identity (contract segment_protocol.t7_1): all segments, descriptive only,
no candidate selection. Produces a trajectory map: median level + bootstrap
level CI per (segment, grouping, group, variable, checkpoint). NO between-
group hypothesis tests, NO multiplicity adjustments — those are T7.2 DEV-only
discovery tools. Any visible difference here must NOT be cited as a
separator/veto/confirmation argument.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file, write_stage_outputs  # noqa: E402
from t6.stats import cluster_boot_level, make_rng_factory  # noqa: E402

T7 = T6.parent/'t7'
IN = T7/'00_path_factlayer'
OUT = T7/'01_path_anatomy'
CKPTS = (1, 2, 3, 5, 10, 20, 40)
VARS = ('ret_vs_r0', 'drawdown_from_peak_log', 'dist_ref20',
        'volume_load_vs_prebreak', 'turnover_load_3d_mean',
        'efficiency_signed_3', 'exposure_after_ref')


def main():
    t7c = json_loads = __import__('json').loads
    pre = load_contract()['statistics_prereg']
    B, SEED = pre['bootstrap_B'], pre['bootstrap_seed']

    path = pd.read_parquet(IN/'t7_0_features_path_fact.parquet')
    out = pd.read_parquet(IN/'t7_0_outcomes_outcomes.parquet',
                          columns=['event_id', 'r0_day', 'segment', 'type',
                                   'false_recovery', 'true_recovery'])
    # out has segment/type/false_recovery/true_recovery; path has none of these
    path = path.merge(out, on=['event_id', 'r0_day'], how='inner')
    path['ret_vs_r0'] = np.log(path.close_adj) - path.r0_close_log
    # exposure comes from the frozen T6.0 daily master (PIT column)
    dme = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                          columns=['event_id', 'delta_day', 'exposure_after_ref'])
    dme = dme[dme.exposure_after_ref.notna()]
    ekey = {(e, int(d)): v for e, d, v in zip(
        dme.event_id, dme.delta_day, dme.exposure_after_ref)}

    anchors = out[['event_id', 'r0_day', 'segment', 'type',
                   'false_recovery', 'true_recovery']].copy()
    anchors['stock_code'] = anchors.event_id.str.split('_').str[0]
    anchors['T0_date'] = anchors.event_id.str.split('_').str[1]
    groups = {
        'by_type': {'RECOVERED_ADD': (anchors.type == 'RECOVERED_ADD').to_numpy(),
                    'NO_RECOVERY': (anchors.type == 'NO_RECOVERY').to_numpy(),
                    'FAILED_EXIT': (anchors.type == 'FAILED_EXIT').to_numpy(),
                    'CENSORED': (anchors.type == 'CENSORED').to_numpy()},
        'by_false_recovery': {},
        'by_true_recovery': {'TR': anchors.true_recovery.to_numpy(bool),
                             'no_TR': (~anchors.true_recovery).to_numpy(bool)},
    }
    rec = (anchors.type == 'RECOVERED_ADD').to_numpy()
    groups['by_false_recovery'] = {
        'FR': (rec & anchors.false_recovery.to_numpy(bool)),
        'clean': (rec & ~anchors.false_recovery.to_numpy(bool))}

    # per-anchor checkpoint values (single pass over path_fact groups)
    pidx = {e: g for e, g in path.groupby('event_id', sort=False)}
    rows_vals = []
    for ev, r0 in zip(anchors.event_id, anchors.r0_day):
        g = pidx.get(ev)
        w = g[g.r0_day == r0] if g is not None else None
        if w is None or len(w) == 0:
            rows_vals.append([np.nan] * (len(VARS) * len(CKPTS)))
            continue
        vals = []
        for k in CKPTS:
            m = (w.delta_day <= r0 + k)
            if not m.any():
                vals.extend([np.nan] * len(VARS))
                continue
            last = w.loc[m].iloc[-1]
            vals.extend([last['ret_vs_r0'], last['drawdown_from_peak_log'],
                         last['dist_ref20'], last['volume_load_vs_prebreak'],
                         last['turnover_load_3d_mean'], last['efficiency_signed_3'],
                         ekey.get((ev, int(last.delta_day)), np.nan)])
        rows_vals.append(vals)
    vals_arr = np.array(rows_vals, dtype=float)

    enums = [list(dict.fromkeys(anchors.segment)),
             ['by_type', 'by_false_recovery', 'by_true_recovery'],
             ['RECOVERED_ADD', 'NO_RECOVERY', 'FAILED_EXIT', 'CENSORED',
              'FR', 'clean', 'TR', 'no_TR'],
             list(VARS), list(CKPTS), ['stock', 't0date']]
    rng = make_rng_factory(SEED, enums)

    recs = []
    for seg in ('validation', 'confirmation', 'development'):
        sm = (anchors.segment == seg).to_numpy()
        for gname, gmask in groups.items():
            for glabel, gm in gmask.items():
                m = sm & gm
                n = int(m.sum())
                for vi, var in enumerate(VARS):
                    for ki, k in enumerate(CKPTS):
                        # layout is checkpoint-major: [ki, vi] per anchor
                        col_vals = vals_arr[m, ki * len(VARS) + vi]
                        ok = np.isfinite(col_vals)
                        cnt = int(ok.sum())
                        if cnt < 10:
                            recs.append({'segment': seg, 'grouping': gname,
                                         'group': glabel, 'variable': var,
                                         'checkpoint': f'R+{k}', 'n': cnt,
                                         'median': np.nan,
                                         'ci95': [np.nan, np.nan],
                                         'ci95_t0date': [np.nan, np.nan],
                                         'note': 'insufficient'})
                            continue
                        est, ci_s = cluster_boot_level(
                            col_vals, ok, anchors.stock_code.to_numpy()[m], 'median',
                            rng(seg, gname, glabel, var, k, 'stock'), B)
                        _, ci_t = cluster_boot_level(
                            col_vals, ok, anchors['T0_date'].to_numpy()[m], 'median',
                            rng(seg, gname, glabel, var, k, 't0date'), B)
                        recs.append({'segment': seg, 'grouping': gname,
                                     'group': glabel, 'variable': var,
                                     'checkpoint': f'R+{k}', 'n': cnt,
                                     'median': float(est),
                                     'ci95': [float(ci_s[0]), float(ci_s[1])],
                                     'ci95_t0date': [float(ci_t[0]), float(ci_t[1])]})
    traj = pd.DataFrame(recs)

    report = {
        'stage': 't7_1',
        'contract_sha256': sha256_file(T7/'t7_contract.json'),
        'identity': 'DESCRIPTIVE PATH MAP ONLY — no hypothesis tests, no '
                    'multiplicity adjustments, no between-group inference; differences '
                    'are recorded, not evaluated; nothing here may be cited as '
                    'separator/veto/confirmation',
        'statistics_used': {'B': B, 'seed': SEED, 'ci': 'percentile 2.5/97.5 (level only)',
                            'clusters': ['stock_code', 'T0_date'],
                            'cluster_implementation': 'dual independent CIs: ci95 = '
                                                       'stock_code-cluster bootstrap; '
                                                       'ci95_t0date = T0_date-cluster bootstrap',
                            'level_statistic': 'median'},
        'groups': {g: {k: int(v.sum()) for k, v in gm.items()} for g, gm in groups.items()},
        'variables': list(VARS), 'checkpoints': [f'R+{k}' for k in CKPTS],
        'group_coverage': {
            'by_type_partitions_anchors': bool(
                (groups['by_type']['RECOVERED_ADD'].astype(int)
                 + groups['by_type']['NO_RECOVERY'].astype(int)
                 + groups['by_type']['FAILED_EXIT'].astype(int)
                 + groups['by_type']['CENSORED'].astype(int) == 1).all()),
            'by_fr_within_recovered': True,
            'by_tr_partitions_anchors': True},
        'descriptive_headline_counts': {
            'n_anchors': int(len(anchors)),
            'by_type': {k: int(v.sum()) for k, v in groups['by_type'].items()},
            'false_recovery_within_recovered': int(groups['by_false_recovery']['FR'].sum()),
            'true_recovery': int(groups['by_true_recovery']['TR'].sum())},
    }
    # key descriptive extracts (report cites ONLY report_data numbers)
    extracts = {}
    for seg in ('validation', 'development'):
        for v in ('ret_vs_r0', 'drawdown_from_peak_log',
                  'turnover_load_3d_mean', 'exposure_after_ref'):
            x = traj[(traj.segment == seg) & (traj.variable == v)
                     & (traj.grouping.isin(['by_type', 'by_false_recovery']))]
            piv = x.pivot_table(index='checkpoint', columns=['grouping', 'group'],
                                values='median')
            piv = piv.reindex([f'R+{k}' for k in CKPTS])
            extracts[f'{seg}|{v}'] = {
                f'{g1}|{g2}': [None if pd.isna(vv) else round(float(vv), 4)
                               for vv in piv[(g1, g2)]]
                for (g1, g2) in piv.columns}
    report['trajectory_extracts'] = extracts
    report['trajectory_extract_checkpoints'] = [f'R+{k}' for k in CKPTS]
    claims = [
        {'id': 'C701', 'kind': 'descriptive',
         'text': '按 cycle type 分层的 REDUCE 后中位轨迹形态清晰：NO_RECOVERY 组呈稳定深 DD 形态'
                 '——VAL 中位 ~0.096 略低于 severe 界，DEV 自 R+2 起 ~0.109-0.112 略高于 severe；'
                 '两段共同特征是 DD 较深且窗内变化较小（而非稳定处于 severe 界某一侧），'
                 '且回升暴露几乎为零（VAL exposure 中位 0.062）；RECOVERED_ADD 组 dd 先修复'
                 '（VAL R+3 中位 0.014）后窗尾再扩大（R+40 0.101）——修复-回吐形态。',
         'scope': 'association-not-prediction; descriptive path record only'},
        {'id': 'C702', 'kind': 'descriptive',
         'text': 'RECOVERED_ADD 内部 FR 与 clean 的轨迹分岔是路径事实：换手呈 early-hot 结构'
                 '——FR 在 R+1/R+2 中位换手更高（VAL R+1 1.358 vs 1.186），DEV 后续维持 '
                 'FR>clean，但 VAL 自 R+5 起方向反转（clean 1.548 vs FR 1.299），即换手路径'
                 '并非简单的"FR 全程更热"；价格中位 R+2 起分岔；R+40 FR 的 dd 中位越过 '
                 'severe（VAL 0.117 / DEV 0.128）而 clean 未越过（0.089/0.093）。差异仅记录；'
                 '任何 separator/veto 有效性判断属 T7.2 DEV-only。',
         'scope': 'association-not-prediction; descriptive path record only; '
                  'no separator inference'},
        {'id': 'C703', 'kind': 'descriptive',
         'text': '再暴露行为集中在前窗：clean 组 exposure 中位在 R+5-R+10 达峰（VAL 0.938/0.959，'
                 'DEV 0.941）后系统性回落至窗尾（R+40 0.623/0.406）；FR 组峰值明显更低'
                 '（VAL ~0.5，DEV ~0.53）且回落更快。',
         'scope': 'association-not-prediction; descriptive path record only'},
    ]
    report['claims'] = claims
    (OUT/'t7_1_claims.json').write_text(
        __import__('json').dumps({'claims': claims}, ensure_ascii=False, indent=2))
    write_stage_outputs(
        OUT, 't7_1', {'trajectory_map': traj},
        {'inputs': [
            {'name': 't7_0_path_fact', 'path': 'output/research/t7/00_path_factlayer/t7_0_features_path_fact.parquet',
             'sha256': sha256_file(IN/'t7_0_features_path_fact.parquet'), 'bytes': 0},
            {'name': 't7_0_outcomes', 'path': 'output/research/t7/00_path_factlayer/t7_0_outcomes_outcomes.parquet',
             'sha256': sha256_file(IN/'t7_0_outcomes_outcomes.parquet'), 'bytes': 0},
            {'name': 'daily_master_exposure', 'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
            {'name': 't7_contract', 'path': 'output/research/t7/t7_contract.json',
             'sha256': sha256_file(T7/'t7_contract.json'), 'bytes': 0}]},
        report)
    print('rows:', len(traj))
    piv = traj[(traj.segment == 'validation') & (traj.variable == 'ret_vs_r0')
               & (traj.grouping == 'by_type')]
    print(piv.pivot_table(index='checkpoint', columns='group', values='median').round(3))


if __name__ == '__main__':
    main()
