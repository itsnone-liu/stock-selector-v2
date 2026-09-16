"""日线特征：原版标签复刻 + 优化版特征并行输出（方案 §四）。

原版（decision/labels.py 取证复现）：
- shrinking_volume_acceleration：今日涨 + 涨幅>昨日 + 缩量 + 涨幅<3.5%上限
- two_day_acceleration：昨日阳 + 今日涨 + 涨幅>=昨日 + 涨幅<3.5%上限
拆分输出：raw_pattern_matched（上限前）与 legacy_labels（含上限），明确"被上限排除"。
优化版（独立命名）：
- 连续/反弹加速分开（昨日收益符号 vs 昨日阳线实体分开记录）
- 成交活动状态（缩/平/放）独立输出
- ATR14[t-1] 标准化涨幅（不吃进今日推动）
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.signals.contracts import DailyEvidence

LEGACY_RETURN_CAP_PCT = 3.5  # 原版涨幅上限（复刻，不在此修改）


def atr14_prev(daily: pd.DataFrame) -> float | None:
    """ATR14 截至 t-1（不吃进今日推动）。"""
    if daily is None or len(daily) < 16:
        return None
    h, l, c = daily["high"].astype(float), daily["low"].astype(float), daily["close"].astype(float)
    prev_close = c.shift(1)
    tr = pd.concat([h - l, (h - prev_close).abs(), (l - prev_close).abs()], axis=1).max(axis=1)
    tr = tr.iloc[:-1]  # 剔除今日
    atr = tr.rolling(14).mean()
    v = atr.iloc[-1]
    return float(v) if pd.notna(v) else None


def activity_state(volume_ratio: float | None) -> str:
    if volume_ratio is None:
        return "unknown"
    if volume_ratio < 0.9:
        return "shrinking"
    if volume_ratio <= 1.1:
        return "normal"
    return "expanding"


def evaluate_daily(snapshot, volume_ratio: float | None = None,
                   yesterday_green_body: bool | None = None) -> DailyEvidence:
    """snapshot: signals.contracts.MarketSnapshot；volume_ratio 可由调用方给实时口径。"""
    daily = snapshot.daily
    ev = DailyEvidence(code=snapshot.code, as_of=snapshot.as_of)

    if daily is None or len(daily) < 3:
        ev.notes.append("insufficient_daily_bars")
        return ev

    bar = snapshot.current_bar
    if bar is None:
        ev.notes.append("current_bar_missing")
        return ev

    rows_mask = pd.DatetimeIndex(daily.index) < pd.Timestamp(snapshot.as_of.date())
    rows = daily[rows_mask]
    if rows is None or rows.empty:
        ev.notes.append("no_prior_bars")
        return ev
    y = rows.iloc[-1]
    prev_close_today = float(y["close"])  # 今日前收盘
    prev2_close = float(rows.iloc[-2]["close"]) if len(rows) >= 2 else None

    price = float(bar["close"])
    r_today = price / prev_close_today - 1 if prev_close_today else None
    r_yesterday = (float(y["close"]) / float(y["open"]) - 1) if float(y["open"]) else None
    # 昨日收益按前收盘口径（连续性判断用）
    r_yesterday_prevclose = (float(y["close"]) / prev2_close - 1) if prev2_close else None

    today_vol = bar.get("volume")
    yesterday_vol = float(y["volume"]) if pd.notna(y.get("volume")) else None
    vr = volume_ratio if volume_ratio is not None else (
        (today_vol / yesterday_vol) if today_vol is not None and yesterday_vol else None
    )

    ev.r_today = round(r_today * 100, 4) if r_today is not None else None
    ev.r_yesterday = round(r_yesterday_prevclose * 100, 4) if r_yesterday_prevclose is not None else None
    ev.return_acceleration = round((r_today - r_yesterday_prevclose) * 100, 4) \
        if r_today is not None and r_yesterday_prevclose is not None else None
    ev.today_volume = today_vol
    ev.yesterday_volume = yesterday_vol
    ev.volume_ratio_vs_prev = round(vr, 4) if vr is not None else None

    # ---------- 原版量价现象（上限前） ----------
    shrinking_raw = bool(
        r_today is not None and r_today > 0
        and ev.return_acceleration is not None and ev.return_acceleration > 0
        and vr is not None and vr < 1
    )
    yesterday_yang = bool(yesterday_green_body) if yesterday_green_body is not None else (
        bool(r_yesterday is not None and r_yesterday > 0)
    )
    two_day_raw = bool(
        yesterday_yang and r_today is not None and r_today > 0
        and ev.return_acceleration is not None and ev.return_acceleration >= 0
    )
    ev.raw_pattern_matched = {
        "shrinking_volume_acceleration_raw": shrinking_raw,
        "two_day_acceleration_raw": two_day_raw,
    }
    # ---------- 原版标签（含 3.5% 上限） ----------
    cap = LEGACY_RETURN_CAP_PCT / 100
    ev.legacy_labels = {
        "shrinking_volume_acceleration": bool(shrinking_raw and r_today is not None and r_today < cap) if shrinking_raw else False,
        "two_day_acceleration": bool(two_day_raw and r_today is not None and r_today < cap) if two_day_raw else False,
        "return_cap_passed": bool(r_today is not None and r_today < cap),
    }

    # ---------- 优化版（独立命名，不占原版名） ----------
    ev.optimized_labels = {
        "SV_continuation": bool(shrinking_raw and (r_yesterday_prevclose or 0) > 0) if shrinking_raw else None,
        "SV_rebound": bool(shrinking_raw and (r_yesterday_prevclose if r_yesterday_prevclose is not None else 1) <= 0) if shrinking_raw else None,
        "acceleration_continuation": bool(two_day_raw and (r_yesterday_prevclose or 0) > 0) if two_day_raw else None,
        "acceleration_rebound": bool(two_day_raw and (r_yesterday_prevclose if r_yesterday_prevclose is not None else 1) <= 0) if two_day_raw else None,
        "activity_state": activity_state(vr),
    }
    ev.atr14_previous = atr14_prev(rows)
    if ev.atr14_previous and r_today is not None:
        ev.atr_normalized_move = round(r_today * float(rows.iloc[-1]["close"]) / ev.atr14_previous, 4)
    return ev
