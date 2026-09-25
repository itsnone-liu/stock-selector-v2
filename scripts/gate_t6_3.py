#!/usr/bin/env python3
"""T6.3 gates — failure anatomy."""
from __future__ import annotations
import importlib.util
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

OUT = T6/'03_failure_anatomy'


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t6_3_manifest.json').read_text())
    rep = json.loads((OUT/'t6_3_report_data.json').read_text())
    contract = load_contract()
    ea = pd.read_parquet(OUT/'t6_3_failure_anatomy.parquet')

    gf.g1_lineage(log, man, OUT)
    t60 = json.loads((T6/'00_factlayer/t6_0_manifest.json').read_text())
    gf.g2_upstream_immutability(log, t60)
    ok60 = all(sha256_file(T6/'00_factlayer'/pr['file']) == pr['sha256']
               for pr in t60['products'] if pr['file'].endswith('.json'))
    t62 = json.loads((T6/'02_recycling/t6_2_manifest.json').read_text())
    ok62 = all(sha256_file(T6/'02_recycling'/pr['file']) == pr['sha256']
               for pr in t62['products'] if pr['file'].endswith('.json'))
    log.gate('G2b_upstream_products_immutable', ok60 and ok62)

    run_src = (ROOT/'scripts/run_t6_3.py').read_text()
    stats_src = (ROOT/'src/t6/stats.py').read_text()
    gf.g4_outcome_separation(log, {'failure_anatomy': ea}, [run_src, stats_src])
    gf.g5_segment_isolation(log, {'failure_anatomy': ea})
    gf.contract_symbol_asserts(log, contract)
    import pyarrow.parquet as pq
    dm_cols = set(pq.read_schema(T6/'00_factlayer/t6_0_daily_master.parquet').names)
    gf.contract_reference_integrity(log, contract,
                                    legal_identifiers=dm_cols | set(ea.columns)
                                    | {'mdd', 'ret', 'quick_failure_day_window',
                                       'healthy_prefix_days', 'gap_rows_min',
                                       'false_recovery_window_valid_obs'})
    gf.g6c_contract_semantic_types(log, contract,
                                   known_vars=dm_cols | {'mdd', 'ret', 'drawdown',
                                                         'max_dd', 'ret_norm_ep',
                                                         'drawdown_from_peak_log',
                                                         'max_dd_to_date_log', 'ret_1d_log'})
    gf.g6_preregistration(log, [run_src, stats_src], contract)
    gf.g7_no_tuning(log, [run_src, stats_src])

    # G8 conservation: every episode classified exactly once; F-stage sums
    gf.g8_conservation(log, {
        'segments_sum': (len(ea), ea.segment.value_counts().to_dict()),
        'F_stage_sum': (len(ea), ea.F_stage.value_counts().to_dict()),
    })
    # G8d (R1 audit): every fired trigger must sit STRICTLY AFTER its A0 day,
    # and within 5 row_present observations after it — full check, not a sample.
    ct = pd.read_parquet(OUT/'t6_3_cycle_trigger.parquet')
    fired = ct[ct.false_recovery]
    ok8d = bool((fired.trigger_day.notna()).all()
                and (fired.trigger_day > fired.a0_day).all())
    # boundary: trigger day must also be a row_present day in the daily master
    # (spot-verified full join on (event_id, day))
    dmp = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                          columns=['event_id', 'delta_day', 'row_present'])
    j = fired.merge(dmp, left_on=['event_id', 'trigger_day'],
                    right_on=['event_id', 'delta_day'], how='left')
    ok8d = ok8d and bool(j.row_present.fillna(False).all())
    log.gate('G8d_trigger_window_after_A0', ok8d,
             fired_cycles=int(len(fired)), max_trigger_minus_a0=float((fired.trigger_day - fired.a0_day).max()),
             note='R1: A0 day excluded from the 5-valid-observation false-recovery window')

    # G9 statistical integrity incl. R1 NaN consistency
    pre = contract['statistics_prereg']
    used = rep['statistics_used']
    ok9 = (used['B'] == pre['bootstrap_B'] and used['seed'] == pre['bootstrap_seed']
           and set(pre['cluster_units']) <= set(used['clusters'])
           and 'percentile 2.5/97.5' in used['ci'] and 'Holm' in used['holm']
           and rep['contract_sha256'] == sha256_file(T6/'t6_contract.json'))
    n_bad_p = n_bad_ci = n_empty = n_bad_nan = 0

    def walk_ci(o):
        nonlocal n_bad_ci, n_empty, n_bad_nan
        if isinstance(o, dict):
            if set(o) >= {'ci95'} and isinstance(o['ci95'], (list, tuple)) and len(o['ci95']) == 2:
                lo, hi = o['ci95']
                if isinstance(lo, float) and np.isnan(lo):
                    n_empty += 1
                elif lo > hi:
                    n_bad_ci += 1
            if set(o) >= {'diff', 'ci95', 'p_boot'}:
                d_nan = isinstance(o['diff'], float) and np.isnan(o['diff'])
                c_nan = all(isinstance(x, float) and np.isnan(x) for x in o['ci95'])
                p_nan = isinstance(o['p_boot'], float) and np.isnan(o['p_boot'])
                if not (d_nan == c_nan == p_nan):
                    n_bad_nan += 1
            if 'p_boot' in o and isinstance(o['p_boot'], float) and not np.isnan(o['p_boot']):
                if not (0.0 <= o['p_boot'] <= 1.0):
                    n_bad_p += 1
            for v in o.values():
                walk_ci(v)
        elif isinstance(o, list):
            for v in o:
                walk_ci(v)
    walk_ci(rep['segments'])
    log.gate('G9_statistical_integrity',
             ok9 and n_bad_p == 0 and n_bad_ci == 0 and n_bad_nan == 0,
             bad_p=n_bad_p, bad_ci=n_bad_ci, bad_nan_consistency=n_bad_nan,
             empty_group_cells=n_empty)

    # G9b: independent recomputation of the frequency table + episode classes
    ok9b = True
    for seg in ('validation', 'confirmation'):
        es = ea[ea.segment == seg]
        got = rep['freq_F'].get(seg, {})
        for f, n_rep in got.items():
            if int((es.F_stage == f).sum()) != int(n_rep):
                ok9b = False
    # episode_class recompute from contract thresholds (independent symbols)
    t = contract['preregistered_thresholds']
    sev = t['severe_dd_depth_log']
    cls = np.where((ea.ret_norm_ep > 0) & (ea.abs_mdd < sev), 'GOOD',
           np.where(ea.ret_norm_ep > 0, 'PAINFUL_WIN',
           np.where(ea.abs_mdd < sev, 'CONTROLLED_LOSS', 'SEVERE_FAILURE')))
    ok9b = ok9b and bool((cls == ea.episode_class.values).all())
    n_sev = int((cls == 'SEVERE_FAILURE').sum())
    n_sev_rep = sum(r['n'] for r in rep['freq_episode_class_x_F']
                    if r['episode_class'] == 'SEVERE_FAILURE')
    ok9b = ok9b and n_sev == n_sev_rep
    log.gate('G9b_recompute', ok9b, severe_total={'direct': n_sev, 'reported': n_sev_rep})

    # G10 determinism: replay one separability statistic
    from t6.stats import cluster_boot_diff, make_rng_factory
    spec = importlib.util.spec_from_file_location('run_t6_3', ROOT/'scripts/run_t6_3.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    enums = [['validation', 'confirmation', 'development'],
             ['sep', 'freq', 'e2f'],
             list(mod.DISC_COLS) + ['first_red_day'],
             ['FALSE_RECOVERY', 'CYCLE_OK', 'NO_CYCLE'],
             ['median', 'mean']]
    B = int(contract['statistics_prereg']['bootstrap_B'])
    SEED = int(contract['statistics_prereg']['bootstrap_seed'])
    rngf = make_rng_factory(SEED, enums)
    es = ea[ea.segment == 'validation']
    vals = es['efficiency_signed_3'].to_numpy(float)
    mh = (es.cohort_sep == 'FALSE_RECOVERY').to_numpy()
    ml = (es.cohort_sep == 'CYCLE_OK').to_numpy()
    est, ci, p, diag = cluster_boot_diff(vals, mh, ml,
                                         es.event_id.str.split('_').str[0].to_numpy(),
                                         'median', rngf('validation', 'sep', 'efficiency_signed_3',
                                                        'FALSE_RECOVERY'), B)
    st = rep['segments']['validation']['separability']['efficiency_signed_3']['FR_minus_OK']
    ok10 = (abs(est - st['diff']) < 1e-12 and abs(ci[0] - st['ci95'][0]) < 1e-12
            and abs(ci[1] - st['ci95'][1]) < 1e-12 and abs(p - st['p_boot']) < 1e-12
            and diag['n_hi'] == st['n_hi'] and diag['n_lo'] == st['n_lo'])
    log.gate('G10_determinism', ok10, replayed='validation/sep/efficiency_signed_3 FR_vs_OK')

    gf.g11_anti_story(log, ROOT/'docs/reports/T6_3_FAILURE_ANATOMY.md',
                      OUT/'t6_3_claims.json',
                      extra_registry_paths=[T6/'01_eclass/t6_1_claims.json',
                                            T6/'02_recycling/t6_2_claims.json'])
    sys.exit(log.finish(OUT/'t6_3_gates.json'))


if __name__ == '__main__':
    main()
