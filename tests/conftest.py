from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from stock_selector.config import load_config


@pytest.fixture
def config():
    cfg = load_config()
    cfg["universe"]["min_median_amount_20d"] = 0
    cfg["universe"]["min_listing_days"] = 60
    return cfg


def make_daily(periods: int = 260, end: str = "2026-09-15", drift: float = 0.12) -> pd.DataFrame:
    index = pd.bdate_range(end=end, periods=periods)
    close = 10 + np.arange(periods) * drift
    open_price = close - 0.05
    return pd.DataFrame(
        {
            "open": open_price,
            "high": close + 0.2,
            "low": open_price - 0.2,
            "close": close,
            "volume": np.full(periods, 1_000_000.0),
            "amount": close * 100_000_000,
        },
        index=index,
    )
