import pandas as pd

from scripts.e2_sector_context import attach


def test_context_obeys_available_at_and_uses_prior_fact():
    events = pd.DataFrame({"code": ["600001", "600002"],
        "date": ["2025-01-02", "2025-01-03"],
        "industry": ["sw_l1:801080", "sw_l1:801080"], "fwd10": [.1, -.1]})
    margin = pd.DataFrame({
        "industry": ["sw_l1:801080", "sw_l1:801080", "sw_l1:801080", "sw_l1:801080"],
        "margin_date": pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-01", "2025-01-02"]),
        "metric": ["margin_balance", "margin_balance", "margin_buy", "margin_buy"],
        "value": [100., 110., 10., 11.],
        "available_at": pd.to_datetime(["2025-01-02 09:15", "2025-01-03 09:15",
                                         "2025-01-02 09:15", "2025-01-03 09:15"]),
    })
    out = attach(events, margin)
    # 1/2 15:05可用1/1事实；1/3才可用1/2事实。
    assert out.loc[0, "margin_balance"] == 100.
    assert out.loc[1, "margin_balance"] == 110.
    assert out.loc[0, "margin_balance_chg20"] != out.loc[0, "margin_balance_chg20"]
