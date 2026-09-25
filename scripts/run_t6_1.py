#!/usr/bin/env python3
"""T6.1 — E-Class Independent Validation (contract-frozen, stage 1 of T6).

Question: does the development-derived E mapping (T4.5) still show meaningful
Reward / Risk / Persistence / Capital-Efficiency structure in validation and
confirmation segments?

Reference execution cell: direct_chase | P2_balanced (contract execution_reference).
Formal gradient: E2_vs_E1, E3_vs_E2. E0 = NON_PARTICIPATION_CONTROL (ret≡0 by
construction) is reported as an existence anchor only, never as a gradient step.
Development = reference only; validation + confirmation are primary.

All constants resolve from t6_contract.json (G6). Bootstrap: B=2000, seed
20260925, two-sided cluster units {stock_code, T0_date} (event_id = code_T0).
Holm within each metric family. NO composite E-score.
"""
from __future__ import annotations
import json
import sys
import zlib
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from t6.common import T6, load_contract, sha256_file, write_stage_outputs

OUT = T6/'01_eclass'
REF_STRATEGY, REF_POLICY = 'direct_chase', 'P2_balanced'


def per_event_frame(ep: pd.DataFrame, dm: pd.DataFrame) -> pd.DataFrame:
    """One row per filled reference-cell episode + path aggregates from Daily Master."""
    ref = ep[(ep.strategy == REF_STRATEGY) & (ep.policy_id == REF_POLICY)
             & ep.filled & (ep.policy_id != 'CONTROL')].copy()
    d = dm[dm.exposure_after_ref.notna()]
    agg = d.groupby('event_id').agg(
        capital_days=('exposure_after_ref', 'sum'),
        max_cum=('cum_ret_from_t0_log', 'max'),
        last_dd=('drawdown_from_peak_log', 'last'),
        min_dist_ref20=('dist_ref20', 'min'),
        max_delta=('delta_day', 'max'),
    )
    # peak_tau: delta_day at max cum (deterministic tie-break = first max)
    peak_tau = d.sort_values(['event_id', 'delta_day']).groupby('event_id').apply(
        lambda g: g.delta_day.iloc[g.cum_ret_from_t0_log.to_numpy().argmax()])
    agg['peak_tau'] = peak_tau
    f = ref.merge(agg, left_on='event_id', right_index=True, how='left')
    f['abs_mdd'] = -f.mdd_ep                       # mdd_ep stored negative
    f['E_rank'] = f.E_class.map({'E1': 1, 'E2': 2, 'E3': 3}).astype(int)
    f['stock_code'] = f.event_id.str.split('_').str[0]
    f['T0_date'] = f.event_id.str.split('_').str[1]
    f['ce1'] = f.ret_norm_ep / f.capital_days.replace(0, np.nan)
    f['ce2'] = f.ret_norm_ep / f.abs_mdd.replace(0, np.nan)
    f['ce3'] = f.portfolio_contribution / f.capital_days.replace(0, np.nan)
    return f


def metric_values(f: pd.DataFrame, metric: str) -> np.ndarray:
    """Per-episode value of a metric (same orientation for all E classes)."""
    if metric == 'median_return':  return f.ret_norm_ep.to_numpy()
    if metric == 'mean_return':    return f.ret_norm_ep.to_numpy()
    if metric == 'p_positive':     return (f.ret_norm_ep > 0).to_numpy(float)
    if metric == 'p05_return':     return f.ret_norm_ep.to_numpy()
    if metric == 'p25_return':     return f.ret_norm_ep.to_numpy()
    if metric == 'median_mdd':     return f.abs_mdd.to_numpy()
    if metric == 'p90_abs_mdd':    return f.abs_mdd.to_numpy()
    if metric == 'p95_abs_mdd':    return f.abs_mdd.to_numpy()
    if metric == 'large_loss_probability': return (f.ret_norm_ep <= LL).to_numpy(float)
    if metric == 'lose_ref20_probability': return (f.min_dist_ref20 < 0).to_numpy(float)
    if metric == 'p_new_high':     return (f.max_cum > 0).to_numpy(float)
    if metric == 'median_peak_tau': return f.peak_tau.to_numpy(float)
    if metric == 'p_survive_h10':  return (f.max_delta >= 10).to_numpy(float)
    if metric == 'p_survive_h20':  return (f.max_delta >= 20).to_numpy(float)
    if metric == 'p_terminal_failure': return (f.last_dd >= SDD).to_numpy(float)
    if metric == 'CE1': return f.ce1.to_numpy()
    if metric == 'CE2': return f.ce2.to_numpy()
    if metric == 'CE3': return f.ce3.to_numpy()
    raise KeyError(metric)


