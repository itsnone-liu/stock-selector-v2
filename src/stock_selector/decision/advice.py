"""建议合成层（蓝图 §5）：把各层证据合成为一条可执行建议。

硬规则：
- unknowns 非空 → confidence 不得为 high；
- 置信度由证据覆盖度规则化生成，不做主观打分；
- 买入建议必须附隔夜风险段（T+1：当日买入不可当日止损）；
- 退出信号优先于入场信号（先保命后进攻）。

决策表是**建议**不是交易指令：人拍板，执行层只负责可成交性与账本。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time as dtime

import pandas as pd

from stock_selector.decision.clock import SessionClock
from stock_selector.decision.exits import ExitMonitor, ExitSignal
from stock_selector.decision.labels import DailyLabels
from stock_selector.decision.portfolio import Portfolio, REGIME_TARGET_EXPOSURE
from stock_selector.decision.regime import BULL, MID, WEAK, CapitalContext
from stock_selector.decision.weekly_momentum import (
    ACTIVE_UP,
    CURRENT_WEEK,
    DISTRIBUTION_RISK,
    EVALUATED,
    MomentumResult,
    PULLBACK_WEAKENING,
)

SCHEMA_VERSION = "1"

BUY = "buy"
ADD = "add"
HOLD = "hold"
REDUCE = "reduce"
SELL = "sell"
WATCH = "watch"

HIGH = "high"
MEDIUM = "medium"
LOW = "low"


@dataclass
class Advice:
    schema_version: str = SCHEMA_VERSION
    as_of: str = ""
    symbol: str = ""
    action: str = WATCH
    size_hint: dict = field(default_factory=dict)
    confidence: str = LOW
    evidence: dict = field(default_factory=dict)
    overnight_risk: dict = field(default_factory=dict)
    unknowns: list[str] = field(default_factory=list)
    invalidation: dict = field(default_factory=dict)
    exit_signals: list[dict] = field(default_factory=list)
    versions: dict = field(default_factory=dict)
    rationale: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "as_of": self.as_of,
            "symbol": self.symbol,
            "action": self.action,
            "size_hint": self.size_hint,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "overnight_risk": self.overnight_risk,
            "unknowns": self.unknowns,
            "invalidation": self.invalidation,
            "exit_signals": self.exit_signals,
            "versions": self.versions,
            "rationale": self.rationale,
        }


def _next_checkpoint(asof: datetime) -> str:
    """下一次复评时点：盘中→当日14:45；14:45后→15:05；盘后→次日14:45。"""
    t = asof.time()
    if asof.weekday() >= 5 or t >= dtime(15, 5):
        return "next_session_14:45"
    if t < dtime(9, 30):
        return f"{asof.date()} 10:00"
    if t < dtime(14, 45):
        return f"{asof.date()} 14:45"
    return f"{asof.date()} 15:05"


def _confidence(unknowns: list[str], clock: SessionClock, momentum: MomentumResult,
                labels: DailyLabels, regime: str | None, context: CapitalContext) -> str:
    """规则化置信度：证据覆盖度决定，禁止主观分。"""
    if unknowns:
        return LOW
    if clock.evidence_level == "L0":
        return LOW
    if momentum.evaluation_status != EVALUATED:
        return LOW
    if labels.features.get("volume_ratio_vs_prev") is None:
        return LOW
    if regime is None or context.context == "unknown":
        return MEDIUM  # 缺市场/板块证据但个股证据完整
    if momentum.state == ACTIVE_UP and momentum.evidence_origin == CURRENT_WEEK:
        return HIGH if clock.evidence_level == "L2" or clock.completion >= 0.9 else MEDIUM
    return MEDIUM


def _structural_stop_from_daily(daily: pd.DataFrame, asof: datetime) -> float | None:
    """结构止损锚：最近一个已完成交易日（或信号日）的日低。"""
    if daily is None or daily.empty:
        return None
    frame = daily[pd.to_datetime(daily.index) <= pd.Timestamp(asof)]
    if frame.empty:
        return None
    return float(frame["low"].iloc[-1])


def compose_advice(
    symbol: str,
    asof: datetime,
    clock: SessionClock,
    monthly: dict | None,            # {"passed": bool, "reason": str, ...}
    weekly_trend: dict | None,       # {"ma_bull": bool, "macd_cross": bool, "macd_stabilizing": bool, "any": bool}
    momentum: MomentumResult,
    labels: DailyLabels,
    regime: str | None,
    context: CapitalContext,
    portfolio: Portfolio | None = None,
    daily: pd.DataFrame | None = None,
    anchor: object | None = None,    # ExitAnchor（持仓时必传）
    quote: object | None = None,
    config: dict | None = None,
) -> Advice:
    cfg = (config or {}).get("decision", {})
    advice = Advice(as_of=asof.isoformat(timespec="seconds"), symbol=symbol)
    advice.evidence = {
        "monthly": monthly or {},
        "weekly_trend": weekly_trend or {},
        "weekly_momentum": {
            "state": momentum.state,
            "origin": momentum.evidence_origin,
            "mode": momentum.mode,
            "source_week": momentum.source_week,
            "metrics": momentum.metrics,
        },
        "daily_labels": labels.labels,
        "primary_type": labels.primary_type,
        "features": labels.features,
        "market_regime": regime,
        "sector_capital_context": {
            "context": context.context,
            "coverage": context.coverage,
            "as_of": context.as_of,
        },
        "evidence_level": clock.evidence_level,
        "session_completion": round(clock.completion, 4),
    }
    advice.versions = {
        "momentum_mode": momentum.mode,
        "advice": "v1",
    }

    # ---- unknowns 收集 ----
    unknowns: list[str] = list(labels.notes)
    if regime is None:
        unknowns.append("market_regime_unavailable")
    if context.context == "unknown":
        unknowns.append("sector_capital_context_unknown")
    if labels.features.get("volume_ratio_vs_prev") is None:
        unknowns.append("volume_reference_missing")
    advice.unknowns = unknowns

    # ---- 退出优先 ----
    if portfolio is not None and anchor is not None and symbol in portfolio.positions:
        monitor = ExitMonitor(config)
        signals = monitor.check(symbol, daily, asof, anchor, quote)
        advice.exit_signals = [
            {"rule": s.rule, "confirm": s.confirm, "trigger": s.trigger_price,
             "action": s.action, "note": s.note, "execution": s.executed_reference}
            for s in signals
        ]
        if any(s.rule.startswith("E1") for s in signals):
            advice.action = SELL
            advice.rationale.append("结构失效（硬风险底线）优先于一切入场逻辑")
        elif any(s.rule.startswith("E3") and s.confirm == "intraday" for s in signals):
            advice.action = SELL
            advice.rationale.append("盘中移动回撤触发（持有≥1日可当日执行）")
        elif signals:
            advice.action = REDUCE if any(s.rule.startswith("E2") for s in signals) else HOLD
            advice.rationale.append(f"退出信号：{[s.rule for s in signals]}")
        stop = getattr(anchor, "structural_stop", None)
        if stop:
            advice.invalidation["structural_stop"] = round(stop, 4)

    # ---- 入场/持有逻辑（无退出信号时） ----
    if advice.action == WATCH:
        monthly_ok = bool((monthly or {}).get("passed"))
        trend_ok = bool((weekly_trend or {}).get("any"))
        any_label = any(labels.labels.values())
        entry_ready = (
            monthly_ok and trend_ok and any_label
            and momentum.state == ACTIVE_UP
            and momentum.evaluation_status == EVALUATED
        )
        held = portfolio is not None and symbol in portfolio.positions

        if held:
            advice.action = HOLD
            advice.rationale.append("持仓且无退出信号")
            if entry_ready and regime != WEAK:
                advice.action = ADD
                advice.rationale.append("动能延续且证据完整，可加仓（受上限约束）")
        elif entry_ready and regime == BULL:
            advice.action = BUY
            advice.rationale.append("月线背景+周线趋势+周级动能active_up+日线标签命中，大盘bull")
        elif entry_ready and regime == MID:
            advice.action = WATCH
            advice.rationale.append("信号齐备但大盘mid：只观察，仓位档0~50%未放量前不建仓")
        elif entry_ready and regime == WEAK:
            advice.action = WATCH
            advice.rationale.append("大盘weak：趋势通道停止，超跌反弹另走专用规则")
        elif momentum.state == PULLBACK_WEAKENING:
            advice.action = WATCH
            advice.rationale.append("周级卖压衰减观察态：非买点，等待动能转正")
        elif momentum.state == DISTRIBUTION_RISK:
            advice.action = WATCH
            advice.rationale.append("疑似资金撤退（放量阴线）：禁止入场")
        else:
            advice.rationale.append("入场条件未齐或动能不足")

        # 板块资金上下文只做证据标注，不当门槛
        if context.context == "divergent" and advice.action in (BUY, ADD):
            advice.rationale.append("注意：板块资金上下文divergent（证据而非门槛）")

    # ---- 仓位区间 ----
    if advice.action in (BUY, ADD):
        single_max = float(cfg.get("portfolio", {}).get("single_max_pct", 20)) / 100.0
        target = REGIME_TARGET_EXPOSURE.get(regime or "", 0.0)
        held_frac = 0.0
        if portfolio is not None and portfolio.equity > 0:
            held_frac = portfolio.position_value(symbol) / portfolio.equity
        suggested = min(single_max - held_frac, single_max / 2) if target > 0 else 0.0
        advice.size_hint = {
            "min": round(max(0.0, suggested * 0.5), 4),
            "suggested": round(max(0.0, suggested), 4),
            "max": round(max(0.0, single_max - held_frac), 4),
            "basis": "equal_weight_single_cap|regime_target",
        }
        if portfolio is not None and portfolio.equity > 0:
            ok, reasons = portfolio.can_buy(
                symbol, labels.features.get("price", 0.0), 1.0,
                cfg.get("portfolio", {}), asof.date(), regime or "weak",
                industry=(portfolio.positions.get(symbol).industry if portfolio.positions.get(symbol) else None),
            )
            if not ok:
                advice.rationale.append(f"组合约束提示：{reasons}")

    # ---- 隔夜风险（买入必附） ----
    if advice.action in (BUY, ADD):
        stop = advice.invalidation.get("structural_stop")
        if stop is None:
            stop = _structural_stop_from_daily(daily, asof) if daily is not None else None
        price = labels.features.get("price") or 0.0
        gap = "unknown"
        if stop and price:
            advice.invalidation.setdefault("structural_stop", round(stop, 4))
            gap = "medium" if regime == BULL else "high"
        advice.overnight_risk = {
            "note": "T+1：当日买入不可当日卖出，承担隔夜缺口风险",
            "gap_exposure": gap,
            "stop_distance_pct": round((stop / price - 1) * 100, 2) if stop and price else None,
        }
        advice.rationale.append("分批建议：盘中试探仓 + 14:45尾盘确认")

    # ---- 失效与复评 ----
    advice.invalidation.setdefault("reassess_at", _next_checkpoint(asof))
    if advice.action in (BUY, ADD) and anchor is None:
        time_stop = int(cfg.get("exits", {}).get("time_stop_days", 5))
        advice.invalidation.setdefault("time_stop", f"{time_stop}个交易日")

    advice.confidence = _confidence(advice.unknowns, clock, momentum, labels, regime, context)
    return advice
