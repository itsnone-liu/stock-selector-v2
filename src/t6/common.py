"""T6 common fact layer — Episode Master & Daily Master builders.

Read-only consumers of frozen T3-T5 products (baseline 80e934c). Every
threshold/window used anywhere in T6 resolves from output/research/t6/
t6_contract.json (G6). The Daily Master is the PIT fact layer: it NEVER
joins t5_daily_outcome (fwd_*) — path statistics present here (cum_ret,
drawdown, days_since_peak, ...) are computed from the T0-prefix up to the
current day, i.e. known at close of that day.

Execution reference columns (_ref suffix) come from the
direct_chase | P2_balanced cell of T5.8R-2; resolution_state is
policy-invariant (verified in T5.8R R6).
"""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
T4 = ROOT/'output/research/t4/entry_policy'
T5F = ROOT/'output/research/t5/facts'
T5S = ROOT/'output/research/t5/state'
T5T = ROOT/'output/research/t5/transition'
T57 = ROOT/'output/research/t5/exposure_adjustment'
T58 = ROOT/'output/research/t5/full_lifecycle'
T6 = ROOT/'output/research/t6'

# Upstream products every T6 gate must verify immutable (G2). Hashes are
# recorded at T6.0 freeze time by record_upstream_hashes() and stored in the
# T6.0 manifest; later gates re-verify against this frozen list.
UPSTREAM_PRODUCTS = [
    T4/'t4_6_assignment.parquet',
    T5F/'t5_daily_state.parquet',
    T5F/'t5_daily_outcome.parquet',
    T5S/'t5_candidate_state_daily.parquet',
    T5T/'t5_operational_state_daily_v2.parquet',
    T57/'t5_7_exposure_trajectory.parquet',
    T58/'t5_8_episode_results.parquet',
    T58/'t5_8_daily_exposure_pnl.parquet',
    T58/'t5_8_counterfactual_attribution.parquet',
    T58/'t5_8_strategy_matrix.parquet',
    T58/'t5_8_manifest.json',
]

REF_STRATEGY = 'direct_chase'
REF_POLICY = 'P2_balanced'


def load_contract() -> dict:
    return json.loads((T6/'t6_contract.json').read_text())


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_frame_hash(df: pd.DataFrame) -> str:
    """Determinism-friendly hash: canonical column order, sorted rows, typed."""
    d = df[sorted(df.columns)].copy()
    for c in d.columns:
        if d[c].dtype == object:
            d[c] = d[c].astype(str)
    d = d.sort_values(by=sorted(d.columns), kind='mergesort').reset_index(drop=True)
    return hashlib.sha256(pd.util.hash_pandas_object(d, index=False).values.tobytes()).hexdigest()


def build_episode_master() -> pd.DataFrame:
    """One row per lifecycle execution cell (event x strategy x policy),
    plus the T4 entry facts joined on (event ~ code|signal_day)."""
    ep = pd.read_parquet(T58/'t5_8_episode_results.parquet')
    a = pd.read_parquet(T4/'t4_6_assignment.parquet',
                        columns=['code', 'signal_day', 'lifecycle_id', 'strategy', 'E_class',
                                 'participation_policy', 'initial_exposure_weight',
                                 'fill_status_close'])
    st0 = pd.read_parquet(T5F/'t5_daily_state.parquet',
                          columns=['event_id', 'code', 'breakout_day', 'delta_day',
                                   'termination_reason'])
    t0 = st0[st0.delta_day == 0][['event_id', 'code', 'breakout_day']].copy()
    t0['lifecycle_days'] = st0.groupby('event_id')['delta_day'].transform('max') + 1
    op = pd.read_parquet(T57/'t5_7_exposure_trajectory.parquet',
                         columns=['lifecycle_id', 'date_delta', 'resolution_state', 'segment'])
    # policy-invariance verified (T5.8R R6); collapse verified copy
    nun = op.groupby(['lifecycle_id', 'date_delta'])['resolution_state'].nunique()
    assert (nun <= 1).all(), 'policy disagreement in frozen T5.7'
    op = op.drop_duplicates(['lifecycle_id', 'date_delta'])
    g = op.sort_values('date_delta').groupby('lifecycle_id').agg(
        initial_state=('resolution_state', 'first'), seg7=('segment', 'first'))

    a['k'] = a.code.astype(str) + '|' + a.signal_day.astype(str)
    t0['k'] = t0.code.astype(str) + '|' + t0.breakout_day.astype(str)
    j = t0.merge(a, on='k', how='inner')
    # trajectory lifecycle_id is `code_T0` == T5 event_id (NOT the T4.6 hash id)
    j = j.merge(g, left_on='event_id', how='left', right_index=True)

    m = ep.merge(j[['event_id', 'strategy', 'E_class', 'participation_policy',
                    'initial_exposure_weight', 'fill_status_close', 'lifecycle_id',
                    'initial_state', 'lifecycle_days', 'seg7']],
                 on=['event_id', 'strategy'], how='left')
    assert m.E_class.notna().all(), 'episode master lost E_class join'
    # 20 events carry no T5.7 trajectory rows at all (empty-state lifecycles):
    # backfill segment from trajectory groups, else from the T5 state file.
    m['segment'] = m.segment.fillna(m.seg7)
    cs_seg = pd.read_parquet(T5S/'t5_candidate_state_daily.parquet',
                             columns=['event_id', 'segment']).groupby('event_id')['segment'].first()
    m['segment'] = m.segment.fillna(m.event_id.map(cs_seg))
    m = m.drop(columns=['seg7'])
    return m.rename(columns={
        'initial_exposure_weight': 'base_exposure', 'ret_ep_log': 'ret_norm_ep'})


