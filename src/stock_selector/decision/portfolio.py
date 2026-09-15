"""组合账本与仓位约束（蓝图 §4）。

T+1 是硬约束：当日买入的份额次日才可卖。账本按 lot 记录，
sellable_qty 只统计买入日期早于当前交易日的份额。

仓位约束（默认值，全部可配置，需组合回测校准后晋升）：
- 大盘regime目标敞口：bull=100% / mid=0~50% / weak=趋势通道停止；
- 单票上限 20%；行业暴露上限 40%；单日新增敞口上限 30%。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

REGIME_TARGET_EXPOSURE = {"bull": 1.0, "mid": 0.5, "weak": 0.0}


@dataclass
class Lot:
    buy_date: date
    qty: float
    price: float


@dataclass
class Position:
    code: str
    lots: list[Lot] = field(default_factory=list)
    last_price: float = 0.0
    industry: str | None = None

    @property
    def qty(self) -> float:
        return sum(lot.qty for lot in self.lots)

    @property
    def cost_value(self) -> float:
        return sum(lot.qty * lot.price for lot in self.lots)

    @property
    def avg_cost(self) -> float:
        qty = self.qty
        return self.cost_value / qty if qty > 0 else 0.0

    @property
    def market_value(self) -> float:
        return self.qty * self.last_price

    def sellable_qty(self, today: date) -> float:
        """T+1：买入日期早于今天的份额才可卖。"""
        return sum(lot.qty for lot in self.lots if lot.buy_date < today)

    def reduce(self, qty: float, today: date) -> float:
        """按先进先出卖出可卖份额，返回实际卖出量（受T+1限制）。"""
        remaining = qty
        sold = 0.0
        for lot in sorted(self.lots, key=lambda x: x.buy_date):
            if remaining <= 0:
                break
            if lot.buy_date >= today:
                continue
            take = min(lot.qty, remaining)
            lot.qty -= take
            sold += take
            remaining -= take
        self.lots = [lot for lot in self.lots if lot.qty > 1e-9]
        return sold


@dataclass
class Portfolio:
    cash: float
    positions: dict[str, Position] = field(default_factory=dict)
    daily_added_value: dict[date, float] = field(default_factory=dict)

    def mark(self, prices: dict[str, float]) -> None:
        for code, price in prices.items():
            if code in self.positions:
                self.positions[code].last_price = float(price)

    @property
    def equity(self) -> float:
        return self.cash + sum(p.market_value for p in self.positions.values())

    def position_value(self, code: str) -> float:
        pos = self.positions.get(code)
        return pos.market_value if pos else 0.0

    def industry_value(self, industry: str) -> float:
        return sum(p.market_value for p in self.positions.values() if p.industry == industry)

    def invested_value(self) -> float:
        return sum(p.market_value for p in self.positions.values())

    def _cap_checks(self, code: str, industry: str | None, amount: float,
                    cfg: dict, today: date) -> list[str]:
        reasons: list[str] = []
        equity = self.equity
        if equity <= 0:
            return ["equity_nonpositive"]
        single_max = float(cfg.get("single_max_pct", 20)) / 100.0
        if (self.position_value(code) + amount) / equity > single_max:
            reasons.append(f"single_cap_exceeded:{single_max:.0%}")
        if industry:
            industry_max = float(cfg.get("industry_max_pct", 40)) / 100.0
            if (self.industry_value(industry) + amount) / equity > industry_max:
                reasons.append(f"industry_cap_exceeded:{industry_max:.0%}")
        daily_max = float(cfg.get("daily_add_max_pct", 30)) / 100.0
        if (self.daily_added_value.get(today, 0.0) + amount) / equity > daily_max:
            reasons.append(f"daily_add_cap_exceeded:{daily_max:.0%}")
        if amount > self.cash:
            reasons.append("insufficient_cash")
        return reasons

    def can_buy(self, code: str, price: float, qty: float, cfg: dict,
                today: date, regime: str, industry: str | None = None) -> tuple[bool, list[str]]:
        """买入可行性检查：regime目标敞口 + 单票/行业/单日上限 + 现金。"""
        amount = price * qty
        reasons = self._cap_checks(code, industry, amount, cfg, today)
        target = REGIME_TARGET_EXPOSURE.get(regime, 0.0)
        equity = self.equity
        if equity > 0 and (self.invested_value() + amount) / equity > target:
            reasons.append(f"regime_exposure_cap:{regime}={target:.0%}")
        return (not reasons), reasons

    def buy(self, code: str, price: float, qty: float, at: datetime,
            industry: str | None = None) -> Lot:
        amount = price * qty
        if amount > self.cash:
            raise ValueError("insufficient_cash")
        pos = self.positions.setdefault(code, Position(code=code, industry=industry))
        if industry:
            pos.industry = industry
        lot = Lot(buy_date=at.date(), qty=qty, price=price)
        pos.lots.append(lot)
        pos.last_price = price
        self.cash -= amount
        self.daily_added_value[at.date()] = self.daily_added_value.get(at.date(), 0.0) + amount
        return lot

    def sell(self, code: str, price: float, qty: float, at: datetime) -> float:
        """T+1约束下卖出，返回实际卖出数量。"""
        pos = self.positions.get(code)
        if not pos:
            return 0.0
        sold = pos.reduce(qty, at.date())
        self.cash += sold * price
        if pos.qty <= 1e-9:
            self.positions.pop(code, None)
        return sold
