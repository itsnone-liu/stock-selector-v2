"""决策服务与PIT回放引擎（蓝图 §6）。

DecisionService：单票、单一 as_of 的完整信号栈 → advice。
PITReplay：历史时点序列回放，数据严格截断到 as_of（防穿越是构造性的：
引擎根本拿不到未来数据，测试再验证）。

回放语义：
- L2 检查点（15:05）：日线 ≤ 当日，完整日K；
- L1 检查点（盘中）：日线 < 当日，当日部分数据由 MinuteProvider 聚合
  （quote），无分钟数据时该时点降级为 EOD 近似并标注。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, time as dtime
from pathlib import Path
from typing import Callable

import pandas as pd

from stock_selector.decision.advice import compose_advice
from stock_selector.decision.clock import session_clock
from stock_selector.decision.labels import daily_labels
from stock_selector.decision.regime import market_regime, parse_capital_context
from stock_selector.decision.weekly_momentum import weekly_momentum
from stock_selector.models import Quote
from stock_selector.strategies.trend import monthly_trend, weekly_trend


def truncate_daily(daily: pd.DataFrame | None, asof: datetime) -> pd.DataFrame | None:
    """截断日线到 as_off 可见范围：盘后含当日，盘中不含当日（当日走quote）。"""
    if daily is None or daily.empty:
        return daily
    idx = pd.to_datetime(daily.index)
    today = pd.Timestamp(asof.date())
    mask = (idx <= today) if asof.time() >= dtime(15, 0) else (idx < today)
    return daily.loc[mask]


def quote_from_minutes(code: str, minutes: pd.DataFrame, daily: pd.DataFrame, asof: datetime) -> Quote | None:
    """由 ≤as_of 的分钟K构造盘中 Quote（当日部分数据）。"""
    if minutes is None or minutes.empty:
        return None
    frame = minutes[minutes.index <= pd.Timestamp(asof)]
    if frame.empty:
        return None
    price = float(frame["close"].iloc[-1])
    open_price = float(frame["open"].iloc[0])
    previous_close = price
    hist = daily[daily.index < pd.Timestamp(asof.date())]
    if not hist.empty:
        previous_close = float(hist["close"].iloc[-1])
    volume = float(frame["volume"].sum())
    amount = float(frame["amount"].sum()) if "amount" in frame.columns else None
    return Quote(code=code, price=price, open=open_price, previous_close=previous_close,
                 volume=volume, amount=amount, timestamp=asof)


class DecisionService:
    """单票信号栈：月线背景 + 周线趋势三布尔 + 周级动能 + 日线多标签 + advice。"""

    def __init__(self, config: dict, daily_loader: Callable[[str], pd.DataFrame | None],
                 index_loader: Callable[[], pd.DataFrame | None] | None = None,
                 minute_provider=None):
        self.config = config
        self.daily_loader = daily_loader
        self.index_loader = index_loader
        self.minute_provider = minute_provider

    def evaluate(self, code: str, asof: datetime, quote: Quote | None = None,
                 context_payload: dict | None = None, portfolio=None, anchor=None) -> dict:
        raw_daily = self.daily_loader(code)
        daily = truncate_daily(raw_daily, asof)
        if daily is None or len(daily) < 60:
            return {"symbol": code, "as_of": asof.isoformat(timespec="seconds"),
                    "action": "watch", "confidence": "low", "unknowns": ["insufficient_daily_data"]}

        if quote is None and self.minute_provider is not None and asof.time() < dtime(15, 0):
            minutes = self.minute_provider.minute_frame(code, asof.date())
            quote = quote_from_minutes(code, minutes, daily, asof)

        clock = session_clock(asof, daily)
        monthly_result = monthly_trend(daily, self.config)
        trend_result = weekly_trend(daily, self.config)
        monthly_dict = {"passed": monthly_result.passed, "reason": monthly_result.reason,
                        "metrics": monthly_result.metrics}
        weekly_dict = {
            "ma_bull": trend_result.reason == "ma_bull" or "ma_bull" in trend_result.signals,
            "macd_cross": "macd_cross" in trend_result.signals,
            "macd_stabilizing": "macd_stabilizing" in trend_result.signals,
            "any": trend_result.passed,
            "reason": trend_result.reason,
        }
        momentum = weekly_momentum(daily, asof, self.config, quote)
        labels = daily_labels(daily, asof, self.config, quote)

        regime = None
        regime_metrics: dict = {}
        if self.index_loader is not None:
            index_daily = truncate_daily(self.index_loader(), asof)
            regime, regime_metrics = market_regime(index_daily, asof)
        context = parse_capital_context(context_payload)

        advice = compose_advice(
            symbol=code, asof=asof, clock=clock,
            monthly=monthly_dict, weekly_trend=weekly_dict,
            momentum=momentum, labels=labels, regime=regime, context=context,
            portfolio=portfolio, daily=daily, anchor=anchor, quote=quote,
            config=self.config,
        )
        advice.evidence["market_regime_metrics"] = regime_metrics
        advice.versions["selector_code"] = "decision-stack-v1"
        return advice.to_dict()


@dataclass
class ReplayRun:
    advices: list[dict]
    path: str | None = None


class PITReplay:
    """历史时点回放：对每个 as_of 重新执行完整信号栈（不读预计算结果）。"""

    def __init__(self, service: DecisionService):
        self.service = service

    def run(self, codes: list[str], asof_list: list[datetime],
            context_loader: Callable[[datetime, str], dict | None] | None = None,
            output_path: str | None = None) -> ReplayRun:
        advices: list[dict] = []
        for asof in asof_list:
            for code in codes:
                payload = context_loader(asof, code) if context_loader else None
                advice = self.service.evaluate(code, asof, context_payload=payload)
                advices.append(advice)
        if output_path:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as fh:
                for advice in advices:
                    fh.write(json.dumps(advice, ensure_ascii=False) + "\n")
            return ReplayRun(advices, str(path))
        return ReplayRun(advices)
