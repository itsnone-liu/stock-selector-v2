"""T2 规则与数据语义审计测试（SPEC §1-8 逐项、确定性、无网络）。

覆盖边界：空数据、短历史、NaN、过期数据、未来数据、周一/盘中边界、
成交量单位、零价零量、缺少同刻快照与买点优先级。
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

from stock_selector.calendar import current_week_rows, elapsed_week_fraction
from conftest import make_daily
from stock_selector.data.realtime import TencentQuoteProvider
from stock_selector.freshness import check_daily_freshness, check_quote_freshness
from stock_selector.models import Decision, Quote
from stock_selector.pipeline import SelectorPipeline
from stock_selector.strategies.buy import daily_buy
from stock_selector.strategies.bottom import bottom_volume_signal
from stock_selector.strategies.risk import check_risk_filters
from stock_selector.strategies.surge import weekly_surge
from stock_selector.strategies.trend import monthly_trend, weekly_trend
from stock_selector.calendar import aggregate_weekly, completed_week_rows, current_week_rows, elapsed_week_fraction


def make_bearish_daily(periods: int = 480, end: str = "2026-09-15", decay: float = 0.05) -> pd.DataFrame:
    index = pd.bdate_range(end=end, periods=periods)
    close = 100 - np.arange(periods) * decay
    open_price = close + decay
    return pd.DataFrame(
        {
            "open": open_price,
            "high": open_price + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": np.full(periods, 1_000_000.0),
            "amount": close * 100_000_000,
        },
        index=index,
    )


def make_accelerating_decline_daily(periods: int = 260, end: str = "2026-09-15") -> pd.DataFrame:
    """二次加速下跌：月/周均线空头且MACD柱持续恶化，不触发小金叉/企稳。"""
    index = pd.bdate_range(end=end, periods=periods)
    steps = np.arange(periods)
    close = 100 - 0.0006 * steps**2
    open_price = close + 0.05 + 0.0012 * steps
    return pd.DataFrame(
        {
            "open": open_price,
            "high": open_price + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": np.full(periods, 1_000_000.0),
            "amount": close * 100_000_000,
        },
        index=index,
    )


# ---- SPEC §1：显式周界与空数据 ----


def test_empty_frame_week_partition_returns_empty(config):
    empty = pd.DataFrame()
    assert current_week_rows(empty, datetime(2026, 9, 15, 10, 0)).empty
    assert completed_week_rows(empty, datetime(2026, 9, 15, 10, 0)).empty


def test_completed_week_excludes_current_week_on_monday(config):
    frame = make_daily(periods=260, end="2026-09-14")
    at = datetime(2026, 9, 14, 10, 30)  # 周一
    completed = completed_week_rows(frame, at)
    assert max(pd.Timestamp(x).date() for x in completed.index) <= pd.Timestamp("2026-09-11").date()
    assert any(pd.Timestamp(x).date() == pd.Timestamp("2026-09-14").date() for x in current_week_rows(frame, at).index)


def test_asof_explicitly_drives_week_partition(config):
    """同一份数据，asof 决定已完成周/当前周切分，而不是数据自身的新旧。"""
    frame = make_daily(periods=260, end="2026-09-15")
    early = completed_week_rows(frame, datetime(2026, 9, 8, 10, 0))
    late = completed_week_rows(frame, datetime(2026, 9, 15, 10, 0))
    assert max(pd.Timestamp(x).date() for x in early.index) == pd.Timestamp("2026-09-04").date()
    assert max(pd.Timestamp(x).date() for x in late.index) == pd.Timestamp("2026-09-11").date()


def test_realtime_change_not_extrapolated(config):
    """盘中真实涨幅只按 当日开盘→现价 计算，绝不按周内进度外推。"""
    daily = make_daily(periods=480, end="2026-09-11", drift=0.12)
    prev_close = float(daily.iloc[-1]["close"])
    at = datetime(2026, 9, 14, 10, 30)  # 周一盘中，fraction=0.05
    quote = Quote("600001", price=prev_close * 1.03, open=prev_close, previous_close=prev_close, volume=250_000, timestamp=at)
    result = weekly_surge(daily, at, config, quote)
    assert result.passed
    assert abs(result.metrics["current_change_pct"] - 3.0) < 1e-6
    assert abs(result.metrics["current_change_pct"] - 3.0 / 0.05) > 1  # 不是外推值60
    assert abs(result.metrics["projected_volume_ratio"] - 1.0) < 1e-6  # 250k/0.05/5e6
    assert abs(result.metrics["elapsed_week_fraction"] - 0.05) < 1e-6


def test_elapsed_week_fraction_progress_semantics(config):
    frame = pd.DataFrame({"close": [1, 1, 1]}, index=pd.to_datetime(["2026-09-14", "2026-09-15", "2026-09-16"]))
    # 周一10:30：(0个完成日 + 60/240) / 5 = 0.05
    assert elapsed_week_fraction(frame, datetime(2026, 9, 14, 10, 30), realtime=True) == 0.05
    # 周三14:00：(2个完成日 + 180/240) / 5 = 0.55
    assert elapsed_week_fraction(frame, datetime(2026, 9, 16, 14, 0), realtime=True) == 0.55
    # 盘后模式只按本周已有交易日：3/5 = 0.6
    assert elapsed_week_fraction(frame, datetime(2026, 9, 16, 14, 0), realtime=False) == 0.6
    # 周末实时模式不计当日盘中进度
    assert elapsed_week_fraction(frame, datetime(2026, 9, 19, 11, 0), realtime=True) == 0.6


# ---- SPEC §2：数据闸门（未来/过期/零价零量/报价时效） ----


def test_future_daily_bar_is_error(config):
    daily = make_daily(periods=60, end="2026-09-16")
    result = check_daily_freshness(daily, datetime(2026, 9, 15, 10, 0), config, realtime=True)
    assert result.decision == Decision.ERROR
    assert result.reason == "future_daily_bar"


def test_stale_realtime_daily_data_is_skipped(config):
    daily = make_daily(periods=60, end="2026-09-01")
    result = check_daily_freshness(daily, datetime(2026, 9, 15, 10, 0), config, realtime=True)
    assert result.decision == Decision.SKIP
    assert result.reason == "daily_data_stale"


def test_after_close_allows_at_most_one_business_day_lag(config):
    monday = make_daily(periods=60, end="2026-09-14")
    assert check_daily_freshness(monday, datetime(2026, 9, 15, 15, 10), config, realtime=False).passed
    friday = make_daily(periods=60, end="2026-09-11")
    result = check_daily_freshness(friday, datetime(2026, 9, 15, 15, 10), config, realtime=False)
    assert result.decision == Decision.SKIP
    assert result.reason == "daily_data_stale"


def test_quote_without_timestamp_is_skipped(config):
    quote = Quote("600001", 10.0, 10.0, 9.9, 1_000_000, timestamp=None)
    result = check_quote_freshness(quote, datetime(2026, 9, 15, 10, 0), config)
    assert result.reason == "quote_timestamp_missing"


def test_stale_quote_is_skipped(config):
    quote = Quote("600001", 10.0, 10.0, 9.9, 1_000_000, timestamp=datetime(2026, 9, 15, 9, 0))
    result = check_quote_freshness(quote, datetime(2026, 9, 15, 10, 30), config)
    assert result.reason == "quote_stale"


class _FakeResponse:
    encoding = None

    def __init__(self, fields):
        fields = [str(x) for x in fields]
        fields += ["0"] * (37 - len(fields))
        self.text = 'v_sh600001="' + "~".join(fields) + '";'

    def raise_for_status(self):
        return None


class _FakeSession:
    def __init__(self, fields):
        self._fields = fields

    def get(self, *args, **kwargs):
        return _FakeResponse(self._fields)


def _provider_with(fields):
    provider = TencentQuoteProvider(volume_multiplier=100)
    provider.session = _FakeSession(fields)
    return provider


def test_zero_price_quote_rejected_as_invalid(config):
    fields = ["1", "测试", "600001", "0.00", "10.00", "10.10", "1234", *["0"] * 22, "20260915100000"]
    quotes, errors = _provider_with(fields).fetch(["600001"], datetime(2026, 9, 15, 10, 0))
    assert quotes == {}
    assert errors["600001"] == "invalid_zero_quote"


def test_zero_open_or_volume_rejected_as_halted(config):
    fields = ["1", "测试", "600001", "10.20", "10.00", "0.00", "1234", *["0"] * 22, "20260915100000"]
    quotes, errors = _provider_with(fields).fetch(["600001"], datetime(2026, 9, 15, 10, 0))
    assert quotes == {}
    assert errors["600001"] == "halted_or_preopen_quote"
    fields_zero_volume = ["1", "测试", "600001", "10.20", "10.00", "10.10", "0", *["0"] * 22, "20260915100000"]
    quotes, errors = _provider_with(fields_zero_volume).fetch(["600001"], datetime(2026, 9, 15, 10, 0))
    assert quotes == {}
    assert errors["600001"] == "halted_or_preopen_quote"


# ---- SPEC §3：风险过滤（短历史/退市/低流动性/B股） ----


def test_short_listing_history_rejected(config):
    result = check_risk_filters("600001", "正常公司", make_daily(periods=30), config)
    assert result.decision == Decision.REJECT
    assert result.reason == "listing_history_too_short"


def test_delisting_name_rejected(config):
    result = check_risk_filters("600001", "某某退市", make_daily(), config)
    assert result.reason == "st_or_delisting_excluded"


def test_sz_b_share_prefix_rejected(config):
    assert check_risk_filters("200001", "", make_daily(), config).reason == "b_share_excluded"


def test_low_liquidity_rejected_when_configured(config):
    config["universe"]["min_median_amount_20d"] = 10_000_000_000
    result = check_risk_filters("600001", "正常公司", make_daily(), config)
    assert result.reason == "liquidity_too_low"


# ---- SPEC §4：月线趋势 ----


def test_monthly_insufficient_bars_skipped(config):
    assert monthly_trend(make_daily(periods=100), config).reason == "insufficient_monthly_bars"


def test_monthly_ma_not_bull_rejected(config):
    result = monthly_trend(make_bearish_daily(), config)
    assert result.decision == Decision.REJECT
    assert result.reason == "monthly_ma_not_bull"


def test_monthly_last_month_drop_rejected(config):
    daily = make_daily(periods=480, drift=0.12)
    daily.iloc[-10:, daily.columns.get_loc("close")] *= 0.6
    result = monthly_trend(daily, config)
    assert result.reason == "last_month_drop_too_large"


def test_monthly_bull_passes_with_ma_ordering(config):
    result = monthly_trend(make_daily(periods=480, drift=0.12), config)
    assert result.passed
    assert result.signals == ["MA5>MA10>MA20"]


# ---- SPEC §5：周线三类信号 ----


def test_weekly_insufficient_bars_skipped(config):
    assert weekly_trend(make_daily(periods=60), config).reason == "insufficient_weekly_bars"


def test_weekly_uptrend_signal_or_reject_is_deterministic(config):
    result = weekly_trend(make_daily(periods=260, drift=0.12), config)
    if result.passed:
        assert result.reason in {"ma_bull", "macd_cross", "macd_stabilizing"}
    else:
        assert result.reason == "weekly_trend_not_passed"


def _weekly_frame(closes: list[float] | np.ndarray) -> pd.DataFrame:
    idx = pd.date_range("2025-06-02", periods=len(closes), freq="7D")
    close = np.asarray(closes, dtype=float)
    return pd.DataFrame(
        {
            "open": close * 0.995,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(len(close), 1_000_000.0),
            "amount": close * 100_000_000,
        },
        index=idx,
    )


def test_weekly_signal_ma_bull(config):
    result = weekly_trend(_weekly_frame(np.linspace(20, 100, 50)), config)
    assert result.passed
    assert result.reason == "ma_bull"


def test_weekly_signal_macd_cross(config):
    steps = np.arange(60)
    decline = 100 - (steps / 59) ** 1.8 * 70  # 加速下跌至30
    w = np.concatenate([decline, np.linspace(30, 39, 2)])  # 2周强反弹恰在最后一根金叉
    result = weekly_trend(_weekly_frame(w), config)
    assert result.passed
    assert result.reason == "macd_cross"


def test_weekly_signal_macd_stabilizing(config):
    w = np.concatenate(
        [
            np.linspace(100, 58.7, 35),  # 主跌段
            np.linspace(58.7, 66.2, 8),  # 反弹
            np.linspace(66.2, 52.48, 7),  # 二次回落（柱体转负）
            [55.18],  # 柱体拐头向上但仍<0，DIF≈DEA
        ]
    )
    result = weekly_trend(_weekly_frame(w), config)
    assert result.passed
    assert result.reason == "macd_stabilizing"


def test_weekly_downtrend_rejected(config):
    assert weekly_trend(make_accelerating_decline_daily(), config).reason == "weekly_trend_not_passed"


# ---- SPEC §6：周线短期形态 ----


def test_surge_insufficient_completed_weeks_skipped(config):
    assert weekly_surge(make_daily(periods=20), datetime(2026, 9, 15, 10, 0), config).reason == "insufficient_completed_weeks"


def test_surge_missing_current_week_rows_without_quote_skipped(config):
    daily = make_daily(periods=260, end="2026-09-11")
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=None)
    assert result.decision == Decision.SKIP
    assert result.reason == "missing_current_week_rows"


def test_surge_bearish_heavy_turnover_veto(config):
    daily = make_daily(periods=260, end="2026-09-11", drift=0.01)
    daily.iloc[-5:, daily.columns.get_loc("open")] = daily["close"].iloc[-5:] + 0.5
    baseline = daily["amount"].iloc[-10:-5].mean()
    daily.iloc[-5:, daily.columns.get_loc("amount")] = baseline * 2
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=None)
    assert result.decision == Decision.REJECT
    assert result.reason == "bearish_heavy_turnover_veto"


def test_surge_current_week_not_bullish_rejected(config):
    daily = make_daily(periods=260, end="2026-09-14", drift=0.01)
    open_price = float(daily.iloc[-1]["open"])
    quote = Quote(
        "600001",
        price=open_price * 0.97,
        open=open_price,
        previous_close=float(daily.iloc[-1]["close"]),
        volume=20_000_000,
        timestamp=datetime(2026, 9, 15, 11, 30),
    )
    result = weekly_surge(daily, datetime(2026, 9, 15, 11, 30), config, quote)
    assert result.decision == Decision.REJECT
    assert result.reason == "current_week_not_bullish"


def _monday_quote(prev_close: float, change: float, volume: float) -> Quote:
    return Quote(
        "600001",
        price=prev_close * (1 + change),
        open=prev_close,
        previous_close=prev_close,
        volume=volume,
        timestamp=datetime(2026, 9, 14, 10, 30),
    )


def test_surge_dual_yang_efficiency_pass(config):
    """双阳形态：当前周阳线+高于上周收盘+投影量比达标+效率提升。"""
    daily = make_daily(periods=480, end="2026-09-11", drift=0.12)
    prev_close = float(daily.iloc[-1]["close"])
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=_monday_quote(prev_close, 0.03, 250_000))
    assert result.passed
    assert result.reason == "dual_yang_efficiency"
    assert result.signals == ["dual_yang_efficiency"]


def test_surge_bearish_to_bullish_reversal_pass(config):
    """阴转阳形态：上一完成周为阴线，当前周阳线且高于上周收盘。"""
    daily = make_daily(periods=480, end="2026-09-11", drift=0.01)
    daily.iloc[-5:, daily.columns.get_loc("open")] = daily["close"].iloc[-5:] + 0.5  # 上周整体阴线
    prev_close = float(daily.iloc[-1]["close"])
    quote = Quote(
        "600001",
        price=prev_close * 1.02,
        open=prev_close * 0.99,
        previous_close=prev_close,
        volume=1_000_000,
        timestamp=datetime(2026, 9, 14, 10, 30),
    )
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=quote)
    assert result.passed
    assert result.reason == "bearish_to_bullish_reversal"


def _engulfing_quote(daily: pd.DataFrame) -> Quote:
    """阳包阴构造：上周严格阴线（open=close+0.5），本周收盘反穿上周开盘。"""
    prev_close = float(daily.iloc[-1]["close"])
    monday_close = float(daily.iloc[-5]["close"])
    prev_week_open = monday_close + 0.5
    return Quote(
        "600001",
        price=prev_week_open + 0.10,  # 收盘高于上周开盘（实体反包）
        open=prev_close * 0.99,  # 开盘不高于上周收盘
        previous_close=prev_close,
        volume=1_000_000,
        timestamp=datetime(2026, 9, 14, 10, 30),
    )


def _bearish_last_week_daily() -> pd.DataFrame:
    daily = make_daily(periods=480, end="2026-09-11", drift=0.01)
    daily.iloc[-5:, daily.columns.get_loc("open")] = daily["close"].iloc[-5:] + 0.5
    return daily


def test_surge_bullish_engulfing_positive(config):
    """第三类正向形态（阳包阴反包）：PASS + 独立 reason/signals + 关键指标。"""
    daily = _bearish_last_week_daily()
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=_engulfing_quote(daily))
    assert result.decision == Decision.PASS
    assert result.passed
    assert result.reason == "bullish_engulfing"
    assert result.signals == ["bullish_engulfing"]
    assert result.metrics["engulfing_body"] is True
    assert result.metrics["projected_volume_ratio"] >= 0.8
    assert result.metrics["current_change_pct"] > 0


def test_surge_engulfing_counterexamples_fall_back_to_reversal(config):
    """反例1：上周阴线但收盘未反穿上周开盘 → 阴转阳（非反包）；
    反例2：反包形态但 allow_bullish_engulfing=False → 阴转阳（配置关闭）。"""
    daily = _bearish_last_week_daily()
    prev_close = float(daily.iloc[-1]["close"])
    non_engulfing = Quote(
        "600001",
        price=prev_close * 1.02,  # 低于上周开盘，实体未反包
        open=prev_close * 0.99,
        previous_close=prev_close,
        volume=1_000_000,
        timestamp=datetime(2026, 9, 14, 10, 30),
    )
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=non_engulfing)
    assert result.passed
    assert result.reason == "bearish_to_bullish_reversal"
    assert "engulfing_body" not in result.metrics

    gated = dict(config)
    gated["surge"] = {**config["surge"], "allow_bullish_engulfing": False}
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), gated, quote=_engulfing_quote(daily))
    assert result.passed
    assert result.reason == "bearish_to_bullish_reversal"
    assert "engulfing_body" not in result.metrics


def test_surge_not_up_vs_previous_close_rejected(config):
    daily = make_daily(periods=480, end="2026-09-11", drift=0.12)
    prev_close = float(daily.iloc[-1]["close"])
    quote = Quote(
        "600001",
        price=prev_close * 0.995,  # 高于周内开盘但低于上周收盘
        open=prev_close * 0.99,
        previous_close=prev_close,
        volume=250_000,
        timestamp=datetime(2026, 9, 14, 10, 30),
    )
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=quote)
    assert result.decision == Decision.REJECT
    assert result.reason == "not_up_vs_previous_close"


def test_surge_weekly_efficiency_not_improved_rejected(config):
    daily = make_daily(periods=480, end="2026-09-11", drift=0.12)
    prev_close = float(daily.iloc[-1]["close"])
    # 大量低效：投影量比4.0 → 效率 3/4=0.75 < 上周0.79
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=_monday_quote(prev_close, 0.03, 1_000_000))
    assert result.decision == Decision.REJECT
    assert result.reason == "weekly_efficiency_not_improved"


def test_surge_projected_volume_too_low_rejected(config):
    daily = make_daily(periods=480, end="2026-09-11", drift=0.12)
    prev_close = float(daily.iloc[-1]["close"])
    # 5万/0.05=100万 投影量，远低于上周500万 → 量比0.2
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote=_monday_quote(prev_close, 0.03, 50_000))
    assert result.decision == Decision.REJECT
    assert result.reason == "projected_volume_too_low"
    assert result.metrics["volume_ratio"] < 0.8


# ---- SPEC §7：日线买点（含同刻快照缺失回退与优先级） ----


def test_buy_insufficient_daily_bars_skipped(config):
    assert daily_buy(make_daily(periods=50), datetime(2026, 9, 15, 10, 0), config).reason == "insufficient_daily_bars"


def test_buy_missing_same_time_snapshot_falls_back_to_projected(config):
    daily = make_daily(periods=120, end="2026-09-14", drift=0.01)
    previous_close = float(daily.iloc[-1]["close"])
    quote = Quote(
        "600001",
        price=previous_close * 1.02,
        open=previous_close,
        previous_close=previous_close,
        volume=30_000_000,
        timestamp=datetime(2026, 9, 15, 11, 30),
    )
    result = daily_buy(daily, datetime(2026, 9, 15, 11, 30), config, quote=quote, same_time_reference_volume=None)
    assert result.metrics["volume_method"] == "projected_full_day"


def test_buy_same_time_reference_missing_when_fallback_disabled(config):
    config = dict(config)
    config["buy"] = {**config["buy"], "allow_projected_volume_fallback": False}
    daily = make_daily(periods=120, end="2026-09-14", drift=0.01)
    previous_close = float(daily.iloc[-1]["close"])
    quote = Quote(
        "600001",
        price=previous_close * 1.02,
        open=previous_close,
        previous_close=previous_close,
        volume=30_000_000,
        timestamp=datetime(2026, 9, 15, 11, 30),
    )
    result = daily_buy(daily, datetime(2026, 9, 15, 11, 30), config, quote=quote, same_time_reference_volume=None)
    assert result.metrics["volume_method"] == "same_time_reference_missing"


def test_buy_preopen_projected_unavailable(config):
    daily = make_daily(periods=120, end="2026-09-14", drift=0.01)
    previous_close = float(daily.iloc[-1]["close"])
    quote = Quote(
        "600001",
        price=previous_close * 1.02,
        open=previous_close,
        previous_close=previous_close,
        volume=1_000_000,
        timestamp=datetime(2026, 9, 15, 9, 15),
    )
    result = daily_buy(daily, datetime(2026, 9, 15, 9, 15), config, quote=quote, same_time_reference_volume=None)
    assert result.metrics["volume_method"] == "market_not_started"


def _pullback_and_two_day_daily() -> pd.DataFrame:
    """构造同时满足回踩不破与两日加速条件的数据，用于验证买点优先级。"""
    periods = 80
    index = pd.bdate_range(end="2026-09-15", periods=periods)
    close = pd.Series(10 + np.arange(periods) * 0.1, index=index)
    ma10 = close.rolling(10).mean()
    today_close = float(ma10.iloc[-1]) * 1.001  # 贴近MA10
    close.iloc[-1] = today_close
    close.iloc[-2] = today_close / 1.005  # 昨日涨幅约0.5%
    close.iloc[-3] = today_close / 1.010
    frame = pd.DataFrame(
        {
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(periods, 1_000_000.0),
            "amount": close * 100_000_000,
        },
        index=index,
    )
    return frame


def test_buy_pullback_has_priority_over_two_day_acceleration(config):
    daily = _pullback_and_two_day_daily()
    result = daily_buy(daily, datetime(2026, 9, 15, 15, 10), config)
    assert result.passed
    assert result.reason == "pullback_holds"


def test_buy_shrinking_volume_acceleration_passes_intraday_same_time(config):
    daily = make_daily(periods=120, end="2026-09-14", drift=0.01)
    previous_close = float(daily.iloc[-1]["close"])
    quote = Quote(
        "600001",
        price=previous_close * 1.015,
        open=previous_close,
        previous_close=previous_close,
        volume=30_000_000,
        timestamp=datetime(2026, 9, 15, 11, 30),
    )
    result = daily_buy(daily, datetime(2026, 9, 15, 11, 30), config, quote=quote, same_time_reference_volume=60_000_000)
    assert result.passed
    assert result.reason == "shrinking_volume_acceleration"
    assert result.metrics["volume_method"] == "same_time"


def test_buy_two_day_acceleration_passes_after_close(config):
    daily = make_daily(periods=260, end="2026-09-15", drift=0.35)
    daily.iloc[-1, daily.columns.get_loc("close")] += 0.8
    daily.iloc[-1, daily.columns.get_loc("volume")] = 2_000_000.0
    result = daily_buy(daily, datetime(2026, 9, 15, 15, 10), config)
    assert result.passed
    assert result.reason == "two_day_acceleration"


def test_buy_shrinking_has_priority_over_two_day_acceleration(config):
    """缩量加速与两日加速同时满足时，优先判定缩量加速。"""
    daily = make_daily(periods=120, end="2026-09-14", drift=0.35)
    previous_close = float(daily.iloc[-1]["close"])
    quote = Quote(
        "600001",
        price=previous_close * 1.015,
        open=previous_close,
        previous_close=previous_close,
        volume=20_000_000,
        timestamp=datetime(2026, 9, 15, 11, 30),
    )
    result = daily_buy(daily, datetime(2026, 9, 15, 11, 30), config, quote=quote, same_time_reference_volume=40_000_000)
    assert result.passed
    assert result.reason == "shrinking_volume_acceleration"


# ---- SPEC §8：板块模式跳过surge但保留闸门与买点 ----


def _bare_pipeline(config, daily: pd.DataFrame, tmp_path: Path) -> SelectorPipeline:
    pipeline = SelectorPipeline.__new__(SelectorPipeline)
    pipeline.config = config
    pipeline.output_dir = tmp_path
    pipeline.names = {}
    cache = {"600001": daily, "600002": daily}
    pipeline._daily = lambda code: cache.get(str(code).zfill(6))
    return pipeline


def test_board_mode_skips_surge_but_keeps_gates_and_buy(config, tmp_path):
    pipeline = _bare_pipeline(config, make_daily(periods=260, end="2026-09-15"), tmp_path)
    pool = pd.DataFrame({"代码": ["600001", "600002"], "名称": ["正常公司", "*ST危险"]})
    paths = pipeline._run_signal_pipeline(pool, datetime(2026, 9, 15, 15, 10), {}, {}, realtime=False, skip_surge=True)
    diagnostics = __import__("json").loads(Path(paths["diagnostics"]).read_text(encoding="utf-8"))
    assert diagnostics["surge"]["reasons"].get("board_mode_skips_surge") == 1
    assert diagnostics["risk"]["reasons"].get("st_or_delisting_excluded") == 1
    assert diagnostics["buy"]["total"] == 1  # ST被拦后仅正常公司进入买点
    rejections = pd.read_csv(paths["rejections"], dtype={"代码": str})
    assert (rejections["阶段"] == "surge").sum() == 0  # surge未被当作淘汰阶段


# ---- NaN 输入与聚合语义 ----


def test_weekly_aggregation_close_is_last_available_close(config):
    """周收盘取周内最后一个可得收盘（缺失日按可得值聚合，不编造、不崩溃）。"""
    daily = make_daily(periods=40, end="2026-09-11")
    thursday_close = float(daily.iloc[-2]["close"])
    daily.iloc[-1, daily.columns.get_loc("close")] = float("nan")  # 周五缺失
    weekly = aggregate_weekly(daily)
    assert not weekly.empty
    assert abs(float(weekly.iloc[-1]["close"]) - thursday_close) < 1e-9


def test_strategies_deterministic_with_nan_close_input(config):
    nan_daily = make_daily(periods=480, end="2026-09-15", drift=0.12)
    nan_daily.iloc[-1, nan_daily.columns.get_loc("close")] = float("nan")
    monthly = monthly_trend(nan_daily, config)
    weekly = weekly_trend(nan_daily, config)
    buy = daily_buy(nan_daily, datetime(2026, 9, 15, 15, 10), config)
    for result in (monthly, weekly, buy):
        assert result.decision in {Decision.PASS, Decision.REJECT, Decision.SKIP}  # 不抛异常且判定确定
    assert buy.decision == Decision.REJECT
    assert buy.reason == "daily_buy_pattern_not_passed"


def test_realtime_volume_unit_default_is_hand_to_share(config):
    """腾讯行情默认手→股换算系数100（系统内部单位为股）。"""
    assert TencentQuoteProvider().volume_multiplier == 100.0


def test_tencent_valid_quote_converts_hands_to_shares(config):
    """有效腾讯报文：1234手 必须解析为 123400股（数值断言，非配置断言）。"""
    fields = ["1", "测试", "600001", "10.20", "10.00", "10.10", "1234", *["0"] * 22, "20260915100000"]
    quotes, errors = _provider_with(fields).fetch(["600001"], datetime(2026, 9, 15, 10, 0))
    assert errors == {}
    quote = quotes["600001"]
    assert quote.volume == 123400
    assert quote.price == 10.20
    assert quote.previous_close == 10.00
    assert quote.open == 10.10


# ---- SPEC §6 第三类：放量阴线否决的独立类与优先级 ----


def test_surge_veto_priority_over_current_week_direction(config):
    """放量阴线否决是独立类别：即使当前周为阳线且高于上周收盘，仍优先否决。"""
    daily = make_daily(periods=480, end="2026-09-11", drift=0.01)
    daily.iloc[-5:, daily.columns.get_loc("open")] = daily["close"].iloc[-5:] + 0.5  # 上周阴线
    baseline = daily["amount"].iloc[-10:-5].mean()
    daily.iloc[-5:, daily.columns.get_loc("amount")] = baseline * 2  # 放量2倍
    prev_close = float(daily.iloc[-1]["close"])
    quote = Quote(
        "600001",
        price=prev_close * 1.03,  # 当前周强势阳线
        open=prev_close,
        previous_close=prev_close,
        volume=1_000_000,
        timestamp=datetime(2026, 9, 14, 10, 30),
    )
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote)
    assert result.decision == Decision.REJECT
    assert result.reason == "bearish_heavy_turnover_veto"
    assert result.metrics["veto_metric"] in {"amount", "volume"}
    assert result.metrics["veto_ratio"] >= 1.5


# ---- SPEC §8：板块模式的统一数据闸门 ----


def _board_diagnostics(pipeline, daily_end, asof, realtime=False, quotes=None):
    pool = pd.DataFrame({"代码": ["600001"], "名称": ["正常公司"]})
    paths = pipeline._run_signal_pipeline(pool, asof, quotes or {}, {}, realtime=realtime, skip_surge=True)
    return paths, __import__("json").loads(Path(paths["diagnostics"]).read_text(encoding="utf-8"))


def test_board_mode_blocks_stale_daily_before_buy(config, tmp_path):
    pipeline = _bare_pipeline(config, make_daily(periods=260, end="2026-09-01"), tmp_path)
    paths, diagnostics = _board_diagnostics(pipeline, None, datetime(2026, 9, 15, 15, 10))
    assert diagnostics["freshness"]["reasons"].get("daily_data_stale") == 1
    assert diagnostics["buy"]["total"] == 0  # 未进入买点
    rejections = pd.read_csv(paths["rejections"], dtype={"代码": str})
    assert (rejections["阶段"] == "freshness").sum() == 1


def test_board_mode_blocks_future_daily_before_buy(config, tmp_path):
    pipeline = _bare_pipeline(config, make_daily(periods=260, end="2026-09-16"), tmp_path)
    paths, diagnostics = _board_diagnostics(pipeline, None, datetime(2026, 9, 15, 15, 10))
    assert diagnostics["freshness"]["reasons"].get("future_daily_bar") == 1
    assert diagnostics["buy"]["total"] == 0


def test_board_mode_realtime_blocks_missing_and_stale_quote(config, tmp_path):
    # 缺失实时报价：quote 阶段直接跳过，不进入买点
    pipeline = _bare_pipeline(config, make_daily(periods=260, end="2026-09-15"), tmp_path)
    _, diagnostics = _board_diagnostics(pipeline, None, datetime(2026, 9, 15, 10, 30), realtime=True, quotes={})
    assert diagnostics["surge"]["reasons"].get("missing_realtime_quote") == 1
    assert diagnostics["buy"]["total"] == 0
    # 过期报价：freshness 阶段 quote_stale 拦截
    stale_quote = {"600001": Quote("600001", 10.0, 10.0, 9.9, 1_000_000, timestamp=datetime(2026, 9, 15, 8, 0))}
    _, diagnostics = _board_diagnostics(pipeline, None, datetime(2026, 9, 15, 10, 30), realtime=True, quotes=stale_quote)
    assert diagnostics["freshness"]["reasons"].get("quote_stale") == 1
    assert diagnostics["buy"]["total"] == 0


# ---- SPEC §9：底部三倍量观察池（日线形态语义） ----


def _bottom_daily(volume_multiple: float = 4.0, final_close: float = 6.6, final_open: float = 6.15) -> pd.DataFrame:
    n = 300
    idx = pd.bdate_range(end="2026-09-15", periods=n)
    close = np.concatenate([np.full(60, 10.0), np.linspace(10, 6.2, 40), np.full(200, 6.2)])
    open_ = close * 0.999
    high = np.concatenate([np.full(60, 10.2), np.linspace(10.2, 6.3, 40), np.full(200, 6.3)])
    low = close * 0.99
    vol = np.full(n, 1_000_000.0)
    close[-1], open_[-1], low[-1], high[-1] = final_close, final_open, 6.1, 6.65
    vol[-1] = volume_multiple * 1_000_000.0
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": vol, "amount": close * vol},
        index=idx,
    )


def test_bottom_volume_launch_positive(config):
    result = bottom_volume_signal(_bottom_daily(), config)
    assert result.passed
    assert result.reason == "bottom_volume_launch"
    assert result.signals == ["bottom_launch"]
    assert result.metrics["volume_multiple"] >= 3.0
    assert result.metrics["drawdown_pct"] <= -30.0


def test_bottom_volume_rejects_low_multiple_and_non_yang(config):
    assert bottom_volume_signal(_bottom_daily(volume_multiple=2.0), config).reason == "volume_multiple_too_low"
    assert bottom_volume_signal(_bottom_daily(final_close=6.0), config).reason == "not_yang"
    assert bottom_volume_signal(make_daily(periods=100), config).reason == "insufficient_daily_bars"


# ---- 输出归档与研究边界 ----


def test_current_week_rows_excludes_future_days(config):
    """前视防护：当前周切片只允许 asof 当日（含）之前的行。"""
    frame = make_daily(periods=40, end="2026-09-18")  # 含周一至周五完整周
    rows_tue = current_week_rows(frame, datetime(2026, 9, 16, 10, 30))
    assert set(pd.to_datetime(rows_tue.index).date) <= {date(2026, 9, 14), date(2026, 9, 15), date(2026, 9, 16)}
    rows_mon = current_week_rows(frame, datetime(2026, 9, 14, 10, 30))
    assert set(pd.to_datetime(rows_mon.index).date) == {date(2026, 9, 14)}


def test_week_fraction_never_counts_future_days_after_close(config):
    """盘后周进度只统计 asof（含）之前已完成的交易日，未来行不计入。"""
    frame = make_daily(periods=40, end="2026-09-18")  # 误同步含周四/周五数据
    fraction = elapsed_week_fraction(frame, datetime(2026, 9, 16, 15, 10), realtime=False)
    assert abs(fraction - 0.6) < 1e-9  # 周一二三 3/5，而非 5/5


def test_daily_buy_ignores_future_rows(config):
    """日线买点盘后语义只允许 asof 当日（含）之前的日线参与计算（与截断数据完全等价）。"""
    frame = make_daily(periods=260, end="2026-09-18", drift=0.01)
    truncated = frame[frame.index <= "2026-09-16"]
    asof = datetime(2026, 9, 16, 15, 10)
    with_future = daily_buy(frame, asof, config)
    without_future = daily_buy(truncated, asof, config)
    assert with_future.reason == without_future.reason
    assert with_future.decision == without_future.decision
    if without_future.passed:
        # “今天”必须是周三：含未来行与截断后价格指标一致
        assert with_future.metrics["price"] == without_future.metrics["price"]
        assert with_future.metrics["price"] == round(float(truncated.iloc[-1]["close"]), 3)


def test_run_archive_preserves_previous_results(config, tmp_path):
    """两次运行的 runs/ 归档各自独立，既有归档不被覆盖。"""
    pipeline = _bare_pipeline(config, make_daily(periods=260, end="2026-09-15"), tmp_path)
    pool = pd.DataFrame({"代码": ["600001"], "名称": ["正常公司"]})
    first = pipeline._run_signal_pipeline(pool, datetime(2026, 9, 15, 15, 10), {}, {}, realtime=False, skip_surge=True)
    second = pipeline._run_signal_pipeline(pool, datetime(2026, 9, 15, 15, 20), {}, {}, realtime=False, skip_surge=True)
    archive1, archive2 = Path(first["run_archive"]), Path(second["run_archive"])
    assert archive1 != archive2
    assert (archive1 / "diagnostics.json").exists()
    assert (archive2 / "diagnostics.json").exists()
    d1 = __import__("json").loads((archive1 / "diagnostics.json").read_text(encoding="utf-8"))
    assert d1["surge"]["reasons"].get("board_mode_skips_surge") == 1  # 第一次归档未被第二次覆盖


def test_run_archive_same_second_collision_appends_suffix(config, tmp_path):
    """归档碰撞边界：同一秒重复运行追加序号目录，既有归档内容原样保留。"""
    pipeline = _bare_pipeline(config, make_daily(periods=260, end="2026-09-15"), tmp_path)
    pool = pd.DataFrame({"代码": ["600001"], "名称": ["正常公司"]})
    same_moment = datetime(2026, 9, 15, 15, 10)
    first = pipeline._run_signal_pipeline(pool, same_moment, {}, {}, realtime=False, skip_surge=True)
    second = pipeline._run_signal_pipeline(pool, same_moment, {}, {}, realtime=False, skip_surge=True)
    archive1, archive2 = Path(first["run_archive"]), Path(second["run_archive"])
    assert archive1 != archive2  # 同秒不覆盖：second 落到 <suffix>-2
    assert archive2.name.endswith("-2")
    assert (archive1 / "diagnostics.json").exists()
    assert (archive2 / "diagnostics.json").exists()


def test_scores_are_ranking_only_and_rules_never_consume_backtest(config):
    """排序分非概率、规则判定不消费回测：可执行的静态契约检查。"""
    import stock_selector.strategies

    strategies_dir = Path(list(stock_selector.strategies.__path__[0:1])[0])
    for module in strategies_dir.glob("*.py"):
        assert "backtest" not in module.read_text(encoding="utf-8"), f"{module.name} 不允许引用回测模块"
    pipeline_src = (Path(strategies_dir).parent / "pipeline.py").read_text(encoding="utf-8")
    output_src = (Path(strategies_dir).parent / "output.py").read_text(encoding="utf-8")
    for src, name in ((pipeline_src, "pipeline.py"), (output_src, "output.py")):
        assert "概率" not in src, f"{name} 不得出现概率表述"
    assert "综合评分" in pipeline_src  # 输出列名明确为评分而非概率
