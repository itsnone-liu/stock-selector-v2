from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.calendar import elapsed_session_fraction
from stock_selector.indicators import macd, safe_pct_change, sma
from stock_selector.models import Decision, Quote, RuleResult


def _historical_offsets(daily: pd.DataFrame, asof: datetime) -> tuple[int, int]:
    last_date = pd.Timestamp(daily.index[-1]).date()
    if last_date == asof.date():
        return -2, -3
    return -1, -2


def _volume_comparison(
    daily: pd.DataFrame,
    quote: Quote | None,
    asof: datetime,
    config: dict,
    same_time_reference_volume: float | None,
) -> tuple[float | None, str]:
    if quote is None or quote.volume is None:
        return None, "volume_unavailable"
    if same_time_reference_volume is not None and same_time_reference_volume > 0:
        return quote.volume / same_time_reference_volume, "same_time"
    if not config["buy"].get("allow_projected_volume_fallback", True):
        return None, "same_time_reference_missing"
    fraction = elapsed_session_fraction(asof)
    if fraction <= 0:
        return None, "market_not_started"
    y_off, _ = _historical_offsets(daily, asof)
    yesterday_volume = float(daily.iloc[y_off]["volume"])
    if yesterday_volume <= 0:
        return None, "yesterday_volume_invalid"
    projected = quote.volume / fraction
    return projected / yesterday_volume, "projected_full_day"


def daily_buy(
    daily: pd.DataFrame,
    asof: datetime,
    config: dict,
    upstream_score: float = 0.0,
    quote: Quote | None = None,
    same_time_reference_volume: float | None = None,
) -> RuleResult:
    if daily is None or len(daily) < 60:
        return RuleResult(Decision.SKIP, "buy", "insufficient_daily_bars")
    cfg = config["buy"]
    close_series = daily["close"].copy()
    # 盘后无实时行情时，最后一根日线就是“今天”，其前两根才是昨天/前天。
    # 盘中有实时行情时，再依据本地日线是否已含当日决定偏移。
    y_off, py_off = _historical_offsets(daily, asof) if quote else (-2, -3)
    yesterday = daily.iloc[y_off]
    previous = daily.iloc[py_off]
    current_price = quote.price if quote else float(daily.iloc[-1]["close"])
    current_open = quote.open if quote else float(daily.iloc[-1]["open"])
    previous_close = quote.previous_close if quote else float(daily.iloc[-2]["close"])
    day_change = safe_pct_change(current_price, previous_close)

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

    buy_type = None
    base_score = 0.0
    signals: list[str] = []
    near_ma10 = abs(current_price - ma10) / ma10 <= tolerance
    near_ma20 = abs(current_price - ma20) / ma20 <= tolerance
    if float(cfg.get("pullback_change_min_pct", -3.0)) <= day_change <= float(cfg.get("pullback_change_max_pct", 2.0)) and (near_ma10 or near_ma20):
        buy_type = "pullback_holds"
        base_score = 30.0
        signals.append("near_ma10" if near_ma10 else "near_ma20")

    yesterday_change = safe_pct_change(yesterday["close"], previous["close"])
    maximum = float(cfg.get("acceleration_max_change_pct", 3.5))
    volume_ratio, volume_method = _volume_comparison(daily, quote, asof, config, same_time_reference_volume)
    if buy_type is None and day_change > 0 and day_change > yesterday_change and day_change < maximum and volume_ratio is not None and volume_ratio < 1:
        buy_type = "shrinking_volume_acceleration"
        base_score = 25.0
        signals.append("volume_contraction")
    if buy_type is None and yesterday["close"] > yesterday["open"] and day_change > 0 and day_change >= yesterday_change and day_change < maximum:
        buy_type = "two_day_acceleration"
        base_score = 25.0
        signals.append("two_day_up")
    if buy_type is None:
        reason = "daily_buy_pattern_not_passed"
        if quote and volume_ratio is None:
            reason = "daily_buy_not_passed_volume_reference_missing"
        return RuleResult(Decision.REJECT, "buy", reason, metrics={"day_change_pct": day_change, "volume_method": volume_method})

    bonus = 0.0
    if hist > prev_hist and hist > 0:
        bonus += 8
        signals.append("macd_hist_expanding")
    if current_price > ma20:
        bonus += 5
        signals.append("above_ma20")
    if ma5 > ma10 > ma20:
        bonus += 5
        signals.append("daily_ma_bull")
    if current_price > ma60:
        bonus += 3
        signals.append("above_ma60")
    score = upstream_score + base_score + bonus
    return RuleResult(
        Decision.PASS,
        "buy",
        buy_type,
        round(score, 2),
        {
            "price": round(current_price, 3),
            "open": round(current_open, 3),
            "previous_close": round(previous_close, 3),
            "day_change_pct": round(day_change, 3),
            "yesterday_change_pct": round(yesterday_change, 3),
            "ma5": round(ma5, 3),
            "ma10": round(ma10, 3),
            "ma20": round(ma20, 3),
            "ma60": round(ma60, 3),
            "volume_ratio": round(volume_ratio, 3) if volume_ratio is not None else None,
            "volume_method": volume_method,
            "upstream_score": upstream_score,
            "base_score": base_score,
            "bonus": bonus,
        },
        signals,
    )
