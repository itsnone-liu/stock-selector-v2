#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retcalc.py — 批次5复权收益计算核心 (STAGE5_POSNEG_ADJUSTED_SPEC v7.1, 2026-09-21)。

因子比式(spec §5.3 冻结, 唯一表达):
    P_adj_buy  = raw_buy_fill_price  × F_entry     # v5 冻结成交价(含滑点)
    P_adj_sell = raw_sell_fill_price × F_exit      # 终点 raw 价 × 卖出滑点
    gross_terminal = invested × P_adj_sell / P_adj_buy
    buy_fee  = fees(invested, buy);  sell_fee = fees(gross_terminal, sell)
    R_net    = (gross_terminal − sell_fee) / (invested + buy_fee) − 1
分红/送转/拆分全部由 F_exit/F_entry 比承载; 不设股数账本(双重计算禁令)。

K2/K3/K4 (spec §3):
    K3_h 终点 = anchor(突破日)后第 h 个该股行情日; 未成交→现金0;
        终点日恰成交→"成交瞬间估值"(价格收益0仅费用); 终点后才成交→现金0
    K2_h 终点 = 各自成交日后 h 日(staged=T1后h); 四态状态机;
        direct_chase capped 未进 → evaluated_cash(K2=0)
    K4_h = 仅成交行, 从成交起按共同终点
    staged 分批 30/30/40: 共同终点=T1后h日; T2/T3 仅在终点前成交才持有;
        终点后批次保持现金(0 计入); 逐批因子比式后资金加权

日期缺失不得邻近填充: 任何日期不在因子表 → 该计算 null + 显式 reason。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from stock_selector.decision.execution import CostModel

HORIZONS = (1, 3, 5, 10, 20)
CAPITAL = 100_000.0
TRANCHES = {"t1": 0.30, "t2": 0.30, "t3": 0.40}


@dataclass
class StockFrame:
    """每股行情+因子视图(因子表冻结 F × per_stock raw OHLC)."""
    dates: list[str]                       # 升序行情日
    pos: dict[str, int]
    open_: dict[str, float]
    close: dict[str, float]
    F: dict[str, float]                    # 冻结因子(首日归一)

    def day_open(self, i: int) -> float:
        return self.open_[self.dates[i]]

    def day_close(self, i: int) -> float:
        return self.close[self.dates[i]]

    def factor(self, i: int) -> float:
        return self.F[self.dates[i]]


def r_net_factor(cost: CostModel, invested: float, buy_price: float,
                 buy_day: str, sell_price: float, sell_day: str,
                 f_entry: float, f_exit: float) -> float | None:
    """因子比式单批净收益(spec §5.3)."""
    if buy_price <= 0 or f_entry <= 0:
        return None
    p_adj_buy = buy_price * f_entry
    p_adj_sell = sell_price * f_exit
    gross_terminal = invested * p_adj_sell / p_adj_buy
    buy_fee = cost.fees(invested, "buy", _d(buy_day))["total"]
    sell_fee = cost.fees(gross_terminal, "sell", _d(sell_day))["total"]
    return (gross_terminal - sell_fee) / (invested + buy_fee) - 1.0


def _d(s: str) -> date:
    return date(int(s[:4]), int(s[5:7]), int(s[8:10]))


def k3_view(sf: StockFrame, cost: CostModel, view: str,
            anchor_pos: int, buy_pos: int | None, buy_price: float | None,
            capped_cash: bool = False) -> dict:
    """K3: 统一突破日终点. 未成交→现金0; capped 未进→现金0(spec v7.1)."""
    out = {}
    last = len(sf.dates) - 1
    for h in HORIZONS:
        end = anchor_pos + h
        if end > last:
            out[f"K3_{h}"] = None            # 窗口不完整(右删失)
            out[f"K3_{h}_reason"] = "window_incomplete"
            continue
        if buy_pos is None or capped_cash:
            out[f"K3_{h}"] = 0.0             # 未成交/上限放弃 → 现金
            out[f"K3_{h}_reason"] = "cash_capped" if capped_cash else "cash_unfilled"
            continue
        if buy_pos > end:
            out[f"K3_{h}"] = 0.0             # 终点后才成交
            out[f"K3_{h}_reason"] = "filled_after_window"
            continue
        if buy_pos == end:
            # 成交瞬间估值: 价格收益0, 仅计费用
            r = r_net_factor(cost, CAPITAL, buy_price, sf.dates[buy_pos],
                             buy_price, sf.dates[end], sf.factor(buy_pos), sf.factor(end))
            out[f"K3_{h}"] = r               # = 费用损(负小量)
            out[f"K3_{h}_reason"] = "filled_at_endpoint_instant"
            continue
        sell_raw = sf.day_close(end) if view == "close" else sf.day_open(end)
        sell_fill = cost.fill_price(sell_raw, "sell")
        r = r_net_factor(cost, CAPITAL, buy_price, sf.dates[buy_pos],
                         sell_fill, sf.dates[end], sf.factor(buy_pos), sf.factor(end))
        out[f"K3_{h}"] = r
        out[f"K3_{h}_reason"] = "position"
    return out


