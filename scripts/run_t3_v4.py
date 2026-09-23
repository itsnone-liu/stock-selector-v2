#!/usr/bin/env python3
"""T3 V4 runner: dynamic risk sets + conditional forward paths.

Consumes ONLY the frozen V3 trajectory panel + market calendar.
Writes products, attrition, overlap audit, manifest; then rebuilds every
product from scratch a second time (fresh bootstrap included) and
hash-compares for the determinism gate.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT / 'src'))
from stock_selector.research import t3_v2 as v2          # noqa: E402
from stock_selector.research import t3_v4 as v4          # noqa: E402

OUT = ROOT / 'output/research/t3_v4'
V3OUT = ROOT / 'output/research/t3_v3'
BASELINE = 'aa249cc7e842f64b2c95d2e740036a1215c022b9'

SPEC = {
    'riskset_version': 'dynamic_riskset_v1',
    'forward_version': 'dynamic_forward_v1',
    'bins_version': 'dynamic_bins_v1',
    'contrast_version': 'dynamic_contrast_v1',
    'overlap_audit_version': 'event_overlap_audit_v1',
}


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def frame_hash(df: pd.DataFrame) -> str:
    return hashlib.sha256(
        pd.util.hash_pandas_object(df, index=True).values.tobytes()
    ).hexdigest() if len(df) else hashlib.sha256(b'empty').hexdigest()


def build_all(daily, mdates):
    rs = v4.build_riskset(daily, mdates)
    fwd = v4.build_forward_outcomes(daily, mdates)
    bins = v4.assign_bins(rs)
    att = v4.build_attrition(rs, fwd, bins)
    dist = v4.state_distributions(rs)
    cur = v4.conditional_curves(rs, fwd, bins)
    con = v4.compute_contrasts(rs, fwd, bins)
    con2 = v4.compute_contrasts_2d(rs, fwd, bins)
    ova = v4.overlap_audit(rs, mdates)
    return dict(riskset=rs, forward=fwd, bins=bins, attrition=att,
                dist=dist, curves=cur, contrasts=con, contrasts_2d=con2,
                overlap=ova)


def write_products(prods, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    prods['riskset'].to_parquet(out_dir / 'dynamic_riskset.parquet',
                                index=False, compression='snappy')
    prods['forward'].to_parquet(out_dir / 'dynamic_forward_outcomes.parquet',
                                index=False, compression='snappy')
    prods['bins'].to_parquet(out_dir / 'dynamic_state_bins.parquet',
                             index=False, compression='snappy')
    prods['contrasts'].to_parquet(out_dir / 'dynamic_contrasts.parquet',
                                  index=False, compression='snappy')
    prods['contrasts_2d'].to_parquet(out_dir / 'dynamic_contrasts_2d.parquet',
                                     index=False, compression='snappy')
    prods['curves'].to_parquet(out_dir / 'dynamic_conditional_curves.parquet',
                               index=False, compression='snappy')
    prods['attrition'].to_csv(out_dir / 'dynamic_attrition.csv', index=False)
    prods['dist'].to_csv(out_dir / 'dynamic_state_distributions.csv',
                         index=False)
    (out_dir / 'event_overlap_audit.json').write_text(
        json.dumps(prods['overlap'], ensure_ascii=False, indent=2))


def main():
    t0 = time.time()
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    assert head == BASELINE, f'baseline mismatch: HEAD={head} want {BASELINE}'
    OUT.mkdir(parents=True, exist_ok=True)
    daily = pd.read_parquet(V3OUT / 'event_path_daily.parquet',
                            columns=v4._V3_COLS)
    mdates, _ = v2.market_calendar_and_close()
    print(f'[v4] loaded V3 daily {len(daily)} rows, calendar '
          f'{mdates[0]}..{mdates[-1]}, dataset_end={v2.DATASET_END}',
          flush=True)
    prods = build_all(daily, mdates)
    write_products(prods, OUT)
    print(f'[v4] first build done {time.time()-t0:.0f}s', flush=True)

    # ---- determinism: full rebuild from same inputs, byte-level compare
    prods2 = build_all(daily, mdates)
    det = {}
    for key in ('riskset', 'forward', 'bins', 'attrition', 'dist', 'curves',
                'contrasts', 'contrasts_2d'):
        a, b = prods[key], prods2[key]
        same = (frame_hash(a) == frame_hash(b))
        det[key] = {'identical': bool(same),
                    'rows': int(len(a)), 'rows_rerun': int(len(b))}
    det['overlap'] = {'identical':
                      json.dumps(prods['overlap'], sort_keys=True)
                      == json.dumps(prods2['overlap'], sort_keys=True)}
    det_json = {'gate': 'V4_DETERMINISM',
                'method': 'full in-process rebuild (bootstrap re-run) + '
                          'pandas content hash compare',
                'products_compared': len(det),
                'identical': all(x['identical'] for x in det.values()),
                'detail': det,
                'verdict': 'PASS' if all(x['identical']
                                         for x in det.values()) else 'FAIL'}
    (OUT / 'dynamic_determinism_check.json').write_text(
        json.dumps(det_json, ensure_ascii=False, indent=2))
    print(json.dumps({k: det_json[k] for k in
                      ('products_compared', 'identical', 'verdict')}), flush=True)

    rs, fwd = prods['riskset'], prods['forward']
    manifest = {
        'task': 'T3_V4_dynamic_riskset',
        'baseline_commit': head,
        'v3_products_consumed': {
            'event_path_daily.parquet': {
                'sha256': sha(V3OUT / 'event_path_daily.parquet'),
                'frozen_in': 'aa249cc'}},
        'dataset_end': v2.DATASET_END,
        'spec': SPEC,
        'events': int(rs['breakout_event_id'].nunique()),
        'riskset_rows': int(len(rs)),
        'forward_rows': int(len(fwd)),
        'riskset_taus': list(v4.RISKSET_TAUS),
        'deltas': list(v4.DELTAS),
        'boot': {'B': v4.BOOT_B, 'seed': v4.BOOT_SEED,
                 'clusterings': ['code6', 'asof_date'],
                 'ci': 'percentile 95', 'min_cell_n': v4.MIN_CELL_N,
                 'holm_family': 'metric(median excess Q4-Q1 diff) x tau x delta '
                                'across 11 quartile state vars'},
        'units_schema_gate': {
            'turn_source': 'baostock field turn, percentage points '
                           '(0.6946 == 0.6946%)',
            'cum_turnover_since_t0': 'percentage-point days summed',
            'mean_turnover_since_t0': 'percentage points per valid turnover day',
            'turnover_ratio_pre20': 'dimensionless',
            'verification': 'amount/turn implies float share count consistent '
                            'with listed share capital (sz.000008 spot check)'},
        'state_vars': {v: v4.STATE_UNITS[v]
                       for v in v4.CONT_VARS + v4.STATE_FLAG},
        'products': {},
        'elapsed_sec': round(time.time() - t0, 2),
    }
    for name in ('dynamic_riskset', 'dynamic_forward_outcomes',
                 'dynamic_state_bins', 'dynamic_contrasts',
                 'dynamic_contrasts_2d', 'dynamic_conditional_curves'):
        p = OUT / f'{name}.parquet'
        manifest['products'][name] = {'sha256': sha(p)}
    for name in ('dynamic_attrition.csv', 'dynamic_state_distributions.csv',
                 'event_overlap_audit.json'):
        manifest['products'][name] = {'sha256': sha(OUT / name)}
    (OUT / 'dynamic_run_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({'events': manifest['events'],
                      'riskset_rows': manifest['riskset_rows'],
                      'forward_rows': manifest['forward_rows'],
                      'elapsed_sec': manifest['elapsed_sec']},
                 ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
