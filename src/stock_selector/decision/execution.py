"""P0 可成交性与交易成本模型（版本化、确定性）。

这是回放执行层，不决定买卖信号。所有判断只使用成交日开盘时可见的
上一收盘和当日开盘/一字板状态。缺少逐笔盘口时，涨跌停判断采用保守近似并
显式记录 limitation，不能称真实可成交回放。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd


EXECUTION_MODEL_VERSION = "cn-a-share-eod-v1"


@dataclass(frozen=True)
class CostModel:
    commission_rate: float = 0.0003
    minimum_commission: float = 5.0
    slippage_bps: float = 5.0
    transfer_fee_rate: float = 0.00001

    def stamp_tax_rate(self, day: date) -> float:
        # 2023-08-28 起证券交易印花税减半；卖方单边征收。
        return 0.0005 if day >= date(2023, 8, 28) else 0.001

    def fill_price(self, reference: float, side: str) -> float:
        slip = self.slippage_bps / 10_000.0
        return float(reference) * (1 + slip if side == "buy" else 1 - slip)

    def fees(self, gross: float, side: str, day: date) -> dict[str, float]:
        commission = max(self.minimum_commission, gross * self.commission_rate)
        transfer = gross * self.transfer_fee_rate
        stamp = gross * self.stamp_tax_rate(day) if side == "sell" else 0.0
        total = commission + transfer + stamp
        return {"commission": commission, "transfer_fee": transfer,
                "stamp_tax": stamp, "total": total}


def limit_ratio(code: str) -> float:
    """A股通常涨跌幅近似；ST/新股特殊规则需历史证券状态后续补齐。"""
    c = str(code).zfill(6)
    if c.startswith(("300", "301", "688")):
        return 0.20
    if c.startswith(("4", "8")):
        return 0.30
    return 0.10


def execution_feasibility(code: str, bar: pd.Series | None, previous_close: float | None,
                          side: str) -> tuple[bool, str | None]:
    """保守EOD可成交性近似：停牌/无量与一字涨跌停阻断。"""
    if bar is None:
        return False, "missing_bar_or_suspended"
    open_px = float(bar.get("open", 0) or 0)
    if open_px <= 0:
        return False, "missing_open_or_suspended"
    if previous_close is None or previous_close <= 0:
        return True, None
    ratio = limit_ratio(code)
    open_px = float(bar.get("open", 0) or 0)
    up = previous_close * (1 + ratio)
    down = previous_close * (1 - ratio)
    tol = max(0.001, previous_close * 0.0015)  # 价格取整/复权误差容忍
    # 执行模型是“次日开盘成交”，所以只看开盘时已知值；不偷看当日high/low。
    # 开盘封板时保守判不可成交（可能低估后来开板成交机会）。
    if side == "buy" and open_px >= up - tol:
        return False, "open_limit_up_buy_blocked"
    if side == "sell" and open_px <= down + tol:
        return False, "open_limit_down_sell_blocked"
    return True, None
