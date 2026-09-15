"""日线买点多标签层（蓝图 §信号层 / 工作表 §4）。

研究口径：回踩不破（位置）/ 缩量上涨加速（量价效率）/ 两日加速（价格动量）
是三个独立维度，**同时记录**，不再按 if/elif 顺序互斥分类——
否则“某类型收益最好”部分来自判断顺序的样本分配，而非条件本身。

生产口径的选择规则由决策层另行定义（advice.py），不在本层。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from stock_selector.calendar import elapsed_session_fraction
from stock_selector.indicators import macd, safe_pct_change, sma
from stock_selector.models import Quote
from stock_selector.strategies.buy import _historical_offsets, _volume_comparison


@dataclass
class DailyLabels:
    labels: dict[str, bool] = field(default_factory=dict)
    primary_type: str | None = None  # 兼容旧输出的首中标签（按讨论顺序）
    features: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def daily_labels(daily: pd.DataFrame, asof: datetime, config: dict,
                 quote: Quote | None = None,
                 same_time_reference_volume: float | None = None) -> DailyLabels:
    cfg = config["buy"]
    if daily is None or len(daily) < 60:
        return DailyLabels(notes=["insufficient_daily_bars"])

    y_off, py_off = _historical_offsets(daily, asof) if quote else (-2, -3)
    yesterday = daily.iloc[y_off]
    previous = daily.iloc[py_off]
    current_price = quote.price if quote else float(daily.iloc[-1]["close"])
    previous_close = quote.previous_close if quote else float(daily.iloc[-2]["close"])
    day_change = safe_pct_change(current_price, previous_close)
    yesterday_change = safe_pct_change(yesterday["close"], previous["close"])

    close_series = daily["close"].copy()
    if quote and pd.Timestamp(daily.index[-1]).date() != asof.date():
        synthetic = pd.Series({"close": current_price}, name=pd.Timestamp(asof.date()))
        close_series = pd.concat([close_series, synthetic.to_frame().T["close"]])
    elif quote:
        close_series.iloc[-1] = current_price
    ma5 = float(sma(close_series, 5).iloc[-1])
    ma10 = float(sma(close_series, 10).iloc[-1])
    ma20 = float(sma(close_series, 20).iloc[-1])
    ma60 = float(sma(close_series, 60).iloc[-1])
    macd_frame = macd(close_series)
    hist = float(macd_frame["hist"].iloc[-1])
    prev_hist = float(macd_frame["hist"].iloc[-2])
    tolerance = float(cfg.get("ma_tolerance_pct", 1.0)) / 100.0
    near_ma10 = abs(current_price - ma10) / ma10 <= tolerance
    near_ma20 = abs(current_price - ma20) / ma20 <= tolerance

    volume_ratio, volume_method = _volume_comparison(daily, quote, asof, config, same_time_reference_volume)
    maximum = float(cfg.get("acceleration_max_change_pct", 3.5))

    # --- 三个维度独立判定（多标签） ---
    pullback = bool(
        float(cfg.get("pullback_change_min_pct", -3.0)) <= day_change <= float(cfg.get("pullback_change_max_pct", 2.0))
        and (near_ma10 or near_ma20)
    )
    shrinking = bool(
        day_change > 0 and day_change > yesterday_change and day_change < maximum
        and volume_ratio is not None and volume_ratio < 1
    )
    two_day = bool(
        yesterday["close"] > yesterday["open"] and day_change > 0
        and day_change >= yesterday_change and day_change < maximum
    )

    # --- 量能旁证字段（不参与标签判定，供分组研究） ---
    def _prorated_today_volume() -> tuple[float | None, str]:
        if quote is None:
            v = float(daily.iloc[-1]["volume"])
            return (v, "daily_bar") if v > 0 else (None, "daily_bar")
        if quote.volume is None:
            return None, "unavailable"
        fraction = elapsed_session_fraction(asof)
        if fraction <= 0:
            return None, "market_not_started"
        return quote.volume / fraction, "session_prorated"

    today_volume, today_volume_method = _prorated_today_volume()
    vol_ma5 = float(daily.iloc[-6:-1]["volume"].mean()) if len(daily) >= 6 else 0.0
    vol_ma20 = float(daily.iloc[-21:-1]["volume"].mean()) if len(daily) >= 21 else 0.0
    prev_day_volume = float(daily.iloc[y_off]["volume"])
    amount = float(quote.amount) if quote and quote.amount else (
        float(daily.iloc[-1]["amount"]) if "amount" in daily.columns else None
    )

    features = {
        "price": round(current_price, 3),
        "day_change_pct": round(day_change, 3),
        "yesterday_change_pct": round(yesterday_change, 3),
        "volume_ratio_vs_prev": round(volume_ratio, 3) if volume_ratio is not None else None,
        "volume_method": volume_method,
        "today_volume_prorated": round(today_volume, 1) if today_volume else None,
        "today_volume_method": today_volume_method,
        "volume_vs_ma5": round(today_volume / vol_ma5, 3) if today_volume and vol_ma5 > 0 else None,
        "volume_vs_ma20": round(today_volume / vol_ma20, 3) if today_volume and vol_ma20 > 0 else None,
        "prev_day_volume": round(prev_day_volume, 1),
        "amount": round(amount, 1) if amount else None,
        "near_ma10": near_ma10,
        "near_ma20": near_ma20,
        "above_ma20": bool(current_price > ma20),
        "above_ma60": bool(current_price > ma60),
        "daily_ma_bull": bool(ma5 > ma10 > ma20),
        "macd_hist": round(hist, 5),
        "macd_hist_expanding": bool(hist > prev_hist and hist > 0),
        "ma5": round(ma5, 3), "ma10": round(ma10, 3), "ma20": round(ma20, 3), "ma60": round(ma60, 3),
    }
    labels = {"pullback_holds": pullback, "shrinking_volume_acceleration": shrinking, "two_day_acceleration": two_day}
    primary = None
    for key in ("pullback_holds", "shrinking_volume_acceleration", "two_day_acceleration"):
        if labels[key]:
            primary = key
            break
    notes = []
    if volume_ratio is None:
        notes.append("量比参考缺失：缩量标签判定不完整")
    return DailyLabels(labels=labels, primary_type=primary, features=features, notes=notes)
