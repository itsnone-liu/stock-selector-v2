"""结果面板：下一日/下一周/多窗口收益与路径（方案 §六/§七）。

与 signal_panel 物理分离：本模块只读未来行情，禁止被信号生成侧引用。
- 隔夜（信号收盘→次日开盘）与次日盘中（开盘→收盘）分开；
- 下一交易周按自然周边界（周一~周日），短周按实际交易日数记录；
- 未成熟窗口必须标 matured=False，不入胜率分母；
- MAE/MFE 区分完整窗口与截尾窗口。
"""
from __future__ import annotations

from datetime import date

import pandas as pd


def _future(daily: pd.DataFrame, signal_date: date) -> pd.DataFrame:
    return daily[daily.index > pd.Timestamp(signal_date)]


PRIMARY_HORIZONS = (1, 2, 3, 5, 10, 15, 20)
DEFAULT_HORIZONS = PRIMARY_HORIZONS + (30,)  # 30仅作旧结果对账，不是本轮主裁决窗口


def next_day_outcomes(daily: pd.DataFrame, signal_date: date,
                      horizons=DEFAULT_HORIZONS) -> dict:
    """按参数计算未来交易日结果；每个窗口独立成熟，未成熟值不输出。

    起点为信号日收盘；窗口只含 t+1..t+h，不包含信号日。
    """
    normalized = tuple(sorted({int(h) for h in horizons}))
    if not normalized or any(h <= 0 for h in normalized):
        raise ValueError("horizons must contain positive trading-session counts")
    fut = _future(daily, signal_date)
    out: dict = {f"matured_{h}": False for h in normalized}
    if fut.empty:
        return out
    signal_close = float(daily.loc[pd.Timestamp(signal_date), "close"])
    o1 = float(fut.iloc[0]["open"])
    out["overnight_gap"] = o1 / signal_close - 1
    for h in normalized:
        if len(fut) >= h:
            window = fut.head(h)
            out[f"fwd{h}"] = float(window.iloc[-1]["close"]) / signal_close - 1
            out[f"mfe{h}_full"] = float(window["high"].max()) / signal_close - 1
            out[f"mae{h}_full"] = float(window["low"].min()) / signal_close - 1
            out[f"matured_{h}"] = True
    d1 = fut.iloc[0]
    out["next_day_open_to_close"] = float(d1["close"]) / o1 - 1
    out["next_day_high_vs_signal_close"] = float(d1["high"]) / signal_close - 1
    out["next_day_low_vs_signal_close"] = float(d1["low"]) / signal_close - 1
    # 弹性与回吐（前3日）
    head = fut.head(3)
    if len(head):
        peak = float(head["high"].max())
        out["peak3_return"] = peak / signal_close - 1
        out["peak3_session_offset"] = int(head["high"].idxmax() == head.index[0]) if len(head) else None
        out["giveback_from_peak3"] = (
            float(fut.iloc[min(2, len(fut) - 1)]["close"]) / peak - 1
        ) if len(fut) >= 3 else None
        out["early3_up_then_flat"] = bool(
            out.get("peak3_return", 0) > 0.03
            and out.get("fwd3") is not None and out["fwd3"] < out.get("peak3_return", 0) * 0.3
        )
    return out


def next_week_boundaries(daily: pd.DataFrame, signal_date: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    ts = pd.Timestamp(signal_date)
    monday = ts - pd.Timedelta(days=ts.weekday())
    next_monday = monday + pd.Timedelta(days=7)
    next_sunday = next_monday + pd.Timedelta(days=6)
    return next_monday, next_sunday


def next_week_outcomes(daily: pd.DataFrame, signal_date: date) -> dict:
    """下一自然交易周：开盘跳空、周内高低、周末收益、实际交易日数。"""
    fut = _future(daily, signal_date)
    out = {"matured_week": False}
    if fut.empty:
        return out
    nm, ns = next_week_boundaries(daily, signal_date)
    week = fut[(fut.index >= nm) & (fut.index <= ns)]
    signal_close = float(daily.loc[pd.Timestamp(signal_date), "close"])
    if week.empty:
        return out
    out["next_week_sessions"] = len(week)
    out["next_week_open_gap"] = float(week.iloc[0]["open"]) / signal_close - 1
    out["next_week_high"] = float(week["high"].max()) / signal_close - 1
    out["next_week_low"] = float(week["low"].min()) / signal_close - 1
    out["next_week_return"] = float(week.iloc[-1]["close"]) / signal_close - 1
    # 周完整性：周内最后一个交易日后还有数据 → 该周已走完
    last_in_week = week.index[-1]
    out["matured_week"] = bool((fut.index > last_in_week).any())
    return out


def same_week_remaining(daily: pd.DataFrame, signal_date: date) -> dict:
    """信号日→本周结束的剩余走势（周中信号用，与下一周分开）。"""
    ts = pd.Timestamp(signal_date)
    monday = ts - pd.Timedelta(days=ts.weekday())
    friday = monday + pd.Timedelta(days=4)
    rows = daily[(daily.index > ts) & (daily.index <= friday)]
    out = {"matured_week_remaining": False}
    if rows.empty:
        return out
    signal_close = float(daily.loc[ts, "close"])
    out["week_remaining_return"] = float(rows.iloc[-1]["close"]) / signal_close - 1
    out["week_remaining_high"] = float(rows["high"].max()) / signal_close - 1
    out["week_remaining_sessions"] = len(rows)
    # 至少存在本周之后的行情，才能确认本周剩余窗口已走完；周五无剩余行保持False。
    out["matured_week_remaining"] = bool((daily.index > friday).any())
    return out
