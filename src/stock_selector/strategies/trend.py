from __future__ import annotations

import pandas as pd

from stock_selector.calendar import aggregate_weekly
from stock_selector.indicators import macd, safe_pct_change, sma
from stock_selector.models import Decision, RuleResult


def aggregate_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    aggregations = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "amount" in daily.columns:
        aggregations["amount"] = "sum"
    return daily.resample("ME").agg(aggregations).dropna(subset=["open", "close"])


def monthly_trend(daily: pd.DataFrame, config: dict) -> RuleResult:
    cfg = config["monthly"]
    bars = aggregate_monthly(daily)
    minimum = max(int(cfg.get("min_bars", 20)), 20)
    if len(bars) < minimum:
        return RuleResult(Decision.SKIP, "monthly", "insufficient_monthly_bars", metrics={"bars": len(bars)})
    close = bars["close"]
    ma5, ma10, ma20 = sma(close, 5), sma(close, 10), sma(close, 20)
    values = (float(ma5.iloc[-1]), float(ma10.iloc[-1]), float(ma20.iloc[-1]))
    if any(pd.isna(value) for value in values):
        return RuleResult(Decision.SKIP, "monthly", "monthly_indicators_nan")
    change = safe_pct_change(close.iloc[-1], close.iloc[-2])
    if change < -float(cfg.get("max_last_month_drop_pct", 8.0)):
        return RuleResult(Decision.REJECT, "monthly", "last_month_drop_too_large", metrics={"month_change_pct": change})
    if cfg.get("require_ma_bull", True) and not (values[0] > values[1] > values[2]):
        return RuleResult(Decision.REJECT, "monthly", "monthly_ma_not_bull")
    score = 35.0
    score += 20 if change > 0 else 10 if change > -5 else 0
    score += 15 if close.iloc[-1] > values[0] else 5 if close.iloc[-1] > values[0] * 0.95 else 0
    score += min(max(change * 1.5, 0), 15)
    return RuleResult(
        Decision.PASS,
        "monthly",
        "monthly_ma_bull",
        round(score, 2),
        {"month_change_pct": round(change, 2), "ma5": values[0], "ma10": values[1], "ma20": values[2]},
        ["MA5>MA10>MA20"],
    )


def weekly_trend(daily: pd.DataFrame, config: dict) -> RuleResult:
    cfg = config["weekly"]
    weekly = aggregate_weekly(daily)
    minimum = max(int(cfg.get("min_bars", 35)), 35)
    if len(weekly) < minimum:
        return RuleResult(Decision.SKIP, "weekly", "insufficient_weekly_bars", metrics={"bars": len(weekly)})
    close = weekly["close"]
    ma5, ma10, ma20 = sma(close, 5), sma(close, 10), sma(close, 20)
    macd_frame = macd(close)
    last = macd_frame.iloc[-1]
    prev = macd_frame.iloc[-2]
    prev2 = macd_frame.iloc[-3]
    if macd_frame.tail(3).isna().any().any():
        return RuleResult(Decision.SKIP, "weekly", "weekly_indicators_nan")
    ma_bull = bool(ma5.iloc[-1] > ma10.iloc[-1] > ma20.iloc[-1])
    cross = bool(prev["dif"] <= prev["dea"] and last["dif"] > last["dea"])
    close_scale = max(abs(float(close.iloc[-1])), 0.01)
    gap_pct = abs(float(last["dif"] - last["dea"])) / close_scale * 100
    stabilizing = bool(
        gap_pct < float(cfg.get("macd_gap_pct", 0.8))
        and last["hist"] > prev["hist"]
        and prev["hist"] < prev2["hist"]
        and last["hist"] < 0
    )
    signal = None
    if cfg.get("allow_ma_bull", True) and ma_bull:
        signal = "ma_bull"
    elif cfg.get("allow_macd_cross", True) and cross:
        signal = "macd_cross"
    elif cfg.get("allow_macd_stabilizing", True) and stabilizing:
        signal = "macd_stabilizing"
    if signal is None:
        return RuleResult(Decision.REJECT, "weekly", "weekly_trend_not_passed")
    score = int(close.iloc[-1] > ma5.iloc[-1]) + 2 * int(close.iloc[-1] > ma10.iloc[-1]) + 3 * int(close.iloc[-1] > ma20.iloc[-1])
    return RuleResult(
        Decision.PASS,
        "weekly",
        signal,
        float(score),
        {
            "ma5": round(float(ma5.iloc[-1]), 3),
            "ma10": round(float(ma10.iloc[-1]), 3),
            "ma20": round(float(ma20.iloc[-1]), 3),
            "macd_hist": round(float(last["hist"]), 5),
            "macd_gap_pct": round(gap_pct, 4),
        },
        [signal],
    )
