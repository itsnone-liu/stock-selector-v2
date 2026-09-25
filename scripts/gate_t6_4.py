#!/usr/bin/env python3
"""T6.4 gates — market/sector regime interaction."""
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

OUT = T6/'04_regime'


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t6_4_manifest.json').read_text())
    rep = json.loads((OUT/'t6_4_report_data.json').read_text())
    contract = load_contract()
    rg = pd.read_parquet(OUT/'t6_4_regime_cycle.parquet')
    epf = pd.read_parquet(OUT/'t6_4_regime_episode.parquet')

    gf.g1_lineage(log, man, OUT)
    t60 = json.loads((T6/'00_factlayer/t6_0_manifest.json').read_text())
    gf.g2_upstream_immutability(log, t60)
    ok_up = all(sha256_file(T6/'00_factlayer'/pr['file']) == pr['sha256']
                for pr in t60['products'] if pr['file'].endswith('.json'))
    for st, mf in (('02_recycling', 't6_2_manifest.json'), ('03_failure_anatomy', 't6_3_manifest.json')):
        m = json.loads((T6/st/mf).read_text())
        ok_up = ok_up and all(sha256_file(T6/st/pr['file']) == pr['sha256']
                              for pr in m['products'] if pr['file'].endswith('.json'))
    log.gate('G2b_upstream_products_immutable', ok_up)

    run_src = (ROOT/'scripts/run_t6_4.py').read_text()
    stats_src = (ROOT/'src/t6/stats.py').read_text()
    gf.g4_outcome_separation(log, {'regime_cycle': rg, 'regime_episode': epf},
                             [run_src, stats_src])
    gf.g5_segment_isolation(log, {'regime_cycle': rg})
    gf.contract_symbol_asserts(log, contract)
    import pyarrow.parquet as pq
    dm_cols = set(pq.read_schema(T6/'00_factlayer/t6_0_daily_master.parquet').names)
    gf.contract_reference_integrity(log, contract,
                                    legal_identifiers=dm_cols | set(rg.columns) | set(epf.columns)
                                    | {'mkt_breadth_5d', 'mkt_new_high_20d'})
    gf.g6c_contract_semantic_types(log, contract,
                                   known_vars=dm_cols | {'mdd', 'ret', 'drawdown',
                                                         'ret_norm_ep', 'abs_mdd'})
    gf.g6_preregistration(log, [run_src, stats_src], contract)
    gf.g7_no_tuning(log, [run_src, stats_src])

    gf.g8_conservation(log, {
        'regime_cycle_segments': (len(rg), rg.segment.value_counts().to_dict()),
        'regime_episode_segments': (len(epf), epf.segment.value_counts().to_dict()),
        'cycle_types': (len(rg), rg.type.value_counts().to_dict()),
    })

    # G9 statistical integrity + NaN consistency (T6.2-R1 lineage)
    pre = contract['statistics_prereg']
    used = rep['statistics_used']
    ok9 = (used['B'] == pre['bootstrap_B'] and used['seed'] == pre['bootstrap_seed']
           and set(pre['cluster_units']) <= set(used['clusters'])
           and 'percentile 2.5/97.5' in used['ci'] and 'Holm' in used['holm']
           and rep['contract_sha256'] == sha256_file(T6/'t6_contract.json'))
    n_bad_p = n_bad_ci = n_empty = n_bad_nan = 0

    def walk_ci(o):
        nonlocal n_bad_ci, n_empty, n_bad_nan, n_bad_p
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
    # sector quarantine: no primary block may reference sector metrics
    quarantined = all(v.get('status') == 'UNAVAILABLE'
                      for v in rep.get('EXPLORATORY_sector', {}).values()) and \
        'sector' not in json.dumps(rep['segments'])
    log.gate('G9_statistical_integrity',
             ok9 and n_bad_p == 0 and n_bad_ci == 0 and n_bad_nan == 0 and quarantined,
             bad_p=n_bad_p, bad_ci=n_bad_ci, bad_nan_consistency=n_bad_nan,
             empty_group_cells=n_empty, sector_quarantine=quarantined)

    # G9b: independent regime recomputation from contract thresholds
    def regime(b, nh):
        if np.isnan(b) or np.isnan(nh):
            return 'NA'
        if b > 0.55 and nh > 0.10:
            return 'M_STRONG'
        if b < 0.45 or nh < 0.04:
            return 'M_WEAK'
        return 'M_NEUTRAL'
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'mkt_breadth_5d', 'mkt_new_high_20d',
                                  'exposure_after_ref'])
    ep = pd.read_parquet(T6/'00_factlayer/t6_0_episode_master.parquet',
                         columns=['event_id', 'strategy', 'policy_id', 'filled'])
    ref_ids = set(ep[(ep.strategy == 'direct_chase') & (ep.policy_id == 'P2_balanced')
                     & ep.filled].event_id)
    dmr = dm[(dm.exposure_after_ref.notna()) & (dm.event_id.isin(ref_ids))]
    kmap = {(e, int(dd)): (b, nh) for e, dd, b, nh in zip(
        dmr.event_id, dmr.delta_day, dmr.mkt_breadth_5d.fillna(np.nan),
        dmr.mkt_new_high_20d.fillna(np.nan))}
    ok9b = True
    mism = 0
    for e, r0, reg in zip(rg.event_id, rg.r0_day, rg.R0_regime):
        got = kmap.get((e, int(r0)))
        want = regime(float(got[0]), float(got[1])) if got else 'NA'
        if want != reg:
            mism += 1
    ok9b = mism == 0
    n_freq = sum(x['n'] for x in rep['freq']['regime_totals'])
    ok9b = ok9b and n_freq == len(rg)
    log.gate('G9b_recompute', ok9b, regime_mismatches=mism, freq_total=n_freq, cycles=len(rg))

    # G10 determinism: replay one A2 statistic
    from t6.stats import cluster_boot_diff, make_rng_factory
    spec = importlib.util.spec_from_file_location('run_t6_4', ROOT/'scripts/run_t6_4.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    enums = [['validation', 'confirmation', 'development'],
             ['A1', 'A2', 'A3', 'X'],
             ['RECOVERED_ADD', 'NO_RECOVERY', 'FAILED_EXIT'],
             ['M_STRONG', 'M_NEUTRAL', 'M_WEAK', 'NA'],
             ['median', 'mean']]
    B = int(contract['statistics_prereg']['bootstrap_B'])
    SEED = int(contract['statistics_prereg']['bootstrap_seed'])
    rngf = make_rng_factory(SEED, enums)
    rec = rg[(rg.segment == 'validation') & (rg.type == 'RECOVERED_ADD')]
    est, ci, p, diag = cluster_boot_diff(rec.false_recovery.to_numpy(float),
                                         (rec.R0_regime == 'M_STRONG').to_numpy(),
                                         (rec.R0_regime == 'M_WEAK').to_numpy(),
                                         rec.stock_code.to_numpy(), 'mean',
                                         rngf('validation', 'A2', 'NO_RECOVERY', 'all_recovered_SvW'), B)
    st = rep['segments']['validation']['A2_FR_rate_by_regime']['all_recovered']['M_STRONG_minus_M_WEAK']
    ok10 = (abs(est - st['diff']) < 1e-12 and abs(ci[0] - st['ci95'][0]) < 1e-12
            and abs(ci[1] - st['ci95'][1]) < 1e-12 and abs(p - st['p_boot']) < 1e-12
            and diag['n_hi'] == st['n_hi'] and diag['n_lo'] == st['n_lo'])
    log.gate('G10_determinism', ok10, replayed='validation/A2/all_recovered SvW FR diff')

    gf.g11_anti_story(log, ROOT/'docs/reports/T6_4_REGIME_INTERACTION.md',
                      OUT/'t6_4_claims.json',
                      extra_registry_paths=[T6/'01_eclass/t6_1_claims.json',
                                            T6/'02_recycling/t6_2_claims.json',
                                            T6/'03_failure_anatomy/t6_3_claims.json'])
    sys.exit(log.finish(OUT/'t6_4_gates.json'))


if __name__ == '__main__':
    main()
