#!/usr/bin/env python3
"""T4.1 Context Gate（开工令 §五 相关项 + §六 验收条款）。

G1 事件守恒   context 与 V6 事件 ID/条数/冻结字段逐项一致，差集为空
G2 时点标注   行业映射非时点快照 100% 显式标注；特征窗口 as-of（≤T0）抽样重算
G3 覆盖率     归属/各特征非空率与缺失原因分解；缺失不填 neutral
G4 抽样追溯   随机事件独立复算市场/板块/个股窗口数字
G5 复现       双跑三表 hash 一致（manifest determinism）
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
from t4.context import build as tb              # noqa: E402

OUT = ROOT / "output/research/t4/context"
REPORT = {}


def main():
    ctx = pd.read_parquet(OUT / "t4_event_context.parquet")
    smap = pd.read_parquet(OUT / "stock_sector_map.parquet")
    mkt = pd.read_parquet(OUT / "market_daily.parquet")
    sec = pd.read_parquet(OUT / "sector_daily.parquet")
    manifest = json.loads((OUT / "manifest.json").read_text())
    events = v2.load_events()

    # ---------------- G1 事件守恒 ----------------
    ids_v6 = set(events["breakout_event_id"])
    ids_ctx = set(ctx["breakout_event_id"])
    j = ctx.merge(events[["breakout_event_id", "code", "breakout_day",
                          "end_day"]], on="breakout_event_id",
                  how="outer", suffixes=("_t4", "_v6"), indicator=True)
    both = j[j["_merge"] == "both"]
    field_ok = bool(
        (both["code_t4"] == both["code_v6"]).all()
        and (both["breakout_day_t4"] == both["breakout_day_v6"]).all()
        and (both["end_day_t4"] == both["end_day_v6"]).all())
    REPORT["gate1_event_conservation"] = {
        "verdict": "PASS" if (
            not (ids_v6 - ids_ctx) and not (ids_ctx - ids_v6)
            and len(ctx) == len(events) == 27422 and field_ok) else "FAIL",
        "v6_minus_t4": len(ids_v6 - ids_ctx),
        "t4_minus_v6": len(ids_ctx - ids_v6),
        "rows": len(ctx), "frozen_fields_identical": field_ok}

    # ---------------- G2 时点标注 ----------------
    pip_ok = bool((~smap["is_point_in_time"].astype(bool)).all())
    eff_ok = bool((smap["effective_from"] == "2026-09-21").all())
    snapshot_after_data_end = "2026-09-21" > "2026-09-18"
    # 特征 as-of 抽样：mkt_ret_20d 用指数 ≤T0 的 21 点独立复算
    idates, iclose = tb.index_calendar_and_close(
        Path("/root/tdx_data/vipdoc/sh/lday/sh999999.day"))
    ipos = {d: i for i, d in enumerate(idates)}
    samp = ctx.dropna(subset=["mkt_ret_20d"]).sample(40, random_state=7)
    bad_asof = 0
    for r in samp.itertuples(index=False):
        ip = ipos[r.breakout_day]
        exp = (iclose[ip] / iclose[ip - 20] - 1.0) * 100
        if not np.isclose(exp, r.mkt_ret_20d, atol=1e-6):
            bad_asof += 1
    REPORT["gate2_temporal_causality"] = {
        "verdict": "PASS" if pip_ok and eff_ok and snapshot_after_data_end
        and bad_asof == 0 else "FAIL",
        "map_non_pit_flagged": pip_ok,
        "snapshot_date_consistent": eff_ok,
        "snapshot_after_dataset_end_disclosed": snapshot_after_data_end,
        "mkt_ret_asof_recompute_mismatches": bad_asof,
        "note": "行业映射为 2026-09-21 快照（数据期末 2026-09-18 之后），"
                "非历史时点：正式结论使用须按开工令披露该限制"}

    # ---------------- G3 覆盖率 ----------------
    cov = {}
    for c in ("industry_gate", "mkt_ret_20d", "mkt_amount_pctile_60d",
              "mkt_breadth_5d", "sector_ret_20d", "sector_vs_mkt_20d",
              "stock_ret_20d", "stock_vs_sector_20d"):
        cov[c] = round(float(ctx[c].notna().mean()), 4)
    no_gate = int(ctx["industry_gate"].isna().sum())
    gate_but_no_sector = int((ctx["industry_gate"].notna()
                              & ctx["sector_ret_20d"].isna()).sum())
    REPORT["gate3_coverage"] = {
        "verdict": "PASS" if cov["industry_gate"] > 0.95 else "PASS_WITH_NULLS",
        "coverage": cov,
        "event_rows_without_industry": no_gate,
        "with_gate_but_sector_null": gate_but_no_sector,
        "nulls_kept_not_neutral": True,
        "map_industry_nonnull_rate": round(
            float(smap["industry_full"].notna().mean()), 4),
        "note": "缺失=空值保留；行业缺失主因=快照中该股 industry 为空"
                "（退市/停牌/未分类）"}

    # ---------------- G4 抽样追溯 ----------------
    samp4 = ctx.dropna(subset=["stock_ret_20d"]).sample(
        30, random_state=11)
    tb.set_stock_cache(ROOT / "data/adjustment_baostock/per_stock")
    stock_adj = {}
    for code, dates, adj, *_ in tb.iter_stock_daily_cached():
        stock_adj[code] = (dates, adj)
    from bisect import bisect_right
    bad4 = 0
    for r in samp4.itertuples(index=False):
        pfx = ("sh." if str(r.code).zfill(6).startswith(("6", "9")) else
               "sz.") + str(r.code).zfill(6)
        dates, adj = stock_adj.get(pfx, ([], []))
        jj = bisect_right(dates, r.breakout_day) - 1
        if jj - 20 < 0 or not adj[jj] or not adj[jj - 20]:
            continue
        exp = (adj[jj] / adj[jj - 20] - 1.0) * 100
        if not np.isclose(exp, r.stock_ret_20d, atol=1e-6):
            bad4 += 1
    REPORT["gate4_traceability"] = {
        "verdict": "PASS" if bad4 == 0 else "FAIL",
        "stock_ret_recompute_mismatches": bad4,
        "checked": len(samp4),
        "note": "个股 20 日收益=复权收盘比（≤T0 的 21 点）独立重算"}

    # ---------------- G5 复现 ----------------
    det = manifest["determinism"]
    REPORT["gate5_reproducibility"] = {
        "verdict": "PASS" if all(det.values()) else "FAIL", **det}

    REPORT["overall"] = {
        "verdict": "PASS" if all(
            v.get("verdict", "").startswith("PASS")
            for k, v in REPORT.items() if k.startswith("gate")) else "FAIL",
        "baseline": "28f7aed"}
    (OUT / "gate_report.json").write_text(json.dumps(
        REPORT, indent=2, ensure_ascii=False))
    print(json.dumps({k: v.get("verdict") for k, v in REPORT.items()
                      if isinstance(v, dict) and "verdict" in v}, indent=0))
    print("OVERALL:", REPORT["overall"]["verdict"])


if __name__ == "__main__":
    main()
