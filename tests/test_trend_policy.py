"""weekly_trend_policy 三档开关测试：hard_gate / feature_only / off。

滚动验证未裁决周趋势硬门槛的价值，故必须是可实验配置而非写死。
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from stock_selector.config import load_config  # noqa: E402
from stock_selector.decision.advice import BUY, WATCH, compose_advice  # noqa: E402
from stock_selector.decision.clock import session_clock  # noqa: E402
from stock_selector.decision.weekly_momentum import ACTIVE_UP, CURRENT_WEEK, MomentumResult  # noqa: E402
from stock_selector.decision.labels import DailyLabels  # noqa: E402
from stock_selector.decision.regime import BULL, parse_capital_context  # noqa: E402
from tests.test_decision_core import make_daily  # noqa: E402
from tests.test_decision_portfolio import _labels, _momentum  # noqa: E402

ASOF = datetime(2026, 9, 16, 15, 5)
TREND_FAIL = {"ma_bull": False, "macd_cross": False, "macd_stabilizing": False, "any": False}


def _advice(policy: str, weekly_trend: dict):
    cfg = {"decision": {"weekly_trend_policy": policy,
                        "portfolio": {"single_max_pct": 20, "industry_max_pct": 40, "daily_add_max_pct": 30},
                        "exits": {"time_stop_days": 5, "trail_pct": 8.0, "max_hold_days": 20}}}
    return compose_advice(
        "600000", ASOF, session_clock(ASOF),
        monthly={"passed": True}, weekly_trend=weekly_trend,
        momentum=_momentum(), labels=_labels(), regime=BULL,
        context=parse_capital_context(None),
        daily=make_daily([10 + i * 0.05 for i in range(30)], end="2026-09-15"),
        config=cfg,
    )


def test_default_is_hard_gate_current_behavior():
    cfg = load_config()["decision"]
    assert cfg.get("weekly_trend_policy", "hard_gate") == "hard_gate"
    a = _advice("hard_gate", TREND_FAIL)
    assert a.action == WATCH, "硬门槛下趋势不过不允许BUY"


def test_feature_only_allows_buy_when_trend_fails():
    a = _advice("feature_only", TREND_FAIL)
    assert a.action == BUY, "feature_only：趋势不过滤，其余齐备应BUY"


def test_off_allows_buy_when_trend_fails():
    a = _advice("off", TREND_FAIL)
    assert a.action == BUY


def test_all_policies_identical_when_trend_passes():
    for policy in ("hard_gate", "feature_only", "off"):
        a = _advice(policy, {"ma_bull": True, "macd_cross": False,
                             "macd_stabilizing": False, "any": True})
        assert a.action == BUY, policy
