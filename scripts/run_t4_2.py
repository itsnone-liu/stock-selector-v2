#!/usr/bin/env python3
"""T4.2 T0 State Table 构建 + 产物 + manifest + 双跑。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2  # noqa: E402
from t4.features import build_t0 as fb          # noqa: E402

BASELINE = "ca5e2a8"
OUT = ROOT / "output/research/t4/t0_state"
FEATURE_VERSION = "t4_t0_state_v1"


def frame_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(
        df.astype(str), index=True).values.tobytes())
    h.update(str(df.shape).encode())
    h.update(str(list(df.columns)).encode())
    return h.hexdigest()


def feature_dictionary() -> pd.DataFrame:
    """字段级 metadata（开工令 §六）：机器可读，sector 字段 pit=false。"""
    D = []

    def add(name, family, source, window, rule, pit, unit, missing,
            note=""):
        D.append({"feature_name": name, "feature_family": family,
                  "source_table": source, "source_window": window,
                  "max_source_date_rule": rule,
                  "pit_eligible": pit, "retrospective_only": not pit,
                  "unit": unit, "missing_semantics": missing, "note": note})

    add("breakout_event_id", "key", "v6 events (28f7aed)", "-", "-",
        True, "-", "never missing")
    add("code", "key", "v6 events", "-", "-",
        True, "-", "never missing")
    add("breakout_day", "key", "v6 events", "-", "-",
        True, "date", "never missing")
    add("end_day", "key", "v6 events", "-", "-",
        True, "date", "never missing")
    for c, fam, unit, note in (
            ("distance_to_ref20", "A_price_structure", "log",
             "V5 frozen: log(close_t0/ref20)"),
            ("distance_to_ref60", "A_price_structure", "log",
             "V5 frozen: log(close_t0/ref60)"),
            ("t0_ref60_breakout", "A_price_structure", "bool",
             "V5 frozen: close_t0>ref60 at t0"),
            ("close_vs_anchored_vwap", "A_price_structure", "log",
             "V5 frozen: log(close_t0/anchored_vwap)"),
            ("close_rel_t0_log", "A_price_structure", "log",
             "V5 frozen; degenerate at tau0 (=0)"),
            ("drawdown_from_running_peak", "A_price_structure", "log",
             "V5 frozen; degenerate at tau0 (=0)"),
            ("days_since_running_peak", "A_price_structure", "days",
             "V5 frozen; degenerate at tau0 (=0)"),
            ("new_high_count_t0", "A_price_structure", "count",
             "V5 frozen; degenerate at tau0 (=0)"),
            ("ref20_obs_n", "A_price_structure", "count",
             "V5 frozen obs window length"),
            ("anchored_vwap_obs_n", "A_price_structure", "count",
             "V5 frozen obs window length"),
            ("pre20_turn_base", "B_turnover_baseline", "turn/day",
             "V3 frozen: mean turn over 20 stock-data days before t0"),
            ("t0_turn", "B_turnover_baseline", "turn",
             "V5 frozen cum_turnover_since_t0 @tau0"),
            ("mean_turnover_since_t0", "B_turnover_baseline", "turn/day",
             "degenerate at tau0 (=t0_turn)"),
            ("turn_n_to_tau", "B_turnover_baseline", "count",
             "degenerate at tau0 (=1)"),
            ("cum_turnover_raw", "B_turnover_baseline", "turn",
             "V5 frozen raw accumulation @tau0"),
            ("t0_volume", "B_volume_amount", "shares",
             "baostock unadj volume @t0"),
            ("t0_amount", "B_volume_amount", "yuan",
             "baostock unadj amount @t0"),
            ("pre20_volume_base", "B_volume_amount", "shares/day",
             "mean volume over 20 stock-data days before t0"),
            ("pre20_amount_base", "B_volume_amount", "yuan/day",
             "mean amount over 20 stock-data days before t0"),
            ("volume_load_t0", "C_normalized_participation", "ratio",
             "t0_volume/pre20_volume_base (deterministic primitive)"),
            ("turnover_load_t0", "C_normalized_participation", "ratio",
             "V5 frozen turnover_load_to_tau @tau0 (=t0_turn/pre20_turn_base)"
             "; doubles as B-family t0 turnover ratio (single definition)"),
            ("mean_turnover_load_to_tau", "C_normalized_participation",
             "ratio", "degenerate at tau0 (=turnover_load_t0)"),
            ("price_progress", "D_efficiency", "log",
             "V5 frozen formula; degenerate at tau0 (=0)"),
            ("efficiency_proxy", "D_efficiency", "log/ratio",
             "V5 frozen: price_progress/max(load,0.25); degenerate at tau0"),
            ("mkt_ret_20d", "E_market_context", "pct",
             "T4.1: index 20-market-day return ending t0"),
            ("mkt_amount_pctile_60d", "E_market_context", "percentile",
             "T4.1: market amount percentile in 60d window ending t0"),
            ("mkt_breadth_5d", "E_market_context", "fraction",
             "T4.1: mean pct_up over 5 days ending t0"),
            ("mkt_day_amount_yi", "E_market_context", "yi yuan",
             "T4.1 market_daily @t0 row"),
            ("mkt_day_pct_up", "E_market_context", "fraction",
             "T4.1 market_daily @t0 row"),
            ("mkt_day_eq_ret_median", "E_market_context", "pct",
             "T4.1 market_daily @t0 row"),
            ("mkt_day_new_high_20d", "E_market_context", "count",
             "T4.1 market_daily @t0 row"),
            ("stock_ret_20d", "E_market_context", "pct",
             "adjusted-close 20d return ending t0 (stock itself, PIT)"),
            ("row_present", "QA_flag", "bool", "V5 frozen availability flag"),
            ("adj_factor_available", "QA_flag", "bool", "V5 frozen availability flag"),
            ("volume_valid", "QA_flag", "bool", "V5 frozen availability flag"),
            ("turn_base_available", "QA_flag", "bool", "V5 frozen availability flag"),
            ("load_available", "QA_flag", "bool", "V5 frozen availability flag"),
            ("load_identity_ok", "QA_flag", "bool", "V5 frozen identity flag")):
        src = ("v5 svd @tau0" if fam != "E_market_context"
               else "t4.1 context/market_daily")
        add(c, fam, src, "ending t0", "max_source_date <= t0",
            True, unit, "null if source missing", note)
    add("pit_primary_eligible", "metadata", "derived", "-", "-",
        True, "bool", "never missing", "table-level PIT marker")
    # sector retrospective（companion 表）
    for c, unit in (("industry_gate", "category"),
                    ("sector_ret_20d", "pct"),
                    ("sector_vs_mkt_20d", "pct"),
                    ("stock_vs_sector_20d", "pct")):
        add(c, "E_sector_context_retrospective",
            "t4.1 context (csrc snapshot 2026-09-21)", "ending t0",
            "membership not point-in-time", False, unit,
            "null if no mapping / sector window insufficient",
            "retrospective_context_only: membership from 2026-09-21 "
            "snapshot; forbidden in PIT primary research")
    add("is_point_in_time", "metadata", "-", "-", "-",
        False, "bool", "-", "always false for sector table")
    add("retrospective_context_only", "metadata", "-", "-", "-",
        False, "bool", "-", "always true for sector table")
    add("membership_snapshot_date", "metadata", "-", "-", "-",
        False, "date", "-", "2026-09-21")
    return pd.DataFrame(D)


def field_coverage(t: pd.DataFrame, sc: pd.DataFrame) -> pd.DataFrame:
    rows = []
    reason = {
        "distance_to_ref20": "svd tau0 null (ref20 obs window insufficient)",
        "t0_volume": "t0 row missing in per-stock library",
        "pre20_volume_base": "fewer than 20 valid pre-t0 rows",
        "volume_load_t0": "t0 volume or baseline missing/zero",
        "sector_ret_20d": "no gate mapping or sector window insufficient",
        "stock_vs_sector_20d": "stock 20d series broken or sector null",
    }
    for c in t.columns:
        if c in ("breakout_event_id", "code", "breakout_day", "end_day",
                 "pit_primary_eligible"):
            continue
        rows.append({"feature_name": c, "n_valid": int(t[c].notna().sum()),
                     "n_missing": int(t[c].isna().sum()),
                     "coverage": round(float(t[c].notna().mean()), 4),
                     "missing_reason": reason.get(c, "source null")})
    for c in sc.columns:
        if c in ("breakout_event_id", "pit_primary_eligible",
                 "is_point_in_time", "retrospective_context_only",
                 "membership_snapshot_date"):
            continue
        rows.append({"feature_name": f"[sector] {c}",
                     "n_valid": int(sc[c].notna().sum()),
                     "n_missing": int(sc[c].isna().sum()),
                     "coverage": round(float(sc[c].notna().mean()), 4),
                     "missing_reason": reason.get(
                         c, "no mapping or window insufficient")})
    return pd.DataFrame(rows)


def main():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    assert head == BASELINE, f"HEAD {head} != baseline {BASELINE}"
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    events = v2.load_events()
    print(f"[t4.2] events {len(events)}", flush=True)

    prods = fb.build_t0_state(events)
    t, sc = prods["t4_t0_state"], prods["t4_t0_sector_retrospective"]
    print(f"[t4.2] t0_state {t.shape}, sector_retrospective {sc.shape} "
          f"{time.time() - t0:.0f}s", flush=True)

    prods2 = fb.build_t0_state(events)
    det = {
        "t4_t0_state": frame_hash(t) == frame_hash(prods2["t4_t0_state"]),
        "sector_retrospective": frame_hash(
            sc) == frame_hash(prods2["t4_t0_sector_retrospective"]),
    }
    (OUT / "t4_2_determinism.json").write_text(json.dumps(
        {"identical": all(det.values()), "frames": det}, indent=2))

    t.to_parquet(OUT / "t4_t0_state.parquet", index=False)
    sc.to_parquet(OUT / "t4_t0_sector_retrospective.parquet", index=False)
    fd = feature_dictionary()
    fd.to_csv(OUT / "t4_t0_feature_dictionary.csv", index=False)
    fc = field_coverage(t, sc)
    fc.to_csv(OUT / "t4_t0_field_coverage.csv", index=False)

    manifest = {
        "stage": "T4.2_t0_state", "baseline_commit": BASELINE,
        "feature_definition_version": FEATURE_VERSION,
        "v6_frozen_source": "events @28f7aed (inherited via v2.load_events)",
        "v5_source": "state_vector_daily @tau0 exact slice",
        "t4_1_source": "output/research/t4/context @ca5e2a8",
        "mapping_snapshot_date": "2026-09-21",
        "rows": len(t), "sector_rows": len(sc),
        "columns": list(t.columns),
        "determinism": det,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (OUT / "t4_t0_manifest.json").write_text(json.dumps(
        manifest, indent=2, ensure_ascii=False))
    print(json.dumps({k: manifest[k] for k in (
        "rows", "sector_rows", "determinism", "elapsed_sec")}, indent=2),
        flush=True)


if __name__ == "__main__":
    main()
