#!/usr/bin/env python3
"""T5.2 开发样本研究（Development = breakout_year 2024，任务书 §五）。

产出：
1) t5_delta_dependency_audit.parquet  候选 primitive 分布 × delta_day
2) t5_axes_dev_distribution.parquet    五轴单变量分布（dev）
3) t5_axes_dev_conditional.parquet     条件分布（P×V、P×E、D×V、pullback×E）
4) 控制台摘要（用于规则设计）

不读取 t5_daily_outcome（G4：规则生成阶段禁 outcome）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from t5.state_axes import AUDIT_NUM, AUDIT_BOOL  # noqa: E402

OUT = ROOT / "output/research/t5/state"
OUT.mkdir(parents=True, exist_ok=True)

Q = [0.10, 0.25, 0.50, 0.75, 0.90]


def main():
    st = pd.read_parquet(ROOT / "output/research/t5/facts/"
                         "t5_daily_state.parquet",
                         columns=["event_id", "code", "delta_day",
                                  "year", "exposure_class"] + AUDIT_NUM
                         + AUDIT_BOOL)
    dev = st[st["year"].astype(str) == "2024"].copy()
    print(f"dev rows={len(dev)} events={dev.event_id.nunique()}")

    # --- delta dependency audit（dev 全体 + 全样本参考）-------------
    parts = []
    for scope, d in (("dev_2024", dev), ("all_years", st)):
        g = d.groupby("delta_day")
        for col in AUDIT_NUM:
            q = g[col].quantile(Q).unstack("level_1") if False else \
                g[col].quantile(Q).unstack(0).T
            q.columns = [f"q{int(c * 100)}" for c in Q]
            q.insert(0, "primitive", col)
            q.insert(0, "n", g[col].count())
            q.insert(0, "n_missing", g[col].apply(lambda s: s.isna().sum()))
            q["scope"] = scope
            parts.append(q.reset_index())
    aud = pd.concat(parts, ignore_index=True)
    aud.to_parquet(OUT / "t5_delta_dependency_audit.parquet",
                   index=False)

    # drift 摘要：每 primitive 的 delta 0/10/20/40 分位数对照
    print("\n=== delta drift (dev_2024, median [q10..q90]) ===")
    for col in AUDIT_NUM:
        sub = aud[(aud["primitive"] == col) & (aud["scope"] == "dev_2024")
                  & (aud["delta_day"].isin([0, 5, 10, 20, 40]))]
        if not len(sub):
            continue
        line = " | ".join(
            f"d{int(r.delta_day)}: {r.q50:+.3f} "
            f"[{r.q10:+.3f},{r.q90:+.3f}]"
            for r in sub.itertuples())
        print(f"{col:34s} {line}")

    # --- 五轴单变量分布（dev，按 delta 分箱：0-2/3-5/6-10/11-20/21-40）
    dev["dbin"] = pd.cut(dev["delta_day"], [-1, 2, 5, 10, 20, 40],
                         labels=["0-2", "3-5", "6-10", "11-20", "21-40"])
    uni = []
    for col in AUDIT_NUM:
        q = dev.groupby("dbin", observed=True)[col].quantile(
            Q).unstack(level=-1)
        q.columns = [f"q{int(c * 100)}" for c in Q]
        q["mean"] = dev.groupby("dbin", observed=True)[col].mean()
        q.insert(0, "primitive", col)
        uni.append(q.reset_index())
    for col in AUDIT_BOOL:   # 频数审计：True 率
        m = dev.groupby("dbin", observed=True)[col].apply(
            lambda s: s.astype(bool).mean() if len(s) else np.nan)
        q = m.to_frame("true_rate")
        q.insert(0, "primitive", col)
        uni.append(q.reset_index())
    pd.concat(uni, ignore_index=True).to_parquet(
        OUT / "t5_axes_dev_distribution.parquet", index=False)

    # --- 条件分布：P×V / P×E / D×V / pullback×E ---------------------
    # 维度（全部 dev 分位或天然锚点，仅用于观察，不冻结）
    P_dim = pd.cut(dev["cum_ret_from_t0_log"], [-np.inf, 0.0, np.inf])
    V_dim = pd.cut(dev["turnover_load_3d_mean"],
                   [-np.inf, 1.0, np.inf])       # anchor=1（pre20 基准）
    E_dim = pd.cut(dev["efficiency_signed_3"], [-np.inf, 0.0, np.inf])
    D_dim = pd.cut(dev["drawdown_from_peak_log"],
                   [0.0, 0.05, 0.10, 0.15, np.inf])  # 深度为正；观察 bin
    cond = []
    for name, dims in (("P_x_V", (P_dim, V_dim)), ("P_x_E", (P_dim, E_dim)),
                       ("D_x_V", (D_dim, V_dim))):
        c = (dev.groupby([dims[0], dims[1]], observed=True)
             .agg(n=("event_id", "size"),
                  fwd_unavailable=("event_id", "size"),
                  mean_dd=("drawdown_from_peak_log", "mean"),
                  mean_eff3=("efficiency_signed_3", "mean"),
                  mean_load=("turnover_load_vs_prebreak", "mean"),
                  mean_ret5=("ret_5d_log", "mean"))
             .drop(columns=["fwd_unavailable"]).reset_index())
        for axc in c.columns[:2]:
            c[axc] = c[axc].astype(str)
        c.insert(0, "pair", name)
        cond.append(c)
    pd.concat(cond, ignore_index=True).to_parquet(
        OUT / "t5_axes_dev_conditional.parquet", index=False)

    # pullback × 效率（回调深度分位 × efficiency）
    pb = pd.cut(dev["drawdown_from_peak_log"],
                [-np.inf, 0.03, 0.05, 0.08, 0.12, np.inf])
    pbe = (dev.groupby(pb, observed=True)
           .agg(n=("event_id", "size"),
                mean_eff3=("efficiency_signed_3", "mean"),
                med_eff3=("efficiency_signed_3", "median"),
                mean_contract=("turnover_contraction_3d", "mean"),
                mean_load3=("turnover_load_3d_mean", "mean"),
                med_days_since_peak=("days_since_peak", "median"),
                med_dist_ref20=("dist_to_ref20", "median"))
           .reset_index())
    pbe["drawdown_from_peak_log"] = pbe[
        "drawdown_from_peak_log"].astype(str)
    pbe.insert(0, "pair", "pullback_x_E")
    pbe.to_parquet(OUT / "t5_axes_dev_pullback_eff.parquet",
                   index=False)

    print("\n=== P×V (dev) ===")
    print(cond[0].to_string(index=False))
    print("\n=== P×E (dev) ===")
    print(cond[1].to_string(index=False))
    print("\n=== pullback×E (dev) ===")
    print(pbe.to_string(index=False))
    print("\nwritten:", sorted(p.name for p in OUT.glob("*.parquet")))


if __name__ == "__main__":
    main()
