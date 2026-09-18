"""2026-09-17 裁定回归：收盘对收盘口径 + 早周准入映射。

裁定原文要点：
① 所有比较用当期收盘 vs 前一期收盘，不用开盘；
② 前两周动能正向时：周一不放量跌→观察；周二反红/缩量小跌→观察；
   早周下跌不做部分周硬约束；
③ 早周上涨才用部分周约束，目的=识别滞涨（滞涨→excluded）。
Legacy passed 语义不变。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.signals.contracts import WeekBar, WeeklyEvidence
from stock_selector.signals.weekly_features import (close_close_context,
                                                    derive_weekly_eligibility)


def _weeks(closes, vols=None):
    vols = vols or [100.0] * len(closes)
    return pd.DataFrame({
        "open": [c - 1 for c in closes], "close": closes,
        "high": [c + 1 for c in closes], "low": [c - 2 for c in closes],
        "volume": vols,
    }, index=pd.RangeIndex(len(closes)))


def test_close_close_context_uses_closes_not_opens():
    # 前两周：10→11(+10%)、11→12.1(+10%) → 动能正向
    w = _weeks([10.0, 11.0, 12.1])
    partial = WeekBar(open=12.0, high=12.4, low=11.9, close=12.3,
                      volume=40.0, amount=None, sessions=1, complete=False)
    ctx = close_close_context(w, partial)
    assert ctx["prev_week_cc_pct"] == 10.0
    assert ctx["prev2_week_cc_pct"] == 10.0
    assert ctx["momentum_context_positive"] is True
    # 12.3/12.1-1 ≈ 1.6529% —— 对上周收盘，不对本周开盘12.0
    assert ctx["partial_week_cc_pct"] == round(12.3 / 12.1 * 100 - 100, 4)


def test_positive_partial_week_stagnation_detects_laggard():
    w = _weeks([10.0, 11.0, 12.1], vols=[100, 100, 100])
    # 折算量 150>100 且折算涨幅 6.2%<10%×0.8=8% → 滞涨
    partial = WeekBar(open=12.0, high=12.4, low=12.0, close=12.25,
                      volume=30.0, amount=None, sessions=1, complete=False)
    ctx = close_close_context(w, partial)
    assert ctx["theory_stagnation_flag"] is True


def test_down_partial_week_has_no_stagnation_constraint():
    w = _weeks([10.0, 11.0, 12.1])
    partial = WeekBar(open=12.2, high=12.3, low=11.5, close=11.8,
                      volume=200.0, amount=None, sessions=2, complete=False)
    ctx = close_close_context(w, partial)
    assert ctx["partial_week_cc_pct"] < 0
    assert ctx["theory_stagnation_flag"] is None  # 下跌不做部分周硬约束


def _ev(**kw):
    base = dict(code="600001", passed=True, weekday_path="monday",
                base_pattern="double_positive_efficiency_improved",
                veto_flag=False, components={})
    base.update(kw)
    return WeeklyEvidence(**base)


def test_tuesday_B_is_observation_not_eligible():
    state, reason = derive_weekly_eligibility(_ev(weekday_path="tuesday_B"))
    assert state == "observation"
    assert reason == "tuesday_reversal_observation"


def test_positive_context_down_day_observes_even_if_legacy_passed():
    ev = _ev(passed=True, momentum_context_positive=True, partial_week_cc_pct=-1.2)
    state, reason = derive_weekly_eligibility(ev)
    assert state == "observation" and reason == "down_day_no_partial_constraint"


def test_positive_context_up_day_stagnant_is_excluded():
    ev = _ev(momentum_context_positive=True, partial_week_cc_pct=2.0,
             theory_stagnation_flag=True)
    assert derive_weekly_eligibility(ev) == ("excluded", "theory_stagnation_partial_week")


def test_positive_context_up_day_legacy_passed_stays_eligible():
    ev = _ev(momentum_context_positive=True, partial_week_cc_pct=2.0,
             theory_stagnation_flag=False)
    state, _ = derive_weekly_eligibility(ev)
    assert state == "eligible"


def test_non_positive_context_falls_back_to_pattern_mapping():
    ev = _ev(momentum_context_positive=False, partial_week_cc_pct=-1.0)
    assert derive_weekly_eligibility(ev)[0] == "eligible"  # 形态判定主导
    ev2 = _ev(passed=False, momentum_context_positive=False)
    assert derive_weekly_eligibility(ev2)[0] == "observation"


def test_confirmed_veto_precedes_legacy_unknown():
    ev = _ev(passed=None, veto_flag=True)
    assert derive_weekly_eligibility(ev) == ("excluded", "bearish_heavy_veto")


def test_tuesday_gate_failed_is_observation_not_unknown():
    ev = _ev(passed=None, weekday_path="tuesday_gate_failed")
    assert derive_weekly_eligibility(ev) == ("observation", "tuesday_legacy_gate_failed")


def test_real_missing_evidence_stays_unknown():
    ev = _ev(passed=None, weekday_path="tuesday_no_daily")
    assert derive_weekly_eligibility(ev) == ("unknown", "insufficient_evidence")


def test_tuesday_gate_history_insufficient_stays_unknown():
    ev = _ev(passed=None, weekday_path="tuesday_gate_unknown")
    assert derive_weekly_eligibility(ev) == ("unknown", "insufficient_evidence")


def test_stagnation_precedes_tuesday_gate_failed_mapping():
    ev = _ev(passed=None, weekday_path="tuesday_gate_failed", theory_stagnation_flag=True)
    assert derive_weekly_eligibility(ev) == ("excluded", "theory_stagnation_partial_week")
