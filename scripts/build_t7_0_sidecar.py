#!/usr/bin/env python3
"""T7.0 Step 2c — sector QUASI-PIT sidecar (EXPLORATORY ONLY).

Aggregates per-stock daily (baostock hfq close / turn) into 84 CSRC
industry daily panels: sector_breadth (share of members up),
sector_ret_20d (equal-weight 20d cumulative log return),
sector_turnover (mean turn). MEMBERSHIP = 2026-09-21 backfill snapshot
=> QUASI-PIT: survivorship/reclassification bias, EXPLORATORY ONLY,
forbidden in C/D policy families and any primary claim.
"""
from __future__ import annotations
import gzip
import json
import sys
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import sha256_file  # noqa: E402

T7 = ROOT/'output/research/t7'
OUT = T7/'00_path_factlayer'
PER = ROOT/'data/adjustment_baostock/per_stock'


def main():
    members = {}
    for date, code, _name, ind, _src in json.loads(
            (ROOT/'data/t4/sector_map/csrc_industry_snapshot.json').read_text()):
        members.setdefault(code, ind)
    industries = sorted(set(members.values()))

    # accumulate per (industry, date): n, n_up, sum_logret, sum_turn
    agg = defaultdict(lambda: [0, 0, 0.0, 0.0])
    n_files = 0
    for fp in sorted(PER.glob('*.json.gz')):
        code = fp.name.removesuffix('.json.gz')
        ind = members.get(code)
        if ind is None:
            continue
        with gzip.open(fp, 'rt') as f:
            d = json.load(f)
        rows = d.get('hfq') or d.get('unadj')
        if not rows:
            continue
        n_files += 1
        prev = None
        for r in rows:
            date, close, turn = r[0], float(r[4]), float(r[7]) if r[7] not in (None, '') else np.nan
            key = (ind, date)
            a = agg[key]
            a[0] += 1
            if prev is not None and np.isfinite(close) and np.isfinite(prev) and prev > 0:
                lr = np.log(close / prev)
                a[2] += lr
                if lr > 0:
                    a[1] += 1
            if np.isfinite(turn):
                a[3] += turn
            prev = close

    recs = [{'industry': k[0], 'date': k[1], 'n_members': v[0],
             'sector_breadth': v[1] / max(1, v[0]),
             'sector_ret_1d': v[2] / max(1, v[0]),
             'sector_turnover': v[3] / max(1, v[0])}
            for k, v in agg.items()]
    df = pd.DataFrame(recs).sort_values(['industry', 'date']).reset_index(drop=True)
    df['sector_ret_20d'] = (df.groupby('industry', sort=False)
                              .sector_ret_1d.rolling(20).sum().reset_index(level=0, drop=True))
    df.to_parquet(OUT/'t7_0_sector_sidecar.parquet', index=False)
    meta = {
        'kind': 'sector_quasi_pit_sidecar',
        'exploratory_only': True,
        'membership_source': 'data/t4/sector_map/csrc_industry_snapshot.json (as-of 2026-09-21, NON-PIT backfill)',
        'price_source': 'data/adjustment_baostock/per_stock (hfq close, turn)',
        'n_files_used': n_files, 'n_industries': df.industry.nunique(),
        'n_rows': int(len(df)),
        'forbidden_in': ['C policy family', 'D policy family', 'any primary claim'],
        'sha256_sidecar': sha256_file(OUT/'t7_0_sector_sidecar.parquet'),
    }
    (OUT/'t7_0_sector_sidecar_meta.json').write_text(
        json.dumps(meta, ensure_ascii=False, indent=2))
    print('sidecar rows:', len(df), 'industries:', df.industry.nunique(),
          'files:', n_files)


if __name__ == '__main__':
    main()
