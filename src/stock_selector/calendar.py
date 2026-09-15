from __future__ import annotations

from datetime import date, datetime, time

import pandas as pd


MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)
MINUTES_PER_SESSION = 240


def trading_dates(frame: pd.DataFrame) -> list[date]:
    if frame is None or frame.empty:
        return []
    return sorted({pd.Timestamp(x).date() for x in frame.index})


def current_week_rows(frame: pd.DataFrame, asof: date | datetime) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame.iloc[0:0].copy()
    day = asof.date() if isinstance(asof, datetime) else asof
    ts = pd.Timestamp(day)
    monday = ts - pd.Timedelta(days=ts.weekday())
    friday = monday + pd.Timedelta(days=4)
    idx = pd.to_datetime(frame.index)
    return frame[(idx >= monday) & (idx < friday + pd.Timedelta(days=1))].copy()


def completed_week_rows(frame: pd.DataFrame, asof: date | datetime) -> pd.DataFrame:
    if frame is None or frame.empty:
        return frame.iloc[0:0].copy()
    day = asof.date() if isinstance(asof, datetime) else asof
    monday = pd.Timestamp(day) - pd.Timedelta(days=pd.Timestamp(day).weekday())
    idx = pd.to_datetime(frame.index)
    return frame[idx < monday].copy()


def aggregate_weekly(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume", "amount"])
    aggregations = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    if "amount" in frame.columns:
        aggregations["amount"] = "sum"
    return frame.resample("W-FRI").agg(aggregations).dropna(subset=["open", "close"])


def elapsed_trading_minutes(at: datetime) -> int:
    t = at.time()
    if t <= MORNING_START:
        return 0
    if t <= MORNING_END:
        return int((datetime.combine(at.date(), t) - datetime.combine(at.date(), MORNING_START)).total_seconds() // 60)
    if t < AFTERNOON_START:
        return 120
    if t <= AFTERNOON_END:
        return 120 + int((datetime.combine(at.date(), t) - datetime.combine(at.date(), AFTERNOON_START)).total_seconds() // 60)
    return MINUTES_PER_SESSION


def elapsed_session_fraction(at: datetime) -> float:
    return max(0.0, min(1.0, elapsed_trading_minutes(at) / MINUTES_PER_SESSION))


def completed_trading_days_this_week(frame: pd.DataFrame, asof: datetime) -> int:
    rows = current_week_rows(frame, asof)
    today = asof.date()
    return sum(pd.Timestamp(x).date() < today for x in rows.index)


def elapsed_week_fraction(frame: pd.DataFrame, asof: datetime, realtime: bool = True) -> float:
    rows = current_week_rows(frame, asof)
    if not realtime:
        # 盘后只按本周实际已有交易日估算量能进度；不把周一数据误当成完整周。
        return max(0.0, min(1.0, len(rows) / 5.0))
    completed = completed_trading_days_this_week(frame, asof)
    today_fraction = elapsed_session_fraction(asof) if asof.weekday() < 5 else 0.0
    return max(0.0, min(1.0, (completed + today_fraction) / 5.0))
