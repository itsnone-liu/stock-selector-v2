"""退出管理（蓝图 §4.4）。

候选退出集：
- E1 结构失效：收盘破买点日低点（底部池=事件日低点）→ 硬风险底线；
- E2 时间退出：固定持有N交易日；
- E3 移动回撤：自峰值回撤x%；
- E5 组合：E1 + E3 + 最长持有。

双口径（都要回测，不预设谁对）：
- confirm="close"    ：收盘确认，触发后次日开盘执行（回放引擎按此成交）；
- confirm="intraday" ：盘中即时触发，持有≥1日的仓位当日可执行。

触发≠成交：本层只出信号，成交由组合账本按可成交性规则处理。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dtime

import pandas as pd

from stock_selector.models import Quote

E1_STRUCTURAL = "E1_structural_stop"
E2_TIME = "E2_time_stop"
E3_TRAIL = "E3_trailing_drawdown"
E5_MAX_HOLD = "E5_max_hold"


@dataclass
class ExitAnchor:
    """入场锚点：结构止损位 + 时间锚。"""

    entry_date: str  # YYYY-MM-DD，信号日（T日收盘信号，T+1开盘成交）
    entry_price: float
    structural_stop: float  # 买点日低点 / 底部池事件日低点
    time_stop_days: int = 5
    trail_pct: float = 0.08
    max_hold_days: int = 20


@dataclass
class ExitSignal:
    code: str
    rule: str
    confirm: str  # "close" | "intraday"
    trigger_price: float
    action: str  # "sell" | "reduce"
    note: str
    executed_reference: str  # 建议执行参考（次日开盘 / 当日即时）


def _completed_closes(daily: pd.DataFrame, entry_date: str, asof: datetime) -> pd.Series:
    """入场后、截至 as_off 已完整的收盘序列。

    盘中（L1，<15:00）当日收盘未完成，不含当日；盘后（≥15:00）当日
    日线即完整收盘，包含当日。
    """
    if daily is None or daily.empty:
        return pd.Series(dtype=float)
    idx = pd.to_datetime(daily.index)
    entry = pd.Timestamp(entry_date)
    today = pd.Timestamp(asof.date())
    if asof.time() >= dtime(15, 0):
        mask = (idx > entry) & (idx <= today)
    else:
        mask = (idx > entry) & (idx < today)
    return daily.loc[mask, "close"]


class ExitMonitor:
    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("decision", {}).get("exits", {})
        self.default_time_stop = int(cfg.get("time_stop_days", 5))
        self.default_trail_pct = float(cfg.get("trail_pct", 8.0)) / 100.0
        self.default_max_hold = int(cfg.get("max_hold_days", 20))

    def check(self, code: str, daily: pd.DataFrame, asof: datetime,
              anchor: ExitAnchor, quote: Quote | None = None,
              held_days_min: int = 1) -> list[ExitSignal]:
        """评估退出信号。

        held_days_min：T+1约束下，不足该天数的新仓即便触发也只提示不执行
        （当日买入不可卖）。默认1=持有至次日才可卖。
        """
        signals: list[ExitSignal] = []
        closes = _completed_closes(daily, anchor.entry_date, asof)
        held_days = len(closes)  # 入场后已完成交易日数
        last_close = float(closes.iloc[-1]) if len(closes) else anchor.entry_price
        price_now = quote.price if quote else last_close
        today = asof.date()

        def _append(rule: str, confirm: str, trigger: float, note: str, executed: str) -> None:
            action = "sell"
            if held_days < held_days_min and confirm == "intraday":
                action = "reduce"  # 实际上不可卖：账本会拒绝，信号仅提示
                note = note + "（T+1：当日买入份额不可卖，次日首务）"
            signals.append(ExitSignal(code, rule, confirm, round(trigger, 4), action, note, executed))

        # --- E1 结构失效（硬底线）---
        if last_close < anchor.structural_stop and closes.size > 0:
            _append(E1_STRUCTURAL, "close", anchor.structural_stop,
                    f"前收{last_close}已破结构位{anchor.structural_stop}", "次日开盘")
        if quote and quote.price < anchor.structural_stop:
            _append(E1_STRUCTURAL, "intraday", anchor.structural_stop,
                    f"盘中价{quote.price}破结构位{anchor.structural_stop}", "当日即时")

        # --- E2 时间退出 ---
        time_stop = anchor.time_stop_days or self.default_time_stop
        if held_days >= time_stop:
            _append(E2_TIME, "close", last_close,
                    f"持有{held_days}个交易日≥时间退出{time_stop}", "次日开盘")

        # --- E3 移动回撤（收盘峰值口径）---
        trail_pct = anchor.trail_pct or self.default_trail_pct
        if closes.size > 0:
            peak_close = float(closes.max())
            if peak_close > 0 and (1 - last_close / peak_close) >= trail_pct:
                _append(E3_TRAIL, "close", last_close,
                        f"自收盘峰值{peak_close}回撤{(1 - last_close / peak_close):.1%}≥{trail_pct:.0%}", "次日开盘")
            if quote:
                peak_intraday = max(peak_close, float(quote.price))
                if peak_intraday > 0 and (1 - quote.price / peak_intraday) >= trail_pct and quote.price < peak_intraday:
                    _append(E3_TRAIL, "intraday", float(quote.price),
                            f"盘中自峰值{peak_intraday}回撤≥{trail_pct:.0%}", "当日即时")

        # --- E5 最长持有 ---
        max_hold = anchor.max_hold_days or self.default_max_hold
        if held_days >= max_hold:
            _append(E5_MAX_HOLD, "close", last_close,
                    f"持有{held_days}个交易日≥最长持有{max_hold}", "次日开盘")
        return signals
