#!/usr/bin/env python3
"""T5.6B resolution engine + T5.6C stability audit.

Read-only over T5.5/T5.6A products (baseline c4a3056). Rules R1-R5 plus a
defensive unseen-vector guard, exactly as commissioned. No outcome data is
read; no priority ordering is invented; unresolved states are legal.

Semantic containment audits (from frozen T5.5 definitions):
  R2: ADD evidence conditions strictly contain the hold rationale on the
      continuation/upside/risk axes; 1100 co-truth is reinforcement.
  R4: EXIT_ELIGIBLE => terminal_positive & failure_positive & high
      reliability & ~sparse, which structurally implies REDUCE_ELIGIBLE's
      disjunction and reliability gate. EXIT therefore independently
      qualifies; REDUCE is the weaker co-occurring flag. Resolution is
      EXIT-by-containment, marked FRAGILE (2 source keys, val=0).
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
SRC = ROOT / 'output/research/t5/action_eligibility'
CEN = ROOT / 'output/research/t5/action_resolution'
OUT = CEN
FLAGS = ['ADD_ELIGIBLE', 'HOLD_ELIGIBLE', 'REDUCE_ELIGIBLE', 'EXIT_ELIGIBLE']

RESOLVED = {
    '0010': ('RESOLVED_REDUCE', 'DIRECT_ACTION'),
    '0100': ('RESOLVED_HOLD', 'DIRECT_ACTION'),
    '1100': ('RESOLVED_ADD', 'SEMANTIC_REINFORCEMENT'),
    '1010': ('CONFLICT_OPPORTUNITY_RISK', 'OPPORTUNITY_RISK_CONFLICT'),
    '0011': ('RESOLVED_EXIT', 'TERMINAL_RISK_RESOLUTION'),
    '0000': ('NO_ACTION_EVIDENCE', 'EVIDENCE_INSUFFICIENT'),
}


def vec_code(r):
    return ''.join('1' if bool(r[f]) else '0' for f in FLAGS)


def no_evidence_reasons(r):
    """R5 multi-cause classification; reasons may co-occur."""
    rs = []
    if r.get('reliability_class') == 'low':
        rs.append('LOW_RELIABILITY')
    if bool(r.get('sparse_evidence', False)):
        rs.append('SPARSE_EVIDENCE')
    if (r.get('n_events', 0) or 0) < 30 or (r.get('support', 0) or 0) < 200:
        rs.append('INSUFFICIENT_SUPPORT')
    cov = r.get('coverage')
    if cov is not None and not (isinstance(cov, float) and np.isnan(cov)):
        if cov < 0.75:
            rs.append('CENSOR_LIMITED')
        elif cov < 0.90:
            rs.append('COVERAGE_LIMITED')
    if not rs:
        rs.append('OTHER_INSUFFICIENT')
    return rs


def main():
    a = pd.read_parquet(SRC / 't5_action_eligibility.parquet')
    e = pd.read_parquet(SRC / 't5_action_evidence.parquet')
    h = pd.read_parquet(SRC / 't5_hierarchy_increment.parquet')
    d = a.merge(e[['segment', 'source_level', 'source_key',
                   'reliability_class', 'sparse_evidence', 'coverage',
                   'n_events', 'support']],
                on=['segment', 'source_level', 'source_key'],
                how='left', suffixes=('', '_ev'))
    d = d.merge(h[['segment', 'source_level', 'source_key',
                   'hierarchy_selected', 'backoff_reason']],
                on=['segment', 'source_level', 'source_key'], how='left')
    d['vector'] = d.apply(vec_code, axis=1)

    rows = []
    for _, r in d.iterrows():
        v = r['vector']
        if v in RESOLVED:
            status, rule = RESOLVED[v]
        else:
            status, rule = 'UNRESOLVED_UNSEEN_VECTOR', 'UNSEEN_VECTOR'
        reasons = no_evidence_reasons(r) if v == '0000' else []
        rows.append({
            'segment': r['segment'],
            'source_level': r['source_level'],
            'source_key': r['source_key'],
            'vector': v,
            'resolution_status': status,
            'resolution_rule': rule,
            'no_evidence_reasons': '|'.join(reasons),
            'n_rows': int(r['n_rows']),
            'n_events': int(r['n_events']),
            'reliability_class': r.get('reliability_class'),
            'sparse_evidence': bool(r.get('sparse_evidence', False)),
            'coverage': r.get('coverage'),
            'hierarchy_selected': r.get('hierarchy_selected'),
            'backoff_reason': r.get('backoff_reason'),
            'exit_fragile': bool(v == '0011'),
        })
    res = pd.DataFrame(rows)
    res.to_parquet(OUT / 't5_6b_resolution.parquet', index=False)

    # -------- T5.6C stability audit --------
    tw = res.n_rows.sum()
    cov = res.groupby('resolution_status').agg(
        n_rows=('n_rows', 'size'), weighted_rows=('n_rows', 'sum'))
    cov['weighted_share'] = cov.weighted_rows / tw
    coverage_tbl = cov.reset_index()

    mix = (res.groupby(['segment', 'resolution_status'])
           .agg(weighted_rows=('n_rows', 'sum')).reset_index())
    mix['wshare'] = mix.weighted_rows / mix.groupby('segment')[
        'weighted_rows'].transform('sum')

    c1010 = mix[mix.resolution_status == 'CONFLICT_OPPORTUNITY_RISK'][
        ['segment', 'wshare', 'weighted_rows']]
    c0011 = res[res.vector == '0011'][
        ['segment', 'source_key', 'n_rows', 'reliability_class']]
    c0000 = (res[res.vector == '0000']
             .assign(reason=res.no_evidence_reasons.str.split('|'))
             .explode('reason'))
    mech0000 = (c0000.groupby(['segment', 'reason'])
                .agg(weighted_rows=('n_rows', 'sum')).reset_index())

    hold_only = mix[mix.resolution_status == 'RESOLVED_HOLD'][
        ['segment', 'wshare']]

    stability = {
        'coverage': coverage_tbl.to_dict('records'),
        'resolved_mix_by_segment': mix.to_dict('records'),
        'check_1010_val_drift': c1010.to_dict('records'),
        'check_0011_fragility': {
            'n_source_keys_total': int(res[res.vector == '0011']
                                       .source_key.nunique()),
            'validation_weighted_rows': int(
                res[(res.vector == '0011')
                    & (res.segment == 'validation')].n_rows.sum()),
            'fragile_flag': True},
        'check_0000_mechanism': mech0000.to_dict('records'),
        'check_hold_only_drift': hold_only.to_dict('records'),
    }
    (OUT / 't5_6c_stability.json').write_text(json.dumps(
        stability, indent=2, ensure_ascii=False, default=str))
    print(coverage_tbl[['resolution_status', 'weighted_share']]
          .to_string(index=False))
    print(mix.pivot(index='resolution_status', columns='segment',
                    values='wshare').round(4).to_string())


if __name__ == '__main__':
    main()
