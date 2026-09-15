"""决策层核心语义的测试：时钟/证据、周级动能三模式、日线多标签。"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from stock_selector.decision.clock import MINUTES_PER_SESSION, session_clock
from stock_selector.decision.labels import daily_labels
from stock_selector.decision.weekly_momentum import (
    ACTIVE_UP,
    CURRENT_WEEK,
    DISTRIBUTION_RISK,
    INSUFFICIENT,
    PREVIOUS_COMPLETED_WEEK,
    PULLBACK_WEAKENING,
    MomentumResult,
    revised_weekday,
    unified,
    weekly_momentum,
)
from stock_selector.models import Quote


def make_daily(closes: list[float], volumes: list[float] | None = None,
               end: str = "2026-09-18", freq: str = "B") -> pd.DataFrame:
    """收盘价序列 → 日线帧（open=前收，high/low 包络，量默认100万）。"""
    n = len(closes)
    volumes = volumes or [1_000_000] * n
    idx = pd.bdate_range(end=end, periods=n, freq=freq)
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0] * 0.995], closes[:-1]])
    frame = pd.DataFrame(
        {
            "open": opens,
            "high": np.maximum(opens, closes) * 1.01,
            "low": np.minimum(opens, closes) * 0.99,
            "close": closes,
            "volume": np.asarray(volumes, dtype=float),
            "amount": np.asarray(volumes, dtype=float) * closes,
        },
        index=idx,
    )
    return frame


def week_frame(prev_week_pct: float = 4.0, prev_week_vol: float = 5_000_000,
               weeks: int = 10, base: float = 10.0) -> pd.DataFrame:
    """构造若干完整交易周：每周5根，按周涨跌幅推进。"""
    closes: list[float] = []
    vols: list[float] = []
    price = base
    for w in range(weeks):
        week_change = prev_week_pct / 100.0 if w == weeks - 1 else 2.0 / 100.0
        for d in range(5):
            price *= 1 + week_change / 5
            closes.append(price)
            vols.append(prev_week_vol / 5)
    return make_daily(closes, vols)


class TestSessionClock:
    def test_levels_by_time(self):
        d = datetime(2026, 9, 15)  # 周二
        assert session_clock(datetime(2026, 9, 15, 9, 0)).evidence_level == "L0"
        assert session_clock(datetime(2026, 9, 15, 10, 30)).evidence_level == "L1"
        assert session_clock(datetime(2026, 9, 15, 12, 0)).evidence_level == "L1"
        assert session_clock(datetime(2026, 9, 15, 15, 0)).evidence_level == "L2"

    def test_minutes_and_completion(self):
        clock = session_clock(datetime(2026, 9, 15, 10, 30))
        assert clock.observed_minutes == 60
        assert clock.completion == pytest.approx(60 / MINUTES_PER_SESSION)
        clock_pm = session_clock(datetime(2026, 9, 15, 14, 0))
        assert clock_pm.observed_minutes == 180

    def test_trading_session_in_week_counts_frame(self):
        # 周三四五三天（周一二为节假日），as_of=周三 → 本周第1个交易日。
        frame = make_daily([10, 10.2, 10.4, 10.5, 10.6], end="2026-09-18")
        frame = frame.iloc[2:]  # 只剩 周三/周四/周五
        asof = datetime(2026, 9, 16, 10, 0)  # 周三
        clock = session_clock(asof, frame)
        assert clock.calendar_weekday == 3
        assert clock.trading_session_in_week == 1

    def test_week_completion(self):
        frame = make_daily([10 + i * 0.1 for i in range(15)], end="2026-09-18")
        asof = datetime(2026, 9, 16, 10, 30)  # 周三盘中，本周第3个交易日
        clock = session_clock(asof, frame)
        assert clock.week_completion_with_today == pytest.approx((2 + 60 / MINUTES_PER_SESSION) / 5)


class TestRevisedWeekday:
    def test_monday_carries_previous_completed_week(self):
        frame = week_frame(prev_week_pct=5.0, prev_week_vol=6_000_000, weeks=8)
        # 上周五是最后一个交易日；as_of=下一个周一盘中。
        last = pd.Timestamp(frame.index[-1])
        monday = last + pd.Timedelta(days=3)
        asof = datetime(monday.year, monday.month, monday.day, 10, 30)
        result = revised_weekday(frame, asof, {"surge": {}})
        assert result.state == ACTIVE_UP
        assert result.evidence_origin == PREVIOUS_COMPLETED_WEEK
        assert result.valid_until == str(asof.date())
        assert any("carry" in note or "延续" in note for note in result.notes)

    def test_monday_distribution_veto_blocks_carry(self):
        frame = week_frame(prev_week_pct=5.0, prev_week_vol=6_000_000, weeks=8)
        last = pd.Timestamp(frame.index[-1])
        monday = last + pd.Timedelta(days=3)
        asof = datetime(monday.year, monday.month, monday.day, 14, 0)
        prev_week_vol = float(frame["volume"].iloc[-5:].sum())
        # 周一盘中：大跌阴线 + 爆量（预期全量≥1.5×上周量）。
        quote = Quote(
            code="600000", price=9.0, open=9.9, previous_close=9.9,
            volume=prev_week_vol * 1.2, amount=None, timestamp=asof,
        )  # completion≈0.75 → 预期全量≈1.6×上周
        result = revised_weekday(frame, asof, {"surge": {}}, quote)
        assert result.state == DISTRIBUTION_RISK
        assert result.evidence_origin == CURRENT_WEEK

    def test_tuesday_double_yin_shrinking(self):
        frame = week_frame(prev_week_pct=4.0, prev_week_vol=5_000_000, weeks=8)
        last = pd.Timestamp(frame.index[-1])
        monday, tuesday = last + pd.Timedelta(days=3), last + pd.Timedelta(days=4)
        price_base = float(frame["close"].iloc[-1])
        # 追加周一阴线（全量100万），周二盘中阴线且预期量更小。
        monday_row = pd.DataFrame(
            {"open": [price_base], "high": [price_base * 1.005], "low": [price_base * 0.96],
             "close": [price_base * 0.97], "volume": [1_000_000.0], "amount": [price_base * 0.97 * 1e6]},
            index=[monday],
        )
        frame2 = pd.concat([frame, monday_row])
        asof = datetime(tuesday.year, tuesday.month, tuesday.day, 11, 30)  # 会话完成0.5
        quote = Quote(
            code="600000", price=price_base * 0.955, open=price_base * 0.97,
            previous_close=price_base * 0.97, volume=300_000.0, amount=None, timestamp=asof,
        )  # 预期全量60万 < 周一100万
        result = revised_weekday(frame2, asof, {"surge": {}}, quote)
        assert result.state == PULLBACK_WEAKENING
        assert result.evidence_origin == CURRENT_WEEK
        assert result.metrics["day2_volume"] < result.metrics["day1_volume"]

    def test_wednesday_velocity_no_price_projection(self):
        frame = week_frame(prev_week_pct=4.0, prev_week_vol=5_000_000, weeks=8)
        last = pd.Timestamp(frame.index[-1])
        monday, tuesday, wednesday = (last + pd.Timedelta(days=i) for i in (3, 4, 5))
        price_base = float(frame["close"].iloc[-1])
        rows = []
        for day, chg, vol in ((monday, 0.02, 1_000_000), (tuesday, 0.02, 1_000_000)):
            close = price_base * (1 + chg)
            rows.append((day, price_base, close, vol))
            price_base = close
        extra = pd.DataFrame(
            [{"open": o, "high": c * 1.01, "low": o * 0.99, "close": c, "volume": v, "amount": c * v}
             for _, o, c, v in rows],
            index=[r[0] for r in rows],
        )
        frame2 = pd.concat([frame, extra])
        asof = datetime(wednesday.year, wednesday.month, wednesday.day, 14, 0)  # completion=0.5
        quote = Quote(
            code="600000", price=price_base * 1.01, open=price_base,
            previous_close=price_base, volume=500_000.0, amount=None, timestamp=asof,
        )
        result = revised_weekday(frame2, asof, {"surge": {}}, quote)
        metrics = result.metrics
        assert "realized_week_return_pct" in metrics
        assert metrics["momentum_velocity"] is not None
        assert abs(metrics["momentum_velocity"] - metrics["realized_week_return_pct"] / metrics["week_completion"]) < 0.01
        assert "projected_week_return" not in metrics  # 禁止价格投影字段

    def test_insufficient_weeks(self):
        frame = make_daily([10, 10.1, 10.2, 10.3])
        result = revised_weekday(frame, datetime(2026, 9, 16, 10, 0), {"surge": {}})
        assert result.evaluation_status == INSUFFICIENT

    def test_holiday_week_first_session_is_monday_semantics(self):
        # 周一周二休市，周三为本周第1个交易日 → 采用周一carry语义。
        frame = week_frame(prev_week_pct=4.0, prev_week_vol=5_000_000, weeks=8)
        frame = frame[[pd.Timestamp(x).weekday() in (2, 3, 4) for x in frame.index]]
        asof = datetime(2026, 9, 16, 10, 0)  # 2026-09-16是周三
        result = revised_weekday(frame, asof, {"surge": {}})
        assert result.trading_session_in_week == 1
        assert result.evidence_origin == PREVIOUS_COMPLETED_WEEK


class TestModes:
    def test_dispatch_revised_default(self):
        frame = week_frame(weeks=6)
        result = weekly_momentum(frame, datetime(2026, 9, 18, 14, 0), {"surge": {}})
        assert result.mode == "revised_weekday"

    def test_unified_maps_surge(self):
        frame = week_frame(weeks=6)
        asof = datetime(2026, 9, 18, 14, 30)
        result = unified(frame, asof, {"surge": {}})
        assert result.mode == "unified"
        assert result.state in (ACTIVE_UP, PULLBACK_WEAKENING, DISTRIBUTION_RISK, "no_momentum")

    def test_unknown_mode_raises(self):
        frame = week_frame(weeks=6)
        with pytest.raises(ValueError):
            weekly_momentum(frame, datetime(2026, 9, 18, 14, 0), {"surge": {}}, mode="bogus")


class TestDailyLabels:
    def test_multi_label_overlap(self):
        # 构造同时命中 缩量加速 与 两日加速 的样本：标签应同时为真。
        closes = [10 + i * 0.05 for i in range(70)]
        closes[-2] = closes[-3] * 1.02  # 昨日阳线+2%
        closes[-1] = closes[-2] * 1.025  # 今日+2.5%超过昨日
        volumes = [1_000_000.0] * 70
        volumes[-1] = 700_000.0  # 今日缩量
        frame = make_daily(closes, volumes)
        asof = datetime(frame.index[-1].year, frame.index[-1].month, frame.index[-1].day, 15, 10)
        result = daily_labels(frame, asof, {"buy": {}})
        assert result.labels["two_day_acceleration"] is True
        assert result.labels["shrinking_volume_acceleration"] is True
        assert result.primary_type == "pullback_holds" or result.primary_type in (
            "shrinking_volume_acceleration", "two_day_acceleration",
        )

    def test_sidecar_volume_features(self):
        closes = [10 + i * 0.02 for i in range(70)]
        volumes = [1_000_000.0] * 70
        volumes[-1] = 2_500_000.0
        frame = make_daily(closes, volumes)
        asof = datetime(frame.index[-1].year, frame.index[-1].month, frame.index[-1].day, 15, 10)
        result = daily_labels(frame, asof, {"buy": {}})
        assert result.features["volume_vs_ma5"] == pytest.approx(2.5, rel=0.02)
        assert result.features["volume_vs_ma20"] is not None
        assert result.features["today_volume_method"] == "daily_bar"
