import pandas as pd

from scripts.e5_volume_price_experiment import enrich


def test_multi_horizon_returns_use_next_open_and_future_bars():
    idx = pd.date_range("2025-01-01", periods=60, freq="B")
    close = [100.0] * 25 + [110.0, 112.0, 115.0] + [120.0] * 32
    frame = pd.DataFrame({"open": [100.0] * 25 + [105.0] + [110.0] * 34,
                          "high": [101.0] * 25 + [116.0, 118.0, 121.0] + [122.0] * 32,
                          "low": [99.0] * 25 + [104.0, 108.0, 113.0] + [118.0] * 32,
                          "close": close, "amount": [100.0] * 60,
                          "volume": [100.0] * 60}, index=idx)
    events = pd.DataFrame({"code": ["600001"], "date": [str(idx[24].date())],
                           "fwd10": [0.0], "fwd10_industry_demeaned": [0.0]})

    class Stub:
        def daily(self, code):
            return frame

    out = enrich(events, Stub())
    assert out.loc[0, "fwd1"] == frame.iloc[25]["close"] / frame.iloc[25]["open"] - 1
    assert out.loc[0, "fwd2"] == frame.iloc[26]["close"] / frame.iloc[25]["open"] - 1
    assert out.loc[0, "fwd3"] == frame.iloc[27]["close"] / frame.iloc[25]["open"] - 1
    assert out.loc[0, "fwd30"] == frame.iloc[54]["close"] / frame.iloc[25]["open"] - 1
    assert out.loc[0, "mae3"] <= 0
    assert out.loc[0, "mfe3"] > 0
