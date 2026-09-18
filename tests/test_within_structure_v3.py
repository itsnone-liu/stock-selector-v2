import pandas as pd

from stock_selector.research.background_panel import attach_pre_context, holding_context_metrics
from stock_selector.research.within_structure_analysis import (label_absolute_and_relative_outcomes,
                                                               within_structure_feature_contrast)


def test_absolute_relative_labels_and_event_identity():
    x = pd.DataFrame({"fwd5": [.10], "market_fwd5": [.02], "industry_fwd5": [.04]})
    y = label_absolute_and_relative_outcomes(x, 5)
    assert y.loc[0, "absolute_result_5"] == "positive"
    assert y.loc[0, "industry_relative_result_5"] == "positive"
    total = y.loc[0, "component_market_5"] + y.loc[0, "component_industry_vs_market_5"] + y.loc[0, "component_stock_vs_industry_5"]
    assert abs(total - .10) < 1e-12


def test_within_structure_contrast_does_not_mix_structures():
    x = pd.DataFrame({
        "monthly_pool_spell_age": [1, 1, 2, 2], "weekly_base_pattern": ["A"] * 4,
        "weekly_weekday_path": ["monday"] * 4, "weekly_eligibility_state": ["eligible"] * 4,
        "daily_trigger_type": ["sv"] * 4, "fwd1": [.1, -.1, .2, -.2],
        "market_fwd1": [0.] * 4, "industry_fwd1": [0.] * 4, "pre_position": [8., 2., 9., 1.],
    })
    out = within_structure_feature_contrast(x, horizon=1, feature_columns=["pre_position"])
    assert len(out) == 2
    assert set(out.median_difference) == {6.0, 8.0}


def test_pre_and_holding_context_are_separate_and_future_only():
    ev = pd.DataFrame({"code": ["1"], "date": ["2025-01-02"]})
    ctx = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=4), "ret": [1., 2., -3., 4.]})
    pre = attach_pre_context(ev, ctx, value_columns=("ret",))
    assert pre.loc[0, "pre_context_ret"] == 2.
    hold = holding_context_metrics(ev, ctx, value_col="ret", horizon=2)
    assert hold.loc[0, "holding_context_ret_h2_sum"] == 1.  # t+1,t+2 = -3 + 4
    assert "holding_context_ret_h2_sum" not in pre
