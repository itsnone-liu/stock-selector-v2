"""第二批：月线双状态、事前位置特征与批量episode表。"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from stock_selector.research.episodes import build_episode_panel
from stock_selector.research.momentum_panel import _monthly_states_fast, _precompute_monthly
from stock_selector.signals.pre_signal_features import pre_signal_features
from stock_selector.signals.snapshot import build_snapshot


def _daily(n=600):
    idx = pd.bdate_range("2023-01-02", periods=n)
    close = np.arange(n, dtype=float) + 100.0
    return pd.DataFrame({"open": close - .5, "high": close + 1, "low": close - 1,
                         "close": close, "volume": 1e6, "amount": 1e7}, index=idx)


def test_monthly_completed_and_provisional_are_separate():
    f = _daily()
    cfg = {"monthly": {"min_bars": 20, "max_last_month_drop_pct": 8.0, "require_ma_bull": True}}
    mf = _precompute_monthly(f)
    day = f.index[-10]
    pos = f.index.searchsorted(day, side="right")
    s = _monthly_states_fast(f, mf, pos, datetime.combine(day.date(), datetime.min.time()), cfg)
    assert set(s) == {"monthly_completed_state", "monthly_provisional_state", "monthly_state_changed_this_month"}
    assert s["monthly_completed_state"] in (True, False, None)
    assert s["monthly_provisional_state"] in (True, False, None)


def test_pre_signal_returns_do_not_use_signal_day():
    f = _daily(100)
    day = f.index[-1]
    snap = build_snapshot("600001", datetime.combine(day.date(), datetime.min.time()).replace(hour=15, minute=30), f)
    x = pre_signal_features(snap)
    expected = (f.close.iloc[-2] / f.close.iloc[-7] - 1) * 100
    assert abs(x["pre_return_5_pct"] - round(expected, 4)) < 1e-12
    # 篡改信号日close会改变位置/日内，但不得改变此前累计涨幅和连续上涨天数。
    f2 = f.copy(); f2.loc[day, "close"] *= 2
    x2 = pre_signal_features(build_snapshot("600001", snap.as_of, f2))
    assert x2["pre_return_5_pct"] == x["pre_return_5_pct"]
    assert x2["prior_up_streak"] == x["prior_up_streak"]


def test_episode_panel_deduplicates_and_unknown_holds():
    p = pd.DataFrame({
        "code": ["600001"] * 7,
        "date": pd.date_range("2025-01-02", periods=7).astype(str),
        "sv_legacy": [False, True, True, None, False, True, True],
        "td_legacy": [False] * 7,
    })
    ep = build_episode_panel(p, signal_columns=("sv_legacy",))
    assert len(ep) == 2
    assert list(ep.consecutive_confirmations) == [2, 2]
    assert ep.iloc[0].end_reason == "signal_inactive"
    assert ep.iloc[0].episode_id != ep.iloc[1].episode_id
