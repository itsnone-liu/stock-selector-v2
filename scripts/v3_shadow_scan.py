#!/usr/bin/env python3
"""运行V3 P1盘后影子扫描；不改变原生产筛选输出。"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stock_selector.config import load_config  # noqa: E402
from stock_selector.data.tdx import TdxStore  # noqa: E402
from stock_selector.shadow_scan import shadow_scan  # noqa: E402
from stock_selector.watchlist import WatchStore  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--as-of", default=datetime.now().date().isoformat())
    p.add_argument("--db", default="state/v3_watch.db")
    args = p.parse_args()
    cfg = load_config(ROOT / args.config)
    tdx = TdxStore(cfg["paths"]["tdx_dir"])
    frames = {}
    for code in tdx.list_codes(cfg["universe"].get("include_b_share", False)):
        frame = tdx.daily(code)
        if frame is not None:
            frames[code] = frame
    result = shadow_scan(frames, datetime.combine(datetime.fromisoformat(args.as_of).date(),
                                                   time(15, 5)), cfg,
                         WatchStore(ROOT / args.db))
    print(json.dumps({k: v for k, v in result.items() if k != "event_ids"},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
