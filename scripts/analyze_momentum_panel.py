#!/usr/bin/env python3
"""P1 分析：日动能→下一日、周效率→下一周、周日协同（报告表生成）。

输入 build_momentum_panel.py 的 signal_panel + outcome_panel。
所有表逐格给出有效样本量；未成熟窗口不入胜率分母。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

CELL_NAMES = {"0_0": "月线池基准(周否_日否)", "1_0": "周线独立", "0_1": "日线独立", "1_1": "周日协同"}
DAY_COLS = ["overnight_gap", "next_day_open_to_close", "fwd1", "fwd2", "fwd3", "fwd30",
            "peak3_return", "giveback_from_peak3", "mae3_full", "mfe3_full"]
WEEK_COLS = ["next_week_open_gap", "next_week_return", "next_week_high", "next_week_low"]


def _agg(g: pd.DataFrame, cols: list[str]) -> dict:
    out: dict = {"n": int(len(g))}
    for c in cols:
        s = g[c].dropna()
        out[f"{c}_med"] = round(float(s.median()), 5) if len(s) else None
        out[f"{c}_pos"] = round(float((s > 0).mean()), 4) if len(s) else None
    return out


def by_group(m: pd.DataFrame, key: str, cols: list[str]) -> pd.DataFrame:
    rows = []
    for val, g in m.groupby(key, dropna=False):
        rows.append({key: val, **_agg(g, cols)})
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", default="output/research/momentum_panel")
    a = p.parse_args()
    d = Path(a.dir)
    out_dir = d / "analysis"
    out_dir.mkdir(exist_ok=True, parents=True)

    sig = pd.read_csv(d / "signal_panel.csv", dtype={"code": str})
    out = pd.read_csv(d / "outcome_panel.csv", dtype={"code": str})
    m = out.merge(sig, on=["code", "date"], suffixes=("", "_sig"))
    m["half"] = m["date"].str[:4] + "H" + np.where(m["date"].str[5:7].astype(int) <= 6, "1", "2")

    tables: dict = {}
    # ---- 1. 主对照：2×2 格，下一日 + 下一周 ----
    day_m = m[m["matured_1"] == True]  # noqa: E712
    week_m = m[m["matured_week"] == True]  # noqa: E712
    rows = []
    for cell, g in day_m.groupby("weekly_daily_cell"):
        wg = week_m[week_m["weekly_daily_cell"] == cell]
        rows.append({"cell": cell, "name": CELL_NAMES.get(cell, cell),
                     **_agg(g, DAY_COLS), **{f"wk_{k}": v for k, v in _agg(wg, WEEK_COLS).items() if k != "n"}})
    tables["cell_main"] = pd.DataFrame(rows)

    # ---- 2. 日动能 → 下一日：原版标签 vs 上限拆分 ----
    for key in ["sv_raw", "sv_legacy", "td_raw", "td_legacy", "sv_continuation", "sv_rebound",
                "acc_continuation", "acc_rebound", "activity_state"]:
        if key in m.columns:
            tables[f"day_{key}"] = by_group(day_m, key, DAY_COLS)

    # ---- 3. 周效率 → 下一周 ----
    for key in ["weekly_passed", "weekly_base_pattern", "weekly_weekday_path", "weekly_veto"]:
        tables[f"week_{key}"] = by_group(week_m, key, WEEK_COLS)
    m2 = week_m.copy()
    m2["eff_bucket"] = pd.cut(m2["eff_delta"], [-np.inf, -2, 0, 2, np.inf],
                              labels=["<-2", "-2~0", "0~2", ">2"])
    tables["week_eff_delta_bucket"] = by_group(m2, "eff_bucket", WEEK_COLS)

    # ---- 4. 半年稳定性（主格） ----
    tables["cell_by_half"] = by_group(day_m, ["half", "weekly_daily_cell"] if False else "half", DAY_COLS)
    rows = []
    for (half, cell), g in day_m.groupby(["half", "weekly_daily_cell"]):
        rows.append({"half": half, "cell": cell, **_agg(g, ["fwd1", "fwd3", "peak3_return"])})
    tables["cell_half_detail"] = pd.DataFrame(rows)
    rows = []
    for (half, wp), g in week_m.groupby(["half", "weekly_passed"]):
        rows.append({"half": half, "weekly_passed": wp, **_agg(g, WEEK_COLS)})
    tables["week_half_detail"] = pd.DataFrame(rows)

    # ---- 5. 覆盖披露 ----
    tables["coverage"] = pd.DataFrame([{
        "signal_rows": len(sig), "outcome_rows": len(out),
        "matured_1": int(m["matured_1"].sum()), "matured_3": int(m["matured_3"].sum()),
        "matured_30": int(m["matured_30"].sum()), "matured_week": int(m["matured_week"].sum()),
        "unique_codes": sig["code"].nunique(), "unique_dates": sig["date"].nunique(),
    }])

    summary = {}
    for name, t in tables.items():
        t.to_csv(out_dir / f"{name}.csv", index=False)
        summary[name] = len(t)
    (out_dir / "tables_index.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    # 快照打印主表
    with pd.option_context("display.width", 220, "display.max_columns", 60):
        print("\n=== 主对照（周日 2×2） ===")
        print(tables["cell_main"].to_string(index=False))


if __name__ == "__main__":
    main()
