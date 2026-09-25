#!/usr/bin/env python3
"""T7.2 gates — DEV-only identity, frozen candidate space, exposure
completeness, lineage. Discovery is allowed, proof is not: nothing in this
stage's products may touch VAL/CONF rows."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, sha256_file  # noqa: E402
from t6 import gate_framework as gf  # noqa: E402

T7 = T6.parent/'t7'
IN = T7/'00_path_factlayer'
OUT = T7/'02_separator_discovery'
FEATS = ('max_bounce_R5', 'vol_load@maxbounce_R5', 'turnover@maxbounce_R5')


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t7_2_manifest.json').read_text())
    rep = json.loads((OUT/'t7_2_report_data.json').read_text())
    disc = pd.read_parquet(OUT/'t7_2_discovery.parquet')
    cells = pd.read_parquet(OUT/'t7_2_cells.parquet')
    bins = json.loads((OUT/'t7_2_bins.json').read_text())

    gf.g1_lineage(log, man, OUT)

    # G2b: frozen T7.0 products unchanged
    ok = True
    n_prod = 0
    for mf in ('t7_0_features_manifest.json', 't7_0_outcomes_manifest.json'):
        for pr in json.loads((IN/mf).read_text())['products']:
            n_prod += 1
            if sha256_file(IN/pr['file']) != pr['sha256']:
                ok = False
    log.gate('G2b_t7_0_immutable', ok, products_verified=n_prod)

    # G22 DEV-only identity
    src = (ROOT/'scripts/run_t7_2.py').read_text()
    ok22 = ("dev = df[df.segment == 'development']" in src
            and len(disc) == 12 and len(cells) == 27
            and all(r.n_hi + r.n_lo <= rep['n_dev_anchors']
                    for r in disc.itertuples())
            and rep['n_dev_anchors'] == 3764
            and 'DEV-ONLY DISCOVERY' in rep['identity'])
    log.gate('G22_dev_only', ok22, dev_anchors=rep['n_dev_anchors'])

    # G23 frozen candidate space + DEV-tertile bins replay
    feat_cols = set(pd.read_parquet(
        IN/'t7_0_features_anchor_features.parquet').columns)
    ok23 = all(f in feat_cols for f in FEATS) and set(disc.feature) <= set(FEATS)
    dev = pd.read_parquet(IN/'t7_0_features_anchor_features.parquet',
                          columns=['segment'] + list(FEATS))
    dev = dev[dev.segment == 'development']
    for f in FEATS:
        q1, q2 = np.nanquantile(dev[f].to_numpy(float), [1/3, 2/3])
        if abs(q1 - bins[f]['q1']) > 1e-12 or abs(q2 - bins[f]['q2']) > 1e-12:
            ok23 = False
    log.gate('G23_frozen_space_bins', ok23)

    # G24 exposure completeness + mechanical candidate replay
    pairs = {(e['target'], e['feature']) for e in rep['exposure_log']}
    ok24 = (len(rep['exposure_log']) == 6 and pairs ==
            {(t, f) for t in ('FR_within_recovered', 'TR_all') for f in FEATS})
    for c in rep['mechanical_candidates']:
        g = disc[(disc.target == 'FR_within_recovered') & (disc.feature == c['feature'])]
        replay = bool(len(g) == 2 and all(g.ci_excludes_zero) and all(g.reject))
        if replay != c['passes_both_clusters']:
            ok24 = False
    log.gate('G24_exposure_and_mechanical_rule', ok24,
             exposure_entries=len(rep['exposure_log']))

    sys.exit(log.finish(OUT/'t7_2_gates.json'))


if __name__ == '__main__':
    main()
