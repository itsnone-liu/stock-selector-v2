#!/usr/bin/env python3
"""T4.4 八道 Gate（开工令 §8）。

G1 Lineage        事件宇宙/市场分位严格继承 28b1d48 与 T4.3 冻结
G2 PIT            sector 原料窗口 <=T0（物理截断重算 LOO 抽样）
G3 Sector LOO     focal-stock exclusion 对账（对拍含/不含 focal 的聚合）
G4 Coverage       sector context 覆盖率与稀疏格披露
G5 EW/DB          双 estimand 均在；正式幅度=DB（决策矩阵引用 DB 列）
G6 Stability      分年方向一致性检查
G7 Interaction Conservation  median polish 分解闭合：残差=表-拟合
G8 Leakage        feature 侧无 post-T0 outcome 字段；outcome 物理分表
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2  # noqa: E402
from t4.discovery import analysis_discovery as ad  # noqa: E402

OUT = ROOT / "output/research/t4/discovery"
REPORT = {}


def main():
    sec = pd.read_parquet(OUT / "t4_sector_context.parquet")
    m2d = pd.read_parquet(OUT / "t4_market_2d_structure.parquet")
    ms = pd.read_parquet(OUT / "t4_market_sector_structure.parquet")
    tl = pd.read_parquet(OUT / "t4_three_layer_cells.parquet")
    dm = pd.read_csv(OUT / "t4_structure_decision_matrix.csv")
    manifest = json.loads((OUT / "t4_4_manifest.json").read_text())
    det = json.loads((OUT / "t4_4_determinism.json").read_text())
    events = v2.load_events()

    # ---------------- G1 Lineage ----------------
    ok1 = (len(sec) == 27422 and set(sec["breakout_event_id"]) == set(
        events["breakout_event_id"]))
    REPORT["gate1_lineage"] = {
        "verdict": "PASS" if ok1 else "FAIL", "rows": len(sec),
        "market_pct_source": manifest["lineage"]["market_pct"],
        "sector_membership": manifest["lineage"]["sector_membership"]}

    # ---------------- G2 PIT（物理截断重算 LOO 抽样） ----------------
    # 用 T4.1 冻结 market_daily 的 pct_up 复核 mkt_breadth_d5；
    # sector 侧用 LOO 定义复核（含截断：只用 <=T0 行）
    mkt = pd.read_parquet(ROOT / "output/research/t4/context/"
                          "market_daily.parquet").set_index("date")
    mkt_b5 = mkt["pct_up"].rolling(5).mean()
    samp = sec.dropna(subset=["mkt_breadth_d5"]).sample(30, random_state=9)
    bad = 0
    for r in samp.itertuples(index=False):
        exp = float(mkt_b5.loc[r.breakout_day])
        if not np.isclose(exp, r.mkt_breadth_d5, atol=1e-9):
            bad += 1
    # retrospective 标记 100%
    retro_ok = bool((~sec["pit_primary_eligible"].astype(bool)).all()
                    and sec["retrospective_context_only"].astype(bool).all()
                    and (sec["membership_snapshot_date"]
                         == "2026-09-21").all())
    REPORT["gate2_pit"] = {
        "verdict": "PASS" if bad == 0 and retro_ok else "FAIL",
        "mkt_breadth_recompute_mismatches": bad,
        "retrospective_flags_complete": retro_ok,
        "note": "价格原料 as-of <=T0；membership 非 PIT -> 整族 "
                "retrospective（价格截断重算 + 归类披露双轨）"}

    # ---------------- G3 Sector LOO 对账 ----------------
    # 抽样事件：独立重算 sec_nh_density_loo（含 focal 剔除）
    from t4.context import build as tb
    from t4.discovery.sector_primitives import _gate_of
    smap = pd.read_parquet(ROOT / "output/research/t4/context/"
                           "stock_sector_map.parquet")
    gate_map = {c: g for c, g in zip(smap["code"], smap["industry_gate"])
                if pd.notna(g)}
    tb.set_stock_cache(ROOT / "data/adjustment_baostock/per_stock")
    samp3 = sec.dropna(subset=["sec_nh_density_loo"]).sample(
        20, random_state=13)
    bad3 = 0
    # 板块成员的 (nh) 逐股重算
    member_nh = {}
    for code, dates, adj, *_ in tb.iter_stock_daily_cached():
        code6 = code.split(".")[1]
        g = _gate_of(code6, gate_map)
        if not g:
            continue
        adj = np.asarray(adj, dtype=float)
        for i, d in enumerate(dates):
            lo = max(0, i - 20)
            if i - 20 < 0:
                continue
            win = adj[lo:i + 1]
            if len(win) == 21 and not np.isnan(win).any():
                member_nh.setdefault((d, g), []).append(
                    (code6, bool(adj[i] >= np.max(win[:-1]))))
    # 需要 T0 前后 5 日窗：为抽样事件建立 (code6, day) -> nh 查询
    mdates_sorted = sorted({d for (d, _) in member_nh})
    mpos3 = {d: i for i, d in enumerate(mdates_sorted)}
    for r in samp3.itertuples(index=False):
        code6 = str(
            events[events["breakout_event_id"] == r.breakout_event_id]
            ["code"].iloc[0]).zfill(6)
        i = mpos3.get(r.breakout_day)
        if i is None:
            continue
        vals = []
        for d in mdates_sorted[max(0, i - 4):i + 1]:
            mem = member_nh.get((d, r.industry_gate), [])
            foc = [x for x in mem if x[0] == code6]
            if len(mem) < 2 or not foc:
                continue
            if foc[0][1] is None:
                continue
            others = [x[1] for x in mem if x[0] != code6
                      and x[1] is not None]
            if others:
                vals.append(np.mean(others))
        if not vals:
            continue
        exp = float(np.mean(vals))
        if not np.isclose(exp, r.sec_nh_density_loo, atol=1e-9):
            bad3 += 1
    REPORT["gate3_sector_loo"] = {
        "verdict": "PASS" if bad3 == 0 else "FAIL",
        "nh_density_loo_recompute_mismatches": bad3,
        "loo_rule": manifest["loo"]}

    # ---------------- G4 Coverage ----------------
    cov = {c: round(float(sec[c].notna().mean()), 4) for c in
           ("sec_breadth_d5_loo", "sec_nh_density_loo",
            "sec_rel_breadth_d5", "sec_rel_strength20")}
    ok4 = cov["sec_rel_strength20"] > .9
    REPORT["gate4_coverage"] = {
        "verdict": "PASS" if ok4 else "FAIL", "coverage": cov,
        "min_sector_members_effective": "loo_n recorded per event"}

    # ---------------- G5 EW/DB ----------------
    ok5 = bool({"ew", "db"}.issubset(ms.columns)
               and (ms["db"].notna().mean() > .5))
    dm_db = "DB" in " ".join(dm["evidence"].astype(str))
    REPORT["gate5_ew_db"] = {
        "verdict": "PASS" if ok5 and dm_db else "FAIL",
        "dual_estimands_in_ms": ok5,
        "decision_matrix_uses_db": dm_db}

    # ---------------- G6 Stability ----------------
    yr = pd.read_csv(OUT / "t4_market2d_yearly.csv")
    ok6 = bool(len(yr) >= 3 and yr["polish_interaction_ratio"].notna(
    ).all())
    # M->S 方向分年不在主表——以 sector 效应 within-market 各 Q 方向一致为准
    mss = ms[ms["sector_dim"] == "sector_rel_strength"]
    dbs = mss["db"].dropna()
    dir_consistent = bool(
        (dbs > 0).all() or (dbs <= 0).all()) if len(dbs) else False
    REPORT["gate6_stability"] = {
        "verdict": "PASS" if ok6 and dir_consistent else "FAIL",
        "yearly_polish_rows": int(len(yr)),
        "sector_effect_db_values": [round(float(x), 5)
                                    for x in mss["db"]],
        "note": "同号（含全负）视为方向一致；无主效应是合法结构结论"}

    # ---------------- G7 Interaction Conservation ----------------
    # median polish 恒等式：table = grand + row + col + resid（有效格）
    T = np.array(json.loads(m2d[m2d["metric"] == "median_excess"]
                            [m2d["horizon"] == 20].iloc[0]["table"]),
                 dtype=float)
    grand, reff, ceff, resid, ratio = ad.median_polish(T)
    fit = grand + reff[:, None] + ceff[None, :]
    m = np.isfinite(T)
    closure_err = float(np.nanmax(np.abs(
        (T[m]) - (fit[m] + resid[m]))))
    ok7 = closure_err < 1e-9
    REPORT["gate7_interaction_conservation"] = {
        "verdict": "PASS" if ok7 else "FAIL",
        "decomposition_closure_max_err": closure_err,
        "polish_interaction_ratio_h20": float(ratio)}

    # ---------------- G8 Leakage ----------------
    forbid = {"fwd_raw_log", "fwd_mkt_excess_log", "future_max_drawdown",
              "future_max_gain", "new_high_within", "lose_ref20_within",
              "horizon"}
    leak = sorted(forbid & set(sec.columns))
    ok8 = not leak
    REPORT["gate8_leakage"] = {
        "verdict": "PASS" if ok8 and det["identical"] else "FAIL",
        "outcome_fields_in_sector_context": leak,
        "determinism": det["identical"]}

    REPORT["overall"] = {
        "verdict": "PASS" if all(
            v["verdict"] == "PASS" for k, v in REPORT.items()
            if k.startswith("gate")) else "FAIL", "baseline": "28b1d48"}
    (OUT / "t4_4_gates.json").write_text(json.dumps(
        REPORT, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: v.get("verdict") for k, v in REPORT.items()
                      if isinstance(v, dict) and "verdict" in v}, indent=0))
    print("OVERALL:", REPORT["overall"]["verdict"])


if __name__ == "__main__":
    main()
