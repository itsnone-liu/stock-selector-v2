from datetime import datetime

import pandas as pd
import pytest

from stock_selector.signals.daily_features import evaluate_daily
from stock_selector.signals.snapshot import build_snapshot
from stock_selector.research.cohorts import daily_increment_cohort
from stock_selector.research.outcomes import same_week_remaining


def test_daily_missing_volume_stays_unknown():
    idx = pd.date_range("2025-01-01", periods=4, freq="B")
    f = pd.DataFrame({"open": [10, 10, 10, 10], "high": [11]*4, "low": [9]*4,
                      "close": [10, 10.1, 10.2, 10.3], "volume": [100, 100, 100, float("nan")]}, index=idx)
    snap = build_snapshot("1", datetime(2025, 1, 6, 15, 30), f)
    ev = evaluate_daily(snap)
    assert ev.legacy_labels["shrinking_volume_acceleration"] is None


def test_cohort_requires_monthly_state_column():
    p = pd.DataFrame({"weekly_eligibility_state": ["eligible"],
                      "sv_legacy": [True], "td_legacy": [False]})
    with pytest.raises(ValueError, match="monthly_provisional_state"):
        daily_increment_cohort(p)


def test_week_remaining_matures_only_with_later_week_data():
    idx = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-10", "2025-01-13"])
    f = pd.DataFrame({"open": [10]*5, "high": [11]*5, "low": [9]*5,
                      "close": [10, 10.1, 10.2, 10.3, 10.4], "volume": [100]*5}, index=idx)
    assert same_week_remaining(f, pd.Timestamp("2025-01-07").date())["matured_week_remaining"] is True
