"""P0 执行模型：费用、滑点与开盘可成交性。"""
from datetime import date

import pandas as pd
import pytest

from stock_selector.decision.execution import CostModel, execution_feasibility
from stock_selector.decision.portfolio import Portfolio


def test_cost_model_buy_sell_and_stamp_cutover():
    c = CostModel(commission_rate=0.0003, minimum_commission=5,
                  slippage_bps=5, transfer_fee_rate=0.00001)
    assert c.fill_price(10, "buy") == pytest.approx(10.005)
    assert c.fill_price(10, "sell") == pytest.approx(9.995)
    buy = c.fees(10_000, "buy", date(2026, 1, 1))
    sell = c.fees(10_000, "sell", date(2026, 1, 1))
    assert buy["commission"] == 5
    assert buy["stamp_tax"] == 0
    assert sell["stamp_tax"] == pytest.approx(5)
    assert c.fees(10_000, "sell", date(2023, 8, 27))["stamp_tax"] == pytest.approx(10)


def test_execution_feasibility_uses_open_only():
    # 开盘封涨停即保守阻断；high/low不参与，避免偷看当日路径。
    bar = pd.Series({"open": 11.0, "high": 11.0, "low": 10.5, "volume": 1e6})
    ok, reason = execution_feasibility("600001", bar, 10.0, "buy")
    assert not ok and reason == "open_limit_up_buy_blocked"
    ok, reason = execution_feasibility("600001", pd.Series({"open": 0}), 10.0, "buy")
    assert not ok and reason == "missing_open_or_suspended"


def test_portfolio_cash_conserves_fees():
    p = Portfolio(cash=100_000)
    p.buy("600001", 10, 1000, at=pd.Timestamp("2026-01-05").to_pydatetime(), fee=5)
    assert p.cash == 89_995
    sold = p.sell("600001", 11, 1000, at=pd.Timestamp("2026-01-06").to_pydatetime(), fee=10)
    assert sold == 1000
    assert p.cash == 100_985
