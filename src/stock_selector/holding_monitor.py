"""V3 P1 持仓独立风险批处理。

它只遍历真实持仓，不依赖月线主池或候选状态；输出风险事实/信号，不下单。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.decision.exits import ExitAnchor, ExitMonitor
from stock_selector.models import Quote


def monitor_holdings(anchors: dict[str, ExitAnchor], frames: dict[str, pd.DataFrame],
                     as_of: datetime, config: dict,
                     quotes: dict[str, Quote] | None = None) -> dict:
    monitor = ExitMonitor(config)
    quotes = quotes or {}
    results: dict[str, dict] = {}
    for code in sorted(anchors):
        daily = frames.get(code)
        if daily is None or daily.empty:
            results[code] = {"status": "unknown", "unknowns": ["daily_data_missing"],
                             "signals": []}
            continue
        signals = monitor.check(code, daily, as_of, anchors[code], quotes.get(code))
        results[code] = {"status": "risk" if signals else "monitored", "unknowns": [],
                         "signals": [vars(x) for x in signals]}
    return {"as_of": as_of.isoformat(), "held_count": len(anchors), "holdings": results}
