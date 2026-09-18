import pandas as pd

from stock_selector.research.cohorts import (daily_increment_cohort,
                                             nonoverlapping_anchors,
                                             weekly_direct_cohort,
                                             weekly_state_within_daily_shape)


def _panel():
    return pd.DataFrame({
        "code": ["1"] * 7, "date": pd.date_range("2025-01-01", periods=7).astype(str),
        "session_index": range(1, 8), "monthly_provisional_state": [True] * 7,
        "weekly_eligibility_state": ["eligible", "eligible", "eligible", "observation",
                                       "excluded", "unknown", "eligible"],
        "sv_legacy": [True, False, None, True, True, True, False],
        "td_legacy": [False, False, None, False, False, False, False],
    })


def test_daily_increment_has_explicit_trigger_and_nontrigger_not_unknown():
    x = daily_increment_cohort(_panel())
    assert set(x.cohort) == {"triggered", "not_triggered"}
    assert 3 not in x.session_index.tolist()  # 日线证据全unknown不进对照
    assert set(x.session_index) == {1, 2, 7}


def test_weekly_state_comparison_excludes_unknown_and_fixes_daily_shape():
    x = weekly_state_within_daily_shape(_panel())
    assert set(x.cohort) == {"eligible", "observation", "excluded"}
    assert set(x.daily_trigger_type) == {"sv_legacy"}


def test_weekly_direct_does_not_require_daily_trigger():
    x = weekly_direct_cohort(_panel())
    assert 2 in set(x.session_index)  # 未触发日仍属于周线直接研究总体
    assert "unknown" not in set(x.cohort)


def test_nonoverlap_uses_real_sessions_per_cohort():
    x = daily_increment_cohort(_panel())
    y = nonoverlapping_anchors(x, 3)
    assert set(y.session_index) == {1, 2, 7}  # 两个cohort分别取锚点；7与2同组相距>3
