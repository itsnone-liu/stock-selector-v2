"""统一市场快照构建：周线与日线共用同一 as_of 证据（方案 §三）。

规则：
- 当日日线已有行 → current_bar 取自日线（daily_bar），quote 仅作时间戳参考；
- 当日日线无行但有实时报价 → 合成临时 bar（realtime_synthetic），不跳过当日分析；
- 已有日线行时 quote 不重复累计（防重复计量）；
- 实时量缺失不得用昨日量冒充 → missing；
- 本周计划交易日数按真实日历（短周=4），无日历时输出 None 并标记近似。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.calendar import (
    elapsed_session_fraction,
)
from stock_selector.decision.clock import session_clock
from stock_selector.models import Quote
from stock_selector.signals.contracts import MarketSnapshot

# 无官方交易日历时的兜底：每周按 5 个交易日近似（必须显式标记）
_APPROX_PLANNED_SESSIONS = 5


def _frame_has_day(frame: pd.DataFrame, day) -> bool:
    if frame is None or frame.empty:
        return False
    idx = pd.DatetimeIndex(frame.index)
    pos = idx.searchsorted(pd.Timestamp(day))
    return pos < len(idx) and idx[pos] == pd.Timestamp(day)


def build_snapshot(
    code: str,
    as_of: datetime,
    daily_history: pd.DataFrame,
    quote: Quote | None = None,
    trading_calendar: pd.DatetimeIndex | None = None,
) -> MarketSnapshot:
    clock = session_clock(as_of, daily_history)

    daily = daily_history
    if daily is not None and not daily.empty:
        idx_all = pd.DatetimeIndex(daily.index)
        pos = idx_all.searchsorted(pd.Timestamp(as_of), side="right")
        # 快照必须只含 as_of 及之前的证据（防未来泄漏）；iloc 视图切片避免整帧复制
        daily = daily.iloc[:pos]

    today = as_of.date()
    has_today_bar = _frame_has_day(daily, today)

    current_bar = None
    bar_source = "missing"
    quote_ts = quote.timestamp if quote is not None else None
    missing: list[str] = []

    if has_today_bar:
        idx_d = pd.DatetimeIndex(daily.index)
        pos_today = idx_d.searchsorted(pd.Timestamp(today))
        row = daily.iloc[pos_today]
        current_bar = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": float(row["volume"]) if pd.notna(row.get("volume")) else None,
            "amount": float(row["amount"]) if "amount" in daily.columns and pd.notna(row.get("amount")) else None,
        }
        bar_source = "daily_bar"
        # quote 不与已有日线重复累计（方案 §3.1）
    elif quote is not None and quote.price:
        current_bar = {
            "open": float(quote.open),
            "high": float(quote.price),
            "low": float(quote.price),
            "close": float(quote.price),
            "volume": float(quote.volume) if quote.volume is not None else None,
            "amount": float(quote.amount) if quote.amount is not None else None,
        }
        bar_source = "realtime_synthetic"
        if quote.volume is None:
            missing.append("realtime_volume")
    else:
        missing.append("current_bar")

    # 本周计划交易日数：真实日历优先
    if trading_calendar is not None and len(trading_calendar):
        cal = pd.DatetimeIndex(trading_calendar)
        monday = pd.Timestamp(today) - pd.Timedelta(days=pd.Timestamp(today).weekday())
        sunday = monday + pd.Timedelta(days=6)
        in_week = cal[(cal >= monday) & (cal <= sunday)]
        planned = int(len(in_week)) if len(in_week) else _APPROX_PLANNED_SESSIONS
        # 本周第几个交易日
        ordinal = int((cal[(cal >= monday) & (cal <= pd.Timestamp(today))]).shape[0]) or None
        approx = False
    else:
        planned = _APPROX_PLANNED_SESSIONS
        ordinal = clock.trading_session_in_week
        approx = True

    sessions_done = (ordinal - 1) if ordinal else 0
    if clock.evidence_level == "L2" and ordinal:
        sessions_done = ordinal
    elif clock.evidence_level == "L1" and ordinal:
        sessions_done = ordinal - 1 + clock.completion
    elif ordinal:
        sessions_done = ordinal - 1

    completion = None
    if planned:
        if clock.evidence_level == "L0":
            completion = max(0.0, min(1.0, sessions_done / planned))
        else:
            completion = max(0.0, min(1.0, (sessions_done) / planned))

    if approx:
        missing.append("trading_calendar")

    return MarketSnapshot(
        code=code,
        as_of=as_of,
        evidence_level=clock.evidence_level,
        daily=daily,
        current_bar=current_bar,
        current_bar_source=bar_source,
        quote_ts=quote_ts,
        calendar_weekday=as_of.isoweekday(),
        session_ordinal_in_week=ordinal,
        planned_sessions_this_week=planned,
        week_completion=completion,
        missing_fields=tuple(missing),
    )
