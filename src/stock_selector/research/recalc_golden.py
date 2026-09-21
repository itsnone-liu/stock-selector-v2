#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recalc_golden.py — 审计用独立因子比式重算(不复用 retcalc.py, 保证审计独立性)."""
from __future__ import annotations
from datetime import date


def golden_recompute(cost, buy_day, u, Fd, dates, bp, ep, view) -> float | None:
    """独立重算单笔 K2(bp→ep): (P_adj_sell_fill/P_adj_buy_fill) 因子比式净收益."""
    buy_date, end_date = dates[bp], dates[ep]
    p_buy_raw = None
    # 成交价无法从v5外推(含滑点) → 该函数只校验市场价部分: 以 close/open 市场价
    # 双侧同加滑点后比值不变(乘法消去), 故直接用市场价对比基准值已含滑点口径的
    # CSV值时, 用同式重建: buy=市场价×(1+slip), sell=市场价×(1-slip)
    slip = cost.slippage_bps / 10_000.0
    ref_buy = u[buy_date][1] if view == "close" else u[buy_date][0]
    ref_sell = u[end_date][1] if view == "close" else u[end_date][0]
    buy_fill = ref_buy * (1 + slip)
    sell_fill = ref_sell * (1 - slip)
    if buy_fill <= 0:
        return None
    capital = 100_000.0
    p_adj_buy = buy_fill * Fd[buy_date]
    p_adj_sell = sell_fill * Fd[end_date]
    gross_terminal = capital * p_adj_sell / p_adj_buy
    buy_fee = cost.fees(capital, "buy", date(int(buy_day[:4]), int(buy_day[5:7]), int(buy_day[8:10])))["total"]
    sell_fee = cost.fees(gross_terminal, "sell", date(int(end_date[:4]), int(end_date[5:7]), int(end_date[8:10])))["total"]
    return (gross_terminal - sell_fee) / (capital + buy_fee) - 1.0