def metric_stat(x: np.ndarray, metric: str) -> float:
    """The family statistic of a metric over an episode sample."""
    if metric.startswith('median_'):  return float(np.nanmedian(x))
    if metric.startswith('mean_'):    return float(np.nanmean(x))
    if metric.startswith('p_positive'): return float(np.nanmean(x))
    if metric.startswith('p05_'):     return float(np.nanpercentile(x, 5))
    if metric.startswith('p25_'):     return float(np.nanpercentile(x, 25))
    if metric.startswith('p90_'):     return float(np.nanpercentile(x, 90))
    if metric.startswith('p95_'):     return float(np.nanpercentile(x, 95))
    if metric.startswith('p_') or 'probability' in metric:
        return float(np.nanmean(x))
    if metric.startswith('CE'):       return float(np.nanmedian(x))
    raise KeyError(metric)


def wq(sorted_v: np.ndarray, w: np.ndarray, q: float) -> float:
    """Weighted quantile == percentile of the repeat-expanded sample
    (linear interpolation between order statistics)."""
    cw = np.cumsum(w)
    pos = q * cw[-1]
    i = int(np.searchsorted(cw, pos, side='left'))
    i = min(i, len(sorted_v) - 1)
    if i == 0:
        return float(sorted_v[0])
    c0, c1 = cw[i - 1], cw[i]
    if c1 == c0:
        return float(sorted_v[i])
    frac = (pos - c0) / (c1 - c0)
    return float(sorted_v[i - 1] * (1 - frac) + sorted_v[i] * frac)


def stat_w(sorted_v: np.ndarray, w: np.ndarray, metric: str) -> float:
    """Family statistic on the weighted (repeat-expanded) sample."""
    if metric.startswith('mean_') or metric.startswith('p_positive') or 'probability' in metric \
       or (metric.startswith('p_') and not metric.startswith(('p05_', 'p25_', 'p90_', 'p95_'))):
        return float(np.nansum(w * sorted_v) / np.nansum(w))
    if metric.startswith('p05_'):  return wq(sorted_v, w, 0.05)
    if metric.startswith('p25_'):  return wq(sorted_v, w, 0.25)
    if metric.startswith('p90_'):  return wq(sorted_v, w, 0.90)
    if metric.startswith('p95_'):  return wq(sorted_v, w, 0.95)
    if metric.startswith('median_') or metric.startswith('CE'):
        return wq(sorted_v, w, 0.50)
    raise KeyError(metric)


def bootstrap_ci(vals: np.ndarray, erank: np.ndarray, clusters: np.ndarray,
                 metric: str, cmp_pair: tuple, rng: np.random.Generator,
                 B: int):
    """Two-sided cluster bootstrap of stat(E_hi) - stat(E_lo), weighted-repeat
    implementation (numerically equivalent to physical cluster resampling).

    Draw C clusters with replacement; episode weight = times its cluster was
    drawn. The repeat-expanded sample has the same discrete distribution, so
    its statistic via weighted quantiles/means equals the physical resample.
    Deterministic given rng.
    """
    lo, hi = cmp_pair
    out = {}
    for r in (lo, hi):
        m = erank == r
        v = vals[m]
        ok = ~np.isnan(v)
        v, cl = v[ok], clusters[m][ok]
        order = np.argsort(v, kind='mergesort')
        v_s, cl_s = v[order], cl[order]
        uq, inv = np.unique(cl_s, return_inverse=True)
        out[r] = (v_s, inv, len(uq))
    C = max(out[lo][2], out[hi][2])
    est = (stat_w(out[hi][0], np.ones(len(out[hi][0])), metric)
           - stat_w(out[lo][0], np.ones(len(out[lo][0])), metric))
    diffs = np.empty(B)
    for b in range(B):
        pick = rng.integers(0, C, C)
        d = 0.0
        for r, sign in ((hi, 1), (lo, -1)):
            v_s, inv, Cu = out[r]
            m_d = np.bincount(pick, minlength=C)[:Cu]
            w = m_d[inv]
            d += sign * stat_w(v_s, w, metric)
        diffs[b] = d
    ci = (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5)))
    p = 2 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    return est, ci, float(min(p, 1.0)), diffs


