#!/usr/bin/env python3
"""T7.2 — DEV-only separator discovery.

Identity change (contract segment_protocol.t7_2): DISCOVERY is now allowed,
PROOF is not. Candidates may be found on DEV only; nothing here validates
anything on VAL/CONF. The frozen candidate space (no additions): the
same-clock hot-bounce triple {max_bounce_R5, vol_load@maxbounce_R5,
turnover@maxbounce_R5}, tertile-binned on DEV, plus the 27-cell cross.

Discovery contrasts (preregistered, exhaustive — exposure log records every
combination run, no unreported peeking):
  family FR  : within RECOVERED_ADD, FR vs clean, hi-tertile vs lo-tertile
  family TR  : all anchors, TR vs no_TR, hi-tertile vs lo-tertile
Holm within each family; dual cluster units (stock_code / T0_date) reported
as two independent CI families. 27-cell table is DESCRIPTIVE (rate + level
CI), no per-cell tests. Candidate list is MECHANICAL (rule below), the
human choice happens later at Policy Amendment Freeze.
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
from t6.stats import (cluster_boot_level, cluster_boot_diff,  # noqa: E402
                      holm, make_rng_factory)

T7 = T6.parent/'t7'
IN = T7/'00_path_factlayer'
OUT = T7/'02_separator_discovery'
FEATS = ('max_bounce_R5', 'vol_load@maxbounce_R5', 'turnover@maxbounce_R5')


def main():
    pre = load_contract()['statistics_prereg']
    B, SEED = pre['bootstrap_B'], pre['bootstrap_seed']

    feat = pd.read_parquet(IN/'t7_0_features_anchor_features.parquet')
    feat = feat.drop(columns=[c for c in ('segment', 'E_class') if c in feat.columns])
    out = pd.read_parquet(IN/'t7_0_outcomes_outcomes.parquet',
                          columns=['event_id', 'r0_day', 'segment', 'type',
                                   'false_recovery', 'true_recovery'])
    df = feat.merge(out, on=['event_id', 'r0_day'], how='inner')
    # HARD DEV FILTER — the segment identity of this stage
    dev = df[df.segment == 'development'].copy()
    dev['stock_code'] = dev.event_id.str.split('_').str[0]
    dev['T0_date'] = dev.event_id.str.split('_').str[1]
    assert len(dev) == 3764

    # frozen bins: DEV tertiles of each feature (boundary values recorded)
    bins = {}
    for f in FEATS:
        q1, q2 = np.nanquantile(dev[f].to_numpy(float), [1/3, 2/3])
        bins[f] = {'q1': float(q1), 'q2': float(q2)}
        dev[f + '_bin'] = np.where(dev[f] <= q1, 'lo',
                                   np.where(dev[f] <= q2, 'mid', 'hi'))

    targets = {
        'FR_within_recovered': (
            (dev.type == 'RECOVERED_ADD').to_numpy(),
            dev.false_recovery.to_numpy(bool)),
        'TR_all': (
            np.ones(len(dev), bool),
            dev.true_recovery.to_numpy(bool)),
    }

    enums = [list(FEATS), sorted(targets), ['stock', 't0date'], ['diff', 'level']]
    rng = make_rng_factory(SEED + 72, enums)

    recs, exposure = [], []
    for tname, (basemask, lbl) in targets.items():
        for f in FEATS:
            m = basemask & np.isfinite(dev[f].to_numpy(float))
            hi = m & (dev[f + '_bin'].to_numpy() == 'hi')
            lo = m & (dev[f + '_bin'].to_numpy() == 'lo')
            exposure.append({'target': tname, 'feature': f,
                             'n_base': int(m.sum()),
                             'n_hi': int(hi.sum()), 'n_lo': int(lo.sum()),
                             'rate_hi': float(lbl[hi].mean()),
                             'rate_lo': float(lbl[lo].mean())})
            for cl_name, cl_col in (('stock', 'stock_code'), ('t0date', 'T0_date')):
                clusters = dev[cl_col].to_numpy()
                est, ci, pv, dg = cluster_boot_diff(
                    lbl.astype(float), hi, lo, clusters, 'mean',
                    rng(f, tname, cl_name, 'diff'), B)
                recs.append({'target': tname, 'feature': f, 'cluster': cl_name,
                             'contrast': 'hi_vs_lo_tertile', 'est': float(est),
                             'ci95': [float(ci[0]), float(ci[1])],
                             'p_boot': float(pv),
                             'n_hi': dg['n_hi'], 'n_lo': dg['n_lo']})
    disc = pd.DataFrame(recs)

    # Holm within (target, cluster) family using the frozen bootstrap p
    holm_rows = []
    for (tname, cl), g in disc.groupby(['target', 'cluster']):
        pvals = {r.feature: float(r.p_boot) for _, r in g.iterrows()
                 if np.isfinite(r.p_boot)}
        adj = holm(pvals)
        for _, r in g.iterrows():
            pj = float(adj.get(r.feature, float('nan')))
            holm_rows.append({'target': tname, 'cluster': cl, 'feature': r.feature,
                              'p_adj': pj, 'reject': bool(np.isfinite(pj) and pj <= 0.05),
                              'ci_excludes_zero': bool(not (r.ci95[0] <= 0 <= r.ci95[1]))})
    holmdf = pd.DataFrame(holm_rows)
    disc = disc.merge(holmdf, on=['target', 'cluster', 'feature'], how='left')

    # 27-cell descriptive table (rate + dual level CI, no tests)
    cell_recs = []
    for b in ('lo', 'mid', 'hi'):
        for v in ('lo', 'mid', 'hi'):
            for t in ('lo', 'mid', 'hi'):
                m = ((dev[FEATS[0] + '_bin'] == b) & (dev[FEATS[1] + '_bin'] == v)
                     & (dev[FEATS[2] + '_bin'] == t)).to_numpy()
                n = int(m.sum())
                row = {'bounce_bin': b, 'vol_bin': v, 'turnover_bin': t, 'n': n}
                for tname, (basemask, lbl) in targets.items():
                    mm = m & basemask
                    ok = mm
                    rate = float(lbl[mm].mean()) if mm.sum() else np.nan
                    row[f'{tname}_rate'] = rate
                    if mm.sum() >= 10:
                        for cl_name, cl_col in (('stock', 'stock_code'),
                                                ('t0date', 'T0_date')):
                            _, ci = cluster_boot_level(
                                lbl.astype(float), mm, dev[cl_col].to_numpy(),
                                'mean', rng(b + v + t, tname, cl_name, 'level'), B)
                            row[f'{tname}_ci95_{cl_name}'] = [float(ci[0]), float(ci[1])]
                cell_recs.append(row)
    cells = pd.DataFrame(cell_recs)

    # MECHANICAL candidate list (no human choice here): structures whose
    # FR-within-recovered hi-vs-lo CI excludes 0 on BOTH cluster units
    cands = []
    for f in FEATS:
        g = disc[(disc.target == 'FR_within_recovered') & (disc.feature == f)]
        both = all(g.ci_excludes_zero) and all(g.reject)
        cands.append({'feature': f, 'passes_both_clusters': bool(both)})
    report = {
        'stage': 't7_2',
        'identity': 'DEV-ONLY DISCOVERY — candidates may be found, nothing is '
                    'proven; no VAL/CONF computation; candidate space frozen '
                    '(same-clock hot-bounce triple + 27-cell cross); human '
                    'selection deferred to Policy Amendment Freeze',
        'n_dev_anchors': int(len(dev)),
        'bins_dev_tertiles': bins,
        'families': {'FR_within_recovered': 'hi vs lo tertile, Holm per cluster',
                     'TR_all': 'hi vs lo tertile, Holm per cluster'},
        'discovery_contrasts': int(len(disc)),
        'exposure_log': exposure,
        'mechanical_candidates': cands,
        'mechanical_rule': 'FR_within_recovered hi-vs-lo CI excludes 0 AND Holm '
                           'reject, on BOTH stock and t0date cluster units',
        'contract_sha256': sha256_file(T7/'t7_contract.json'),
    }
    write_stage_outputs(
        OUT, 't7_2', {'discovery': disc, 'cells': cells},
        {'inputs': [
            {'name': 't7_0_anchor_features', 'path': 'output/research/t7/00_path_factlayer/t7_0_features_anchor_features.parquet',
             'sha256': sha256_file(IN/'t7_0_features_anchor_features.parquet'), 'bytes': 0},
            {'name': 't7_0_outcomes', 'path': 'output/research/t7/00_path_factlayer/t7_0_outcomes_outcomes.parquet',
             'sha256': sha256_file(IN/'t7_0_outcomes_outcomes.parquet'), 'bytes': 0},
            {'name': 't7_contract', 'path': 'output/research/t7/t7_contract.json',
             'sha256': sha256_file(T7/'t7_contract.json'), 'bytes': 0}]},
        report)
    (OUT/'t7_2_bins.json').write_text(json.dumps(bins, indent=2))
    print('discovery rows:', len(disc), 'cells:', len(cells))
    print(disc[['target', 'feature', 'cluster', 'est', 'ci95', 'reject']]
          .to_string(index=False))


if __name__ == '__main__':
    main()