POLICY_TERMINAL_REASONS = {          # "政策已终结": 数据结束前策略层面已无入场可能
    "wait_expired", "gave_up", "breakout_invalidated", "structure_broken",
    "capped_gave_up", "no_chance_before_data_end",
}


def k2_state(filled: bool, capped_cash: bool, not_filled_reason: str | None,
             right_censored: bool, end_pos: int | None, last: int) -> tuple[str, str]:
    """行级四态状态机 → (state, 细分reason)."""
    if capped_cash:                    # direct_chase 3.5%上限明确放弃
        return "evaluated_cash", "capped_abandon"
    if not filled:
        if right_censored:
            return "null_entry_pending", "data_end_pending"
        if not_filled_reason in POLICY_TERMINAL_REASONS:
            return "evaluated_cash", f"policy_terminal:{not_filled_reason}"
        return "null_entry_pending", f"pending:{not_filled_reason}"
    if end_pos is None or end_pos > last:
        return "null_holding_tail", "endpoint_beyond_data"
    return "evaluated_position", "ok"


def k2_view(sf: StockFrame, cost: CostModel, view: str,
            buy_pos: int, buy_price: float,
            legs: list[tuple[str, int, float]] | None = None) -> dict:
    """K2/K4: 策略共同终点(单笔=成交后h; staged=T1后h, 分批资金加权).

    legs: staged [(tname, buy_pos, buy_price), ...]; None=单笔.
    """
    out = {}
    last = len(sf.dates) - 1
    base_pos = buy_pos if legs is None else legs[0][1]      # staged 基准=T1
    for h in HORIZONS:
        end = base_pos + h
        # 四态只由状态机(在调用方)判; 此处终点超界 → null_holding_tail 语义
        if end > last:
            out[f"K2_{h}"] = None
            out[f"K4_{h}"] = None
            out[f"K2_{h}_reason"] = "null_holding_tail"
            continue
        if legs is None:
            sell_raw = sf.day_close(end) if view == "close" else sf.day_open(end)
            sell_fill = cost.fill_price(sell_raw, "sell")
            out[f"K2_{h}"] = out[f"K4_{h}"] = r_net_factor(
                cost, CAPITAL, buy_price, sf.dates[buy_pos],
                sell_fill, sf.dates[end], sf.factor(buy_pos), sf.factor(end))
            out[f"K2_{h}_reason"] = "single_leg"
        else:
            # staged: 逐批因子比式; 终点日后成交的批次=现金0计入
            total = 0.0
            detail = {}
            for tname, tpos, tprice in legs:
                w = TRANCHES[tname]
                invested = w * CAPITAL
                if tpos is None or tprice is None or tpos > end:
                    detail[tname] = 0.0                    # 现金
                    continue
                if tpos == end:
                    r = r_net_factor(cost, invested, tprice, sf.dates[tpos],
                                     tprice, sf.dates[end], sf.factor(tpos), sf.factor(end))
                else:
                    sell_raw = sf.day_close(end) if view == "close" else sf.day_open(end)
                    sell_fill = cost.fill_price(sell_raw, "sell")
                    r = r_net_factor(cost, invested, tprice, sf.dates[tpos],
                                     sell_fill, sf.dates[end], sf.factor(tpos), sf.factor(end))
                detail[tname] = r if r is not None else 0.0
            # 资金加权(分母=全部资金: 未投入现金收益0)
            total = sum(TRANCHES[t] * detail[t] for t in detail)
            out[f"K2_{h}"] = total
            out[f"K4_{h}"] = total
            out[f"K2_{h}_reason"] = "staged_weighted"
            out[f"K2_{h}_legs"] = detail
    return out
