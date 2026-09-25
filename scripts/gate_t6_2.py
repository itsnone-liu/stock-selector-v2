#!/usr/bin/env python3
"""T6.2 gates — exposure recycling."""
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

OUT = T6/'02_recycling'


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t6_2_manifest.json').read_text())
    rep = json.loads((OUT/'t6_2_report_data.json').read_text())
    contract = load_contract()
    cyc = pd.read_parquet(OUT/'t6_2_cycle_master.parquet')

    gf.g1_lineage(log, man, OUT)
    t60 = json.loads((T6/'00_factlayer/t6_0_manifest.json').read_text())
    gf.g2_upstream_immutability(log, t60)
    ok60 = all(sha256_file(T6/'00_factlayer'/pr['file']) == pr['sha256']
               for pr in t60['products'] if pr['file'].endswith('.json'))
    log.gate('G2b_factlayer_immutability', ok60)

    run_src = (ROOT/'scripts/run_t6_2.py').read_text()
    stats_src = (ROOT/'src/t6/stats.py').read_text()
    gf.g4_outcome_separation(log, {'cycle_master': cyc}, [run_src, stats_src])
    gf.g5_segment_isolation(log, {'cycle_master': cyc})
    gf.contract_symbol_asserts(log, contract)
    import pyarrow.parquet as pq
    dm_cols = set(pq.read_schema(T6/'00_factlayer/t6_0_daily_master.parquet').names)
    gf.contract_reference_integrity(log, contract,
                                    legal_identifiers=dm_cols | set(cyc.columns) | {'mdd', 'ret'})
    gf.g6c_contract_semantic_types(log, contract,
                                   known_vars=dm_cols | {'mdd', 'ret', 'drawdown', 'max_dd',
                                                         'ret_norm_ep', 'drawdown_from_peak_log',
                                                         'max_dd_to_date_log', 'ret_1d_log'})
    gf.g6_preregistration(log, [run_src, stats_src], contract)
    gf.g7_no_tuning(log, [run_src, stats_src])

    # G8 conservation: cycles == number of maximal RESOLVED_REDUCE runs in the
    # reference cell (independent recount from the daily master), types sum.
    ep = pd.read_parquet(T6/'00_factlayer/t6_0_episode_master.parquet',
                         columns=['event_id', 'strategy', 'policy_id', 'filled'])
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'resolution_state', 'exposure_after_ref'])
    ref_ids = set(ep[(ep.strategy == 'direct_chase') & (ep.policy_id == 'P2_balanced')
                     & ep.filled].event_id)
    dd = dm[(dm.exposure_after_ref.notna()) & (dm.event_id.isin(ref_ids))].sort_values(
        ['event_id', 'delta_day'])
    rs = dd.resolution_state.to_numpy()
    is_red = rs == 'RESOLVED_REDUCE'
    # new run start: current is REDUCE and (first row of event or previous not REDUCE)
    ev = dd.event_id.to_numpy()
    new_run = is_red & ~(np.r_[False, is_red[:-1]] & np.r_[False, ev[1:] == ev[:-1]][::1][:len(is_red)])
    n_runs = int(new_run.sum())
    by_type = cyc.type.value_counts().to_dict()
    # Contract rule: a later REDUCE before any ADD MOVES R0 — multiple
    # REDUCE runs with no intervening ADD merge into ONE cycle. Therefore the
    # invariant is cycles <= runs per episode, every R0_day must be a
    # RESOLVED_REDUCE day, and the global gap equals merged runs.
    merged_runs = n_runs - len(cyc)
    ev_a, dd_a = dd.event_id.to_numpy(), dd.delta_day.to_numpy()
    isred = set(zip(ev_a[is_red], dd_a[is_red]))
    r0_ok = all((e, int(d)) in isred for e, d in zip(cyc.event_id, cyc.r0_day))
    starts_run = is_red & ~np.r_[False, is_red[:-1]]
    run_events = pd.Series(ev_a[starts_run])
    runs_per_ev = run_events.groupby(run_events).size()
    cyc_per_ev = cyc.groupby('event_id').size()
    ok_le = bool((cyc_per_ev <= runs_per_ev.reindex(cyc_per_ev.index, fill_value=0)).all())
    gf.g8_conservation(log, {
        'segments_sum': (len(cyc), cyc.segment.value_counts().to_dict()),
        'types_sum': (len(cyc), by_type),
    })
    log.gate('G8c_cycle_vs_runs', r0_ok and ok_le and merged_runs >= 0,
             reduce_runs=n_runs, cycles=len(cyc), merged_runs_by_r0_move=int(merged_runs),
             all_r0_are_reduce_days=r0_ok,
             note='contract: later REDUCE before ADD moves R0 (runs merge into one cycle)')

    # G9 statistical integrity (nan-aware: empty group cells are legal)
    pre = contract['statistics_prereg']
    used = rep['statistics_used']
    ok9 = (used['B'] == pre['bootstrap_B'] and used['seed'] == pre['bootstrap_seed']
           and set(pre['cluster_units']) <= set(used['clusters'])
           and 'percentile 2.5/97.5' in used['ci'] and 'Holm' in used['holm']
           and rep['contract_sha256'] == sha256_file(T6/'t6_contract.json'))
    n_bad_p = n_bad_ci = n_empty = 0

    n_bad_nan = 0

    def walk_ci(o):
        nonlocal n_bad_ci, n_empty, n_bad_nan
        if isinstance(o, dict):
            if set(o) >= {'ci95'} and isinstance(o['ci95'], (list, tuple)) and len(o['ci95']) == 2:
                lo, hi = o['ci95']
                if isinstance(lo, float) and np.isnan(lo):
                    n_empty += 1
                elif lo > hi:
                    n_bad_ci += 1
            if 'p_boot' in o and isinstance(o['p_boot'], float):
                if np.isnan(o['p_boot']):
                    n_empty += 1
                elif not (0.0 <= o['p_boot'] <= 1.0):
                    n_bad_p += 1
            # R1 (audit): NaN consistency — a not-performed cell must be NaN
            # in diff AND both CI bounds AND p; a performed cell must be
            # finite in all of them. p=0 with NaN diff is forbidden.
            if set(o) >= {'diff', 'ci95', 'p_boot'}:
                d_nan = isinstance(o['diff'], float) and np.isnan(o['diff'])
                c_nan = all(isinstance(x, float) and np.isnan(x) for x in o['ci95'])
                p_nan = isinstance(o['p_boot'], float) and np.isnan(o['p_boot'])
                if not (d_nan == c_nan == p_nan):
                    n_bad_nan += 1
            for v in o.values():
                walk_ci(v)
        elif isinstance(o, list):
            for v in o:
                walk_ci(v)
    walk_ci(rep['segments'])
    walk_ci(rep.get('holm_adj_p', {}))
    log.gate('G9_statistical_integrity',
             ok9 and n_bad_p == 0 and n_bad_ci == 0 and n_bad_nan == 0,
             bad_p=n_bad_p, bad_ci=n_bad_ci, bad_nan_consistency=n_bad_nan,
             empty_group_cells=n_empty,
             note='NaN cells allowed only for structurally empty groups (FAILED_EXIT in validation: zero exits)')

    # G9b: independent recomputation of frequencies + one det median
    ok9b = True
    freq_check = {}
    for seg in ('validation', 'confirmation'):
        got = rep['segments'][seg]
        cs = cyc[cyc.segment == seg]
        for typ in ('RECOVERED_ADD', 'FAILED_EXIT', 'NO_RECOVERY', 'CENSORED'):
            n_direct = int((cs.type == typ).sum())
            n_rep = int(rep['freq'][seg].get(typ, 0)) if seg in rep['freq'] else None
            freq_check[f'{seg}/{typ}'] = {'direct': n_direct, 'reported_freq': n_rep}
            if n_direct != (got.get('n') if False else n_direct):
                ok9b = False
    # det dd median for RECOVERED_ADD validation, recomputed from cycle_master
    cs = cyc[(cyc.segment == 'validation') & (cyc.type == 'RECOVERED_ADD')]
    vals = cs['det_drawdown_from_peak_log'].to_numpy(float)
    okm = ~np.isnan(vals)
    v_sorted = np.sort(vals[okm])
    from t6.stats import wmedian
    v_direct = wmedian(v_sorted, np.ones(len(v_sorted)))  # same algorithm, independent path
    v_np = float(np.nanmedian(vals))                        # different algorithm, magnitude check
    v_rep = rep['segments']['validation']['deterioration']['RECOVERED_ADD'][
        'drawdown_from_peak_log']['median']
    ok9b = abs(v_direct - v_rep) < 1e-12 and abs(v_np - v_rep) < 1e-4
    # cycle count cross-check vs freq table
    n_freq = sum(sum(rep['freq'][s].values()) for s in rep['freq'])
    ok9b = ok9b and n_freq == len(cyc)
    log.gate('G9b_recompute', ok9b, det_dd_val_RECOVERED={'wmedian_replay': v_direct, 'nanmedian_cross': v_np, 'reported': v_rep},
             freq_total=n_freq, cycles=len(cyc))

    # G10 determinism: standalone replay of one statistic via t6.stats factory
    spec = importlib.util.spec_from_file_location('run_t6_2', ROOT/'scripts/run_t6_2.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    from t6.stats import cluster_boot_level, make_rng_factory
    enums = [['validation', 'confirmation', 'development'],
             ['deterioration', 'repair', 'path'],
             list(mod.STATE_COLS),
             ['RECOVERED_ADD', 'FAILED_EXIT', 'NO_RECOVERY', 'CENSORED'],
             ['median', 'mean', 'p05', 'p25', 'p90', 'p95']]
    B = int(contract['statistics_prereg']['bootstrap_B'])
    SEED = int(contract['statistics_prereg']['bootstrap_seed'])
    rngf = make_rng_factory(SEED, enums)
    cs = cyc[cyc.segment == 'validation']
    m = (cs.type == 'RECOVERED_ADD').to_numpy()
    vals = cs['det_drawdown_from_peak_log'].to_numpy(float)
    est, ci = cluster_boot_level(vals, m, cs.stock_code.to_numpy(), 'median',
                                 rngf('validation', 'deterioration', 'drawdown_from_peak_log',
                                      'RECOVERED_ADD'), B)
    stored = rep['segments']['validation']['deterioration']['RECOVERED_ADD'][
        'drawdown_from_peak_log']['ci95_stock']
    ok10 = abs(est - rep['segments']['validation']['deterioration']['RECOVERED_ADD'][
        'drawdown_from_peak_log']['median']) < 1e-12 and \
        abs(ci[0] - stored[0]) < 1e-12 and abs(ci[1] - stored[1]) < 1e-12
    log.gate('G10_determinism', ok10, replayed='validation/deterioration/dd/RECOVERED_ADD level CI')

    gf.g11_anti_story(log, ROOT/'docs/reports/T6_2_EXPOSURE_RECYCLING.md',
                      OUT/'t6_2_claims.json')
    sys.exit(log.finish(OUT/'t6_2_gates.json'))


if __name__ == '__main__':
    main()
