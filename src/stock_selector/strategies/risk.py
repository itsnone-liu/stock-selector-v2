from __future__ import annotations

import re

import pandas as pd

from stock_selector.models import Decision, RuleResult


ST_PATTERN = re.compile(r"(?:\*?ST|退市)", re.IGNORECASE)


def check_risk_filters(
    code: str,
    name: str,
    daily: pd.DataFrame,
    config: dict,
) -> RuleResult:
    code = str(code).zfill(6)
    cfg = config["universe"]
    if not cfg.get("include_b_share", False) and (code.startswith("900") or code.startswith("200")):
        return RuleResult(Decision.REJECT, "risk", "b_share_excluded")
    if cfg.get("exclude_st", True) and name and ST_PATTERN.search(str(name)):
        return RuleResult(Decision.REJECT, "risk", "st_or_delisting_excluded")
    if daily is None or daily.empty:
        return RuleResult(Decision.SKIP, "risk", "missing_daily_data")
    if len(daily) < int(cfg.get("min_listing_days", 120)):
        return RuleResult(Decision.REJECT, "risk", "listing_history_too_short", metrics={"days": len(daily)})
    minimum_amount = float(cfg.get("min_median_amount_20d", 0))
    if minimum_amount > 0 and "amount" in daily.columns:
        median_amount = float(daily["amount"].tail(20).median())
        if pd.isna(median_amount) or median_amount < minimum_amount:
            return RuleResult(
                Decision.REJECT,
                "risk",
                "liquidity_too_low",
                metrics={"median_amount_20d": median_amount, "minimum": minimum_amount},
            )
    return RuleResult(Decision.PASS, "risk", "risk_filters_passed")
