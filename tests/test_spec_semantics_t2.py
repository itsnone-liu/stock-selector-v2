"""T2 规则与数据语义审计测试（SPEC §1-8 逐项、确定性、无网络）。

覆盖边界：空数据、短历史、NaN、过期数据、未来数据、周一/盘中边界、
成交量单位、零价零量、缺少同刻快照与买点优先级。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from conftest import make_daily
from stock_selector.data.realtime import TencentQuoteProvider
from stock_selector.freshness import check_daily_freshness, check_quote_freshness
from stock_selector.models import Decision, Quote
from stock_selector.pipeline import SelectorPipeline
from stock_selector.strategies.buy import daily_buy
from stock_selector.strategies.risk import check_risk_filters
from stock_selector.strategies.surge import weekly_surge
from stock_selector.strategies.trend import monthly_trend, weekly_trend
from stock_selector.calendar import completed_week_rows, current_week_rows


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
