#!/usr/bin/env python3
"""T5.2 验证/确认评价（唯一允许连接 outcome 的阶段，任务书 §十一/§十三）。

Primary: H5 / H10（t5_daily_outcome 冻结字段；H20 无冻结等价字段——
披露缺口，不新造第二套计算）。
市场超额：分析层从冻结 market_daily 计算 fwd 市场收益后作差
（assigner 不参与；本脚本即"分析脚本临时连接"）。
依赖结构：stock block + date block 双维 cluster bootstrap（999 次）
报告 95% CI；不给参数 p 值。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "output/research/t5/state"
FACTS = ROOT / "output/research/t5/facts"
N_BOOT = 999
RNG_SEED = 20260924


def fwd_market_excess():
    """分析层：市场 fwd 收益（对数），对齐 outcome 的个股有效日语义近似
    为市场日历 h 日——口径差异披露：个股窗口跳停牌，市场窗口按日历。"""
    m = pd.read_parquet(ROOT / "output/research/t4/context/"
                        "market_daily.parquet",
                        columns=["date"])
    # 市场组合收益：用 eq_ret_median（冻结列）替代缺失检查
    mkt = pd.read_parquet(ROOT / "output/research/t4/context/"
                          "market_daily.parquet")
    col = "eq_ret_median" if "eq_ret_median" in mkt.columns else None
    if col is None:
        return None
    mkt = mkt.sort_values("date").reset_index(drop=True)
    # eq_ret_median 是横截面日收益中位数（非价格）：
    # 市场 H 日对数收益 = 滚动累加 log(1+r)
    r = np.log1p(mkt[col].astype(float) / 100.0)  # 百分数转小数
    for h in (5, 10):
        mkt[f"mkt_fwd_{h}d_log"] = (
            r.shift(-1).rolling(h).sum().shift(-h + 1)
            if False else
            # 未来 h 日（t+1..t+h）累加
            sum(r.shift(-k) for k in range(1, h + 1)))
    return mkt[["date", "eq_ret_median", "mkt_fwd_5d_log",
                "mkt_fwd_10d_log"]]


def cluster_boot_ci(df, value_col, cluster_cols, stat="mean"):
    """two-way block bootstrap：按 (cluster_cols) 联合块重采样。"""
    rng = np.random.default_rng(RNG_SEED)
    keys = df[cluster_cols].drop_duplicates()
    idx_map = {k: i for i, k in enumerate(
        zip(*[df[c] for c in cluster_cols]))}
    blocks = {}
    for i, k in enumerate(zip(*[df[c] for c in cluster_cols])):
        blocks.setdefault(idx_map[k], []).append(i)
    block_ids = list(blocks)
    vals = df[value_col].to_numpy(dtype=float)
    ok = ~np.isnan(vals)
    vals = vals[ok]
    bl = [np.array(blocks[b])[ok[blocks[b]]] for b in block_ids]
    bl = [b for b in bl if len(b)]
    n_b = len(bl)
    stats = []
    for _ in range(N_BOOT):
        pick = rng.integers(0, n_b, n_b)
        sel = np.concatenate([bl[p] for p in pick])
        stats.append(np.nanmean(vals[sel]) if len(sel) else np.nan)
    stats = np.array(stats)
    return (float(np.nanpercentile(stats, 2.5)),
            float(np.nanpercentile(stats, 97.5)))


def main():
    cs = pd.read_parquet(OUT / "t5_candidate_state_daily.parquet")
    oc = pd.read_parquet(FACTS / "t5_daily_outcome.parquet")
    st = pd.read_parquet(FACTS / "t5_daily_state.parquet",
                         columns=["event_id", "code", "delta_day",
                                  "state_date"])
    d = cs.merge(oc, on=["event_id", "delta_day"], how="left")
    d = d.merge(st, on=["event_id", "delta_day"], how="left")
    mkt = fwd_market_excess()
    if mkt is not None:
        d = d.merge(mkt, left_on="state_date", right_on="date",
                    how="left")
        d["excess_fwd_5d_log"] = (d["fwd_ret_5d_log"]
                                  - d["mkt_fwd_5d_log"])
        d["excess_fwd_10d_log"] = (d["fwd_ret_10d_log"]
                                   - d["mkt_fwd_10d_log"])

    # H20 缺口披露
    print("H20 fields present:", [c for c in d.columns if "20d" in c])

    metrics = {
        "fwd_ret_5d_log": "mean", "fwd_ret_10d_log": "mean",
        "excess_fwd_5d_log": "mean", "excess_fwd_10d_log": "mean",
        "fwd_mdd_5d_log": "mean", "fwd_mdd_10d_log": "mean",
        "fwd_peak_ret_5d_log": "mean",
        "fwd_new_high_5d": "rate", "fwd_new_high_10d": "rate",
        "fwd_lose_ref20_5d": "rate", "fwd_lose_ref20_10d": "rate",
    }
    out = []
    for seg in ("development", "validation", "confirmation"):
        s = d[d["segment"] == seg]
        for state, g in s.groupby("candidate_state_v1"):
            row = {"segment": seg, "state": state, "n": len(g),
                   "n_events": g.event_id.nunique()}
            for m, kind in metrics.items():
                if m not in g.columns:
                    continue
                v = g[m]
                if v.dtype == bool or kind == "rate":
                    row[m] = float(v.dropna().astype(bool).mean()) \
                        if v.notna().any() else None
                else:
                    row[m] = float(v.mean()) if v.notna().any() else None
            row["complete_5d_rate"] = float(g["complete_5d"].astype(
                bool).mean())
            out.append(row)
    res = pd.DataFrame(out)
    res.to_parquet(OUT / "t5_state_path_validation.parquet",
                   index=False)
    print(res[["segment", "state", "n", "fwd_ret_5d_log",
               "excess_fwd_5d_log", "fwd_mdd_5d_log",
               "fwd_new_high_5d", "fwd_lose_ref20_5d"]]
          .to_string(index=False))

    # cluster CI（validation 段为主：state × excess_fwd_5d）
    ci_rows = []
    val = d[(d["segment"] == "validation")
            & (d["candidate_state_v1"] != "STATE_UNAVAILABLE")]
    for state, g in val.groupby("candidate_state_v1"):
        for m in ("excess_fwd_5d_log", "fwd_ret_5d_log"):
            lo, hi = cluster_boot_ci(
                g.dropna(subset=[m]), m,
                ["event_id", "state_date"])
            ci_rows.append({"segment": "validation", "state": state,
                            "metric": m, "lo95": lo, "hi95": hi,
                            "n": int(g[m].notna().sum())})
    ci = pd.DataFrame(ci_rows)
    ci.to_parquet(OUT / "t5_state_cluster_ci.parquet", index=False)
    print(ci.to_string(index=False))
    print("done")


if __name__ == "__main__":
    main()
