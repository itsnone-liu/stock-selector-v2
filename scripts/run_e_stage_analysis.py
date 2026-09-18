#!/usr/bin/env python3
"""E阶段正式分析入口：事件层正负/路径/归因（只消费冻结面板，不改信号）。

流程：
  episode首触发事件 × 信号证据 × 结果面板
  → 历史行业（有效期关联，重叠报错）
  → 全市场/行业横截面基准（TDX全量日线，中位数口径）
  → 市场/行业前视超额
  → 当日市场/行业背景（宽度）
  → 正中负 + 五路径标注 → 分层汇总 + 股票/日期块bootstrap
输出 E_STAGE_MANIFEST.json + CSV 组。

用法（冒烟）:
  PYTHONPATH=src python scripts/run_e_stage_analysis.py \
    --panel-dir output/research/momentum_panel_smoke \
    --membership /root/project/workspace/capital-observer/output/research_context/membership_history.csv \
    --tdx-dir /root/tdx_data --bench-limit 800 --out output/research/e_stage_smoke
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from stock_selector.data.tdx import TdxStore
from stock_selector.research.benchmarks import (attach_relative_outcomes,
                                                daily_cross_section_benchmarks,
                                                forward_cross_section_benchmarks)
from stock_selector.research.contrast import HORIZONS, grouped_contrast, label_contrast_rows
from stock_selector.research.context_join import (attach_historical_membership,
                                                  join_industry_context,
                                                  join_market_context)
from stock_selector.research.comparisons import build_progressive_comparisons
from stock_selector.research.momentum_panel import PANEL_VERSION


def load_events(panel_dir: Path) -> pd.DataFrame:
    sig = pd.read_csv(panel_dir / "signal_panel.csv", dtype={"code": str}, low_memory=False)
    out = pd.read_csv(panel_dir / "outcome_panel.csv", dtype={"code": str}, low_memory=False)
    ep = pd.read_csv(panel_dir / "episode_panel.csv", dtype={"code": str})
    first = ep.rename(columns={"first_trigger_date": "date"})
    x = first.merge(sig, on=["code", "date"], how="left", validate="many_to_one")
    x = x.merge(out, on=["code", "date"], how="left", suffixes=("", "_out"), validate="many_to_one")
    return x


def build_market_frames(tdx_dir: str, limit: int, memberships: pd.DataFrame,
                        start: str, end: str, *, end_buffer_sessions: int = 20):
    """全市场日收益/收盘长表；逐日历史行业，尾部为前视窗口留足行情。"""
    store = TdxStore(tdx_dir)
    codes = sorted(store.list_codes())
    if limit:
        codes = codes[:limit]
    ret_rows, close_rows = [], []
    for c in codes:
        df = store.daily(c)
        if df is None or df.empty:
            continue
        df = df.sort_index()
        # 收益先在完整序列计算，避免截窗首日因缺前收盘而丢失。
        full_return = df["close"].astype(float).pct_change()
        idx = pd.to_datetime(df.index)
        end_pos = idx.searchsorted(pd.Timestamp(end), side="right")
        stop = min(len(idx), end_pos + end_buffer_sessions)
        begin = idx.searchsorted(pd.Timestamp(start), side="left")
        if begin >= stop:
            continue
        take = slice(begin, stop)
        d = idx[take].strftime("%Y-%m-%d")
        ret_rows.append(pd.DataFrame({"code": c, "date": d,
                                      "return": full_return.iloc[take].to_numpy()}))
        close_rows.append(pd.DataFrame({"code": c, "date": d,
                                        "close": df["close"].iloc[take].astype(float).to_numpy()}))
    returns = pd.concat(ret_rows, ignore_index=True)
    prices = pd.concat(close_rows, ignore_index=True)
    # 事件侧与基准侧复用同一PIT有效期关联，保证行业历史口径对称。
    returns = attach_historical_membership(returns, memberships)
    prices = attach_historical_membership(prices, memberships)
    return returns, prices


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--panel-dir", required=True)
    p.add_argument("--membership", required=True)
    p.add_argument("--tdx-dir", default="/root/tdx_data")
    p.add_argument("--bench-limit", type=int, default=0, help="基准股票数上限（冒烟用）")
    p.add_argument("--protocol", default="config/research/momentum_efficiency/protocol_v1.yaml")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(Path(a.protocol).read_text())["result_classification"]
    source_manifest = json.loads((Path(a.panel_dir) / "manifest.json").read_text())
    if source_manifest.get("panel_version") != PANEL_VERSION:
        raise SystemExit(f"stale panel contract: expected {PANEL_VERSION}, got {source_manifest.get('panel_version')}")
    # 新三对照先构造并落盘；收益汇总仍以独立outcome阶段连接。
    signal_all = pd.read_csv(Path(a.panel_dir) / "signal_panel.csv", dtype={"code": str}, low_memory=False)
    designs = build_progressive_comparisons(signal_all, horizons=HORIZONS)
    design_dir = out / "designs"; design_dir.mkdir(exist_ok=True)
    for name, frame in designs.items():
        frame.to_csv(design_dir / f"{name}.csv", index=False)

    events = load_events(Path(a.panel_dir))
    memberships = pd.read_csv(a.membership, dtype={"code": str, "industry_code": str})
    events = attach_historical_membership(events, memberships)

    start, end = str(events["date"].min()), str(events["date"].max())
    returns, prices = build_market_frames(a.tdx_dir, a.bench_limit, memberships, start, end,
                                          end_buffer_sessions=max(HORIZONS))
    market_daily, industry_daily = daily_cross_section_benchmarks(returns.dropna(subset=["return"]))
    market_fwd, industry_fwd = forward_cross_section_benchmarks(prices, horizons=HORIZONS)

    events = attach_relative_outcomes(events, market_fwd, industry_fwd, horizons=HORIZONS)
    events = join_market_context(events, market_daily)
    events = join_industry_context(events, industry_daily)
    events["half"] = pd.to_datetime(events["date"]).dt.to_period("2Q").astype(str)
    events["market_context"] = np.where(events["market_return_med"].isna(), "unknown",
                                        np.select([events["market_down3_ratio"] > .3,
                                                   events["market_up_ratio"] > .7],
                                                  ["market_shock_down", "market_broad_up"],
                                                  default="market_normal"))
    events["industry_context"] = np.where(events["industry_return_med"].isna(), "unknown",
                                          np.select([events["industry_up_ratio"] > .7,
                                                     events["industry_up_ratio"] < .3],
                                                    ["industry_broad_up", "industry_broad_down"],
                                                    default="industry_normal"))
    events = label_contrast_rows(events, horizons=HORIZONS,
                                 delta=float(cfg["excess_return_neutral_band"]),
                                 meaningful_mfe=float(cfg["meaningful_mfe"]),
                                 deep_mae=float(cfg["deep_mae"]))
    events.to_csv(out / "e_stage_events.csv", index=False)

    groups = [g for g in ["signal_type", "weekly_base_pattern", "weekly_weekday_path",
                          "weekly_eligibility_state", "industry_code", "market_context",
                          "industry_context", "half"] if g in events.columns]
    tables = []
    for g in groups:
        t = grouped_contrast(events, [g], horizons=HORIZONS)
        t.insert(0, "dimension", g); tables.append(t)
    summary = pd.concat(tables, ignore_index=True)
    summary.to_csv(out / "e_stage_summary.csv", index=False)

    # 禁止恢复旧的 eligible-vs-all-noneligible 混合主对照；
    # 正式对照只存在于 designs/ 三组明确cohort，统计脚本按各自cohort两两比较。
    (out / "e_stage_bootstrap.json").write_text(json.dumps({
        "status": "not_run",
        "reason": "bootstrap must consume explicit progressive design cohorts; mixed noneligible control is forbidden"
    }, ensure_ascii=False, indent=2))

    manifest = {"panel_dir": str(a.panel_dir), "events": len(events),
                "bench_codes": int(prices["code"].nunique()),
                "membership_coverage": float(events["industry_code"].notna().mean()),
                "groups": groups,
                "eligibility_counts": events["weekly_eligibility_state"].value_counts(dropna=False).to_dict()}
    (out / "E_STAGE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
