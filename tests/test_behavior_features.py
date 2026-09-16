import numpy as np
import pandas as pd

from stock_selector.behavior_features import behavior_features, rolling_vwap, trend_age


def _frame(n=40):
    close = np.arange(1, n + 1, dtype=float)
    volume = np.full(n, 100.0)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": volume,
                         "amount": close * volume})


def test_vwap_and_price_relation_have_explicit_units():
    f = _frame()
    assert rolling_vwap(f, 5) == 38.0
    x = behavior_features(f)
    assert x["vwap_5d"] == 0.38  # 默认TDX volume=手；本合成amount=price*手
    assert x["price_to_vwap_5d"] == round(40 / .38 - 1, 6)
    assert "amount_volume_unit_ratio_unverified" in x["data_quality"]
    # 若volume本身是股，调用方必须显式声明1。
    x_shares = behavior_features(f, shares_per_volume_unit=1)
    assert x_shares["vwap_5d"] == 38.0
    assert x["feature_version"] == "behavior-v1"


def test_trend_age_counts_contiguous_bull_tail():
    assert trend_age(_frame()["close"]) > 0
    close = _frame()["close"].copy()
    close.iloc[-1] = 1
    assert trend_age(close) == 0


def test_zero_volume_and_missing_bars_are_unknown_not_zero():
    f = _frame()
    f.loc[f.index[-5:], "volume"] = 0
    assert rolling_vwap(f, 5) is None
    assert "insufficient_bars" in behavior_features(f.head(10))["data_quality"]
