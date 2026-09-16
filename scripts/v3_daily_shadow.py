#!/usr/bin/env python3
"""V3盘后影子链（方案§6）：全市场扫描→事件账本→过期→持仓风险→日摘要。

影子语义：不产生交易指令，不改变原生产输出；所有判定只用 as_of 当时
可见数据。可挂cron：python3 scripts/v3_daily_shadow.py --as-of $(date +%F)。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, time as dtime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stock_selector.config import load_config  # noqa: E402
from stock_selector.data.tdx import TdxStore  # noqa: E402
from stock_selector.decision.exits import ExitAnchor  # noqa: E402
from stock_selector.holding_monitor import monitor_holdings  # noqa: E402
from stock_selector.shadow_scan import shadow_scan  # noqa: E402
from stock_selector.watchlist import WatchStore  # noqa: E402

HOLDINGS_FILE = ROOT / "state" / "v3_holdings.json"
OUT_DIR = ROOT / "output" / "shadow"


def load_holdings(path: Path) -> dict[str, ExitAnchor]:
    """影子持仓清单（人工维护/导入）；缺文件=无持仓，不伪造。"""
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {code: ExitAnchor(**fields) for code, fields in raw.items()}


def run_daily_shadow(as_of: datetime, cfg: dict, store: WatchStore,
                     frames: dict | None = None,
                     holdings_path: Path = HOLDINGS_FILE) -> dict:
    if frames is None:
        tdx = TdxStore(cfg["paths"]["tdx_dir"])
        frames = {}
        for code in tdx.list_codes(cfg["universe"].get("include_b_share", False)):
            f = tdx.daily(code)
            if f is not None:
                frames[code] = f
    scan = shadow_scan(frames, as_of, cfg, store)
    expired = store.expire_due(as_of.date().isoformat())

    anchors = load_holdings(holdings_path)
    holdings_report = (monitor_holdings(anchors, frames, as_of, cfg)
                       if anchors else {"held_count": 0, "holdings": {},
                                        "note": "no shadow holdings file"})

    day = as_of.date().isoformat()
    summary = {"as_of": as_of.isoformat(), "input": scan["input"],
               "monthly_pass": scan["monthly_pass"], "unknown": scan["unknown"],
               "new_events": scan["events"], "watch_codes": len(scan["watch_codes"]),
               "expired_events": expired,
               "holdings": {c: h["status"] for c, h in holdings_report["holdings"].items()},
               "limitations": ["行业资金快照待接入盘后链(申万L1映射服务已上线)",
                               "影子链不产生交易指令"]}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{day}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--as-of", default=datetime.now().date().isoformat())
    p.add_argument("--config", default="config/default.yaml")
    p.add_argument("--db", default="state/v3_watch.db")
    args = p.parse_args()
    cfg = load_config(ROOT / args.config)
    day = datetime.fromisoformat(args.as_of).date()
    at = datetime.combine(day, dtime(15, 5))
    summary = run_daily_shadow(at, cfg, WatchStore(ROOT / args.db))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
