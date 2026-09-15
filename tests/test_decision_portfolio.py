"""组合/T+1、退出、建议合成、regime与上下文的测试。"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from stock_selector.decision.advice import BUY, HOLD, SELL, WATCH, compose_advice
from stock_selector.decision.clock import session_clock
from stock_selector.decision.exits import E1_STRUCTURAL, E2_TIME, E3_TRAIL, ExitAnchor, ExitMonitor
from stock_selector.decision.labels import DailyLabels
from stock_selector.decision.portfolio import Portfolio
from stock_selector.decision.regime import (
    BULL,
    MID,
    WEAK,
    CapitalContext,
    market_regime,
    parse_capital_context,
)
from stock_selector.decision.weekly_momentum import (
    ACTIVE_UP,
    CURRENT_WEEK,
    EVALUATED,
    MomentumResult,
)
from tests.test_decision_core import make_daily


class TestPortfolioT1:
    def test_buy_today_not_sellable(self):
        p = Portfolio(cash=1_000_000)
        p.buy("600000", 10.0, 1000, datetime(2026, 9, 15, 10, 0))
        assert p.positions["600000"].qty == 1000
        assert p.positions["600000"].sellable_qty(datetime(2026, 9, 15).date()) == 0  # T+1
        assert p.positions["600000"].sellable_qty(datetime(2026, 9, 16).date()) == 1000

    def test_sell_respects_t1(self):
        p = Portfolio(cash=1_000_000)
        p.buy("600000", 10.0, 1000, datetime(2026, 9, 15, 10, 0))
        sold = p.sell("600000", 10.5, 500, datetime(2026, 9, 15, 14, 0))
        assert sold == 0  # 当日不可卖
        sold2 = p.sell("600000", 10.5, 500, datetime(2026, 9, 16, 10, 0))
        assert sold2 == 500

    def test_single_cap(self):
        p = Portfolio(cash=1_000_000)
        p.buy("600000", 10.0, 15000, datetime(2026, 9, 15, 10, 0))  # 15万=15%
        p.mark({"600000": 10.0})
        ok, reasons = p.can_buy("600000", 10.0, 10000, {"single_max_pct": 20}, datetime(2026, 9, 16).date(), BULL)
        assert not ok and any("single_cap" in r for r in reasons)  # 15%+10%>20%

    def test_regime_exposure_cap(self):
        p = Portfolio(cash=1_000_000)
        ok, reasons = p.can_buy("600001", 10.0, 20000, {}, datetime(2026, 9, 16).date(), WEAK)
        assert not ok and any("regime_exposure_cap" in r for r in reasons)  # weak=0目标敞口

    def test_daily_add_cap(self):
        p = Portfolio(cash=1_000_000)
        p.buy("600000", 10.0, 20000, datetime(2026, 9, 15, 10, 0))  # 当日已加20%
        p.mark({"600000": 10.0})
        ok, reasons = p.can_buy("600001", 10.0, 20000, {"daily_add_max_pct": 30}, datetime(2026, 9, 15).date(), BULL)
        assert not ok and any("daily_add_cap" in r for r in reasons)

    def test_industry_cap(self):
        p = Portfolio(cash=1_000_000)
        p.buy("600000", 10.0, 20000, datetime(2026, 9, 12, 10, 0), industry="银行")
        p.mark({"600000": 10.0})
        ok, reasons = p.can_buy("600001", 10.0, 30000, {"industry_max_pct": 40}, datetime(2026, 9, 15).date(), BULL, industry="银行")
        assert not ok and any("industry_cap" in r for r in reasons)


def _make_anchor(**kw) -> ExitAnchor:
    defaults = dict(entry_date="2026-09-10", entry_price=10.0, structural_stop=9.4)
    defaults.update(kw)
    return ExitAnchor(**defaults)


class TestExits:
    def test_e1_close_confirm(self):
        daily = make_daily([10, 10.1, 10.2, 9.2, 9.1], end="2026-09-15")  # 收盘跌破9.4
        anchor = _make_anchor()
        signals = ExitMonitor().check("600000", daily, datetime(2026, 9, 15, 15, 10), anchor)
        rules = [s.rule for s in signals]
        assert E1_STRUCTURAL in rules
        e1 = next(s for s in signals if s.rule == E1_STRUCTURAL and s.confirm == "close")
        assert e1.executed_reference == "次日开盘"

    def test_e1_intraday_trigger(self):
        daily = make_daily([10, 10.1, 10.2, 9.8], end="2026-09-15")
        from stock_selector.models import Quote

        quote = Quote(code="600000", price=9.2, open=9.8, previous_close=9.8, volume=100.0)
        anchor = _make_anchor(entry_date="2026-09-11")
        signals = ExitMonitor().check("600000", daily, datetime(2026, 9, 15, 13, 30), anchor, quote=quote)
        intraday = [s for s in signals if s.rule == E1_STRUCTURAL and s.confirm == "intraday"]
        assert intraday and intraday[0].executed_reference == "当日即时"

    def test_e2_time_stop(self):
        # 入场2026-09-01后给足交易日
        closes = [10 + i * 0.02 for i in range(12)]
        daily = make_daily(closes, end="2026-09-16")
        anchor = _make_anchor(entry_date="2026-09-01", time_stop_days=5)
        signals = ExitMonitor().check("600000", daily, datetime(2026, 9, 16, 15, 10), anchor)
        assert any(s.rule == E2_TIME for s in signals)

    def test_e3_trailing_close(self):
        closes = [10, 10.5, 11.0, 10.6, 10.1]  # 峰值11→回撤8.2%
        daily = make_daily(closes, end="2026-09-15")
        anchor = _make_anchor(entry_date="2026-09-08", trail_pct=0.08)
        signals = ExitMonitor().check("600000", daily, datetime(2026, 9, 15, 15, 10), anchor)
        assert any(s.rule == E3_TRAIL for s in signals)

    def test_t1_note_on_intraday_exit(self):
        # 当日买入(持有0个完整日)盘中触发E1 → 信号带T+1提示
        daily = make_daily([10, 10.1, 10.0], end="2026-09-15")
        from stock_selector.models import Quote

        quote = Quote(code="600000", price=9.3, open=10.0, previous_close=10.0, volume=100.0)
        anchor = _make_anchor(entry_date="2026-09-15", structural_stop=9.4)
        signals = ExitMonitor().check("600000", daily, datetime(2026, 9, 15, 14, 0), anchor, quote=quote)
        e1 = [s for s in signals if s.rule == E1_STRUCTURAL and s.confirm == "intraday"]
        assert e1 and "T+1" in e1[0].note


class TestRegimeAndContext:
    def test_market_regime_states(self):
        idx = make_daily([3000 + i * 5 for i in range(80)], end="2026-09-15")
        regime, m = market_regime(idx, datetime(2026, 9, 15, 15, 10))
        assert regime == BULL
        idx_down = make_daily([4000 - i * 5 for i in range(80)], end="2026-09-15")
        regime2, _ = market_regime(idx_down, datetime(2026, 9, 15, 15, 10))
        assert regime2 == WEAK

    def test_regime_insufficient_is_none_not_mid(self):
        idx = make_daily([10, 10.1, 10.2], end="2026-09-15")
        regime, m = market_regime(idx, datetime(2026, 9, 15, 15, 10))
        assert regime is None

    def test_context_unknown_not_neutral(self):
        ctx = parse_capital_context(None)
        assert ctx.context == "unknown"
        assert ctx.divergent_or_unknown()
        ctx2 = parse_capital_context({"context": "supportive", "channels": {"margin": {"evidence_type": "fact", "status": "fresh"}}})
        assert ctx2.context == "supportive"
        assert ctx2.coverage == "1/1"

    def test_context_corrupt_channel(self):
        ctx = parse_capital_context({"context": "bogus", "channels": {"etf": "垃圾"}})
        assert ctx.context == "unknown"
        assert ctx.channels["etf"].status == "unknown"


def _momentum(state=ACTIVE_UP, origin=CURRENT_WEEK) -> MomentumResult:
    return MomentumResult(state, origin, EVALUATED, mode="revised_weekday",
                          calendar_weekday=3, trading_session_in_week=3,
                          source_week="2026-09-18", metrics={"realized_week_return_pct": 2.0})


def _labels() -> DailyLabels:
    return DailyLabels(
        labels={"pullback_holds": False, "shrinking_volume_acceleration": True, "two_day_acceleration": True},
        primary_type="shrinking_volume_acceleration",
        features={"price": 10.5, "volume_ratio_vs_prev": 0.7, "volume_method": "daily_bar_ratio"},
    )


class TestAdvice:
    def test_buy_in_bull_with_full_evidence(self):
        asof = datetime(2026, 9, 16, 14, 50)
        clock = session_clock(asof)
        advice = compose_advice(
            "600000", asof, clock,
            monthly={"passed": True, "reason": "monthly_ma_bull"},
            weekly_trend={"ma_bull": True, "macd_cross": False, "macd_stabilizing": False, "any": True},
            momentum=_momentum(), labels=_labels(), regime=BULL,
            context=parse_capital_context({"context": "supportive", "channels": {}}),
            daily=make_daily([10 + i * 0.05 for i in range(30)], end="2026-09-15"),
            config={},
        )
        assert advice.action == BUY
        assert advice.overnight_risk.get("note")
        assert "T+1" in advice.overnight_risk["note"]
        assert advice.size_hint["max"] <= 0.20 + 1e-9
        assert advice.invalidation.get("structural_stop")

    def test_no_high_confidence_with_unknowns(self):
        asof = datetime(2026, 9, 16, 14, 50)
        advice = compose_advice(
            "600000", asof, session_clock(asof),
            monthly={"passed": True}, weekly_trend={"any": True},
            momentum=_momentum(), labels=_labels(), regime=None,
            context=parse_capital_context(None),
            daily=make_daily([10] * 30, end="2026-09-15"), config={},
        )
        assert advice.unknowns
        assert advice.confidence != "high"

    def test_weak_regime_blocks_buy(self):
        asof = datetime(2026, 9, 16, 14, 50)
        advice = compose_advice(
            "600000", asof, session_clock(asof),
            monthly={"passed": True}, weekly_trend={"any": True},
            momentum=_momentum(), labels=_labels(), regime=WEAK,
            context=parse_capital_context({"context": "supportive"}),
            daily=make_daily([10] * 30, end="2026-09-15"), config={},
        )
        assert advice.action == WATCH
        assert any("weak" in r for r in advice.rationale)

    def test_exit_overrides_entry(self):
        asof = datetime(2026, 9, 16, 14, 50)
        daily = make_daily([10, 10.2, 10.4, 9.1], end="2026-09-15")  # 破结构位
        p = Portfolio(cash=100_000)
        p.buy("600000", 10.2, 1000, datetime(2026, 9, 10, 10, 0))
        p.mark({"600000": 9.1})
        advice = compose_advice(
            "600000", asof, session_clock(asof),
            monthly={"passed": True}, weekly_trend={"any": True},
            momentum=_momentum(), labels=_labels(), regime=BULL,
            context=parse_capital_context({"context": "supportive"}),
            portfolio=p, daily=daily, anchor=_make_anchor(entry_date="2026-09-10", structural_stop=9.4),
            config={},
        )
        assert advice.action == SELL
        assert advice.exit_signals

    def test_hold_without_exit(self):
        asof = datetime(2026, 9, 16, 14, 50)
        daily = make_daily([10, 10.2, 10.4, 10.5], end="2026-09-15")
        p = Portfolio(cash=100_000)
        p.buy("600000", 10.2, 1000, datetime(2026, 9, 8, 10, 0))
        p.mark({"600000": 10.5})
        advice = compose_advice(
            "600000", asof, session_clock(asof),
            monthly={"passed": True}, weekly_trend={"any": True},
            momentum=_momentum(state=ACTIVE_UP), labels=_labels(), regime=BULL,
            context=parse_capital_context({"context": "supportive"}),
            portfolio=p, daily=daily, anchor=_make_anchor(entry_date="2026-09-08", time_stop_days=99, max_hold_days=99),
            config={},
        )
        assert advice.action in (HOLD, "add")
