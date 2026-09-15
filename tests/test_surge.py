from datetime import datetime

from stock_selector.models import Quote
from stock_selector.strategies.surge import weekly_surge
from conftest import make_daily


def test_monday_current_week_uses_current_open_not_last_week_open(config):
    daily = make_daily(periods=260, end="2026-09-11", drift=0.01)
    last_close = float(daily.iloc[-1].close)
    quote = Quote("600001", price=last_close * 1.01, open=last_close * 1.005, previous_close=last_close, volume=10_000_000, timestamp=datetime(2026, 9, 14, 10, 30))
    result = weekly_surge(daily, datetime(2026, 9, 14, 10, 30), config, quote)
    assert result.reason != "missing_current_week_rows"
    if "current_change_pct" in result.metrics:
        expected = (quote.price / quote.open - 1) * 100
        assert abs(result.metrics["current_change_pct"] - expected) < 0.01


def test_realtime_return_is_not_projected_to_five_days(config):
    daily = make_daily(periods=260, end="2026-09-14", drift=0.01)
    last_close = float(daily.iloc[-2].close)
    quote = Quote("600001", price=float(daily.iloc[-1].open) * 1.02, open=float(daily.iloc[-1].open), previous_close=float(daily.iloc[-1].close), volume=100_000_000, timestamp=datetime(2026, 9, 15, 11, 30))
    result = weekly_surge(daily, datetime(2026, 9, 15, 11, 30), config, quote)
    if "current_change_pct" in result.metrics:
        assert abs(result.metrics["current_change_pct"] - 2.0) < 0.01
