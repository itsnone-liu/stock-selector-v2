import pandas as pd

from scripts.e6_vwap_experiment import enrich


def test_vwap_uses_lot_conversion_and_horizons():
    idx = pd.date_range("2025-01-01", periods=60, freq="B")
    close = [10.0] * 25 + [11.0, 11.2, 11.5] + [12.0] * 32
    frame = pd.DataFrame({"open": [10.0] * 25 + [10.5] + [11.0] * 34,
                          "high": [10.1] * 25 + [11.6, 11.8, 12.1] + [12.2] * 32,
                          "low": [9.9] * 25 + [10.4, 10.8, 11.3] + [11.8] * 32,
                          "close": close, "amount": [10000.0] * 60,
                          "volume": [100.0] * 60}, index=idx)
    events = pd.DataFrame({"code": ["600001"], "date": [str(idx[24].date())]})

    class Stub:
        def daily(self, code): return frame

    out = enrich(events, Stub())
    # amount/volume/100 = 1.0; price 10 => price_to_vwap=9.0
    assert out.loc[0, "price_to_vwap_5d"] == 9.0
    assert out.loc[0, "fwd1"] == frame.iloc[25].close / frame.iloc[25].open - 1
    assert out.loc[0, "fwd3"] == frame.iloc[27].close / frame.iloc[25].open - 1
    assert out.loc[0, "fwd30"] == frame.iloc[54].close / frame.iloc[25].open - 1
