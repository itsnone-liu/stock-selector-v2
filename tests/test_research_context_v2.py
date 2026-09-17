from __future__ import annotations

import pandas as pd
import pytest

from stock_selector.research.context_join import join_industry_context, join_market_context
from stock_selector.research.path_classification import outcome_bucket, price_path


def test_context_join_is_left_and_does_not_filter_signal():
    p = pd.DataFrame({"code": ["1", "2"], "date": ["2025-01-02", "2025-01-03"]})
    c = pd.DataFrame({"date": ["2025-01-02"], "market_return": [-.03]})
    out = join_market_context(p, c)
    assert len(out) == 2 and out.market_return.isna().sum() == 1


def test_context_join_rejects_duplicate_background():
    p = pd.DataFrame({"code": ["1"], "date": ["2025-01-02"]})
    c = pd.DataFrame({"date": ["2025-01-02", "2025-01-02"], "x": [1, 2]})
    with pytest.raises(ValueError):
        join_market_context(p, c)


def test_industry_join_requires_historical_key():
    p = pd.DataFrame({"code": ["1"], "date": ["2025-01-02"], "industry_code": ["801010"]})
    c = pd.DataFrame({"date": ["2025-01-02"], "industry_code": ["801010"], "industry_return": [-.02]})
    assert join_industry_context(p, c).industry_return.iloc[0] == -.02


def test_outcome_buckets_have_neutral_band():
    assert outcome_bucket(.001, .002) == "neutral"
    assert outcome_bucket(.003, .002) == "positive"
    assert outcome_bucket(-.003, .002) == "negative"


def test_price_path_five_types():
    kw = dict(positive_delta=.002, meaningful_mfe=.03, deep_mae=.04)
    assert price_path(.03, .01, .04, -.01, **kw) == "immediate_continuation"
    assert price_path(.03, -.01, .04, -.01, **kw) == "delayed_start"
    assert price_path(-.01, .01, .05, -.02, **kw) == "spike_then_fade"
    assert price_path(-.01, -.01, .01, -.02, **kw) == "direct_failure"
    assert price_path(.03, -.01, .05, -.06, **kw) == "deep_drawdown_recovery"
