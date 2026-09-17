"""第一批落地验收：七期限、ATR时点、Theory加速、四态和事件去重。"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from stock_selector.research.momentum_panel import _tri_cell, attach_outcomes
from stock_selector.research.outcomes import next_day_outcomes
from stock_selector.signals.daily_features import atr14_prev, evaluate_daily
from stock_selector.signals.lifecycle import EpisodeTracker
from stock_selector.signals.snapshot import build_snapshot
from stock_selector.signals.contracts import WeeklyEvidence
from stock_selector.signals.weekly_features import derive_weekly_eligibility, evaluate_weekly


class _Store:
    def __init__(self, frame):
        self.frame = frame

    def daily(self, code):
        return self.frame


def _frame(n=80):
    idx = pd.bdate_range("2025-01-02", periods=n)
    close = np.arange(n, dtype=float) + 100.0
    return pd.DataFrame({
        "open": close - 0.2, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": 1_000_000.0, "amount": 10_000_000.0,
    }, index=idx)


def test_all_requested_horizons_and_forward_window_exact():
    f = _frame()
    sig = f.index[30].date()
    hs = (1, 2, 3, 5, 10, 15, 20)
    out = next_day_outcomes(f, sig, horizons=hs)
    base = f.loc[pd.Timestamp(sig), "close"]
    for h in hs:
        assert out[f"matured_{h}"] is True
        assert out[f"fwd{h}"] == f.iloc[30 + h]["close"] / base - 1
        future = f.iloc[31:31 + h]
        assert out[f"mfe{h}_full"] == future.high.max() / base - 1
        assert out[f"mae{h}_full"] == future.low.min() / base - 1


def test_attach_outcomes_forwards_custom_horizons():
    f = _frame()
    day = f.index[25].date().isoformat()
    panel = pd.DataFrame([{"code": "600001", "date": day, "weekly_passed": True,
                           "sv_legacy": True, "td_legacy": False,
                           "weekly_daily_cell": "1_1", "t_eff": 2.0,
                           "eff_delta": 1.0, "weekly_weekday_path": "monday"}])
    out = attach_outcomes(_Store(f), panel, horizons=(2, 5, 15))
    assert {"fwd2", "fwd5", "fwd15", "matured_15"} <= set(out.columns)
    assert "fwd1" not in out.columns


def test_atr14_prev_includes_last_prior_bar():
    idx = pd.bdate_range("2025-01-02", periods=15)
    # 前14个完整TR约2，最后一个TR=20；正确ATR必须包含最后prior bar。
    close = np.full(15, 100.0)
    high = np.full(15, 101.0); low = np.full(15, 99.0)
    high[-1] = 110.0; low[-1] = 90.0
    f = pd.DataFrame({"high": high, "low": low, "close": close}, index=idx)
    expected = (13 * 2.0 + 20.0) / 14
    assert abs(atr14_prev(f) - expected) < 1e-12


def test_theory_rebound_does_not_require_green_body():
    idx = pd.bdate_range("2025-01-02", periods=20)
    close = np.full(20, 100.0)
    close[-3] = 100.0
    close[-2] = 98.0  # 昨日相对前收-2%
    close[-1] = 99.0  # 今日约+1.02%，高于昨日收益
    open_ = close.copy()
    open_[-2] = 99.0  # 昨日收98<开99：实体阴线
    f = pd.DataFrame({"open": open_, "high": close + 1, "low": close - 1,
                      "close": close, "volume": 1e6, "amount": 1e7}, index=idx)
    as_of = datetime.combine(idx[-1].date(), datetime.min.time()).replace(hour=15, minute=30)
    ev = evaluate_daily(build_snapshot("600001", as_of, f))
    assert ev.optimized_labels["yesterday_green_body"] is False
    assert ev.raw_pattern_matched["two_day_acceleration_raw"] is False
    assert ev.optimized_labels["theory_acceleration_raw"] is True
    assert ev.optimized_labels["acceleration_rebound"] is True


def test_unknown_cell_is_not_false():
    assert _tri_cell(None) == "u"
    assert _tri_cell(False) == "0"
    assert _tri_cell(True) == "1"


def test_weekly_four_state_mapping():
    f = _frame(100)
    as_of = datetime.combine(f.index[-1].date(), datetime.min.time()).replace(hour=15, minute=30)
    ev = evaluate_weekly(build_snapshot("600001", as_of, f))
    assert ev.eligibility_state in {"eligible", "observation", "excluded", "unknown"}
    if ev.veto_flag:
        assert ev.eligibility_state == "excluded"


def test_tuesday_legacy_hold_is_observation_not_admission():
    # passed保持Legacy差分语义；Theory准入由纯派生状态决定。
    for path in ("tuesday_pending", "tuesday_C"):
        ev = WeeklyEvidence(code="600001", passed=True, weekday_path=path,
                            base_pattern="double_positive_efficiency_improved")
        state, reason = derive_weekly_eligibility(ev)
        assert state == "observation"
        assert path in reason
        assert ev.passed is True
    failed = WeeklyEvidence(code="600001", passed=False,
                            weekday_path="tuesday_C_failed_volume", base_pattern="none")
    assert derive_weekly_eligibility(failed)[0] == "excluded"


def test_episode_dedup_unknown_hold_and_retrigger():
    t = EpisodeTracker()
    d1, d2, d3, d4, d5 = [datetime(2025, 1, x) for x in range(2, 7)]
    a = t.observe("600001", "daily_trigger", "sv", d1)
    b = t.observe("600001", "daily_trigger", "sv", d2)
    assert a.episode_id == b.episode_id and b.consecutive_confirmations == 2
    u = t.observe("600001", "daily_trigger", "unknown", d3)
    assert u.episode_id == a.episode_id and u.invalidated_at is None
    x = t.observe("600001", "daily_trigger", "none", d4)
    assert x.invalidated_at == d4
    c = t.observe("600001", "daily_trigger", "sv", d5)
    assert c.episode_id != a.episode_id
    assert c.retriggered_at == d5
    assert len(t.history()) == 2
