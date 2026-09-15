from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.calendar import aggregate_weekly, completed_week_rows, current_week_rows, elapsed_week_fraction
from stock_selector.indicators import safe_pct_change
from stock_selector.models import Decision, Quote, RuleResult


def _weekly_bar(rows: pd.DataFrame, quote: Quote | None = None) -> dict[str, float] | None:
    if rows is None or rows.empty:
        if quote is None:
            return None
        return {
            "open": quote.open,
            "high": max(quote.open, quote.price),
            "low": min(quote.open, quote.price),
            "close": quote.price,
            "volume": float(quote.volume or 0.0),
            "amount": float(quote.amount or 0.0),
        }
    result = {
        "open": float(rows.iloc[0]["open"]),
        "high": float(rows["high"].max()),
        "low": float(rows["low"].min()),
        "close": float(rows.iloc[-1]["close"]),
        "volume": float(rows["volume"].sum()),
        "amount": float(rows["amount"].sum()) if "amount" in rows.columns else 0.0,
    }
    if quote:
        result["close"] = quote.price
        result["high"] = max(result["high"], quote.price)
        result["low"] = min(result["low"], quote.price)
        if quote.volume is not None:
            dates = {pd.Timestamp(x).date() for x in rows.index}
            if quote.timestamp and quote.timestamp.date() in dates:
                historical_before_today = rows[pd.to_datetime(rows.index).date < quote.timestamp.date()]
                result["volume"] = float(historical_before_today["volume"].sum()) + quote.volume
            else:
                result["volume"] += quote.volume
    return result


def _bearish_turnover_veto(completed: pd.DataFrame, cfg: dict) -> tuple[bool, dict]:
    lookback = int(cfg.get("bearish_turnover_lookback", 4))
    if len(completed) < lookback + 1:
        return False, {}
    metric = "amount" if "amount" in completed.columns else "volume"
    latest = completed.iloc[-1]
    previous = completed.iloc[-lookback - 1 : -1]
    baseline = float(previous[metric].mean())
    ratio = float(latest[metric]) / baseline if baseline > 0 else 0.0
    veto = latest["close"] < latest["open"] and ratio >= float(cfg.get("bearish_turnover_veto_ratio", 1.5))
    return bool(veto), {"veto_metric": metric, "veto_ratio": round(ratio, 3)}


def weekly_surge(daily: pd.DataFrame, asof: datetime, config: dict, quote: Quote | None = None) -> RuleResult:
    cfg = config["surge"]
    completed_daily = completed_week_rows(daily, asof)
    completed = aggregate_weekly(completed_daily)
    if len(completed) < 5:
        return RuleResult(Decision.SKIP, "surge", "insufficient_completed_weeks")
    veto, veto_metrics = _bearish_turnover_veto(completed, cfg)
    if veto:
        return RuleResult(Decision.REJECT, "surge", "bearish_heavy_turnover_veto", metrics=veto_metrics)

    current_rows = current_week_rows(daily, asof)
    current = _weekly_bar(current_rows, quote)
    if current is None:
        return RuleResult(Decision.SKIP, "surge", "missing_current_week_rows")
    previous = completed.iloc[-1]
    current_change = safe_pct_change(current["close"], current["open"])
    previous_change = safe_pct_change(previous["close"], previous["open"])
    week_up = current["close"] > current["open"]
    up_vs_previous_close = current["close"] > previous["close"]
    if not week_up:
        return RuleResult(Decision.REJECT, "surge", "current_week_not_bullish", metrics={"current_change_pct": current_change})
    if cfg.get("require_current_week_up_vs_prev_close", True) and not up_vs_previous_close:
        return RuleResult(Decision.REJECT, "surge", "not_up_vs_previous_close")

    previous_is_bearish = previous["close"] <= previous["open"]
    previous_is_bullish = previous["close"] > previous["open"]
    pattern = None
    if cfg.get("allow_reversal", True) and previous_is_bearish:
        pattern = "bearish_to_bullish_reversal"
    elif cfg.get("allow_dual_yang", True) and previous_is_bullish:
        pattern = "dual_yang_efficiency"
    if pattern is None:
        return RuleResult(Decision.REJECT, "surge", "weekly_pattern_not_passed")

    fraction = elapsed_week_fraction(daily, asof, realtime=quote is not None)
    if asof.weekday() >= 5 or fraction <= 0:
        fraction = 1.0
    projected_volume = current["volume"] / fraction
    volume_ratio = projected_volume / float(previous["volume"]) if previous["volume"] > 0 else 0.0
    if volume_ratio < float(cfg.get("min_projected_volume_ratio", 0.8)):
        return RuleResult(Decision.REJECT, "surge", "projected_volume_too_low", metrics={"volume_ratio": volume_ratio})

    current_efficiency = abs(current_change) / volume_ratio if volume_ratio > 0 else 0.0
    previous_efficiency = abs(previous_change)
    if pattern == "dual_yang_efficiency" and current_efficiency <= previous_efficiency * float(cfg.get("efficiency_improvement_ratio", 1.0)):
        return RuleResult(
            Decision.REJECT,
            "surge",
            "weekly_efficiency_not_improved",
            metrics={"current_efficiency": current_efficiency, "previous_efficiency": previous_efficiency},
        )
    score = min(abs(current_change) / 2, 10) + min((current_efficiency / max(previous_efficiency, 0.1)) * 5, 10)
    if pattern == "bearish_to_bullish_reversal":
        score = min(abs(current_change) / 2, 10) + 5
    return RuleResult(
        Decision.PASS,
        "surge",
        pattern,
        round(score, 2),
        {
            "current_change_pct": round(current_change, 3),
            "previous_change_pct": round(previous_change, 3),
            "projected_volume_ratio": round(volume_ratio, 3),
            "elapsed_week_fraction": round(fraction, 4),
            "current_efficiency": round(current_efficiency, 3),
            "previous_efficiency": round(previous_efficiency, 3),
        },
        [pattern],
    )
