"""T4.5 Exposure Response Mapping：surface、compression、counterfactual。

三步（开工令）：
- A Exposure Surface：Market 2D（breadth/new-high 中位二分 4 格）
  × Stock（load 三分位 × ref60 bool = 6）= 24 格，每格
  Reward / Risk / Persistence 三族 DB 口径 profile。
- B Compression：格级 composite evidence（多指标单调打分，全 DB）
  -> E0-E3 四档；单调性/年度/horizon 稳定性验证。
- C Counterfactual：E-class 权重 vs 真实 outcome 排序匹配
  （Spearman + 分层加权分布），不做资产曲线排名。

红线：T0-only feature；outcome 物理分离；EW 仅诊断、幅度以 DB 为准；
不训练预测分数；不加 Market-specific stock thresholds（T4.4 冻结）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))

# 格定义
M_COLS = ("M_breadth", "M_newhigh")
LOAD_Q = ("L1", "L2", "L3")

# 指标方向：+1 越大越好（reward/persistence），-1 越小越好（risk）
METRIC_DIR = {
    "median_excess": 1, "median_max_gain": 1, "p_new_high": 1,
    "median_mdd": -1, "p_lose_ref20": -1, "p_survive_t0": 1,
    "median_peak_tau": 1,
}


def build_grid_ids(panel: pd.DataFrame) -> pd.DataFrame:
    p = panel.copy()
    p["M_cell"] = (p[M_COLS[0]] >= .5).astype(int) * 2 + (
        p[M_COLS[1]] >= .5).astype(int)   # 0=lo/lo .. 3=hi/hi
    p["L_q"] = pd.qcut(p["turnover_load_t0"], 3, labels=LOAD_Q,
                       duplicates="drop")
    p["R60"] = p["t0_ref60_breakout"].astype("float")
    return p


def cell_profile_db(g: pd.DataFrame, h: int) -> dict:
    """一格一格的 DB 口径 profile：日内先聚合（median），跨日 median。"""
    out = {"n_events": int(len(g)), "n_dates": int(
        g["breakout_day"].nunique())}
    for col, name, agg in (
            ("fwd_mkt_excess_log", "median_excess", "median"),
            ("future_max_gain", "median_max_gain", "median"),
            ("future_max_drawdown", "median_mdd", "median")):
        s = g.dropna(subset=[col])
        if not len(s):
            out[name] = np.nan
            continue
        per_day = s.groupby("breakout_day")[col].median()
        out[name] = float(per_day.median()) if agg == "median" else float(
            per_day.mean())
    for col, name in (("new_high_within", "p_new_high"),
                      ("lose_ref20_within", "p_lose_ref20"),
                      ("survive_t0", "p_survive_t0")):
        s = g.dropna(subset=[col])
        if not len(s):
            out[name] = np.nan
            continue
        per_day = s.groupby("breakout_day")[col].apply(lambda x: x.astype(float).mean())
        out[name] = float(per_day.median())
    s = g.dropna(subset=["peak_tau"])
    out["median_peak_tau"] = float(
        s.groupby("breakout_day")["peak_tau"].median().median()) if len(
        s) else np.nan
    out["horizon"] = h
    return out


def composite_evidence(prof: dict) -> float:
    """格级综合证据：各指标按方向转秩分（跨格 rank 的均值，
    0-1）。解释性打分，非模型。"""
    return prof


def rank_average(df: pd.DataFrame, cols=METRIC_DIR) -> pd.Series:
    """每列按方向秩一化到 [0,1]，取均值 -> composite。"""
    parts = []
    for c, d in cols.items():
        if c not in df.columns:
            continue
        r = df[c].rank(ascending=(d > 0), pct=True)
        parts.append(r)
    return pd.concat(parts, axis=1).mean(axis=1)
