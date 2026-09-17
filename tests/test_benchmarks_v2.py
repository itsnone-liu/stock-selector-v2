from __future__ import annotations

import pandas as pd

from stock_selector.research.benchmarks import (
    attach_relative_outcomes,
    daily_cross_section_benchmarks,
    forward_cross_section_benchmarks,
)


def test_daily_market_and_industry_benchmarks():
    x = pd.DataFrame({
        "code": ["1", "2", "3", "4"], "date": ["2025-01-02"] * 4,
        "return": [.01, -.02, -.04, .03], "industry_code": ["A", "A", "B", "B"],
    })
    m, i = daily_cross_section_benchmarks(x)
    assert m.iloc[0].market_return_med == -.005
    assert m.iloc[0].market_up_ratio == .5
    assert m.iloc[0].market_down3_ratio == .25
    assert i[i.industry_code == "A"].iloc[0].industry_return_med == -.005


def test_forward_benchmarks_and_excess():
    dates = pd.bdate_range("2025-01-02", periods=4).astype(str)
    p = pd.DataFrame({
        "code": ["1"] * 4 + ["2"] * 4,
        "date": list(dates) * 2,
        "close": [100, 110, 121, 133.1, 100, 100, 100, 100],
        "industry_code": ["A"] * 8,
    })
    m, i = forward_cross_section_benchmarks(p, horizons=(1, 2))
    first = m[m.date == dates[0]].iloc[0]
    assert round(first.market_fwd1, 6) == .05
    out = pd.DataFrame({"code": ["1"], "date": [dates[0]], "industry_code": ["A"], "fwd1": [.1]})
    joined = attach_relative_outcomes(out, m, i, horizons=(1,))
    assert round(joined.market_excess1.iloc[0], 6) == .05
    assert round(joined.industry_excess1.iloc[0], 6) == .05


def test_missing_benchmark_does_not_drop_event():
    out = pd.DataFrame({"code": ["1"], "date": ["2025-01-02"], "fwd1": [.1]})
    m = pd.DataFrame({"date": ["2025-01-03"], "market_fwd1": [0.]})
    joined = attach_relative_outcomes(out, m, None, horizons=(1,))
    assert len(joined) == 1 and pd.isna(joined.market_excess1.iloc[0])
