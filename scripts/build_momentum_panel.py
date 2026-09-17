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
from stock_selector.research.episodes import build_episode_panel
from stock_selector.research.momentum_panel import (
    PANEL_VERSION,
    SIGNAL_RULESET,
    attach_outcomes,
    build_panel,
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

    # 交易日采样：用指数日线做真实日历
    dates_idx = store.daily(codes[0]) if codes else None
    if dates_idx is None:
        raise SystemExit("no daily data")
    all_days = pd.DatetimeIndex(dates_idx.index)
    days = all_days[(all_days >= pd.Timestamp(a.start)) & (all_days <= pd.Timestamp(a.end))]
    days = days[:: a.every]
    dates = [datetime.combine(d.date(), datetime.min.time()).replace(hour=15, minute=30) for d in days]

    panel, stats = build_panel(store, codes, dates, config)
    panel.to_csv(out / "signal_panel.csv", index=False)
    episodes = build_episode_panel(panel)
    episodes.to_csv(out / "episode_panel.csv", index=False)
    manifest = {
        "panel_version": PANEL_VERSION,
        "signal_ruleset": SIGNAL_RULESET,
        "config_hash": panel_config_hash(config),
        "start": a.start, "end": a.end, "every": a.every,
        "stocks": len(codes), "dates": len(dates), "stats": stats,
        "horizons": list(horizons), "episode_rows": len(episodes),
        "note": "研究面板不自动晋升生产；条件闭合前结果仅作工程校验和假设生成",
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(stats, ensure_ascii=False))

    outcomes = attach_outcomes(store, panel, horizons=horizons)
    outcomes.to_csv(out / "outcome_panel.csv", index=False)
    print(f"outcome rows: {len(outcomes)}")


if __name__ == "__main__":
    main()
