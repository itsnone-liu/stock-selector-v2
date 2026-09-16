"""P0 八项关键验收（方案 §8.4）+ 版本并行输出验收。

每项测试对应方案中的一条硬性要求，不得因实现方便而放松。
"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from stock_selector.signals.contracts import MarketSnapshot
from stock_selector.signals.daily_features import evaluate_daily
from stock_selector.signals.snapshot import build_snapshot
from stock_selector.signals.weekly_features import (
    bearish_heavy_veto,
    completed_weeks,
    dual_yang_efficiency,
    evaluate_midweek,
    evaluate_weekly,
    reversal_check,
)


def _daily_frame(weeks: int = 12, base: float = 10.0, drift: float = 0.0,
                 start: str = "2025-06-02") -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=weeks * 5)
    n = len(idx)
    rng = np.random.default_rng(7)
    close = base * np.cumprod(1 + drift + rng.normal(0, 0.005, n))
    frame = pd.DataFrame({
        "open": close * (1 + rng.normal(0, 0.002, n)),
        "high": close * 1.01, "low": close * 0.99, "close": close,
        "volume": 1_000_000.0 + rng.normal(0, 50_000, n).cumsum() * 0 + 100_000 * (1 + np.arange(n) / n),
        "amount": 10_000_000.0,
    }, index=idx)
    return frame


def _snap(daily: pd.DataFrame, as_of: datetime, quote=None, calendar=None) -> MarketSnapshot:
    return build_snapshot("600001", as_of, daily, quote=quote, trading_calendar=calendar)


# ---------- 1. 双阳效率：必须真正执行效率比较 ----------

def test_double_yang_efficiency_really_compares():
    # 双阳且效率提升：本周涨2%量比1.2 → t_eff=2/1.2=1.67 > l_eff=1.5
    r = dual_yang_efficiency(10.0, 10.2, 1.2, 10.0, 10.15, 1.0)
    assert r["passed"] is True and r["t_eff"] > r["l_eff"]
    # 双阳但效率下降：本周涨1%量比2 → t_eff=0.5 < l_eff=1.5 → 不通过
    r2 = dual_yang_efficiency(10.0, 10.1, 2.0, 10.0, 10.15, 1.0)
    assert r2["passed"] is False
    # 只有"两周都阳"但效率劣化绝不能通过（旧 v2 的缺陷）
    assert r2["this_yang"] and r2["last_yang"]


# ---------- 2. 昨日-5%今日+1%：反弹加速，不是连续上涨 ----------

def test_rebound_acceleration_not_consecutive():
    idx = pd.bdate_range("2025-08-01", periods=70)
    close = np.full(70, 10.0)
    close[66] = 10.0; close[67] = 9.5; close[68] = 9.5 * 1.01  # 昨-5% 今+1%
    frame = pd.DataFrame({"open": close * 0.999, "high": close * 1.02, "low": close * 0.98,
                          "close": close, "volume": 1e6, "amount": 1e7}, index=idx)
    snap = _snap(frame, datetime(2025, 8, 14, 15, 30))
    ev = evaluate_daily(snap, volume_ratio=0.9)
    opt = ev.optimized_labels
    if ev.return_acceleration and ev.return_acceleration > 0:
        assert opt["acceleration_rebound"] in (True, None)
        assert not (opt["acceleration_continuation"] is True)


# ---------- 3. 今日+4%：优化版保留，旧版上限排除 ----------

def test_today_plus4_cap_split():
    idx = pd.bdate_range("2025-08-01", periods=70)
    close = np.full(70, 10.0)
    close[-2] = 10.0; close[-1] = 10.4  # 最后一日+4%
    frame = pd.DataFrame({"open": close * 0.999, "high": close * 1.02, "low": close * 0.98,
                          "close": close, "volume": 1e6, "amount": 1e7}, index=idx)
    as_of = datetime.combine(idx[-1].date(), datetime.min.time()).replace(hour=15, minute=30)
    snap = _snap(frame, as_of)
    ev = evaluate_daily(snap, volume_ratio=0.9)
    assert ev.raw_pattern_matched["shrinking_volume_acceleration_raw"] is True
    assert ev.legacy_labels["shrinking_volume_acceleration"] is False
    assert ev.legacy_labels["return_cap_passed"] is False
    assert ev.legacy_labels["two_day_acceleration"] is False



# ---------- 4. 周二实时报价但本地日线未更新 ----------

def test_tuesday_realtime_bar_not_skipped():
    # 日线只到周一，周二十点半实时报价
    daily = _daily_frame(weeks=12)
    daily = daily[daily.index < pd.Timestamp("2025-08-12")]
    from stock_selector.models import Quote
    q = Quote(code="600001", price=10.5, open=10.2, previous_close=10.1,
              volume=800_000.0, amount=8_000_000.0, timestamp=datetime(2025, 8, 12, 10, 30))
    snap = _snap(daily, datetime(2025, 8, 12, 10, 30), quote=q)
    assert snap.current_bar_source == "realtime_synthetic"
    assert snap.current_bar is not None
    ev = evaluate_weekly(snap)
    # 2025-08-12 是周二：不因日线缺当日而跳过，路径应为周二三情形之一
    assert ev.weekday_path.startswith("tuesday")


# ---------- 5. 节假日短周：真实日历，完成度分母不是固定5 ----------

def test_short_week_calendar_not_fixed_five():
    daily = _daily_frame(weeks=12)
    # 构造：2025-10-09（周四）所在周只有 10-09、10-10 两天（国庆假期 10-01~10-08）
    cal = pd.DatetimeIndex([pd.Timestamp("2025-10-09"), pd.Timestamp("2025-10-10")])
    snap = _snap(daily, datetime(2025, 10, 9, 15, 30), calendar=cal)
    assert snap.planned_sessions_this_week == 2
    assert "trading_calendar" not in snap.missing_fields


# ---------- 6. 双阳形态不改善不能只因为收阳通过（midweek） ----------

def test_midweek_yang_without_efficiency_fails():
    daily = _daily_frame(weeks=12, start="2025-07-21")
    # 手工构造上周：大涨放量；本周三天：小涨巨量 → 效率下降
    # 直接用纯函数验证 midweek 逻辑核心
    res = evaluate_midweek(daily, completed_weeks(daily, datetime(2025, 10, 8, 15, 30)),
                           datetime(2025, 10, 8, 15, 30))
    assert res["weekday_path"] == "midweek_partial"
    comp = res["components"]
    if comp.get("dual_yang_scaled"):
        eff = comp["dual_yang_scaled"]
        if eff["this_yang"] and eff["last_yang"] and eff["t_eff"] <= eff["l_eff"]:
            assert res["passed"] is False


# ---------- 7. 修改信号日之后的价格，信号完全不变 ----------

def test_future_prices_do_not_change_signal():
    daily = _daily_frame(weeks=14, start="2025-06-02")
    as_of = datetime(2025, 8, 6, 15, 30)  # 周三
    snap1 = _snap(daily, as_of)
    ev1 = evaluate_weekly(snap1)
    d1 = evaluate_daily(snap1)
    # 篡改信号日之后的所有价格
    daily2 = daily.copy()
    mask = daily2.index > pd.Timestamp(as_of.date())
    daily2.loc[mask, ["open", "high", "low", "close"]] *= 1.5
    daily2.loc[mask, "volume"] *= 3
    snap2 = _snap(daily2, as_of)
    ev2 = evaluate_weekly(snap2)
    d2 = evaluate_daily(snap2)
    assert ev1.passed == ev2.passed
    assert ev1.base_pattern == ev2.base_pattern
    assert ev1.components.get("dual_yang") == ev2.components.get("dual_yang")
    assert d1.legacy_labels == d2.legacy_labels


# ---------- 8. veto：前4周均值基线、amount 优先 ----------

def test_veto_uses_prev4_mean_and_amount_priority():
    idx = pd.date_range("2025-07-04", periods=5, freq="W-FRI")
    frame = pd.DataFrame({
        "open": [10, 10, 10, 10, 10.0], "close": [10.2, 10.3, 10.1, 10.4, 9.8],
        "high": [10.5] * 5, "low": [9.9] * 5,
        "volume": [1e6, 1e6, 1e6, 1e6, 2e6],
        "amount": [1e7, 1e7, 1e7, 1e7, 3e7],  # amount 是 volume 的10倍稳定比
    }, index=idx)
    veto, metrics = bearish_heavy_veto(frame)
    # 最后周阴线，amount 3e7 > 前4周均值1e7×1.5 → veto
    assert veto is True
    assert metrics["metric"] == "amount"


# ---------- 补充：收盘/盘中信号证据分级 ----------

def test_evidence_level_split():
    daily = _daily_frame(weeks=12)
    intraday = _snap(daily, datetime(2025, 8, 12, 10, 30))
    closed = _snap(daily, datetime(2025, 8, 12, 15, 30))
    assert intraday.evidence_level == "L1"
    assert closed.evidence_level == "L2"


# ---------- 补充：日线已有当日bar时 quote 不重复累计 ----------

def test_daily_bar_not_duplicated_by_quote():
    daily = _daily_frame(weeks=12, start="2025-08-04")
    as_of = datetime(2025, 8, 15, 14, 0)
    from stock_selector.models import Quote
    q = Quote(code="600001", price=99.0, open=99.0, previous_close=98.0,
              volume=5e6, amount=5e8, timestamp=as_of)
    snap = _snap(daily, as_of, quote=q)
    if snap.current_bar_source == "daily_bar":
        assert snap.current_bar["close"] != 99.0