def spearman_ci(vals: np.ndarray, erank: np.ndarray, clusters: np.ndarray,
                rng: np.random.Generator, B: int):
    ok = ~np.isnan(vals)
    vals, erank, clusters = vals[ok], erank[ok], clusters[ok]
    ranks_v = pd.Series(vals).rank().to_numpy()
    ranks_e = pd.Series(erank).rank().to_numpy()
    def sp(v, e):
        if len(np.unique(e)) < 2:
            return 0.0
        rv, re = pd.Series(v).rank().to_numpy(), pd.Series(e).rank().to_numpy()
        return float(np.corrcoef(rv, re)[0, 1])
    est = sp(ranks_v, ranks_e)
    uniq = np.unique(clusters)
    members = [np.where(clusters == c)[0] for c in uniq]
    ds = np.empty(B)
    for b in range(B):
        pick = rng.integers(0, len(uniq), len(uniq))
        rows = np.concatenate([members[p] for p in pick])
        ds[b] = sp(ranks_v[rows], ranks_e[rows])
    ci = (float(np.percentile(ds, 2.5)), float(np.percentile(ds, 97.5)))
    p = 2 * min((ds <= 0).mean(), (ds >= 0).mean())
    return est, ci, float(min(p, 1.0))


def holm(pvals: dict) -> dict:
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    adj, running = {}, 0.0
    for i, (k, p) in enumerate(items):
        a = min(1.0, (m - i) * p)
        running = max(running, a)
        adj[k] = running
    return adj


SEGS = ('validation', 'confirmation', 'development')


def make_child_rng(seed, segs, fams, comparisons):
    """Factory closed over frozen stage enumerations; child_rng(seg, fam, met,
    cmp_name, cunit, tag) -> deterministic independent SeedSequence substream.
    Any single statistic is standalone replayable for G10 determinism check."""
    def child_rng(seg, fam, met, cmp_name=None, cunit=None, tag=0):
        return np.random.default_rng(np.random.SeedSequence(
            [seed, segs.index(seg), fams.index(fam), zlib.crc32(met.encode()) % (2**31),
             0 if cmp_name is None else list(comparisons).index(cmp_name) + 1,
             0 if cunit is None else ('stock_code', 'T0_date').index(cunit) + 1, tag]))
    return child_rng


