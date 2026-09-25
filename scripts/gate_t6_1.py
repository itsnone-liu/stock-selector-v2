#!/usr/bin/env python3
"""T6.1 gates — E-class independent validation on the frozen fact layer."""
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

OUT = T6/'01_eclass'


def load_run_module():
    spec = importlib.util.spec_from_file_location('run_t6_1', ROOT/'scripts/run_t6_1.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t6_1_manifest.json').read_text())
    rep = json.loads((OUT/'t6_1_report_data.json').read_text())
    contract = load_contract()
    f = pd.read_parquet(OUT/'t6_1_per_event.parquet')

    # G1 lineage of this stage's declared inputs
    gf.g1_lineage(log, man, OUT)

    # G2 upstream immutability: T6.0's frozen upstream hashes must still hold,
    # and the T6.0 masters (this stage's direct inputs) must match their
    # T6.0 manifest product hashes.
    t60 = json.loads((T6/'00_factlayer/t6_0_manifest.json').read_text())
    gf.g2_upstream_immutability(log, t60)
    ok60 = all(sha256_file(T6/'00_factlayer'/pr['file']) == pr['sha256']
               for pr in t60['products'] if pr['file'].endswith('.json'))
    log.gate('G2b_factlayer_immutability', ok60,
             note='t6_0 json products re-hashed against t6_0 manifest')

    # G4 outcome separation on the stage frame + builder lineage
    run_src = (ROOT/'scripts/run_t6_1.py').read_text()
    gf.g4_outcome_separation(log, {'per_event': f}, [run_src])
    # G5 segment isolation
    gf.g5_segment_isolation(log, {'per_event': f})
    # G6 family: prereg + sign + reference + semantic types
    gf.contract_symbol_asserts(log, contract)
    ep0 = pd.read_parquet(T6/'00_factlayer/t6_0_episode_master.parquet',
                          columns=['ret_norm_ep'])
    import pyarrow.parquet as pq
    dm_cols = set(pq.read_schema(T6/'00_factlayer/t6_0_daily_master.parquet').names)
    gf.contract_reference_integrity(log, contract,
                                    legal_identifiers=dm_cols | set(f.columns) | {'mdd', 'ret'})
    gf.g6c_contract_semantic_types(log, contract,
                                   known_vars=dm_cols | {'mdd', 'ret', 'drawdown', 'max_dd',
                                                         'ret_norm_ep', 'drawdown_from_peak_log',
                                                         'max_dd_to_date_log', 'ret_1d_log'})
    gf.g6_preregistration(log, [run_src], contract)
    # G7 no tuning
    gf.g7_no_tuning(log, [run_src], allow={
        r'argmax': 'peak_tau first-maximum day location (order statistic, not parameter search)'})

    # G8 conservation: reference-cell episodes decompose exactly
    ep_full = pd.read_parquet(T6/'00_factlayer/t6_0_episode_master.parquet',
                              columns=['strategy', 'policy_id', 'filled', 'E_class', 'segment'])
    n_ref = int(((ep_full.strategy == 'direct_chase') & (ep_full.policy_id == 'P2_balanced')
                 & ep_full.filled).sum())
    by_E = f.E_class.value_counts().to_dict()
    seg_n = {s: int(rep['segments'][s]['n']) for s in rep['segments']}
    gf.g8_conservation(log, {
        'per_event_vs_reference_cell': (n_ref, by_E),
        'segments_sum': (len(f), seg_n),
    })

    # G9 statistical integrity (REAL check this stage)
    pre = contract['statistics_prereg']
    used = rep['statistics_used']
    ok9 = (used['B'] == pre['bootstrap_B'] and used['seed'] == pre['bootstrap_seed']
           and set(pre['cluster_units']) <= set(used['clusters'])
           and 'percentile 2.5/97.5' in used['ci'] and 'Holm' in used['holm']
           and rep['contract_sha256'] == sha256_file(T6/'t6_contract.json'))
    n_bad_p = n_bad_ci = 0
    for seg, sv in rep['segments'].items():
        for m in sv['metrics'].values():
            for c in m['comparisons'].values():
                if not (0.0 <= c['p_boot'] <= 1.0):
                    n_bad_p += 1
                if not (c['ci95'][0] <= c['ci95'][1]):
                    n_bad_ci += 1
        if len(sv['holm_adj_p']) != 2 * len(sv['metrics']):
            ok9 = False
    log.gate('G9_statistical_integrity', ok9 and n_bad_p == 0 and n_bad_ci == 0,
             bad_p=n_bad_p, bad_ci=n_bad_ci, B=used['B'], seed=used['seed'],
             note='contract-resolved constants + p/CI sanity on all reported comparisons')

    # G9b: independent recomputation of point estimates (no run-module code)
    LL = contract['preregistered_thresholds']['large_loss_ret_log']
    ok9b, checked = True, 0
    for seg in ('validation', 'confirmation'):
        fs = f[f.segment == seg]
        for r, E in ((1, 'E1'), (2, 'E2'), (3, 'E3')):
            g = fs[fs.E_class == E]
            vals = {
                ('reward', 'median_return'): float(g.ret_norm_ep.median()),
                ('risk', 'median_mdd'): float(g.abs_mdd.median()),
                ('risk', 'large_loss_probability'): float((g.ret_norm_ep <= LL).mean()),
            }
            for (fam, met), v in vals.items():
                got = rep['segments'][seg]['metrics'][f'{fam}/{met}']['per_E'][E]
                checked += 1
                if abs(got - v) > 1e-9:
                    ok9b = False
    log.gate('G9b_point_estimate_recompute', ok9b, spot_checks=checked)

    # G10 determinism: standalone replay of one bootstrap statistic via the
    # module-level SeedSequence substream factory (independent of run order)
    mod = load_run_module()
    fs = f[f.segment == 'validation']
    vals = mod.metric_values(fs, 'median_return')
    erank = fs.E_rank.to_numpy()
    cl = fs.stock_code.to_numpy()
    fams = ['reward', 'risk', 'persistence', 'capital_efficiency']
    cmps = {'E2_vs_E1': (1, 2), 'E3_vs_E2': (2, 3)}
    cr = mod.make_child_rng(int(contract['statistics_prereg']['bootstrap_seed']),
                            mod.SEGS, fams, cmps)
    est, ci, p, _ = mod.bootstrap_ci(vals, erank, cl, 'median_return', (2, 3),
                                     cr('validation', 'reward', 'median_return',
                                        'E3_vs_E2', 'stock_code'),
                                     int(contract['statistics_prereg']['bootstrap_B']))
    stored = rep['segments']['validation']['metrics']['reward/median_return'][
        'comparisons']['E3_vs_E2|stock_code']
    ok10 = (abs(est - stored['diff']) < 1e-12
            and abs(ci[0] - stored['ci95'][0]) < 1e-12
            and abs(ci[1] - stored['ci95'][1]) < 1e-12
            and abs(p - stored['p_boot']) < 1e-12)
    log.gate('G10_determinism', ok10,
             replayed='validation/reward/median_return/E3_vs_E2|stock_code',
             replay_diff=est, stored_diff=stored['diff'])

    # G11 anti-story
    report = ROOT/'docs/reports/T6_1_ECLASS_VALIDATION.md'
    claims = OUT/'t6_1_claims.json'
    gf.g11_anti_story(log, report, claims if claims.exists() else None)

    sys.exit(log.finish(OUT/'t6_1_gates.json'))


if __name__ == '__main__':
    main()
