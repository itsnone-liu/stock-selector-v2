"""T4.4 结构发现分析：市场二维性、M→S、M×S、三层可加性。

工具：Tukey median polish（纯 numpy 可加分解）——行效+列效+交互残差，
用于判断 response surface 是否可加（§5 连续结构发现的稳健替代，
不建预测器）。DiD 与 Q 趋势沿用 T4.3 的双 estimand + 双簇 bootstrap。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

RNG = np.random.default_rng(20260925)
N_BOOT = 300


def median_polish(table: np.ndarray, max_iter: int = 10):
    """table: R×C（NaN 允许）。返回 (grand, row_eff, col_eff, resid,
    收敛信息)。加性拟合: fit = grand + row_eff[i] + col_eff[j]，
    resid = table - fit；交互强度 = RMS(resid)/RMS(fit - grand)。"""
    t = np.where(np.isfinite(table), table, 0.0)
    mask = np.isfinite(table)
    grand = 0.0
    row_eff = np.zeros(table.shape[0])
    col_eff = np.zeros(table.shape[1])
    for _ in range(max_iter):
        for i in range(table.shape[0]):
            m = mask[i]
            if m.any():
                med = np.median(t[i][m])
                row_eff[i] += med
                t[i][m] -= med
        for j in range(table.shape[1]):
            m = mask[:, j]
            if m.any():
                med = np.median(t[:, j][m])
                col_eff[j] += med
                t[:, j][m] -= med
    m = mask
    if m.any():
        g = np.median(t[m])
        grand += g
        t[m] -= g
    fit = grand + row_eff[:, None] + col_eff[None, :]
    resid = np.where(mask, table - fit, np.nan)
    denom = np.sqrt(np.nanmean((fit - grand) ** 2))
    numer = np.sqrt(np.nanmean(resid ** 2))
    ratio = float(numer / denom) if denom > 1e-12 else np.nan
    return grand, row_eff, col_eff, resid, ratio


def q4_minus_q1_ew_db(values: np.ndarray, grp: np.ndarray,
                       dates: np.ndarray, stocks: np.ndarray,
                       boot: bool = True):
    """EW Q4−Q1（date/stock 双簇 bootstrap CI + p）与 DB 差，
    复用 T4.3 语义。grp=0/1。"""
    def _cells(rows):
        a = values[rows][grp[rows] == 1]
        b = values[rows][grp[rows] == 0]
        a = a[np.isfinite(a)]
        b = b[np.isfinite(b)]
        if not len(a) or not len(b):
            return np.nan
        return float(np.median(a) - np.median(b))

    point = _cells(np.arange(len(values)))
    duniq, dinv = np.unique(dates, return_inverse=True)
    suniq, sinv = np.unique(stocks, return_inverse=True)
    idx = np.arange(len(values))
    dmap = {k: idx[dinv == k] for k in range(len(duniq))}
    smap = {k: idx[sinv == k] for k in range(len(suniq))}
    cis, pv = {"date": (np.nan, np.nan), "stock": (np.nan, np.nan)}, np.nan
    if boot:
        for kind, gmap in (("date", dmap), ("stock", smap)):
            keys = np.fromiter(gmap.keys(), dtype=int)
            stats = np.empty(N_BOOT)
            for b in range(N_BOOT):
                pick = RNG.choice(keys, size=len(keys), replace=True)
                rows = np.concatenate([gmap[k] for k in pick])
                stats[b] = _cells(rows)
            fin = stats[np.isfinite(stats)]
            if len(fin):
                cis[kind] = (float(np.percentile(fin, 2.5)),
                             float(np.percentile(fin, 97.5)))
        w = max(abs(cis["date"][1] - cis["date"][0]),
                abs(cis["stock"][1] - cis["stock"][0]))
        # 零分布取 date-cluster 重采样分布
        _ = []
        for b in range(N_BOOT):
            pick = np.fromiter(dmap.keys(), dtype=int)
            pick = RNG.choice(pick, size=len(pick), replace=True)
            rows = np.concatenate([dmap[k] for k in pick])
            _.append(_cells(rows))
        v = np.array([x for x in _ if np.isfinite(x)])
        if len(v) and np.isfinite(point):
            pv = float(min(1.0, 2 * min((v <= 0).mean(), (v >= 0).mean())))
    # DB
    uniq = np.unique(dates)
    a_days, b_days = [], []
    for d in uniq:
        m = dates == d
        a = values[m & (grp == 1)]
        b = values[m & (grp == 0)]
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if len(a):
            a_days.append(np.median(a))
        if len(b):
            b_days.append(np.median(b))
    db = (float(np.median(a_days) - np.median(b_days))
          if a_days and b_days else np.nan)
    lo = point - (max(abs(cis['date'][1] - cis['date'][0]),
                      abs(cis['stock'][1] - cis['stock'][0])) / 2
                  if np.isfinite(cis['date'][0]) else np.nan)
    return {"ew": point, "ew_ci_lo": lo,
            "ew_ci_hi": point + (lo - point) if np.isfinite(lo) else np.nan,
            "db": db, "p_date_cluster": pv}


def conditional_contrast(panel: pd.DataFrame, cond_col: str, cond_vals: tuple,
                         axis_col: str, value_col: str) -> dict:
    """在 cond_col ∈ cond_vals 子样本内做 axis Q4−Q1（EW/DB/bootstrap）。"""
    sub = panel[panel[cond_col].isin(cond_vals)
                & panel[axis_col].isin(["Q1", "Q4"])
                & panel[value_col].notna()]
    vals = sub[value_col].astype(float).to_numpy()
    grp = (sub[axis_col] == "Q4").astype(int).to_numpy()
    dates = sub["breakout_day"].to_numpy()
    stocks = sub["code"].to_numpy()
    return q4_minus_q1_ew_db(vals, grp, dates, stocks)