def main():
    global LL, SDD
    contract = load_contract()
    t = contract['preregistered_thresholds']
    LL = t['large_loss_ret_log']
    SDD = t['severe_dd_depth_log']
    B = contract['statistics_prereg']['bootstrap_B']
    SEED = contract['statistics_prereg']['bootstrap_seed']

    ep = pd.read_parquet(T6/'00_factlayer/t6_0_episode_master.parquet')
    dm = pd.read_parquet(T6/'00_factlayer/t6_0_daily_master.parquet',
                         columns=['event_id', 'delta_day', 'exposure_after_ref',
                                  'cum_ret_from_t0_log', 'drawdown_from_peak_log',
                                  'dist_ref20'])
    f = per_event_frame(ep, dm)

    families = {
        'reward': ['median_return', 'mean_return', 'p_positive', 'p05_return', 'p25_return'],
        'risk': ['median_mdd', 'p90_abs_mdd', 'p95_abs_mdd', 'large_loss_probability',
                 'lose_ref20_probability'],
        'persistence': ['p_new_high', 'median_peak_tau', 'p_survive_h10',
                        'p_survive_h20', 'p_terminal_failure'],
        'capital_efficiency': ['CE1', 'CE2', 'CE3'],
    }
    comparisons = {'E2_vs_E1': (1, 2), 'E3_vs_E2': (2, 3)}

    child_rng = make_child_rng(SEED, SEGS, list(families.keys()), comparisons)
    report = {
        'stage': 't6_1',
        'contract_sha256': sha256_file(T6/'t6_contract.json'),
        'reference_cell': {'strategy': REF_STRATEGY, 'policy': REF_POLICY,
                           'episodes': int(len(f))},
        'statistics_used': {'B': B, 'seed': SEED, 'ci': 'percentile 2.5/97.5',
                            'clusters': ['stock_code', 'T0_date'],
                            'holm': 'Holm within each metric family (stock_code primary)',
                            'rng': 'SeedSequence([seed, seg, fam, met, cmp, cunit, tag]) independent substreams (G10 replayable)'},
        'metric_defs': {
            'abs_mdd': '-mdd_ep (episode MDD stored negative in T5.8R-2)',
            'capital_days': 'sum(exposure_after_ref) over lifecycle; exposure_after_ref is ABSOLUTE executed exposure (0-1, base already applied in T5.7 execution)',
            'p_new_high': 'P(max cum_ret_from_t0_log > 0) — episode ever traded above T0 close',
            'median_peak_tau': 'median of delta_day at argmax cum_ret_from_t0_log (ties: first max)',
            'p_survive_h10/h20': 'P(max observed delta_day >= 10/20) — physical path length',
            'p_terminal_failure': 'P(last-day drawdown_from_peak_log >= severe_dd_depth_log) — ends with unrepaired severe drawdown',
            'lose_ref20_probability': 'P(min dist_ref20 < 0 over lifecycle; master column name) — episode ever closed below ref20',
            'p05/p25/p90/p95': 'percentiles of per-episode values within segment x E_class',
            'E1_vs_E0': 'E0 = CONTROL ret≡0 by construction (22,988 rows); anchor only, not a gradient test',
        },
        'segments': {},
    }

    for seg in SEGS:
        fs = f[f.segment == seg]
        seg_out = {'n': int(len(fs)),
                   'by_E': fs.E_class.value_counts().to_dict(), 'metrics': {},
                   'role': 'reference_only' if seg == 'development' else 'primary'}
        pvals = {}
        for fam, mets in families.items():
            for met in mets:
                vals = metric_values(fs, met)
                erank = fs.E_rank.to_numpy()
                per_E = {f'E{r}': metric_stat(vals[erank == r], met) for r in (1, 2, 3)}
                entry = {'per_E': per_E, 'comparisons': {}}
                for cname, (lo, hi) in comparisons.items():
                    for cunit in ('stock_code', 'T0_date'):
                        cl = fs[cunit].to_numpy()
                        est, ci, p, _ = bootstrap_ci(
                            vals, erank, cl, met, (lo, hi),
                            child_rng(seg, fam, met, cname, cunit), B)
                        entry['comparisons'][f'{cname}|{cunit}'] = {
                            'diff': est, 'ci95': ci, 'p_boot': p}
                        if cunit == 'stock_code':
                            pvals[(fam, met, cname)] = p
                # spearman for reward/risk/CE-type metrics: episode-level E_rank vs value
                sp_est, sp_ci, sp_p = spearman_ci(
                    vals, erank, fs.stock_code.to_numpy(), child_rng(seg, fam, met), B)
                entry['spearman_E_rank'] = {'rho': sp_est, 'ci95': sp_ci, 'p_boot': sp_p}
                seg_out['metrics'][f'{fam}/{met}'] = entry
        adj = holm({f'{a}|{b}|{c}': p for (a, b, c), p in pvals.items()})
        seg_out['holm_adj_p'] = adj
        report['segments'][seg] = seg_out

    write_stage_outputs(
        OUT, 't6_1',
        {'per_event': f.reset_index(drop=True)},
        {'inputs': [
            {'name': 'episode_master', 'path': 'output/research/t6/00_factlayer/t6_0_episode_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_episode_master.parquet'), 'bytes': 0},
            {'name': 'daily_master', 'path': 'output/research/t6/00_factlayer/t6_0_daily_master.parquet',
             'sha256': sha256_file(T6/'00_factlayer/t6_0_daily_master.parquet'), 'bytes': 0},
            {'name': 't6_contract', 'path': 'output/research/t6/t6_contract.json',
             'sha256': sha256_file(T6/'t6_contract.json'), 'bytes': 0}]},
        report)
    print('T6.1 done. per-event rows:', len(f))
    for seg in ('validation', 'confirmation'):
        s = report['segments'][seg]
        print(f"--- {seg} n={s['n']} by_E={s['by_E']}")
        for key in ('reward/median_return', 'risk/median_mdd', 'persistence/p_terminal_failure', 'capital_efficiency/CE1'):
            m = s['metrics'][key]
            print(f"  {key}: per_E={ {k: round(v,4) for k,v in m['per_E'].items()} } "
                  f"E3vE2(stock)={round(m['comparisons']['E3_vs_E2|stock_code']['diff'],4)} "
                  f"CI=[{m['comparisons']['E3_vs_E2|stock_code']['ci95'][0]:.4f},{m['comparisons']['E3_vs_E2|stock_code']['ci95'][1]:.4f}]")


if __name__ == '__main__':
    main()
