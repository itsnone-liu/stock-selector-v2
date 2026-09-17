import numpy as np
import pandas as pd

from stock_selector.research.event_evaluation import (deduplicate_events,
    distribution_summary, event_path_metrics)


def test_dedup_clusters_same_code_label_but_keeps_other_label():
    e = pd.DataFrame([
        ["600001", "a", "2026-01-05", 0], ["600001", "a", "2026-01-07", 2],
        ["600001", "b", "2026-01-07", 2], ["600001", "a", "2026-01-14", 7]],
        columns=["code", "event_type", "detection_at", "session_index"])
    out = deduplicate_events(e, 5)
    assert list(out["event_type"]).count("a") == 2
    assert list(out["event_type"]).count("b") == 1


def test_dedup_refuses_calendar_weekday_approximation():
    import pytest
    e = pd.DataFrame([["600001", "a", "2026-01-05"]],
                     columns=["code", "event_type", "detection_at"])
    with pytest.raises(ValueError, match="session_index"):
        deduplicate_events(e)


def test_path_metrics_never_includes_event_day():
    idx = pd.date_range("2026-01-05", periods=25, freq="B")
    close = np.arange(10, 35, dtype=float)
    p = pd.DataFrame({"close": close, "high": close + 1, "low": close - 1}, index=idx)
    x = event_path_metrics(p, str(idx[0].date()))
    assert x["return_5d"] == 15 / 10 - 1
    assert x["mfe"] == 31 / 10 - 1  # 默认最长20日，严格不含事件日high=11
    assert x["mae"] == 10 / 10 - 1


def test_distribution_reports_right_tail_contribution():
    x = distribution_summary(pd.Series([-1, 1, 1, 1, 10]))
    assert x["n"] == 5
    assert x["median"] == 1
    assert x["top_decile_positive_contribution"] == 10 / 13
