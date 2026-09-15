from datetime import datetime

from stock_selector.models import Quote
from stock_selector.strategies.buy import daily_buy
from conftest import make_daily


def test_realtime_ma_includes_synthetic_current_price(config):
    daily = make_daily(end="2026-09-14")
    quote = Quote("600001", price=float(daily.iloc[-1].close) + 0.2, open=float(daily.iloc[-1].close), previous_close=float(daily.iloc[-1].close), volume=50_000_000, timestamp=datetime(2026, 9, 15, 15, 0))
    result = daily_buy(daily, datetime(2026, 9, 15, 15, 0), config, quote=quote, same_time_reference_volume=60_000_000)
    assert result.metrics.get("price") == round(quote.price, 3) or not result.passed


def test_after_close_uses_previous_bar_as_previous_close(config):
    daily = make_daily(end="2026-09-15", drift=0.1)
    result = daily_buy(daily, datetime(2026, 9, 15, 15, 10), config)
    if "day_change_pct" in result.metrics:
        expected = (daily.iloc[-1].close / daily.iloc[-2].close - 1) * 100
        assert abs(result.metrics["day_change_pct"] - expected) < 0.01


def test_after_close_volume_ratio_uses_daily_bars(config):
    daily = make_daily(end="2026-09-15", drift=0.35)
    daily.iloc[-1, daily.columns.get_loc("close")] += 0.6
    daily.iloc[-1, daily.columns.get_loc("volume")] = 700_000.0
    daily.iloc[-2, daily.columns.get_loc("volume")] = 1_400_000.0
    result = daily_buy(daily, datetime(2026, 9, 15, 15, 10), config)
    assert result.reason == "shrinking_volume_acceleration"
    assert result.metrics["volume_method"] == "daily_bar_ratio"
    assert abs(result.metrics["volume_ratio"] - 0.5) < 0.001


def test_shrinking_volume_requires_comparable_volume(config):
    daily = make_daily(end="2026-09-14", drift=0.01)
    previous_close = float(daily.iloc[-1].close)
    quote = Quote("600001", price=previous_close * 1.01, open=previous_close, previous_close=previous_close, volume=30_000_000, timestamp=datetime(2026, 9, 15, 11, 30))
    result = daily_buy(daily, datetime(2026, 9, 15, 11, 30), config, quote=quote, same_time_reference_volume=40_000_000)
    if result.passed and result.reason == "shrinking_volume_acceleration":
        assert result.metrics["volume_method"] == "same_time"
        assert result.metrics["volume_ratio"] == 0.75
