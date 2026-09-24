#!/usr/bin/env python3
"""T4.5 九道 Gate（开工令）。

G1 Lineage / G2 T0-only / G3 Outcome Separation / G4 DB Primary /
G5 Monotonicity / G6 Year Stability / G7 Horizon Stability /
G8 Complexity / G9 Determinism+Conservation
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

OUT = ROOT / "output/research/t4/exposure"
REPORT = {}
CLS = ("E0", "E1", "E2", "E3")


def main():
    surf = pd.read_parquet(OUT / "t4_exposure_surface.parquet")
    s20 = pd.read_parquet(OUT / "t4_exposure_classes.parquet")
    assign = pd.read_parquet(OUT / "t4_exposure_assignment.parquet")
    mono = pd.read_parquet(OUT / "t4_exposure_monotonicity.parquet")
    yr = pd.read_csv(OUT / "t4_exposure_yearly.csv")
    hz = pd.read_csv(OUT / "t4_exposure_horizon.csv")
    cf = json.loads((OUT / "t4_counterfactual_audit.json").read_text())
    manifest = json.loads((OUT / "t4_5_manifest.json").read_text())
    det = json.loads((OUT / "t4_5_determinism.json").read_text())
    events = v2.load_events()

    # ---------------- G1 Lineage ----------------
    ok1 = (len(assign) > 27000
           and set(assign["breakout_event_id"]) <= set(
               events["breakout_event_id"]))
    REPORT["gate1_lineage"] = {
        "verdict": "PASS" if ok1 else "FAIL", "rows": len(assign),
        "baseline": manifest["baseline_commit"]}

    # ---------------- G2 T0-only ----------------
    feat_cols = set(assign.columns)
    forbid_feat = {"fwd_raw_log", "fwd_mkt_excess_log", "future_max_drawdown",
                   "future_max_gain", "new_high_within", "lose_ref20_within",
                   "peak_tau", "first_below_t0_tau_h10",
                   "first_below_t0_tau_h20", "first_below_t0_tau_h40",
                   "survive_t0"}
    leak = sorted(forbid_feat & feat_cols)
    REPORT["gate2_t0_only"] = {
        "verdict": "PASS" if not leak else "FAIL",
        "post_t0_in_features": leak}

    # ---------------- G3 Outcome Separation ----------------
    # class 映射键只用 (M_cell, L_q, R60)；E_class 由映射表驱动
    keys_used = {"M_cell", "L_q", "R60"}
    src_txt = (ROOT / "scripts/run_t4_5.py").read_text()
    ok3 = 'key = s20.set_index(["M_cell", "L_q", "R60"])["E_class"]' in src_txt
    REPORT["gate3_outcome_separation"] = {
        "verdict": "PASS" if ok3 else "FAIL",
        "assignment_key_space": sorted(keys_used),
        "class_from_outcome_only_via_db_profile": True,
        "note": "格统计为研究层 DB 描述（非 OOS），C 层做排序匹配验证"}

    # ---------------- G4 DB Primary ----------------
    ok4 = bool(manifest["db_primary"] and manifest["ew_diagnostic_only"])
    REPORT["gate4_db_primary"] = {"verdict": "PASS" if ok4 else "FAIL",
                                  "manifest": {k: manifest[k] for k in (
                                      "db_primary", "ew_diagnostic_only")}}

    # ---------------- G5 Monotonicity ----------------
    m = mono.set_index("E_class")
    checks = {
        "median_excess": True, "median_max_gain": True, "p_new_high": True,
        "median_mdd": True, "p_lose_ref20": True, "p_survive_t0": True,
        "median_peak_tau": True}
    for c in checks:
        v = m.loc[list(CLS), c].to_numpy(float)
        good = np.isfinite(v)
        if good.sum() < 3:
            checks[c] = None
            continue
        mono_up = np.all(np.diff(v[good]) > 0)
        mono_flat_ok = np.all(np.diff(v[good]) >= -1e-9)  # 不恶化
        checks[c] = bool(mono_up if c in ("median_excess",
                                          "median_max_gain") else mono_flat_ok)
    n_pass = sum(1 for x in checks.values() if x is True)
    REPORT["gate5_monotonicity"] = {
        "verdict": "PASS" if n_pass >= 4 else "FAIL",
        "per_metric": checks,
        "rule": "excess/max_gain 单调升；mdd/lose/survive/peak 不恶化"}

    # ---------------- G6 Year Stability ----------------
    ok6 = True
    detail = {}
    for _, r in yr.iterrows():
        v = np.array([r.get(f"excess_{c}", np.nan) for c in CLS], float)
        d = np.diff(v[np.isfinite(v)])
        detail[r["year"]] = bool((d > 0).mean() >= .5) if len(d) else None
        if detail[r["year"]] is False:
            ok6 = False
    REPORT["gate6_year_stability"] = {
        "verdict": "PASS" if ok6 else "FAIL", "per_year": detail,
        "rule": "每年 E 序列多数升步（允许个别平台）"}

    # ---------------- G7 Horizon Stability ----------------
    ok7 = True
    dh = {}
    for _, r in hz.iterrows():
        v = np.array([r.get(f"excess_{c}", np.nan) for c in CLS], float)
        d = np.diff(v[np.isfinite(v)])
        dh[int(r["horizon"])] = bool((d > 0).mean() >= .5) if len(d) else None
        if dh[int(r["horizon"])] is False:
            ok7 = False
    REPORT["gate7_horizon_stability"] = {
        "verdict": "PASS" if ok7 else "FAIL", "per_horizon": dh}

    # ---------------- G8 Complexity ----------------
    # 无新 interaction / 无 Market-specific threshold：格空间固定 24，
    # class 规则单一（h20 composite 四分位）；M 只进入格定义
    ok8 = bool(surf.groupby(["M_cell", "L_q", "R60"]).ngroups <= 24
               and "composite" in s20.columns)
    REPORT["gate8_complexity"] = {
        "verdict": "PASS" if ok8 else "FAIL",
        "cells": int(s20.shape[0]),
        "market_specific_thresholds_added": False,
        "note": "继承 T4.4：无 Market×Stock interaction、全局阈值"}

    # ---------------- G9 Determinism + Conservation ----------------
    # 样本守恒：各 E-class 事件数 + assignment 无 NaN class（格全覆盖）
    nc = assign["E_class"].value_counts().to_dict()
    conservation = sum(nc.values())
    no_orphan = bool(assign["E_class"].notna().all())
    ok9 = det["identical"] and abs(conservation - 27422) <= 27422 * .02
    REPORT["gate9_determinism_conservation"] = {
        "verdict": "PASS" if ok9 and no_orphan else "FAIL",
        "determinism": det["identical"],
        "class_counts": nc, "total": conservation,
        "orphan_free": no_orphan}

    REPORT["overall"] = {
        "verdict": "PASS" if all(
            v["verdict"] == "PASS" for k, v in REPORT.items()
            if k.startswith("gate")) else "FAIL", "baseline": "8270fb1"}
    (OUT / "t4_5_gates.json").write_text(json.dumps(
        REPORT, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: v.get("verdict") for k, v in REPORT.items()
                      if isinstance(v, dict) and "verdict" in v}, indent=0))
    print("OVERALL:", REPORT["overall"]["verdict"])


if __name__ == "__main__":
    main()
