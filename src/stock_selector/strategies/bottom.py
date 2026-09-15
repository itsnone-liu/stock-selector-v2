from __future__ import annotations

import pandas as pd

from stock_selector.indicators import safe_pct_change
from stock_selector.models import Decision, RuleResult


def bottom_volume_signal(daily: pd.DataFrame, config: dict) -> RuleResult:
    """底部三倍量大涨事件：评估最后一根日线（盘后语义，事件日=当日）。

    定义（与用户2026-09-15确认的日线形态版一致）：
    - 长期深位：收盘相对此前250日最高回撤≥30%；
    - 低位平台：收盘不高于此前60日最低点上方15%，且此前20日累计涨幅在[-20%,+15%]（未提前启动）；
    - 三倍量：当日量≥前5日均量3倍，且前5日均量≤前60日均量1.3倍（启动前安静）；
    - 大涨：涨幅≥6%，收阳，收盘位于当日振幅上60%。
    """
    cfg = config.get("bottom_volume", {})
    if daily is None or len(daily) < int(cfg.get("min_bars", 260)):
        return RuleResult(Decision.SKIP, "bottom_volume", "insufficient_daily_bars")
    close, open_, high, low = daily["close"], daily["open"], daily["high"], daily["low"]
    vol = daily["volume"]
    price = float(close.iloc[-1])
    day_open = float(open_.iloc[-1])
    prev_close = float(close.iloc[-2])
    day_change = safe_pct_change(price, prev_close)
    day_low = float(low.iloc[-1])
    day_high = float(high.iloc[-1])
    volume = float(vol.iloc[-1])
    vol5 = float(vol.iloc[-6:-1].mean())
    vol60 = float(vol.iloc[-61:-1].mean())
    roll_high = float(high.iloc[-1 - int(cfg.get("lookback_high", 250)) : -1].max())
    low60 = float(low.iloc[-1 - int(cfg.get("lookback_low", 60)) : -1].min())
    prelaunch = (prev_close / float(close.iloc[-22]) - 1) * 100 if len(close) >= 22 else None

    metrics = {
        "volume_multiple": round(volume / vol5, 2) if vol5 > 0 else None,
        "day_change_pct": round(day_change, 2),
        "drawdown_pct": round((price / roll_high - 1) * 100, 1),
        "platform_pct": round((price / low60 - 1) * 100, 1),
        "prelaunch_pct": round(prelaunch, 1) if prelaunch is not None else None,
        "close_position": round((price - day_low) / (day_high - day_low), 2) if day_high > day_low else None,
        "quiet_ratio": round(vol5 / vol60, 2) if vol60 > 0 else None,
    }

    def reject(reason: str) -> RuleResult:
        return RuleResult(Decision.REJECT, "bottom_volume", reason, metrics=metrics)

    if vol5 <= 0 or vol60 <= 0 or prelaunch is None or day_high <= day_low:
        return reject("bottom_volume_reference_invalid")
    if price <= day_open:
        return reject("not_yang")
    if volume / vol5 < float(cfg.get("min_volume_multiple", 3.0)):
        return reject("volume_multiple_too_low")
    if vol5 / vol60 > float(cfg.get("quiet_volume_ratio", 1.3)):
        return reject("not_quiet_before_launch")
    if day_change < float(cfg.get("min_change_pct", 6.0)):
        return reject("change_too_small")
    if price / roll_high - 1 > float(cfg.get("max_drawdown_pct", -30.0)) / 100.0:
        return reject("drawdown_too_shallow")
    if price / low60 - 1 > float(cfg.get("platform_tolerance_pct", 15.0)) / 100.0:
        return reject("above_low_platform")
    if not (float(cfg.get("prelaunch_min_pct", -20.0)) <= prelaunch <= float(cfg.get("prelaunch_max_pct", 15.0))):
        return reject("prelaunch_out_of_range")
    if (price - day_low) / (day_high - day_low) < float(cfg.get("close_position_min", 0.6)):
        return reject("weak_close")
    return RuleResult(
        Decision.PASS,
        "bottom_volume",
        "bottom_volume_launch",
        round(min(volume / vol5, 20.0), 2),
        metrics,
        ["bottom_launch"],
    )
