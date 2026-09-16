"""V3 P1 廉价盘后影子扫描：月线主池 + 日线多标签事件。

不接生产决策。输入必须已按 as_of 截断；调用者负责证券历史资格与数据新鲜度。
"""
from __future__ import annotations

from datetime import datetime

from pandas.tseries.offsets import BDay

import pandas as pd

from stock_selector.behavior_features import behavior_features
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
    watch_cfg = config.get("v3_watch", {})
    expiry_sessions = int(watch_cfg.get("event_expiry_sessions", 20))
    expiry_at = (pd.Timestamp(as_of.date()) + BDay(expiry_sessions)).date().isoformat()
    stale_note: str | None = None
    event_ids: list[str] = []
    for code in sorted(frames):
        frame = frames[code]
        visible = frame.loc[frame.index <= pd.Timestamp(as_of.date())]
        visible = frame.loc[frame.index <= pd.Timestamp(as_of.date())]
        if visible.empty:
            counts["unknown"] += 1
            continue
        if stale_note is None and pd.Timestamp(visible.index[-1]).date() != as_of.date():
            # as_of当天无bar（休市/数据未到）：旧bar不得冒充当日触发新事件。
            stale_note = f"data_stale_through_{pd.Timestamp(visible.index[-1]).date()}"
        monthly = monthly_trend(visible, config)
        monthly_metrics = dict(monthly.metrics)
        month_start = pd.Timestamp(as_of.date()).replace(day=1)
        completed = visible.loc[visible.index < month_start]
        previous = monthly_trend(completed, config)
        monthly_metrics["current_month_incomplete"] = True
        monthly_metrics["previous_complete_month"] = {
            "passed": previous.decision == Decision.PASS,
            "reason": previous.reason, "metrics": previous.metrics,
            "through": str(completed.index[-1].date()) if len(completed) else None}
        store.record_monthly_state(code, day, monthly.decision == Decision.PASS,
                                   monthly.reason, monthly_metrics, MONTHLY_STATE_VERSION)
        if monthly.decision != Decision.PASS:
            if monthly.decision == Decision.SKIP:
                counts["unknown"] += 1
            continue
        counts["monthly_pass"] += 1
        store.record_behavior_features(code, as_of.isoformat(), behavior_features(visible))
        if stale_note:
            continue  # 月线状态照记，但当天没有新日线bar，不触发事件
        labels = daily_labels(visible, as_of, config)
        for event_type, hit in sorted(labels.labels.items()):
            if not hit:
                continue
            event_ids.append(store.record_event(SignalEvent(
                code=code, detection_at=as_of.isoformat(), event_type=event_type,
                event_version=EVENT_VERSION, expiry_at=expiry_at,
                evidence={"features": labels.features, "monthly_reason": monthly.reason,
                          "expiry_sessions": expiry_sessions})))
            counts["events"] += 1
    return {**counts, "event_ids": event_ids,
            "monthly_pool": sorted(store.monthly_pool(day, MONTHLY_STATE_VERSION)),
            "watch_codes": sorted(store.active_codes()),
            "data_note": stale_note}
