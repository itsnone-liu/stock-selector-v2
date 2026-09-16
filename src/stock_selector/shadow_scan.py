"""V3 P1 廉价盘后影子扫描：月线主池 + 日线多标签事件。

不接生产决策。输入必须已按 as_of 截断；调用者负责证券历史资格与数据新鲜度。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.decision.labels import daily_labels
from stock_selector.models import Decision
from stock_selector.strategies.trend import monthly_trend
from stock_selector.watchlist import SignalEvent, WatchStore

MONTHLY_STATE_VERSION = "monthly-v1"
EVENT_VERSION = "daily-label-v1"


def shadow_scan(frames: dict[str, pd.DataFrame], as_of: datetime, config: dict,
                store: WatchStore) -> dict:
    counts = {"input": len(frames), "monthly_pass": 0, "events": 0, "unknown": 0}
    day = as_of.date().isoformat()
    event_ids: list[str] = []
    for code in sorted(frames):
        frame = frames[code]
        visible = frame.loc[frame.index <= pd.Timestamp(as_of.date())]
        if visible.empty:
            counts["unknown"] += 1
            continue
        monthly = monthly_trend(visible, config)
        store.record_monthly_state(code, day, monthly.decision == Decision.PASS,
                                   monthly.reason, monthly.metrics, MONTHLY_STATE_VERSION)
        if monthly.decision != Decision.PASS:
            if monthly.decision == Decision.SKIP:
                counts["unknown"] += 1
            continue
        counts["monthly_pass"] += 1
        labels = daily_labels(visible, as_of, config)
        for event_type, hit in sorted(labels.labels.items()):
            if not hit:
                continue
            event_ids.append(store.record_event(SignalEvent(
                code=code, detection_at=as_of.isoformat(), event_type=event_type,
                event_version=EVENT_VERSION,
                evidence={"features": labels.features, "monthly_reason": monthly.reason})))
            counts["events"] += 1
    return {**counts, "event_ids": event_ids,
            "monthly_pool": sorted(store.monthly_pool(day, MONTHLY_STATE_VERSION)),
            "watch_codes": sorted(store.active_codes())}