def build_daily_master() -> pd.DataFrame:
    """One row per (event, delta_day): PIT primitives + states + policy-
    invariant resolution + reference execution columns (_ref). NEVER joins
    t5_daily_outcome."""
    ds = pd.read_parquet(T5F/'t5_daily_state.parquet')
    cs = pd.read_parquet(T5S/'t5_candidate_state_daily.parquet',
                         columns=['event_id', 'delta_day', 'final_candidate_state', 'segment'])
    osv = pd.read_parquet(T5T/'t5_operational_state_daily_v2.parquet',
                          columns=['event_id', 'delta_day', 'operational_state_v2'])
    tr = pd.read_parquet(T57/'t5_7_exposure_trajectory.parquet',
                         columns=['lifecycle_id', 'date_delta', 'resolution_state', 'segment'])
    nun = tr.groupby(['lifecycle_id', 'date_delta'])['resolution_state'].nunique()
    assert (nun <= 1).all(), 'policy disagreement in frozen T5.7'
    tr = tr.drop_duplicates(['lifecycle_id', 'date_delta']).rename(
        columns={'lifecycle_id': 'event_id', 'date_delta': 'delta_day'})

    d = ds.merge(cs, on=['event_id', 'delta_day'], how='left')
    d = d.merge(osv, on=['event_id', 'delta_day'], how='left')
    d = d.merge(tr[['event_id', 'delta_day', 'resolution_state']],
                on=['event_id', 'delta_day'], how='left')
    # segment comes from cs (state file); events with no trajectory rows keep it
    d = d.rename(columns={'final_candidate_state': 'raw_state',
                          'operational_state_v2': 'operational_state',
                          'dist_to_ref20': 'dist_ref20', 'dist_to_ref60': 'dist_ref60'})

    # Reference execution columns from the frozen T5.8R-2 daily table
    dd = pd.read_parquet(T58/'t5_8_daily_exposure_pnl.parquet',
                         columns=['event_id', 'strategy', 'policy_id', 'delta_day',
                                  'exposure_prev', 'exposure_after', 'pnl_log',
                                  'effective_status'])
    dd = dd[(dd.strategy == REF_STRATEGY) & (dd.policy_id == REF_POLICY)]
    dd = dd.rename(columns={'exposure_prev': 'exposure_prev_ref', 'exposure_after': 'exposure_after_ref',
                            'pnl_log': 'pnl_ref', 'effective_status': 'effective_status_ref'})
    d = d.merge(dd[['event_id', 'delta_day', 'exposure_prev_ref', 'exposure_after_ref',
                    'pnl_ref', 'effective_status_ref']], on=['event_id', 'delta_day'], how='left')

    banned = [c for c in d.columns if c.startswith(('fwd_', 'future_', 'outcome_'))]
    assert not banned, f'PIT violation: {banned}'
    return d


def write_stage_outputs(out_dir: Path, stage: str, parquets: dict, extra_manifest: dict,
                        report_data: dict) -> dict:
    """Uniform stage writer: parquets + manifest + report_data; returns manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    products = []
    for name, df in parquets.items():
        p = out_dir/f'{stage}_{name}.parquet'
        df.to_parquet(p, index=False)
        products.append({'file': p.name, 'sha256': sha256_file(p), 'bytes': p.stat().st_size,
                         'rows': int(len(df))})
    (out_dir/f'{stage}_report_data.json').write_text(
        json.dumps(report_data, indent=2, ensure_ascii=False))
    products.append({'file': f'{stage}_report_data.json',
                     'sha256': sha256_file(out_dir/f'{stage}_report_data.json'),
                     'bytes': (out_dir/f'{stage}_report_data.json').stat().st_size})
    man = {'stage': stage, 'baseline': '80e934c',
           'inputs': extra_manifest.get('inputs', []),
           'upstream_hashes': extra_manifest.get('upstream_hashes'),
           'products': products}
    (out_dir/f'{stage}_manifest.json').write_text(json.dumps(man, indent=2, ensure_ascii=False))
    return man
