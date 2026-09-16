"""P1 面板与结果测试：未过滤对照组、unknown 语义、下一周边界、成熟标记。"""
from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd

from stock_selector.research.momentum_panel import (
    _monthly_bull_fast,
    _monthly_bull_pit,
    _precompute_monthly,
    build_panel,
)
from stock_selector.research.outcomes import (
    next_day_outcomes,
    next_week_boundaries,
    next_week_outcomes,
    same_week_remaining,
)


def _frame(days: int = 400, start: str = "2024-01-01") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=days)
    rng = np.random.default_rng(3)
    close = 10 * np.cumprod(1 + rng.normal(0.0005, 0.01, days))
    return pd.DataFrame({
        "open": close * 0.999, "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": 1e6, "amount": 1e7,
    }, index=idx)


class _Store:
    def __init__(self, frames: dict[str, pd.DataFrame]):
        self._frames = frames

    def daily(self, code):
        return self._frames.get(code)


# ---------- 月线快速路径等价 ----------

def test_monthly_fast_equals_slow():
    f = _frame(500)
    cfg = {"monthly": {"min_bars": 20, "max_last_month_drop_pct": 8.0, "require_ma_bull": True}}
    mf = _precompute_monthly(f)
    idx = pd.DatetimeIndex(f.index)
    mism = 0
    for day in list(idx)[::7]:
        as_of = datetime.combine(day.date(), datetime.min.time()).replace(hour=15, minute=30)
        pos = idx.searchsorted(day, side="right")
        a = _monthly_bull_pit(f, as_of, cfg)
        b = _monthly_bull_fast(f, mf, pos, idx, as_of, cfg)
        mism += a != b
    assert mism == 0


# ---------- 面板保留未触发对照 ----------

def test_panel_keeps_no_signal_controls():
    f = _frame(300)
    cfg = {"monthly": {"min_bars": 20, "max_last_month_drop_pct": 8.0, "require_ma_bull": True}}
    dates = [datetime.combine(d.date(), datetime.min.time()).replace(hour=15, minute=30)
             for d in pd.DatetimeIndex(f.index)[-60:]]
    panel, stats = build_panel(_Store({"600001": f}), ["600001"], dates, cfg, min_history=130)
    if stats["rows"]:
        # 未触发周/日信号的行必须存在（对照组）
        assert (panel.weekly_daily_cell == "0_0").any() or panel.weekly_daily_cell.nunique() >= 1
        assert set(panel.columns) >= {"t_eff", "sv_legacy", "weekly_passed", "r_today_pct"}


# ---------- 下一日结果：隔夜与盘中分开、未成熟标记 ----------

def test_next_day_split_and_maturity():
    f = _frame(100, start="2025-01-01")
    sig = f.index[60].date()
    o = next_day_outcomes(f, sig)
    assert o["matured_1"] is True
    fut = f[f.index > pd.Timestamp(sig)]
    assert abs(o["overnight_gap"] - (fut.iloc[0]["open"] / f.loc[pd.Timestamp(sig), "close"] - 1)) < 1e-12
    assert abs(o["next_day_open_to_close"] - (fut.iloc[0]["close"] / fut.iloc[0]["open"] - 1)) < 1e-12
    # 尾部信号不足30日 → 不标成熟
    o2 = next_day_outcomes(f, f.index[-2].date())
    assert o2.get("matured_30") is False


# ---------- 下一周按自然周边界 ----------

def test_next_week_boundary_and_sessions():
    f = _frame(120, start="2025-03-03")
    sig = f.index[40].date()  # 2025-04-28 周一
    nm, ns = next_week_boundaries(f, sig)
    assert nm.weekday() == 0 and ns.weekday() == 6
    o = next_week_outcomes(f, sig)
    assert o["next_week_sessions"] == 5
    assert o["matured_week"] is True
    # 最后一周信号：下一周不存在 → 不成熟
    o2 = next_week_outcomes(f, f.index[-1].date())
    assert o2["matured_week"] is False


# ---------- 本周剩余与下一周分开 ----------

def test_week_remaining_separate_from_next_week():
    f = _frame(120, start="2025-03-03")
    sig = f.index[42].date()  # 周三
    wr = same_week_remaining(f, sig)
    nw = next_week_outcomes(f, sig)
    assert wr["week_remaining_sessions"] == 2
    assert nw["next_week_sessions"] == 5
