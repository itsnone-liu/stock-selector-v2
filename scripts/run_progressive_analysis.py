#!/usr/bin/env python3
"""正式递进分析入口：三组对照×收益/基准×组间统计 + 策略事件表现 + 同结构正负 + 持有期背景。

仅消费 v3 面板（契约闸门）；所有对照均为明确组间比较，不出现混合对照。
输出目录：
  designs/                     三组cohort设计表（__all全量；非重叠口径由summary/bootstrap内用）
  progressive_summary.csv      组×期限中位数/均值/胜率/样本量
  bootstrap_contrasts.json     明确组间块bootstrap（code块）
  strategy_episode_report.csv  策略事件表现（按终止原因/池龄/时滞）
  pattern_episode_report.csv   形态事件表现（独立保留）
  within_structure_contrast.csv 同结构内正/负组事前特征差异
  holding_context.csv          事件持有期市场/行业路径背景
  PROGRESSIVE_MANIFEST.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, "src")
sys.path.insert(0, "scripts")

from run_e_stage_analysis import build_market_frames  # noqa:E402
from stock_selector.research.benchmarks import attach_relative_outcomes  # noqa:E402
from stock_selector.research.background_panel import (attach_pre_context,  # noqa:E402
                                                      holding_context_metrics)
from stock_selector.research.comparisons import build_progressive_comparisons  # noqa:E402
from stock_selector.research.contrast import (HORIZONS,  # noqa:E402
                                              block_bootstrap_median_diff)
from stock_selector.research.context_join import attach_historical_membership  # noqa:E402
from stock_selector.research.momentum_panel import PANEL_VERSION  # noqa:E402
from stock_selector.research.within_structure_analysis import (  # noqa:E402
    within_structure_feature_contrast,
)

COHORT_NAMES = ["daily_increment_within_monthly_weekly",
                "weekly_state_within_daily_shape",
                "weekly_direct_within_monthly"]


def load_panel(panel_dir: Path) -> dict[str, pd.DataFrame]:
    manifest = json.loads((panel_dir / "manifest.json").read_text())
    if manifest.get("panel_version") != PANEL_VERSION:
        raise SystemExit(f"stale panel contract: expected {PANEL_VERSION}, got {manifest.get('panel_version')}")
    sig = pd.read_csv(panel_dir / "signal_panel.csv", dtype={"code": str}, low_memory=False)
    out = pd.read_csv(panel_dir / "outcome_panel.csv", dtype={"code": str}, low_memory=False)
    uni = pd.read_csv(panel_dir / "universe_state_panel.csv", dtype={"code": str}, low_memory=False)
    strat = pd.read_csv(panel_dir / "strategy_episode_panel.csv", dtype={"code": str})
    pat = pd.read_csv(panel_dir / "episode_panel.csv", dtype={"code": str})
    return {"signal": sig, "outcome": out, "universe": uni, "strategy": strat, "pattern": pat,
            "manifest": manifest}


def group_summary(frame: pd.DataFrame, horizons, group_cols=("cohort",),
                  *, comparison: str, sample_kind: str) -> pd.DataFrame:
    rows = []
    for keys, g in frame.groupby(list(group_cols), dropna=False):
        if not isinstance(keys, tuple): keys = (keys,)
        base = dict(zip(group_cols, keys))
        for h in horizons:
            v = pd.to_numeric(g.get(f"fwd{h}"), errors="coerce").dropna()
            ex = pd.to_numeric(g.get(f"industry_excess{h}"), errors="coerce").dropna()
            row = {**base, "comparison": comparison, "sample_kind": sample_kind,
                   "horizon": h, "events": len(g), "n_fwd": len(v),
                   "median_fwd": v.median() if len(v) else None,
                   "mean_fwd": v.mean() if len(v) else None,
                   "positive_rate": float((v > 0).mean()) if len(v) else None,
                   "n_excess": len(ex), "median_excess": ex.median() if len(ex) else None}
            if comparison == "weekly_direct_within_monthly":
                # 下一交易周必须使用成熟标记；未走完下一自然周的临时收益不得进入正式描述统计。
                nw_frame = g[g["matured_week"] == True] if "matured_week" in g else g.iloc[0:0]  # noqa:E712
                nw = (pd.to_numeric(nw_frame["next_week_return"], errors="coerce").dropna()
                      if "next_week_return" in nw_frame else pd.Series(dtype=float))
                row.update(next_week_n=len(nw), next_week_median=nw.median() if len(nw) else None,
                           next_week_mean=nw.mean() if len(nw) else None,
                           next_week_positive_rate=float((nw > 0).mean()) if len(nw) else None)
            rows.append(row)
    return pd.DataFrame(rows)


def pairwise_bootstrap(frame: pd.DataFrame, horizons, contrasts: list[tuple[str, str]],
                       block_col: str = "code", iterations: int = 500,
                       min_n: int = 30, group_col: str = "cohort") -> dict:
    """显式组间bootstrap；block_col可为code或date，禁止混合非目标组。"""
    res = {}
    for h in horizons:
        col = f"industry_excess{h}"
        if col not in frame:
            continue
        x = frame.dropna(subset=[col])
        for a, b in contrasts:
            ga, gb = x[x[group_col] == a], x[x[group_col] == b]
            if len(ga) >= min_n and len(gb) >= min_n:
                merged = pd.concat([ga.assign(_t=1), gb.assign(_t=0)], ignore_index=True)
                r = block_bootstrap_median_diff(merged, col, "_t", block_col=block_col,
                                                iterations=iterations)
                lo, hi = r.get("ci_low"), r.get("ci_high")
                res[f"h{h}|{a}_vs_{b}"] = {
                    "n_a": len(ga), "n_b": len(gb), "estimate": r.get("estimate"),
                    "ci_low": lo, "ci_high": hi,
                    "ci_excludes_zero": (lo is not None and hi is not None
                                         and (lo > 0 or hi < 0)),
                    "blocks": r.get("blocks"), "block_col": block_col,
                }
    return res


def strategy_report(strat: pd.DataFrame, outcome: pd.DataFrame,
                    universe: pd.DataFrame | None = None) -> pd.DataFrame:
    """策略事件从首触发日关联收益；形态事件独立，不混入。"""
    o = outcome.rename(columns={"date": "first_trigger_date"})
    keep = [c for c in ("code", "first_trigger_date") + tuple(f"fwd{h}" for h in HORIZONS)
            if c in set(o)]
    # 多个策略事件可同日首触发（sv/td并存）；outcome按(code,日期)唯一，many_to_one合法
    x = strat.merge(o[keep], on=["code", "first_trigger_date"], how="left",
                    validate="many_to_one")
    if universe is not None and {"code", "date", "monthly_pool_spell_age"} <= set(universe):
        uni = universe[["code", "date", "monthly_pool_spell_age"]].rename(
            columns={"date": "first_trigger_date"})
        x = x.merge(uni, on=["code", "first_trigger_date"], how="left", validate="many_to_one")
    rows = []
    for reason, g in x.groupby("end_reason", dropna=False):
        ages = g["monthly_pool_spell_age"].dropna() if "monthly_pool_spell_age" in g else pd.Series(dtype=float)
        row = {"end_reason": reason, "episodes": len(g),
               "median_lag": g["pattern_to_strategy_lag_sessions"].median(),
               "median_spell_age": ages.median() if len(ages) else None,
               "median_confirmations": g["consecutive_confirmations"].median(),
               "right_censored_share": float(g["right_censored"].mean())}
        for h in (1, 5, 20):
            v = pd.to_numeric(g.get(f"fwd{h}"), errors="coerce").dropna()
            row[f"median_fwd{h}"] = v.median() if len(v) else None
            row[f"positive_rate{h}"] = float((v > 0).mean()) if len(v) else None
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--panel-dir", required=True)
    p.add_argument("--membership", required=True)
    p.add_argument("--tdx-dir", default="/root/tdx_data")
    p.add_argument("--protocol", default="config/research/momentum_efficiency/protocol_v1.yaml")
    p.add_argument("--out", required=True)
    p.add_argument("--bootstrap-iterations", type=int, default=500)
    a = p.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(Path(a.protocol).read_text())["result_classification"]
    data = load_panel(Path(a.panel_dir))
    sig, outcome = data["signal"], data["outcome"]

    # ---- 基准（逐日历史行业+前收盘+尾部缓冲，与E阶段同一实现） ----
    merged0 = sig.merge(outcome, on=["code", "date"], how="left",
                        suffixes=("", "_out"), validate="one_to_one")
    memberships = pd.read_csv(a.membership, dtype={"code": str, "industry_code": str})
    start, end = str(merged0["date"].min()), str(merged0["date"].max())
    returns, prices = build_market_frames(a.tdx_dir, 0, memberships, start, end,
                                          end_buffer_sessions=max(HORIZONS))
    from stock_selector.research.benchmarks import forward_cross_section_benchmarks
    market_fwd, industry_fwd = forward_cross_section_benchmarks(prices, horizons=HORIZONS)
    from stock_selector.research.context_join import (join_industry_context,
                                                      join_market_context)
    from stock_selector.research.benchmarks import daily_cross_section_benchmarks
    market_daily, industry_daily = daily_cross_section_benchmarks(returns.dropna(subset=["return"]))

    # ---- 三组对照：设计→收益/基准关联→全量+逐期限非重叠统计 ----
    design_dir = out / "designs"; design_dir.mkdir(exist_ok=True)
    designs = build_progressive_comparisons(merged0, horizons=HORIZONS)
    summary_parts, boot_all = [], {}

    def enrich(frame):
        frame = attach_historical_membership(frame, memberships)
        return attach_relative_outcomes(frame, market_fwd, industry_fwd, horizons=HORIZONS)

    def compare(frame, name, sample_kind, horizons):
        group_cols = ("daily_trigger_type", "cohort") if name == "weekly_state_within_daily_shape" else ("cohort",)
        summary_parts.append(group_summary(frame, horizons, group_cols=group_cols,
                                            comparison=name, sample_kind=sample_kind))
        result = {}
        if name == "weekly_state_within_daily_shape":
            for shape, shaped in frame.groupby("daily_trigger_type", dropna=False):
                states = sorted(shaped["cohort"].dropna().unique())
                contrasts = [(x, y) for i, x in enumerate(states) for y in states[i + 1:]]
                for block in ("code", "date"):
                    result[f"shape={shape}|block={block}"] = pairwise_bootstrap(
                        shaped, horizons, contrasts, block_col=block,
                        iterations=a.bootstrap_iterations)
        else:
            states = sorted(frame["cohort"].dropna().unique())
            contrasts = [(x, y) for i, x in enumerate(states) for y in states[i + 1:]]
            for block in ("code", "date"):
                result[f"block={block}"] = pairwise_bootstrap(
                    frame, horizons, contrasts, block_col=block,
                    iterations=a.bootstrap_iterations)
        return result

    for name in COHORT_NAMES:
        all_frame = enrich(designs[f"{name}__all"])
        all_frame.to_csv(design_dir / f"{name}__all.csv", index=False)
        boot_all[f"{name}__all"] = compare(all_frame, name, "all", HORIZONS)
        for h in HORIZONS:
            key = f"{name}__nonoverlap_h{h}"
            no_frame = enrich(designs[key])
            no_frame.to_csv(design_dir / f"{key}.csv", index=False)
            boot_all[key] = compare(no_frame, name, f"nonoverlap_h{h}", (h,))
    pd.concat(summary_parts, ignore_index=True).to_csv(out / "progressive_summary.csv", index=False)
    (out / "bootstrap_contrasts.json").write_text(
        json.dumps(boot_all, ensure_ascii=False, indent=2, default=str))

    # ---- 策略事件表现（独立于形态事件） ----
    data["strategy"].to_csv(out / "strategy_episode_report_raw.csv", index=False)
    srep = strategy_report(data["strategy"], outcome, data["universe"])
    srep.to_csv(out / "strategy_episode_report.csv", index=False)

    # ---- 形态事件表现（单独保留，不与策略事件混表） ----
    pat = data["pattern"].rename(columns={"first_trigger_date": "date"})
    pat = pat.merge(outcome, on=["code", "date"], how="left", validate="many_to_one")
    pat_rows = []
    for stype, g in pat.groupby("signal_type"):
        row = {"signal_type": stype, "episodes": len(g)}
        for h in (1, 5, 20):
            v = pd.to_numeric(g.get(f"fwd{h}"), errors="coerce").dropna()
            row[f"median_fwd{h}"] = v.median() if len(v) else None
            row[f"positive_rate{h}"] = float((v > 0).mean()) if len(v) else None
        pat_rows.append(row)
    pd.DataFrame(pat_rows).to_csv(out / "pattern_episode_report.csv", index=False)

    # ---- 同结构正负 + 持有期背景（对照A事件日） ----
    a_rows = pd.read_csv(design_dir / "daily_increment_within_monthly_weekly__all.csv",
                         dtype={"code": str}, low_memory=False)
    a_rows = join_market_context(a_rows, market_daily)
    a_rows = join_industry_context(a_rows, industry_daily)
    a_rows = attach_pre_context(a_rows, market_daily,
                                value_columns=("market_return_med", "market_up_ratio"))
    # 池龄不作为特征（同组固定池龄会产生必然零差）；改为分段结构条件。
    a_rows["monthly_pool_age_band"] = pd.cut(
        pd.to_numeric(a_rows["monthly_pool_spell_age"], errors="coerce"),
        bins=[0, 5, 20, 60, 120, np.inf],
        labels=["1_5", "6_20", "21_60", "61_120", "121_plus"],
        include_lowest=True).astype(object)
    feats = [c for c in (
        "pre_context_market_return_med", "pre_context_market_up_ratio",
        "pre_return_20_pct", "dist_to_prior_ma20_pct", "today_close_position",
        "today_upper_shadow_pct", "t_eff", "eff_delta",
        "volume_ratio_vs_prev_week") if c in set(a_rows)]
    contrast = within_structure_feature_contrast(
        a_rows, horizon=5, feature_columns=feats,
        structure_columns=("monthly_pool_age_band", "weekly_base_pattern",
                           "weekly_weekday_path", "daily_trigger_type"))
    contrast.to_csv(out / "within_structure_contrast.csv", index=False)

    event_keys = a_rows.drop_duplicates(["code", "date"])[["code", "date"]]
    hold_market = holding_context_metrics(
        event_keys, market_daily.rename(columns={"market_return_med": "mret"})[["date", "mret"]],
        value_col="mret", horizon=5).rename(columns={
            "holding_context_mret_h5_sum": "holding_context_market_h5_sum",
            "holding_context_mret_h5_min": "holding_context_market_h5_min",
            "holding_context_mret_h5_n": "holding_context_market_h5_n",
            "holding_context_mret_h5_complete": "holding_context_market_h5_complete"})
    # 行业持有期路径按事件当日PIT行业分组计算，再与市场路径合并。
    industry_hold_parts = []
    if "industry_code" in a_rows and "industry_code" in industry_daily:
        for ind, eg in a_rows.drop_duplicates(["code", "date", "industry_code"]).groupby("industry_code"):
            ctx = industry_daily[industry_daily["industry_code"] == ind]
            if ctx.empty: continue
            part = holding_context_metrics(
                eg[["code", "date"]], ctx.rename(columns={"industry_return_med": "iret"})[["date", "iret"]],
                value_col="iret", horizon=5)
            part["industry_code"] = ind
            industry_hold_parts.append(part)
    hold_ind = pd.concat(industry_hold_parts, ignore_index=True) if industry_hold_parts else pd.DataFrame()
    if not hold_ind.empty:
        hold_ind = hold_ind.rename(columns={
            "holding_context_iret_h5_sum": "holding_context_industry_h5_sum",
            "holding_context_iret_h5_min": "holding_context_industry_h5_min",
            "holding_context_iret_h5_n": "holding_context_industry_h5_n",
            "holding_context_iret_h5_complete": "holding_context_industry_h5_complete"})
    hold_market.to_csv(out / "holding_context.csv", index=False)
    if not hold_ind.empty:
        hold_market.merge(hold_ind, on=["code", "date"], how="left").to_csv(
            out / "holding_context.csv", index=False)

    manifest = {"panel_dir": str(a.panel_dir), "panel_version": PANEL_VERSION,
                "horizons": list(HORIZONS), "bootstrap_iterations": a.bootstrap_iterations,
                "events_signal": len(sig), "strategy_episodes": len(data["strategy"]),
                "pattern_episodes": len(data["pattern"]),
                "neutral_band": float(cfg["excess_return_neutral_band"]),
                "bootstrap_min_n": 30,
                "median_note": "组内median不跨分项相加；恒等分解仅均值成立",
                "note": "全部对照为明确组间比较；混合对照已被禁用；不回写选股逻辑"}
    (out / "PROGRESSIVE_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    print(json.dumps({k: manifest[k] for k in
                      ("events_signal", "strategy_episodes", "pattern_episodes")}, default=str))


if __name__ == "__main__":
    main()
