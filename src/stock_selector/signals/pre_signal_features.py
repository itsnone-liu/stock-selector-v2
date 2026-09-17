"""信号日前已知的位置、阶段与日内承接特征。

口径约束：
- pre_return_N / prior_up_streak 只使用 t-1 及以前，不吃进信号日；
- dist_to_prior_ma/high 使用信号日收盘与 t-1 之前基准比较；
- 日内承接字段使用信号日已知 OHLC 与前收盘。
"""
from __future__ import annotations

import pandas as pd


LOOKBACKS = (5, 10, 20, 60)


def pre_signal_features(snapshot) -> dict:
    daily = snapshot.daily
    bar = snapshot.current_bar
    out: dict = {}
    if daily is None or bar is None:
        return out
    day = pd.Timestamp(snapshot.as_of.date())
    prior = daily[pd.DatetimeIndex(daily.index) < day].sort_index()
    if prior.empty:
        return out

    closes = prior["close"].astype(float)
    highs = prior["high"].astype(float)
    current_close = float(bar["close"])
    previous_close = float(closes.iloc[-1])

    for n in LOOKBACKS:
        # “前N日累计”严格截止t-1：C[t-1]/C[t-1-N]-1。
        out[f"pre_return_{n}_pct"] = (
            round((float(closes.iloc[-1]) / float(closes.iloc[-1 - n]) - 1) * 100, 4)
            if len(closes) >= n + 1 and float(closes.iloc[-1 - n]) else None
        )
        out[f"dist_to_prior_ma{n}_pct"] = (
            round((current_close / float(closes.tail(n).mean()) - 1) * 100, 4)
            if len(closes) >= n and float(closes.tail(n).mean()) else None
        )
        out[f"dist_to_prior_high{n}_pct"] = (
            round((current_close / float(highs.tail(n).max()) - 1) * 100, 4)
            if len(highs) >= n and float(highs.tail(n).max()) else None
        )

    prior_returns = closes.pct_change().dropna()
    streak = 0
    for value in reversed(prior_returns.tolist()):
        if value > 0:
            streak += 1
        else:
            break
    out["prior_up_streak"] = streak

    o, h, l = float(bar["open"]), float(bar["high"]), float(bar["low"])
    out["today_overnight_pct"] = round((o / previous_close - 1) * 100, 4) if previous_close else None
    out["today_intraday_pct"] = round((current_close / o - 1) * 100, 4) if o else None
    out["today_close_position"] = round((current_close - l) / (h - l), 4) if h > l else None
    out["today_upper_shadow_pct"] = round((h - max(o, current_close)) / o * 100, 4) if o else None
    return out
