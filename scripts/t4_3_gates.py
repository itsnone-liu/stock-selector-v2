#!/usr/bin/env python3
"""T4.3 七道 Gate（开工令 §二十三）。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2  # noqa: E402
from t4.path import build_outcomes as bo        # noqa: E402

OUT = ROOT / "output/research/t4/context_path"
REPORT = {}


def main():
    cs = pd.read_parquet(OUT / "t4_context_state.parquet")
    oc = pd.read_parquet(OUT / "t4_context_path_outcomes.parquet")
    mc = pd.read_parquet(OUT / "t4_market_context_contrasts.parquet")
    ic = pd.read_parquet(OUT / "t4_context_interactions.parquet")
    src = pd.read_parquet(OUT / "t4_sector_retrospective_contrasts.parquet")
    manifest = json.loads((OUT / "t4_context_manifest.json").read_text())
    det = json.loads((OUT / "t4_3_determinism.json").read_text())
    dep = json.loads((OUT / "t4_context_dependency_audit.json").read_text())
    events = v2.load_events()
    t0 = pd.read_parquet(ROOT / "output/research/t4/t0_state/"
                         "t4_t0_state.parquet")

    # ---------------- G1 Event Conservation ----------------
    ids = set(events["breakout_event_id"])
    ok1 = (len(cs) == 27422 and cs["breakout_event_id"].is_unique
           and set(cs["breakout_event_id"]) == ids
           and set(oc["breakout_event_id"]) == ids)
    REPORT["gate1_event_conservation"] = {
        "verdict": "PASS" if ok1 else "FAIL", "rows": len(cs),
        "outcome_events": oc["breakout_event_id"].nunique()}

    # ---------------- G2 Context PIT ----------------
    # asof percentile 只用 <T0：物理截断重算抽样
    m = bo.market_daily_breadth()
    dates = list(m.index)
    pos = {d: i for i, d in enumerate(dates)}
    series = {"breadth_5d": m["breadth_5d_daily"].to_numpy(float),
              "amount_yi": m["mkt_amount_yi"].to_numpy(float),
              "new_high_20d": m["new_high_20d_count"].to_numpy(float)}
    samp = cs.sample(40, random_state=5)
    bad = 0
    for r in samp.itertuples(index=False):
        i = pos[r.breakout_day]
        for k, arr in series.items():
            v = getattr(r, f"{k}_asof_pct")
            hist = arr[:i]
            hist = hist[~np.isnan(hist)]
            if len(hist) >= bo.MIN_HISTORY:
                exp = float((hist < arr[i]).mean())
                if not np.isclose(exp, v, atol=1e-12):
                    bad += 1
    rank_ok = bool(cs["context_rank_available"].dtype == bool)
    # rank 不足 120 天的事件必须 null
    short = cs[cs[f"breadth_5d_history_n"] < bo.MIN_HISTORY]
    null_ok = bool(short[f"breadth_5d_asof_pct"].isna().all()) if len(
        short) else True
    REPORT["gate2_context_pit"] = {
        "verdict": "PASS" if bad == 0 and null_ok else "FAIL",
        "asof_recompute_mismatches": bad, "checked_cells":
            len(samp) * 3,
        "short_history_events_null": null_ok,
        "n_short_history": int(len(short)),
        "rule": "expanding percentile, market dates < T0, min 120 days"}

    # ---------------- G3 State Reconciliation ----------------
    t0i = t0.set_index("breakout_event_id").sort_index()
    csi = cs.set_index("breakout_event_id").sort_index()
    bad3 = []
    for c in ("turnover_load_t0", "t0_ref60_breakout", "distance_to_ref60",
              "pre20_turn_base", "mkt_breadth_5d", "mkt_day_amount_yi",
              "mkt_day_new_high_20d", "code", "breakout_day"):
        a, b = csi[c], t0i[c]
        if pd.api.types.is_numeric_dtype(a):
            mm = int((~np.isclose(a.astype(float).fillna(-9e18),
                                  b.astype(float).fillna(-9e18),
                                  rtol=1e-10, atol=1e-10)).sum())
        else:
            mm = int((a.astype(str).fillna("__NA__")
                      != b.astype(str).fillna("__NA__")).sum())
        if mm:
            bad3.append((c, mm))
    REPORT["gate3_state_reconciliation"] = {
        "verdict": "PASS" if not bad3 else "FAIL",
        "columns_checked": 9, "mismatches": bad3}

    # ---------------- G4 Outcome Reconciliation ----------------
    recon = json.loads(
        (OUT / "t4_context_outcome_reconciliation.json").read_text())
    ok4 = not recon["any_mismatch"]
    REPORT["gate4_outcome_reconciliation"] = {
        "verdict": "PASS" if ok4 else "FAIL",
        "overlapping": ["h5", "h10", "h20"],
        "metrics": ["fwd_raw_log", "fwd_mkt_excess_log",
                    "future_max_drawdown", "future_max_gain",
                    "new_high_within", "lose_ref20_within"],
        "h40_basis": "V3 frozen daily + V4 frozen formula "
                     "(calibrated on H<=20, 0 mismatch)"}

    # ---------------- G5 Context/Outcome Isolation ----------------
    ctx_cols = set(cs.columns)
    oc_cols = set(oc.columns)
    forbid = {"fwd_raw_log", "fwd_mkt_excess_log", "future_max_drawdown",
              "future_max_gain", "new_high_within", "lose_ref20_within"}
    leak_outcome_in_ctx = sorted(forbid & ctx_cols)
    state_cols = {"turnover_load_t0", "t0_ref60_breakout",
                  "distance_to_ref20", "mkt_breadth_5d"}
    leak_state_in_outcome = sorted(state_cols & oc_cols)
    REPORT["gate5_isolation"] = {
        "verdict": "PASS" if not leak_outcome_in_ctx
        and not leak_state_in_outcome else "FAIL",
        "outcome_fields_in_context_state": leak_outcome_in_ctx,
        "state_fields_in_outcomes": leak_state_in_outcome}

    # ---------------- G6 Dependency / Weighting ----------------
    ew_db = bool(mc["db_q4_minus_q1"].notna().any()
                 and mc["ew_q4_minus_q1"].notna().any())
    ci_cols = bool({"ew_ci_lo", "ew_ci_hi"} <= set(mc.columns)
                   and {"did_ci_lo", "did_ci_hi"} <= set(ic.columns))
    dep_ok = bool(dep["cluster_design"]["primary"] == "breakout_day "
                  "date cluster" and dep["dual_estimands"] == [
                      "event-weighted", "date-balanced"])
    REPORT["gate6_dependency_weighting"] = {
        "verdict": "PASS" if ew_db and ci_cols and dep_ok else "FAIL",
        "dual_estimands_present": ew_db,
        "two_cluster_cis_present": ci_cols,
        "dependency_audit_complete": dep_ok,
        "events_per_date_median": dep["events_per_date_median"],
        "events_per_date_p95": dep["events_per_date_p95"]}

    # ---------------- G7 Determinism ----------------
    REPORT["gate7_determinism"] = {
        "verdict": "PASS" if det["identical"] else "FAIL", **det}

    REPORT["overall"] = {
        "verdict": "PASS" if all(
            v["verdict"] == "PASS" for k, v in REPORT.items()
            if k.startswith("gate")) else "FAIL",
        "baseline": "c605a39"}
    (OUT / "t4_context_gates.json").write_text(json.dumps(
        REPORT, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: v.get("verdict") for k, v in REPORT.items()
                      if isinstance(v, dict) and "verdict" in v}, indent=0))
    print("OVERALL:", REPORT["overall"]["verdict"])


if __name__ == "__main__":
    main()
