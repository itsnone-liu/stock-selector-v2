"""V3 P3 量价行为特征（研究/影子，只记录不决策）。

raw metrics 与命名保持克制：VWAP是成交参考成本，不是持仓者真实成本；
高换手低推进是观测组合，不命名吸筹/出货。
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

FEATURE_VERSION = "behavior-v1"


def _finite(x: float) -> float | None:
    return round(float(x), 6) if math.isfinite(float(x)) else None


def rolling_vwap(frame: pd.DataFrame, window: int) -> float | None:
    tail = frame.tail(window)
    if len(tail) < window or "amount" not in tail or "volume" not in tail:
        return None
    volume = float(tail["volume"].sum())
    if volume <= 0:
        return None
    # TDX amount/volume的绝对单位可能因市场版本不同；比率必须先经unit_ratio校验。
    return _finite(float(tail["amount"].sum()) / volume)


def trend_age(close: pd.Series, short: int = 5, mid: int = 10, long: int = 20) -> int:
    ma_s, ma_m, ma_l = close.rolling(short).mean(), close.rolling(mid).mean(), close.rolling(long).mean()
    bull = (ma_s > ma_m) & (ma_m > ma_l)
    age = 0
    for hit in reversed(bull.fillna(False).tolist()):
        if not hit:
            break
        age += 1
    return age


def behavior_features(frame: pd.DataFrame, shares_per_volume_unit: float = 100.0) -> dict:
    if frame is None or len(frame) < 21:
        return {"feature_version": FEATURE_VERSION, "data_quality": ["insufficient_bars"]}
    f = frame.copy()
    close = f["close"].astype(float)
    ret5 = close.iloc[-1] / close.iloc[-6] - 1
    high5 = float(f.tail(5)["high"].max())
    low5 = float(f.tail(5)["low"].min())
    span = high5 - low5
    closing_location = (float(close.iloc[-1]) - low5) / span if span > 0 else None
    amount20 = f["amount"].tail(20).astype(float) if "amount" in f else pd.Series(dtype=float)
    amount_relative = (float(f.iloc[-1]["amount"]) / float(amount20.median())
                       if len(amount20) == 20 and amount20.median() > 0 else None)
    out = {"feature_version": FEATURE_VERSION,
           "return_realized_5d": _finite(ret5),
           "closing_location_5d": _finite(closing_location) if closing_location is not None else None,
           "amount_relative_20d": _finite(amount_relative) if amount_relative is not None else None,
           "daily_ma_bull_age": trend_age(close),
           "data_quality": []}
    for w in (5, 10, 20):
        raw = rolling_vwap(f, w)
        out[f"vwap_{w}d"] = _finite(raw / shares_per_volume_unit) if raw is not None else None
        out[f"price_to_vwap_{w}d"] = (_finite(float(close.iloc[-1]) / out[f"vwap_{w}d"] - 1)
                                      if out[f"vwap_{w}d"] else None)
    if out["vwap_20d"] and not (0.5 <= close.iloc[-1] / out["vwap_20d"] <= 2):
        out["data_quality"].append("amount_volume_unit_ratio_unverified")
    out["shares_per_volume_unit"] = shares_per_volume_unit
    return out
