#!/usr/bin/env python3
"""T5.6A Eligibility Conflict Census.

Read-only over T5.5 products (frozen at aac1f9f). Purely descriptive: the 16
ADD/HOLD/REDUCE/EXIT boolean vectors are censused by frequency, coverage,
split, source level, reliability, backoff, sparse evidence and destination
type. No resolution of any kind is performed here.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
SRC = ROOT / 'output/research/t5/action_eligibility'
TR = ROOT / 'output/research/t5/transition'
OUT = ROOT / 'output/research/t5/action_resolution'; OUT.mkdir(parents=True, exist_ok=True)
FLAGS = ['ADD_ELIGIBLE', 'HOLD_ELIGIBLE', 'REDUCE_ELIGIBLE', 'EXIT_ELIGIBLE']


def vec_code(row):
    return ''.join('1' if bool(row[f]) else '0' for f in FLAGS)


def main():
    a = pd.read_parquet(SRC / 't5_action_eligibility.parquet')
    e = pd.read_parquet(SRC / 't5_action_evidence.parquet')
    h = pd.read_parquet(SRC / 't5_hierarchy_increment.parquet')
    d = a.merge(
        e[['segment', 'source_level', 'source_key', 'source_state',
           'reliability_class', 'sparse_evidence', 'coverage',
           'censor_missing_rate']],
        on=['segment', 'source_level', 'source_key'], how='left',
        suffixes=('', '_ev'))
    d = d.merge(
        h[['segment', 'source_level', 'source_key',
           'hierarchy_selected', 'backoff_reason']],
        on=['segment', 'source_level', 'source_key'], how='left')
    # destination type for transition-level rows (OBS_UNAVAILABLE/TERMINAL
    # are not ordinary C-states; census must not silently blend them).
    tr = pd.read_parquet(TR / 't5_transition_edges.parquet',
                         columns=['event_id', 'delta_day', 'horizon_k',
                                  'dest_type'])
    # T5.5 rows are aggregates, not per-day edges; per-day OBS/TERMINAL
    # association is reported at the source-key level instead.
    d['dest_kind'] = np.where(
        d.source_key.str.contains('STATE_UNAVAILABLE', na=False),
        'obs_unavailable',
        np.where(d.source_key.str.startswith('STATE_UNAVAILABLE'),
                 'obs_unavailable',
                 np.where(d.source_key.str.contains('TERMINAL', na=False),
                          'terminal', 'c_state')))
    d['vector'] = d.apply(vec_code, axis=1)
    d['n_labels'] = d[FLAGS].sum(axis=1).astype(int)
    d['label_class'] = np.select(
        [d.n_labels == 0, d.n_labels == 1, d.n_labels >= 2],
        ['none', 'single', 'multi'], default='multi').astype(str)

    # ---- main census: 16 vectors ----
    rows = []
    for v, g in d.groupby('vector'):
        add, hold, red, ext = (int(c) for c in v)
        rows.append({
            'vector': v, 'ADD': add, 'HOLD': hold, 'REDUCE': red,
            'EXIT': ext, 'n_labels': add + hold + red + ext,
            'label_class': ('none' if add + hold + red + ext == 0
                            else 'single' if add + hold + red + ext == 1
                            else 'multi'),
            'n_rows': len(g),
            'share': len(g) / len(d),
            'weighted_rows': float(g.n_rows.sum()),
            'weighted_share': float(g.n_rows.sum() / d.n_rows.sum()),
            'mean_coverage': float(np.average(g.coverage, weights=g.n_rows)),
            'mean_support': float(np.average(g.support if 'support' in g
                                             else g.n_rows, weights=g.n_rows)),
            'mean_events': float(np.average(g.n_events, weights=g.n_rows)),
            'sparse_rate': float((g.sparse_evidence == True).mean()
                                 if g.sparse_evidence.notna().any() else np.nan),
            'low_reliability_rate': float(
                (g.reliability_class == 'low').mean()),
            'high_reliability_rate': float(
                (g.reliability_class == 'high').mean()),
            'n_source_keys': g.source_key.nunique(),
        })
    cen = pd.DataFrame(rows).sort_values('n_rows', ascending=False)
    cen.to_parquet(OUT / 't5_6a_conflict_census.parquet', index=False)

    # ---- by split ----
    sp = (d.groupby(['segment', 'vector'])
          .agg(n_rows=('n_rows', 'size'),
               weighted_rows=('n_rows', 'sum'),
               mean_coverage=('coverage', 'mean'),
               single_label=('n_labels', lambda s: (s == 1).mean()),
               multi_label=('n_labels', lambda s: (s >= 2).mean()),
               none_label=('n_labels', lambda s: (s == 0).mean()))
          .reset_index())
    sp['share_within_split'] = sp.n_rows / sp.groupby('segment')[
        'n_rows'].transform('sum')
    sp.to_parquet(OUT / 't5_6a_vector_by_split.parquet', index=False)

    # ---- by source level ----
    sl = (d.groupby(['source_level', 'vector'])
          .agg(n_rows=('n_rows', 'size'), weighted_rows=('n_rows', 'sum'),
               mean_coverage=('coverage', 'mean'),
               mean_events=('n_events', 'mean'),
               sparse_rate=('sparse_evidence',
                            lambda s: (s == True).mean()),
               high_rel=('reliability_class',
                         lambda s: (s == 'high').mean()),
               low_rel=('reliability_class',
                        lambda s: (s == 'low').mean()))
          .reset_index())
    sl['share_within_level'] = sl.n_rows / sl.groupby('source_level')[
        'n_rows'].transform('sum')
    sl.to_parquet(OUT / 't5_6a_vector_by_source_level.parquet',
                  index=False)

    # ---- by reliability ----
    rl = (d.groupby(['reliability_class', 'vector'])
          .agg(n_rows=('n_rows', 'size'), weighted_rows=('n_rows', 'sum'),
               mean_coverage=('coverage', 'mean'),
               mean_events=('n_events', 'mean'),
               sparse_rate=('sparse_evidence',
                            lambda s: (s == True).mean()))
          .reset_index())
    rl['share_within_reliability'] = rl.n_rows / rl.groupby(
        'reliability_class')['n_rows'].transform('sum')
    rl.to_parquet(OUT / 't5_6a_vector_by_reliability.parquet',
                  index=False)

    # ---- split composition stability: per-vector share drift ----
    piv = sp.pivot(index='vector', columns='segment',
                   values='share_within_split').fillna(0.0)
    drift = (piv.max(axis=1) - piv.min(axis=1)).rename('max_share_drift')
    nlab = d.groupby('vector')['n_labels'].first()
    top_vectors = piv.sum(axis=1).sort_values(ascending=False).head(8)
    composition = {
        'single_label_rate': float((d.n_labels == 1).mean()),
        'multi_label_rate': float((d.n_labels >= 2).mean()),
        'none_rate': float((d.n_labels == 0).mean()),
        'per_split': {
            seg: {
                'single': float((g.n_labels == 1).mean()),
                'multi': float((g.n_labels >= 2).mean()),
                'none': float((d2 := g).n_labels.eq(0).mean()),
                'weighted_rows': int(g.n_rows.sum()),
            } for seg, g in d.groupby('segment')
        },
        'dest_kind_rows': d.dest_kind.value_counts().to_dict(),
        'top8_vectors_share_by_split': {
            v: {seg: float(piv.loc[v, seg]) for seg in piv.columns}
            for v in top_vectors.index},
        'max_share_drift_top8': {
            v: float(drift[v]) for v in top_vectors.index},
    }

    man = {
        'stage': 'T5.6A_eligibility_conflict_census',
        'baseline': 'aac1f9f',
        'read_only_inputs': [
            't5_action_eligibility.parquet',
            't5_action_evidence.parquet',
            't5_hierarchy_increment.parquet'],
        'resolution_performed': False,
        'rows': {'aggregate_rows': len(d),
                 'weighted_day_rows': int(d.n_rows.sum())},
        'vector_count': int(d.vector.nunique()),
        'single_label_rate': composition['single_label_rate'],
        'multi_label_rate': composition['multi_label_rate'],
        'none_rate': composition['none_rate'],
        'composition': composition,
    }
    (OUT / 't5_6a_manifest.json').write_text(json.dumps(
        man, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: man[k] for k in
                      ['baseline', 'rows', 'vector_count',
                       'single_label_rate', 'multi_label_rate',
                       'none_rate']}, indent=2))
    print(cen[['vector', 'n_rows', 'share', 'weighted_share',
               'label_class', 'mean_coverage', 'sparse_rate']].head(12)
          .to_string(index=False))
    print('\nby split label-class rates:')
    print(pd.DataFrame({
        seg: {'single': float((g.n_labels == 1).mean()),
              'multi': float((g.n_labels >= 2).mean()),
              'none': float((g.n_labels == 0).mean())}
        for seg, g in d.groupby('segment')}).round(4).to_string())


if __name__ == '__main__':
    main()
