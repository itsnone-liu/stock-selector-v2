#!/usr/bin/env python3
"""T6.2 — Exposure Recycling: does REDUCE mark deterioration and the next ADD
mark repair? Is the dynamic-exposure advantage 'release capital in bad
states, re-enter after repair' rather than 'simply hold less'?

Cycle taxonomy (contract recycling_prereg): R0 = REDUCE day; a later REDUCE
before any ADD moves R0; A0 = first ADD after R0. Types: RECOVERED_ADD /
FAILED_EXIT (EXIT before any ADD) / NO_RECOVERY (lifecycle ends, no ADD) /
CENSORED (right-censored before resolution). POST_EXIT_LOCKED is permanent,
so EXIT can never be followed by re-entry — control groups compared jointly
(no success-only selection).

All constants from t6_contract.json (G6). Bootstrap per statistics_prereg.
Reference cell direct_chase | P2_balanced.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file, write_stage_outputs
from t6.stats import cluster_boot_diff, cluster_boot_level, holm, make_rng_factory

OUT = T6/'02_recycling'
REF_STRATEGY, REF_POLICY = 'direct_chase', 'P2_balanced'
STATE_COLS = ['drawdown_from_peak_log', 'efficiency_signed_3', 'dist_ref20',
              'turnover_load_3d_mean', 'cum_ret_from_t0_log']


def lifecycles_to_cycles(d: pd.DataFrame, H: list) -> pd.DataFrame:
    """Single pass over the sorted reference-cell daily frame."""
    ev_a = d.event_id.to_numpy()
    dd_a = d.delta_day.to_numpy()
    rs_a = d.resolution_state.to_numpy()
    st = {c: d[c].to_numpy(float) for c in STATE_COLS}
    cum = st['cum_ret_from_t0_log']
    # event boundaries
    starts = np.flatnonzero(np.r_[True, ev_a[1:] != ev_a[:-1]])
    ends = np.r_[starts[1:], len(ev_a)]
    rows = []
    for s, e in zip(starts, ends):
        seg_evc, ecl, cens = d.segment.iloc[s], d.E_class.iloc[s], bool(d.censored.iloc[s])
        days, states = dd_a[s:e], rs_a[s:e]
        i = 0
        n = e - s
        while i < n:
            if states[i] == 'RESOLVED_REDUCE':
                r0 = i
                j = i + 1
                while j < n and states[j] == 'RESOLVED_REDUCE':
                    r0 = j
                    j += 1
                a0 = exitp = None
                k = r0 + 1
                while k < n:
                    if states[k] == 'RESOLVED_ADD':
                        a0 = k
                        break
                    if states[k] == 'RESOLVED_EXIT':
                        exitp = k
                        break
                    if states[k] == 'RESOLVED_REDUCE':
                        r0 = k
                    k += 1
                if a0 is not None:
                    typ = 'RECOVERED_ADD'
                elif exitp is not None:
                    typ = 'FAILED_EXIT'
                else:
                    typ = 'CENSORED' if cens else 'NO_RECOVERY'
                row = {'event_id': ev_a[s], 'segment': seg_evc, 'E_class': ecl,
                       'r0_day': int(days[r0]), 'a0_day': int(days[a0]) if a0 is not None else np.nan,
                       'type': typ}
                for c in STATE_COLS:
                    lo = max(0, r0 - 5)
                    w = st[c][s + lo:s + r0]
                    w = w[~np.isnan(w)]
                    row[f'{c}@BASE'] = float(w.mean()) if len(w) else np.nan
                    row[f'{c}@R0'] = float(st[c][s + r0]) if not np.isnan(st[c][s + r0]) else np.nan
                    if a0 is not None:
                        row[f'{c}@A0'] = float(st[c][s + a0])
                        row[f'rep_{c}'] = row[f'{c}@A0'] - row[f'{c}@R0']
                    else:
                        row[f'{c}@A0'] = np.nan
                        row[f'rep_{c}'] = np.nan
                    row[f'det_{c}'] = (row[f'{c}@R0'] - row[f'{c}@BASE']
                                       if not (np.isnan(row[f'{c}@R0']) or np.isnan(row[f'{c}@BASE']))
                                       else np.nan)
                cum0 = cum[s + r0]
                tgt = days - days[r0]
                for h in H:
                    cand = np.flatnonzero(tgt >= h)
                    lastp = s + cand[-1] if len(cand) else None
                    if lastp is not None and not np.isnan(cum0):
                        row[f'bh_R0_H{h}'] = float(cum[lastp] - cum0)
                    else:
                        row[f'bh_R0_H{h}'] = np.nan
                    for c in STATE_COLS:
                        v0, v1 = st[c][s + r0], (st[c][lastp] if lastp is not None else np.nan)
                        row[f'drift_{c}@H{h}'] = (float(v1 - v0)
                                                   if not (np.isnan(v0) or np.isnan(v1)) else np.nan)
                rows.append(row)
                i = (a0 if a0 is not None else exitp + 1 if exitp is not None else n)
            else:
                i += 1
    return pd.DataFrame(rows)


def main():
    contract = load_contract()
    t = contract['preregistered_thresholds']
    pre = contract['statistics_prereg']
    B, SEED = pre['bootstrap_B'], pre['bootstrap_seed']
    H = t['horizons_H']

    ep = pd.read_parquet(T6/'00_factlayer/t6_0_episode_master.parquet',
                         columns=['event_id', 'strategy', 'policy_id', 'filled', 'E_class',
                                  'segment', 'ret_norm_ep', 'censored', 'terminal_reason'])
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'resolution_state',
                                  'exposure_after_ref'] + STATE_COLS)
    ref = ep[(ep.strategy == REF_STRATEGY) & (ep.policy_id == REF_POLICY) & ep.filled]
    d = dm[dm.exposure_after_ref.notna()].merge(
        ref[['event_id', 'E_class', 'segment', 'ret_norm_ep', 'censored']],
        on='event_id', how='inner')
    d = d.sort_values(['event_id', 'delta_day']).reset_index(drop=True)
    d['stock_code'] = d.event_id.str.split('_').str[0]
    d['T0_date'] = d.event_id.str.split('_').str[1]

    cyc = lifecycles_to_cycles(d, H)
    cyc['stock_code'] = cyc.event_id.str.split('_').str[0]
    cyc['T0_date'] = cyc.event_id.str.split('_').str[1]

    enums = [['validation', 'confirmation', 'development'],
             ['deterioration', 'repair', 'path'],
             list(STATE_COLS),
             ['RECOVERED_ADD', 'FAILED_EXIT', 'NO_RECOVERY', 'CENSORED'],
             ['median', 'mean', 'p05', 'p25', 'p90', 'p95']]
    rng = make_rng_factory(SEED, enums)

    report = {
        'stage': 't6_2',
        'contract_sha256': sha256_file(T6/'t6_contract.json'),
        'reference_cell': {'strategy': REF_STRATEGY, 'policy': REF_POLICY},
        'statistics_used': {'B': B, 'seed': SEED, 'ci': 'percentile 2.5/97.5',
                            'clusters': ['stock_code', 'T0_date'],
                            'holm': 'Holm within each test family',
                            'rng': 'SeedSequence substreams via t6.stats.make_rng_factory'},
        'metric_defs': {
            'R0': 'last RESOLVED_REDUCE day before any ADD (repeated REDUCE moves R0, contract rule)',
            'A0': 'first RESOLVED_ADD day after R0 in same lifecycle',
            'det_X': 'X@R0 - mean(X over R0-5..R0-1 valid rows) — deterioration at reduce',
            'rep_X': 'X@A0 - X@R0 — repair between reduce and re-add (RECOVERED_ADD only; NaN otherwise)',
            'bh_R0_Hh': 'cum_ret_from_t0_log at last day with (day - R0) >= h, minus value at R0 — buy&hold path from R0 (PIT prefix stat); NaN if no such day',
            'censored_cyc': 'lifecycle censored (terminal_reason=MAX_HORIZON) with cycle unresolved at data end',
        },
        'freq': {},
        'segments': {},
    }
    ft = cyc.groupby(['segment', 'type'], observed=True).size().unstack(fill_value=0)
    report['freq'] = {seg: row.to_dict() for seg, row in ft.iterrows()}

    groups = ['RECOVERED_ADD', 'FAILED_EXIT', 'NO_RECOVERY']
    for seg in ('validation', 'confirmation', 'development'):
        cs = cyc[cyc.segment == seg]
        seg_out = {'n': int(len(cs)), 'role': 'reference_only' if seg == 'development' else 'primary'}
        pvals = {}
        det = {}
        for gname in groups:
            m = (cs.type == gname).to_numpy()
            entry = {}
            for col in STATE_COLS:
                vals = cs[f'det_{col}'].to_numpy(float)
                est, ci = cluster_boot_level(vals, m, cs.stock_code.to_numpy(), 'median',
                                             rng(seg, 'deterioration', col, gname), B)
                _, ci2 = cluster_boot_level(vals, m, cs.T0_date.to_numpy(), 'median',
                                            rng(seg, 'deterioration', col, gname, 'T0_date'), B)
                entry[col] = {'median': est, 'ci95_stock': ci, 'ci95_T0': ci2}
                pvals[f'det|{gname}|{col}'] = 0.0 if (ci[0] > 0 or ci[1] < 0) else 1.0
            det[gname] = entry
        seg_out['deterioration'] = det
        # repair: (a) RECOVERED_ADD rep level (A0-R0 change, level CI);
        # (b) fixed-window drift comparison across groups (same window h,
        #     all three groups observable -> no success-only selection)
        rep = {}
        mh = (cs.type == 'RECOVERED_ADD').to_numpy()
        for col in STATE_COLS:
            est, ci = cluster_boot_level(cs[f'rep_{col}'].to_numpy(float), mh,
                                         cs.stock_code.to_numpy(), 'median',
                                         rng(seg, 'repair', col, 'RECOVERED_ADD'), B)
            rep[col] = {'RECOVERED_ADD_rep_level': {'median': est, 'ci95': ci}}
        for h in (5, 10, 20):
            for col in STATE_COLS:
                vals = cs[f'drift_{col}@H{h}'].to_numpy(float)
                ml = (cs.type == 'NO_RECOVERY').to_numpy()
                est, ci, p, diag = cluster_boot_diff(vals, mh, ml, cs.stock_code.to_numpy(), 'median',
                                                     rng(seg, 'repair', col, f'RECvNO_H{h}'), B)
                rep.setdefault(f'driftH{h}', {})[col] = {
                    'RECOVERED_minus_NORECOVERY': {'diff': est, 'ci95': ci, 'p_boot': p, **diag}}
                if np.isfinite(p):
                    pvals[f'drift|H{h}|REC_vs_NO|{col}'] = p
        seg_out['repair'] = rep
        path = {}
        for h in H:
            entry = {}
            for gname in groups:
                m = (cs.type == gname).to_numpy()
                vals = cs[f'bh_R0_H{h}'].to_numpy(float)
                est, ci = cluster_boot_level(vals, m, cs.stock_code.to_numpy(), 'median',
                                             rng(seg, 'path', 'cum_ret_from_t0_log', gname, h), B)
                entry[gname] = {'median': est, 'ci95': ci}
            vals = cs[f'bh_R0_H{h}'].to_numpy(float)
            est, ci, p, diag = cluster_boot_diff(vals, (cs.type == 'RECOVERED_ADD').to_numpy(),
                                                 (cs.type == 'NO_RECOVERY').to_numpy(),
                                                 cs.stock_code.to_numpy(), 'median',
                                                 rng(seg, 'path', 'cum_ret_from_t0_log', f'RECvNO_{h}'), B)
            entry['RECOVERED_minus_NORECOVERY'] = {'diff': est, 'ci95': ci, 'p_boot': p, **diag}
            if np.isfinite(p):
                pvals[f'path|REC_vs_NO|H{h}'] = p
            path[f'H{h}'] = entry
        seg_out['path'] = path
        seg_out['holm_adj_p'] = holm(pvals)
        report['segments'][seg] = seg_out

    cyc_out = cyc.drop(columns=[c for c in cyc.columns if c.endswith('@BASE')], errors='ignore')
    write_stage_outputs(
        OUT, 't6_2', {'cycle_master': cyc_out},
        {'inputs': [
            {'name': 'episode_master', 'path': 'output/research/t6/00_factlayer/t6_0_episode_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_episode_master.parquet'), 'bytes': 0},
            {'name': 'daily_master', 'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
            {'name': 't6_contract', 'path': 'output/research/t6/t6_contract.json',
             'sha256': sha256_file(T6/'t6_contract.json'), 'bytes': 0}]},
        report)
    print('cycles:', len(cyc), '| by type:', cyc.type.value_counts().to_dict())
    for seg in ('validation', 'confirmation'):
        cs = cyc[cyc.segment == seg]
        print(f'--- {seg}:', cs.type.value_counts().to_dict())
        for col in ('drawdown_from_peak_log', 'efficiency_signed_3', 'dist_ref20'):
            m = (cs.type == 'RECOVERED_ADD').to_numpy()
            est, ci = cluster_boot_level(cs[f'det_{col}'].to_numpy(float), m,
                                         cs.stock_code.to_numpy(), 'median',
                                         rng(seg, 'deterioration', col, 'RECOVERED_ADD'), B)
            print(f'  det[{col}] RECOVERED_ADD: {est:+.4f} [{ci[0]:+.4f},{ci[1]:+.4f}]')


if __name__ == '__main__':
    main()
