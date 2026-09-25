#!/usr/bin/env python3
"""T8.2 gates — G45 fixed contrasts / G46 primary sample / G47 Holm replay."""
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
from t6.stats import holm  # noqa: E402

T8 = T6.parent/'t8'
OUT = T8/'02_order_inference'


def main():
    log = gf.GateLog()
    man = json.loads((OUT/'t8_2_manifest.json').read_text())
    rep = json.loads((OUT/'t8_2_report_data.json').read_text())
    inf = pd.read_parquet(OUT/'t8_2_inference.parquet')
    an = pd.read_parquet(T8/'01_order_anatomy/t8_1_order_anatomy.parquet')

    gf.g1_lineage(log, man, OUT)

    # G45: exactly the preregistered contrast set, no additions, no extra
    # condition variables (only outcome1 strata), no policy words
    want_m = {'k1_vs_k2', 'k2_vs_k3+', 'k1_vs_k3+'}
    want_c = {'FR:k2_vs_k3+', 'CYCLE_OK:k2_vs_k3+', 'OTHER:k2_vs_k3+'}
    prim = inf[inf['sample'] == 'primary_val_conf']
    got = set(prim.contrast.unique())
    ok45 = (got == (want_m | want_c)
            and set(prim.metric.unique()) ==
            {'false_add_rate', 'recovery_rate', 'dd_w10', 'mfe_w10',
             'ret_w10', 'contrib_w10'}
            and not any(('mae' in c or 'depth' in c or 'stratif' in c)
                        for c in got)
            and not any('rule|policy|stop' in json.dumps(rep).lower()
                        for _ in [0]))
    log.gate('G45_preregistered_contrasts', ok45,
             contrasts=sorted(got), n_tests=int(len(inf)))

    # G46: primary sample sizes reconcile with anatomy VAL+CONF counts
    vc = an[an.segment.isin(['validation', 'confirmation'])]
    exp = {'k1': int((vc.k_group == 'k1').sum()),
           'k2': int((vc.k_group == 'k2').sum()),
           'k3+': int((vc.k_group == 'k3+').sum())}
    nrec = {}
    for c in want_m | want_c:
        r = prim[(prim.contrast == c) & (prim.cluster == 'stock_code')
                 & (prim.metric == 'recovery_rate')].iloc[0]
        nrec[c] = (int(r.n_hi), int(r.n_lo))
    ok46 = (nrec['k1_vs_k2'] == (exp['k1'], exp['k2'])
            and nrec['k2_vs_k3+'] == (exp['k2'], exp['k3+'])
            and nrec['k1_vs_k3+'] == (exp['k1'], exp['k3+'])
            and nrec['FR:k2_vs_k3+'][0] + nrec['CYCLE_OK:k2_vs_k3+'][0]
            + nrec['OTHER:k2_vs_k3+'][0] == exp['k2']
            and nrec['FR:k2_vs_k3+'][1] + nrec['CYCLE_OK:k2_vs_k3+'][1]
            + nrec['OTHER:k2_vs_k3+'][1] == exp['k3+'])
    log.gate('G46_primary_sample_reconcile', ok46, expected_k=exp,
             strata_partition=bool(ok46))

    # G47: Holm replay — recompute adj from on-disk p within each family
    mism = 0
    fams = 0
    def famkey(c):
        return 'marginal' if ':' not in c else 'cond'
    for (samp, cl, met), g in inf.groupby(['sample', 'cluster', 'metric']):
        for fk in ('marginal', 'cond'):
            sub = g[g.contrast.map(famkey) == fk]
            if not len(sub):
                continue
            fams += 1
            adj = holm({r.contrast: r.p for r in sub.itertuples()})
            for r in sub.itertuples():
                if np.isfinite(r.p_holm) and np.isfinite(adj[r.contrast]):
                    if abs(r.p_holm - adj[r.contrast]) > 1e-12:
                        mism += 1
                elif np.isfinite(r.p_holm) != np.isfinite(adj[r.contrast]):
                    mism += 1
    # stats params match frozen contract
    contract = json.loads((T6/'t6_contract.json').read_text())
    sp = contract['statistics_prereg']
    ok47 = (mism == 0 and rep['stats']['B'] == sp['bootstrap_B']
            and rep['stats']['seed'] == sp['bootstrap_seed']
            and rep['stats']['clusters'] == sp['cluster_units'])
    log.gate('G47_holm_family_replay', ok47, families=fams, mismatches=mism)

    sys.exit(log.finish(OUT/'t8_2_gates.json'))


if __name__ == '__main__':
    main()
