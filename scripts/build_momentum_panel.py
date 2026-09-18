#!/usr/bin/env python3
"""P1 面板构建入口：月线主池全量证据 + 下一日/下一周收益（研究，不动生产）。

用法：
  PYTHONPATH=src python scripts/build_momentum_panel.py --start 2024-01-01 --end 2026-09-01 \
      [--limit N] [--every K] [--out output/research/momentum_panel]
特征面板先落盘冻结（含配置哈希与规则集标识），收益面板独立生成。
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from stock_selector.config import load_config
from stock_selector.data.tdx import TdxStore
from stock_selector.research.episodes import build_episode_panel, build_strategy_episode_panel
from stock_selector.research.momentum_panel import (
    PANEL_VERSION,
    SIGNAL_RULESET,
    attach_outcomes,
    build_panel_with_universe,
    panel_config_hash,
)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--start", required=True)
    p.add_argument("--end", required=True)
    p.add_argument("--tdx-dir", default="/root/tdx_data")
    p.add_argument("--limit", type=int, default=0, help="限制股票数（冒烟用）")
    p.add_argument("--every", type=int, default=1, help="每 K 个交易日采样一次")
    p.add_argument("--out", default="output/research/momentum_panel")
    p.add_argument("--horizons", default="1,2,3,5,10,15,20",
                   help="未来交易日窗口，逗号分隔（默认: 1,2,3,5,10,15,20）")
    p.add_argument("--batch", type=int, default=250,
                   help="每批股票数（流式落盘，控内存）")
    a = p.parse_args()
    horizons = tuple(sorted({int(x) for x in a.horizons.split(",") if x.strip()}))
    if not horizons or any(h <= 0 for h in horizons):
        raise SystemExit("--horizons must be positive integers")

    config = load_config()
    store = TdxStore(a.tdx_dir)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)

    codes = sorted(store.list_codes())
    if a.limit:
        codes = codes[: a.limit]
    if not codes:
        raise SystemExit("no codes to build")

    # 完整市场交易日历来自指数日线（与个股缺bar/研究区间无关）；
    # 采样日期从市场日历抽取，session_index按市场日历定位，--every不再压缩时间轴。
    market_calendar = store.market_calendar()
    calendar_source = "index_sh000001"
    if market_calendar is None:
        first = store.daily(codes[0]) if codes else None
        if first is None:
            raise SystemExit("no daily data for calendar")
        market_calendar = pd.DatetimeIndex(first.index)
        calendar_source = "first_stock_fallback"
    all_days = market_calendar
    days = all_days[(all_days >= pd.Timestamp(a.start)) & (all_days <= pd.Timestamp(a.end))]
    days = days[:: a.every]
    dates = [datetime.combine(d.date(), datetime.min.time()).replace(hour=15, minute=30) for d in days]

    # 分批流式构建：按股票批次生成→落盘→释放，3GB内存机器跑不下列表全量累积。
    batch_size = a.batch
    total_stats = {"stocks": 0, "stocks_with_data": 0, "monthly_pool_hits": 0,
                   "monthly_pool_out": 0, "monthly_pool_unknown": 0,
                   "rows": 0, "universe_rows": 0, "missing_current_bar": 0, "panel_version": PANEL_VERSION,
                   "signal_ruleset": SIGNAL_RULESET}
    outcome_rows = 0
    sig_path, out_path = out / "signal_panel.csv", out / "outcome_panel.csv"
    universe_path = out / "universe_state_panel.csv"
    for path in (sig_path, out_path, universe_path):
        path.unlink(missing_ok=True)
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        panel, universe, stats = build_panel_with_universe(store, batch, dates, config,
                                                           trading_calendar=market_calendar)
        outcomes = attach_outcomes(store, panel, horizons=horizons)
        panel.to_csv(sig_path, mode="a", index=False, header=not sig_path.exists())
        outcomes.to_csv(out_path, mode="a", index=False, header=not out_path.exists())
        universe.to_csv(universe_path, mode="a", index=False, header=not universe_path.exists())
        outcome_rows += len(outcomes)
        for k in ("stocks", "stocks_with_data", "monthly_pool_hits", "monthly_pool_out",
                  "monthly_pool_unknown", "rows", "universe_rows", "missing_current_bar"):
            total_stats[k] += stats.get(k, 0)
        del panel, universe, outcomes
        print(f"batch {i // batch_size + 1}: codes {batch[0]}-{batch[-1]} "
              f"rows {stats.get('rows', 0)} total {total_stats['rows']}", flush=True)

    # episode折叠只读轻量列（内存友好）
    slim = pd.read_csv(sig_path, usecols=["code", "date", "sv_legacy", "td_legacy"],
                       dtype={"code": str})
    episodes = build_episode_panel(slim)
    episodes.to_csv(out / "episode_panel.csv", index=False)
    strategy_cols = ["code", "date", "weekly_eligibility_state", "sv_legacy", "td_legacy"]
    strategy_signal = pd.read_csv(sig_path, usecols=strategy_cols, dtype={"code": str})
    universe = pd.read_csv(universe_path, dtype={"code": str})
    strategy_episodes = build_strategy_episode_panel(strategy_signal, universe)
    strategy_episodes.to_csv(out / "strategy_episode_panel.csv", index=False)
    manifest = {
        "panel_version": PANEL_VERSION,
        "signal_ruleset": SIGNAL_RULESET,
        "config_hash": panel_config_hash(config),
        "start": a.start, "end": a.end, "every": a.every,
        "stocks": len(codes), "dates": len(dates), "stats": total_stats,
        "horizons": list(horizons), "episode_rows": len(episodes),
        "strategy_episode_rows": len(strategy_episodes),
        "universe_rows": total_stats["universe_rows"],
        "outcome_rows": outcome_rows, "batch_size": batch_size,
        "pattern_episode_scope": "monthly_pool_only",
        "strategy_episode_max_unknown_gap": 5,
        "sampling_every_sessions": a.every,
        "calendar_source": calendar_source,
        "note": "研究面板不自动晋升生产；条件闭合前结果仅作工程校验和假设生成",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(total_stats, ensure_ascii=False))
    print(f"outcome rows: {outcome_rows}")


if __name__ == "__main__":
    main()
