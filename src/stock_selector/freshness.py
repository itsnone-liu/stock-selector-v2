from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.models import Decision, Quote, RuleResult


def business_day_lag(last_date, asof_date) -> int:
    if last_date >= asof_date:
        return 0
    return max(0, len(pd.bdate_range(pd.Timestamp(last_date) + pd.Timedelta(days=1), pd.Timestamp(asof_date))))


def check_daily_freshness(daily: pd.DataFrame, asof: datetime, config: dict, realtime: bool) -> RuleResult:
    if daily is None or daily.empty:
        return RuleResult(Decision.SKIP, "freshness", "missing_daily_data")
    last_date = pd.Timestamp(daily.index[-1]).date()
    if config["freshness"].get("reject_future_daily_bar", True) and last_date > asof.date():
        return RuleResult(Decision.ERROR, "freshness", "future_daily_bar", metrics={"last_date": last_date})
    max_lag = int(config["freshness"].get("max_daily_data_business_day_lag", 5))
    lag = business_day_lag(last_date, asof.date())
    # 盘中允许历史日线截至上一个交易日；盘后应包含当日，节假日配置缺失时保留可解释宽限。
    allowed = max_lag if realtime else min(max_lag, 1)
    if lag > allowed:
        return RuleResult(Decision.SKIP, "freshness", "daily_data_stale", metrics={"last_date": last_date, "business_day_lag": lag})
    return RuleResult(Decision.PASS, "freshness", "daily_data_fresh", metrics={"last_date": last_date, "business_day_lag": lag})


def check_quote_freshness(quote: Quote, asof: datetime, config: dict) -> RuleResult:
    if quote.timestamp is None:
        return RuleResult(Decision.SKIP, "freshness", "quote_timestamp_missing")
    age = abs((asof - quote.timestamp).total_seconds())
    maximum = float(config["freshness"].get("max_quote_age_seconds", 180))
    if age > maximum:
        return RuleResult(Decision.SKIP, "freshness", "quote_stale", metrics={"quote_age_seconds": age})
    return RuleResult(Decision.PASS, "freshness", "quote_fresh", metrics={"quote_age_seconds": age})
