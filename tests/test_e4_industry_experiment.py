import pandas as pd

from scripts.e4_industry_experiment import enrich


def test_membership_interval_switches_on_effective_date(monkeypatch):
    events = pd.DataFrame({"code": ["600001", "600001"],
                          "date": ["2025-05-12", "2025-05-13"],
                          "trend": ["ma_bull", "ma_bull"], "fwd10": [.1, .2]})
    idx = pd.date_range("2025-04-01", periods=40, freq="B")
    frame = pd.DataFrame({"close": range(40), "high": range(40), "low": range(40),
                          "amount": [100.0] * 40, "volume": [100.0] * 40}, index=idx)

    class Stub:
        def daily(self, code):
            return frame

    membership = pd.DataFrame({"code": ["600001", "600001"],
        "group_key": ["sw_l1:801080", "sw_l1:801010"],
        "date_from": pd.to_datetime(["2021-12-13", "2025-05-13"]),
        "date_to": pd.to_datetime(["2025-05-13", None])})
    out = enrich(events, Stub(), membership)
    assert out.loc[0, "industry"] == "sw_l1:801080"
    assert out.loc[1, "industry"] == "sw_l1:801010"
    assert pd.isna(out.loc[0, "fwd10_industry_demeaned"])
    assert pd.isna(out.loc[1, "fwd10_industry_demeaned"])
