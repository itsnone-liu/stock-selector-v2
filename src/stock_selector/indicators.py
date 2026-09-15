from __future__ import annotations

import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window, min_periods=window).mean()


def macd(close: pd.Series) -> pd.DataFrame:
    ema12 = close.ewm(span=12, adjust=False, min_periods=12).mean()
    ema26 = close.ewm(span=26, adjust=False, min_periods=26).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False, min_periods=9).mean()
    hist = 2 * (dif - dea)
    return pd.DataFrame({"dif": dif, "dea": dea, "hist": hist}, index=close.index)


def safe_pct_change(current: float, base: float) -> float:
    if base is None or base == 0:
        return 0.0
    return (float(current) / float(base) - 1.0) * 100.0
