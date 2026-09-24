"""T4.3 条件对比分析：event-weighted / date-balanced / interaction。

依赖结构（开工令 §九/§十/§十一）：
- breakout_day 是核心 dependency cluster；stock 为第二维。
- 不确定性：date-cluster 与 stock-cluster bootstrap 并列（N_BOOT 次），
  主区间取两者中较宽者（dependency audit 同时记录两套）。
- p 值与 CI 同一批 bootstrap 生成（零分布=重采样分布），无二次抽样。
- date-balanced：先日内聚合（当日事件 median），再跨日 median。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260924)
N_BOOT = 300

METRICS = ("median_excess", "mean_excess", "median_mdd",
           "median_max_gain", "p_new_high", "p_lose_ref20")
METRIC_VALUE_COL = {
    "median_excess": "fwd_mkt_excess_log",
    "mean_excess": "fwd_mkt_excess_log",
    "median_mdd": "future_max_drawdown",
    "median_max_gain": "future_max_gain",
    "p_new_high": "new_high_within",
    "p_lose_ref20": "lose_ref20_within",
}


def cell_value(arr: np.ndarray, metric: str) -> float:
    v = arr[np.isfinite(arr)]
    if not len(v):
        return np.nan
    if metric in ("median_excess", "median_mdd", "median_max_gain"):
        return float(np.median(v))
    if metric == "mean_excess":
        return float(np.mean(v))
    return float((v > 0).mean())  # bool 指标以 0/1 float 编码


def _cluster_maps(dates: np.ndarray, stocks: np.ndarray):
    duniq, dinv = np.unique(dates, return_inverse=True)
    suniq, sinv = np.unique(stocks, return_inverse=True)
    idx = np.arange(len(dates))
    dmap = {k: idx[dinv == k] for k in range(len(duniq))}
    smap = {k: idx[sinv == k] for k in range(len(suniq))}
    return dmap, smap


def two_cluster_ci(values: np.ndarray, grp: np.ndarray, dates: np.ndarray,
                   stocks: np.ndarray, metric: str, n_groups: int = 2):
    """grp: int 0..n_groups-1（Q4-Q1 用 0/1；DiD 内部另行处理）。

    返回 (diff_point, ci_lo, ci_hi, ci_date, ci_stock, p_two_sided)。
    diff = cell(g=n_groups-1) - cell(g=0)。
    """
    dmap, smap = _cluster_maps(dates, stocks)

    def _diff(rows):
        out = []
        for g in (0, n_groups - 1):
            sel = values[rows][grp[rows] == g]
            out.append(cell_value(sel, metric))
        return out[1] - out[0]

    point = _diff(np.arange(len(values)))
    cis, stats_by = {}, {}
    for kind, gmap in (("date", dmap), ("stock", smap)):
        keys = np.fromiter(gmap.keys(), dtype=int)
        stats = np.empty(N_BOOT)
        for b in range(N_BOOT):
            pick = RNG.choice(keys, size=len(keys), replace=True)
            rows = np.concatenate([gmap[k] for k in pick])
            stats[b] = _diff(rows)
        stats_by[kind] = stats
        fin = stats[np.isfinite(stats)]
        cis[kind] = (float(np.percentile(fin, 2.5)),
                     float(np.percentile(fin, 97.5))) if len(fin) else (
            np.nan, np.nan)
    w = max(abs(cis["date"][1] - cis["date"][0]),
            abs(cis["stock"][1] - cis["stock"][0]))
    v = stats_by["date"][np.isfinite(stats_by["date"])]
    p = float(min(1.0, 2 * min((v <= 0).mean(), (v >= 0).mean()))) if (
        len(v) and np.isfinite(point)) else np.nan
    return point, point - w / 2, point + w / 2, cis["date"], cis[
        "stock"], p


def date_balanced_diff(values: np.ndarray, grp: np.ndarray,
                       dates: np.ndarray, metric: str) -> float:
    """date-balanced Q4−Q1：每日每格聚合 -> 跨日 median -> 相减。"""
    uniq = np.unique(dates)
    a_days, b_days = [], []
    for d in uniq:
        m = dates == d
        a = values[m & (grp == 1)]
        b = values[m & (grp == 0)]
        va, vb = cell_value(a, metric), cell_value(b, metric)
        if np.isfinite(va):
            a_days.append(va)
        if np.isfinite(vb):
            b_days.append(vb)
    if not a_days or not b_days:
        return np.nan
    return float(np.median(a_days) - np.median(b_days))


def market_contrast_row(ph: pd.DataFrame, axis_col: str, h: int,
                        metric: str) -> dict:
    sub = ph[ph[axis_col].notna()]
    vc = METRIC_VALUE_COL[metric]
    sub = sub[sub[vc].notna()]
    qmap = sub[axis_col].map({"Q1": 0, "Q4": 1})
    sub = sub.assign(_q=qmap)
    sub = sub[sub["_q"].notna()]
    sub = sub.assign(_q=sub["_q"].astype(int))
    vals = sub[vc].astype(float).to_numpy()
    if metric in ("p_new_high", "p_lose_ref20"):
        vals = vals.astype(float)
    grp = sub["_q"].to_numpy()
    dates = sub["breakout_day"].to_numpy()
    stocks = sub["code"].to_numpy()

    full = ph[ph[axis_col].notna()]
    levels = {}
    for q in ("Q1", "Q2", "Q3", "Q4"):
        g = full[full[axis_col] == q]
        gv = g[vc].astype(float).to_numpy()
        levels[q] = {"n_events": int(len(g)),
                     "n_dates": int(g["breakout_day"].nunique()),
                     "value": cell_value(gv, metric)}
    pt, lo, hi, cd, cs, p = two_cluster_ci(vals, grp, dates, stocks, metric)
    db = date_balanced_diff(vals, grp, dates, metric)
    return {
        "context_axis": axis_col, "horizon": h, "metric": metric,
        **{f"{q}_{k}": levels[q][k] for q in
           ("Q1", "Q2", "Q3", "Q4") for k in
           ("n_events", "n_dates", "value")},
        "ew_q4_minus_q1": pt, "ew_ci_lo": lo, "ew_ci_hi": hi,
        "db_q4_minus_q1": db, "p_two_sided_date_cluster": p,
        "n_base": int(len(ph)), "n_context_available": int(len(full)),
        "n_outcome_available": int(sub.shape[0])}


def interaction_row(ph: pd.DataFrame, stock_col: str, mkt_col: str,
                    h: int, metric: str) -> dict:
    sub = ph[ph[stock_col].notna() & ph[mkt_col].notna()]
    vc = METRIC_VALUE_COL[metric]
    sub = sub[sub[vc].notna()]
    sh = sub[stock_col].astype(bool).to_numpy()
    mh = (sub[mkt_col].to_numpy() >= .5)
    vals = sub[vc].astype(float).to_numpy()
    dates = sub["breakout_day"].to_numpy()
    stocks = sub["code"].to_numpy()
    # 格码：s*2+m（0=lo/lo, 1=lo/hi, 2=hi/lo, 3=hi/hi）
    cell = (sh.astype(int) * 2 + mh.astype(int))

    def _cells(v):
        return [cell_value(v[cell == c], metric) for c in range(4)]

    lo_lo, lo_hi, hi_lo, hi_hi = _cells(vals)
    did = ((hi_hi - lo_hi) - (hi_lo - lo_lo)
           if all(np.isfinite(x) for x in
                  (hi_hi, lo_hi, hi_lo, lo_lo)) else np.nan)
    # DiD 的 bootstrap：直接对 cell 码 0..3 用线性组合
    dmap, smap = _cluster_maps(dates, stocks)
    # cell0=lo/lo, 1=lo/hi, 2=hi/lo, 3=hi/hi；DiD = (hi−lo)|mkt_hi − (hi−lo)|mkt_lo
    W = np.array([1.0, -1.0, -1.0, 1.0])

    def _did(rows):
        c = [cell_value(vals[rows][cell[rows] == k], metric)
             for k in range(4)]
        return (W @ np.nan_to_num(np.array(c), nan=0.0)
                if all(np.isfinite(x) for x in c) else np.nan)

    point = _did(np.arange(len(vals)))
    cis, stats_by = {}, {}
    for kind, gmap in (("date", dmap), ("stock", smap)):
        keys = np.fromiter(gmap.keys(), dtype=int)
        stats = np.empty(N_BOOT)
        for b in range(N_BOOT):
            pick = RNG.choice(keys, size=len(keys), replace=True)
            rows = np.concatenate([gmap[k] for k in pick])
            stats[b] = _did(rows)
        stats_by[kind] = stats
        fin = stats[np.isfinite(stats)]
        cis[kind] = (float(np.percentile(fin, 2.5)),
                     float(np.percentile(fin, 97.5))) if len(fin) else (
            np.nan, np.nan)
    w = max(abs(cis["date"][1] - cis["date"][0]),
            abs(cis["stock"][1] - cis["stock"][0]))
    v = stats_by["date"][np.isfinite(stats_by["date"])]
    pv = float(min(1.0, 2 * min((v <= 0).mean(), (v >= 0).mean()))) if (
        len(v) and np.isfinite(point)) else np.nan
    # date-balanced DiD
    uniq = np.unique(dates)
    hi_days, lo_days = [], []
    for d in uniq:
        m = dates == d
        a = [cell_value(vals[m & (cell == k)], metric) for k in (3, 1)]
        b = [cell_value(vals[m & (cell == k)], metric) for k in (2, 0)]
        if all(np.isfinite(x) for x in a):
            hi_days.append(a[0] - a[1])
        if all(np.isfinite(x) for x in b):
            lo_days.append(b[0] - b[1])
    db = (float(np.median(hi_days) - np.median(lo_days))
          if hi_days and lo_days else np.nan)
    return {
        "stock_dim": stock_col, "market_axis": mkt_col, "horizon": h,
        "metric": metric,
        "cell_stock_hi_mkt_hi": hi_hi, "cell_stock_lo_mkt_hi": lo_hi,
        "cell_stock_hi_mkt_lo": hi_lo, "cell_stock_lo_mkt_lo": lo_lo,
        "n_hi_hi": int((cell == 3).sum()), "n_lo_hi": int((cell == 1).sum()),
        "n_hi_lo": int((cell == 2).sum()), "n_lo_lo": int((cell == 0).sum()),
        "did_contrast": point, "did_ci_lo": point - w / 2,
        "did_ci_hi": point + w / 2, "db_did_contrast": db,
        "p_two_sided_date_cluster": pv,
        "n_final": int(len(vals)),
        "note": "descriptive interaction contrast, not causal"}


def holm(pvals) -> np.ndarray:
    p = np.asarray(pvals, dtype=float)
    m = len(p)
    order = np.argsort(p, kind="stable")
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * p[i])
        adj[i] = min(1.0, running)
    return adj
