#!/usr/bin/env python3
"""T8.2 — Preregistered Order Inference (Estimand B, frozen T8 Plan v2 §3).

Fixed contrasts (no additions after seeing T8.1):
  marginal : k1 vs k2 / k2 vs k3+ / k1 vs k3+
  conditional: within outcome1 stratum {FR, CYCLE_OK, OTHER}, k2 vs k3+
              (k1 DEFINES the stratum, it does not enter the contrast)

outcome1 (episode-level, preregistered mapping from the frozen ADD1 flags,
priority FR > CYCLE_OK > OTHER; both-true conflict count reported):
  FR        = ADD1 false_add
  CYCLE_OK  = ADD1 recovery and not false_add
  OTHER     = neither

Primary sample = validation + confirmation pooled (frozen t6 statistics
contract primary_tests); development and all-segment tables are reference
only. Holm within each metric x cluster family. No policy, no thresholds
beyond the preregistered alpha=0.05 reading grid; no additional condition
variables (MAE/MFE/DD stratification explicitly excluded).
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, sha256_file, write_stage_outputs  # noqa: E402
from t6.stats import cluster_boot_diff, make_rng_factory, holm  # noqa: E402

T7 = T6.parent/'t7'
T8 = T6.parent/'t8'
OUT = T8/'02_order_inference'

METRICS = {  # frozen metric set: 2 rates (mean) + 4 medians
    'false_add_rate': ('false_add', 'mean'),
    'recovery_rate': ('recovery', 'mean'),
    'dd_w10': ('dd_w10', 'median'),
    'mfe_w10': ('mfe_w10', 'median'),
    'ret_w10': ('ret_w10', 'median'),
    'contrib_w10': ('contrib_w10', 'median'),
}
MARG = [('k1', 'k2'), ('k2', 'k3+'), ('k1', 'k3+')]
COND_STRATA = ['FR', 'CYCLE_OK', 'OTHER']


def outcome1_of(k1row):
    if k1row.false_add:
        return 'FR'
    if k1row.recovery:
        return 'CYCLE_OK'
    return 'OTHER'


def main():
    an = pd.read_parquet(T8/'01_order_anatomy/t8_1_order_anatomy.parquet')
    contract = __import__('json').loads(
        (T6/'t6_contract.json').read_text())['statistics_prereg']
    B = int(contract['bootstrap_B'])
    SEED = int(contract['bootstrap_seed'])
    rngf = make_rng_factory(SEED, [['t8_2']])

    # outcome1 map (episode level, from frozen ADD1 flags)
    k1 = an[an.k_add == 1]
    o1 = {r.event_id: outcome1_of(r) for r in k1.itertuples()}
    conflicts = int((k1.false_add & k1.recovery).sum())
    an['outcome1'] = an.event_id.map(o1)
    assert an.outcome1.notna().all()

    # primary sample: VAL+CONF pooled; dev/all reference
    prim = an[an.segment.isin(['validation', 'confirmation'])].copy()

    rows = []

    def run(vals, hi_mask, lo_mask, cl_col, metric, label, sample_tag):
        est, ci, p, diag = cluster_boot_diff(
            vals, hi_mask.to_numpy(), lo_mask.to_numpy(),
            cl_col.to_numpy(), METRICS[metric][1],
            rngf('t8_2|' + metric + '|' + label + '|' + sample_tag), B)
        rows.append({'sample': sample_tag, 'contrast': label,
                     'metric': metric, 'cluster': cl_col.name,
                     'est_hi': None if not np.isfinite(est) else float(est),
                     'diff': float(est), 'ci_lo': ci[0], 'ci_hi': ci[1],
                     'p': float(p), 'n_hi': diag['n_hi'], 'n_lo': diag['n_lo']})

    def population(df, tag):
        for cl_name in ('stock_code', 'T0_date'):
            cl = df[cl_name]
            for m in METRICS:
                vals = df[METRICS[m][0]].to_numpy(float)
                fam = {}
                for hi, lo in MARG:
                    label = f'{hi}_vs_{lo}'
                    run(vals, df.k_group == hi, df.k_group == lo, cl, m,
                        label, tag)
                    fam[label] = rows[-1]['p']
                adj = holm(fam)
                for r in rows[-3:]:
                    r['p_holm'] = adj[r['contrast']]
        # conditional: within outcome1 stratum, k2 vs k3+
        for cl_name in ('stock_code', 'T0_date'):
            cl = df[cl_name]
            for m in METRICS:
                vals = df[METRICS[m][0]].to_numpy(float)
                fam = {}
                for s in COND_STRATA:
                    sub = df.outcome1 == s
                    run(vals, sub & (df.k_group == 'k2'),
                        sub & (df.k_group == 'k3+'), cl, m,
                        f'{s}:k2_vs_k3+', tag)
                    fam[f'{s}:k2_vs_k3+'] = rows[-1]['p']
                adj = holm(fam)
                for r in rows[-3:]:
                    r['p_holm'] = adj[r['contrast']]

    population(prim, 'primary_val_conf')
    population(an, 'reference_all')

    inf = pd.DataFrame(rows)

    # descriptive cell table for the report (primary sample)
    def cell(df, key, m):
        g = df.groupby(key)
        def sk(kk):
            return kk if isinstance(kk, str) else '|'.join(map(str, kk))
        return {sk(kk): (int(len(vv)), round(float(vv[METRICS[m][0]].mean()), 4)
                         if METRICS[m][1] == 'mean' else
                         round(float(np.nanmedian(vv[METRICS[m][0]])), 4))
                for kk, vv in g}

    desc = {'primary_by_k': {m: cell(prim, 'k_group', m) for m in METRICS},
            'primary_by_k_outcome1': {m: cell(prim, ['outcome1', 'k_group'], m)
                                      for m in METRICS},
            'outcome1_dist_k1': prim[prim.k_add == 1]
                                .outcome1.value_counts().to_dict()}

    report = {
        'stage': 't8_2',
        'identity': 'preregistered order inference: fixed contrasts '
                    '(marginal k1/k2/k3+ + conditional outcome1 strata '
                    'k2 vs k3+), Estimand B conditional order contrast; '
                    'NO policy, NO additional condition variables',
        'contrasts_marginal': ['k1_vs_k2', 'k2_vs_k3+', 'k1_vs_k3+'],
        'contrasts_conditional': [f'{s}:k2_vs_k3+' for s in COND_STRATA],
        'outcome1_mapping': 'FR > CYCLE_OK > OTHER from frozen ADD1 flags; '
                            f'both-true conflicts={conflicts}',
        'outcome1_conflicts_both_true': conflicts,
        'primary_sample': 'validation+confirmation pooled (frozen t6 '
                          'statistics contract); dev/all reference',
        'stats': {'B': B, 'seed': SEED, 'clusters': ['stock_code', 'T0_date'],
                  'holm_family': 'metric x cluster x family-type '
                                 '(3 marginal contrasts | 3 strata)'},
        'n_tests': int(len(inf)),
        'reading_grid': 'three preregistered outcomes: gradient-gone | '
                        'gradient-persists | strata-diverge',
        'descriptives': desc,
        'inputs': [
            {'name': 't8_1_order_anatomy',
             'path': 'output/research/t8/01_order_anatomy/t8_1_order_anatomy.parquet',
             'sha256': sha256_file(T8/'01_order_anatomy/t8_1_order_anatomy.parquet'),
             'bytes': 0},
            {'name': 't6_contract_statistics',
             'path': 'output/research/t6/t6_contract.json',
             'sha256': sha256_file(T6/'t6_contract.json'), 'bytes': 0},
        ],
    }
    write_stage_outputs(OUT, 't8_2', {'inference': inf},
                        {'inputs': report['inputs']}, report)
    # console digest: primary, stock_code cluster, Holm
    sel = inf[(inf['sample'] == 'primary_val_conf')
              & (inf.cluster == 'stock_code')]
    print(sel[['contrast', 'metric', 'diff', 'ci_lo', 'ci_hi', 'p_holm']]
          .round(4).to_string(index=False))


if __name__ == '__main__':
    main()
