"""周级量价动能（蓝图 §3.4 / 工作表 §3）。

业务名称 weekly_capital_momentum：在月/周趋势背景下观察本周量价
是否仍在推动价格。**它是量价代理，不是对资金身份/意图的直接观测。**

三个维度分开输出，不合成单一标签：
- momentum_state: active_up / pullback_weakening / no_momentum / distribution_risk
- evidence_origin: current_week / previous_completed_week / none
- evaluation_status: evaluated / insufficient_data / stale_data

模式：
- revised_weekday：周一carry_forward（上一完整周状态延续一日，当日
  distribution_risk 可否决）、周二双阴缩量=pullback_weakening、周三四
  momentum_velocity（价格只留已实现值）、周五/收盘后完整周判定；
- unified：现有 weekly_surge 的语义映射（对照组）；
- legacy_weekday：按讨论记录重建的旧分支逻辑（reconstructed，待旧代码取证）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from stock_selector.calendar import aggregate_weekly, completed_week_rows, current_week_rows
from stock_selector.decision.clock import VolumeClock, iso_week_end, session_clock
from stock_selector.indicators import safe_pct_change
from stock_selector.models import Quote
from stock_selector.strategies.surge import weekly_surge

ACTIVE_UP = "active_up"
PULLBACK_WEAKENING = "pullback_weakening"
NO_MOMENTUM = "no_momentum"
DISTRIBUTION_RISK = "distribution_risk"

CURRENT_WEEK = "current_week"
PREVIOUS_COMPLETED_WEEK = "previous_completed_week"
NONE_ORIGIN = "none"

EVALUATED = "evaluated"
INSUFFICIENT = "insufficient_data"
STALE = "stale_data"


@dataclass
class MomentumResult:
    state: str
    evidence_origin: str
    evaluation_status: str
    mode: str
    calendar_weekday: int
    trading_session_in_week: int | None
    source_week: str | None = None
    valid_until: str | None = None  # carry_forward 的失效日（YYYY-MM-DD）
    metrics: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


def _week_bar(rows: pd.DataFrame) -> dict | None:
    if rows is None or rows.empty:
        return None
    bar = {
        "open": float(rows.iloc[0]["open"]),
        "high": float(rows["high"].max()),
        "low": float(rows["low"].min()),
        "close": float(rows.iloc[-1]["close"]),
        "volume": float(rows["volume"].sum()),
    }
    bar["amount"] = float(rows["amount"].sum()) if "amount" in rows.columns else 0.0
    return bar


def _partial_week_bar(daily: pd.DataFrame, asof: datetime, quote: Quote | None) -> dict | None:
    """本周截至 as_of 的临时周K（含当日部分数据）。

    quote 优先：其 price/volume 代表当日盘中已实现值；日线帧中若已含
    当日行则剔除后叠加 quote，避免重复累计。
    """
    rows = current_week_rows(daily, asof)
    if rows.empty and quote is None:
        return None
    if quote is None:
        return _week_bar(rows)
    today = asof.date()
    historical = rows[[pd.Timestamp(x).date() < today for x in rows.index]]
    bar = _week_bar(historical) if not historical.empty else {
        "open": quote.open, "high": max(quote.open, quote.price),
        "low": min(quote.open, quote.price), "close": quote.open,
        "volume": 0.0, "amount": 0.0,
    }
    bar["close"] = quote.price
    bar["high"] = max(bar["high"], quote.price)
    bar["low"] = min(bar["low"], quote.price)
    if quote.volume:
        bar["volume"] += float(quote.volume)
    if quote.amount:
        bar["amount"] += float(quote.amount)
    return bar


def _distribution_risk(bar: dict, baseline_volume: float, veto_ratio: float) -> bool:
    """放量阴线=疑似资金撤退（量价代理判定，非出货事实）。"""
    if baseline_volume <= 0:
        return False
    return bool(bar["close"] < bar["open"] and bar["volume"] >= veto_ratio * baseline_volume)


def _classify_current(bar: dict, prev: dict, cfg: dict, week_completion: float,
                      volume_clock: VolumeClock, observed_minutes: int) -> tuple[str, dict]:
    """对（可能是部分的）本周K分类。价格只用已实现值；量按周完成度折算。"""
    min_volume_ratio = float(cfg.get("min_projected_volume_ratio", 0.8))
    veto_ratio = float(cfg.get("bearish_turnover_veto_ratio", 1.5))
    prev_volume = float(prev.get("volume", 0.0))
    if 0 < week_completion < 1:
        week_projected = bar["volume"] / week_completion
    else:
        week_projected = bar["volume"]
    volume_ratio = week_projected / prev_volume if prev_volume > 0 else 0.0
    realized = safe_pct_change(bar["close"], bar["open"])
    above_prev_close = bar["close"] > float(prev["close"])
    bearish = bar["close"] < bar["open"]
    metrics = {
        "realized_week_return_pct": round(realized, 3),
        "momentum_velocity": round(realized / week_completion, 3) if week_completion > 0 else None,
        "week_completion": round(week_completion, 4),
        "projected_volume_ratio": round(volume_ratio, 3),
        "volume_method": "week_completion_prorated" if 0 < week_completion < 1 else "full_week",
        "above_prev_week_close": above_prev_close,
    }
    if _distribution_risk(bar, prev_volume, veto_ratio):
        return DISTRIBUTION_RISK, metrics
    if bearish and volume_ratio < min_volume_ratio:
        # 回调仍在继续但卖压衰减：量价代理口径的 pullback_weakening。
        return PULLBACK_WEAKENING, metrics
    if not bearish and above_prev_close and volume_ratio >= min_volume_ratio:
        return ACTIVE_UP, metrics
    return NO_MOMENTUM, metrics


def _classify_completed(week: dict, prev: dict, cfg: dict) -> tuple[str, dict]:
    """对完整周K分类（周五收盘后/历史周）。"""
    veto_ratio = float(cfg.get("bearish_turnover_veto_ratio", 1.5))
    min_volume_ratio = float(cfg.get("min_projected_volume_ratio", 0.8))
    volume_ratio = week["volume"] / prev["volume"] if prev.get("volume", 0) > 0 else 0.0
    realized = safe_pct_change(week["close"], week["open"])
    above_prev_close = week["close"] > float(prev["close"])
    bearish = week["close"] < week["open"]
    metrics = {
        "realized_week_return_pct": round(realized, 3),
        "volume_ratio_vs_prev_week": round(volume_ratio, 3),
        "above_prev_week_close": above_prev_close,
    }
    if _distribution_risk(week, prev.get("volume", 0.0), veto_ratio):
        return DISTRIBUTION_RISK, metrics
    if bearish and volume_ratio < min_volume_ratio:
        return PULLBACK_WEAKENING, metrics
    if not bearish and above_prev_close and volume_ratio >= min_volume_ratio:
        return ACTIVE_UP, metrics
    return NO_MOMENTUM, metrics


def revised_weekday(daily: pd.DataFrame, asof: datetime, config: dict,
                    quote: Quote | None = None) -> MomentumResult:
    cfg = config.get("surge", {})
    clock = session_clock(asof, daily)
    completed_daily = completed_week_rows(daily, asof)
    completed = aggregate_weekly(completed_daily)
    base = dict(
        mode="revised_weekday",
        calendar_weekday=clock.calendar_weekday,
        trading_session_in_week=clock.trading_session_in_week,
    )
    if len(completed) < 2:
        return MomentumResult(
            NO_MOMENTUM, NONE_ORIGIN, INSUFFICIENT, **base,
            metrics={"completed_weeks": len(completed)},
            notes=["需要至少2个完整周（基线+对照）"],
        )
    prev_bar = _week_bar(completed.iloc[[-1]])
    prev2_bar = _week_bar(completed.iloc[[-2]])
    prev_state, prev_metrics = _classify_completed(prev_bar, prev2_bar, cfg)
    source_week = iso_week_end(pd.Timestamp(completed.index[-1]).date())

    session_idx = clock.trading_session_in_week or clock.calendar_weekday
    week_completion = clock.week_completion_with_today

    # --- 周一语义：本周第一个交易日（节假日安全），允许上一完整周状态延续 ---
    if session_idx == 1 and clock.evidence_level != "L2":
        bar = _partial_week_bar(daily, asof, quote)
        veto = False
        if bar:
            # 与通用口径一致：按周完成度折算后再与上周总量比较，避免早盘误判。
            wc = week_completion if 0 < week_completion < 1 else max(week_completion, 1e-9)
            veto_volume = bar["volume"] / wc if wc > 0 else bar["volume"]
            veto = bool(
                bar["close"] < bar["open"]
                and veto_volume >= float(cfg.get("bearish_turnover_veto_ratio", 1.5)) * float(prev_bar["volume"])
            )
        if veto:
            return MomentumResult(
                DISTRIBUTION_RISK, CURRENT_WEEK, EVALUATED, **base,
                source_week=iso_week_end(asof.date()),
                metrics={"today_realized_pct": round(safe_pct_change(bar["close"], bar["open"]), 3),
                         "today_volume": bar["volume"], "prev_week_volume": prev_bar["volume"]},
                notes=["周一当日内出现放量阴线，carry_forward被否决"],
            )
        return MomentumResult(
            prev_state, PREVIOUS_COMPLETED_WEEK, EVALUATED, **base,
            source_week=source_week,
            valid_until=str(asof.date()),
            metrics=prev_metrics,
            notes=["周一低信息日：上一完整周状态延续至收盘", "置信降级：evidence_origin=previous_completed_week"],
        )

    # --- 周二语义：双阴缩量 = 卖压衰减（非买点） ---
    if session_idx == 2:
        rows = current_week_rows(daily, asof)
        day1 = rows[[pd.Timestamp(x).date() < asof.date() for x in rows.index]]
        day1_bar = _week_bar(day1) if not day1.empty else None
        bar = _partial_week_bar(daily, asof, quote)
        vclock = VolumeClock()
        today_expected, vmethod = (vclock.expected_day_volume(quote.volume, clock.observed_minutes)
                                   if quote and quote.volume is not None else (None, vclock.method))
        if (day1_bar is not None and bar is not None
                and prev_state == ACTIVE_UP
                and day1_bar["close"] < day1_bar["open"]
                and bar["close"] < bar["open"]):
            day2_volume = today_expected if today_expected is not None else bar["volume"]
            if day1_bar["volume"] > 0 and day2_volume < day1_bar["volume"]:
                return MomentumResult(
                    PULLBACK_WEAKENING, CURRENT_WEEK, EVALUATED, **base,
                    source_week=iso_week_end(asof.date()),
                    metrics={
                        "day1_volume": day1_bar["volume"],
                        "day2_volume": day2_volume,
                        "day2_volume_method": vmethod,
                        "day2_is_expected": today_expected is not None,
                        "prev_week_state": prev_state,
                    },
                    notes=["双阴缩量：价格回调但卖压衰减", "非买入信号，观察状态"],
                )
        # 不满足双阴缩量则落入通用部分周评估。
        state, metrics = _classify_current(bar, prev_bar, cfg, week_completion, vclock, clock.observed_minutes)
        return MomentumResult(state, CURRENT_WEEK, EVALUATED, **base,
                              source_week=iso_week_end(asof.date()), metrics=metrics)

    # --- 周三四/周五盘中：部分周通用评估（价格只留已实现值+速度） ---
    bar = _partial_week_bar(daily, asof, quote)
    if bar is None:
        return MomentumResult(NO_MOMENTUM, NONE_ORIGIN, INSUFFICIENT, **base,
                              notes=["本周无可用数据"])
    state, metrics = _classify_current(bar, prev_bar, cfg, week_completion, VolumeClock(), clock.observed_minutes)
    origin = CURRENT_WEEK
    notes: list[str] = []
    if clock.evidence_level == "L1":
        notes.append("盘中L1证据：momentum_velocity为速度指标，非周涨幅预测")
    else:
        if session_idx >= 5:
            notes.append("收盘后完整周判定")
    return MomentumResult(state, origin, EVALUATED, **base,
                          source_week=iso_week_end(asof.date()), metrics=metrics, notes=notes)


def unified(daily: pd.DataFrame, asof: datetime, config: dict,
            quote: Quote | None = None) -> MomentumResult:
    """现有 weekly_surge 的语义映射（对照组，不改变其行为）。"""
    result = weekly_surge(daily, asof, config, quote)
    clock = session_clock(asof, daily)
    base = dict(
        mode="unified",
        calendar_weekday=clock.calendar_weekday,
        trading_session_in_week=clock.trading_session_in_week,
    )
    if result.decision.value == "pass":
        return MomentumResult(ACTIVE_UP, CURRENT_WEEK, EVALUATED, **base,
                              source_week=iso_week_end(asof.date()),
                              metrics=dict(result.metrics), notes=[f"surge_pattern={result.reason}"])
    mapping = {
        "bearish_heavy_turnover_veto": DISTRIBUTION_RISK,
        "current_week_not_bullish": NO_MOMENTUM,
        "not_up_vs_previous_close": NO_MOMENTUM,
        "projected_volume_too_low": PULLBACK_WEAKENING,
        "weekly_efficiency_not_improved": NO_MOMENTUM,
        "weekly_pattern_not_passed": NO_MOMENTUM,
    }
    if result.decision.value == "skip":
        return MomentumResult(NO_MOMENTUM, NONE_ORIGIN, INSUFFICIENT, **base,
                              metrics={"surge_reason": result.reason})
    state = mapping.get(result.reason, NO_MOMENTUM)
    metrics = dict(result.metrics)
    metrics["surge_reason"] = result.reason
    return MomentumResult(state, CURRENT_WEEK, EVALUATED, **base,
                          source_week=iso_week_end(asof.date()), metrics=metrics)


def legacy_weekday(daily: pd.DataFrame, asof: datetime, config: dict,
                   quote: Quote | None = None) -> MomentumResult:
    """旧星期分支逻辑的重建版（mode=legacy_reconstructed_v0）。

    依据讨论记录重建，**未经旧代码逐行取证**，只作对照实验种子：
    - 周一：本周+上周不满足 → 上周+前周；
    - 周二：双阴缩量；
    - 周三四：当日涨幅×5/已过天数（旧投影口径，仅记录）；
    - 周五：完整周。
    取证后若与旧实现不符，以旧代码为准修订本函数。
    """
    cfg = config.get("surge", {})
    clock = session_clock(asof, daily)
    base = dict(
        mode="legacy_reconstructed_v0",
        calendar_weekday=clock.calendar_weekday,
        trading_session_in_week=clock.trading_session_in_week,
    )
    completed_daily = completed_week_rows(daily, asof)
    completed = aggregate_weekly(completed_daily)
    if len(completed) < 2:
        return MomentumResult(NO_MOMENTUM, NONE_ORIGIN, INSUFFICIENT, **base,
                              metrics={"completed_weeks": len(completed)},
                              notes=["legacy重建需要至少2个完整周"])
    prev_bar = _week_bar(completed.iloc[[-1]])
    prev2_bar = _week_bar(completed.iloc[[-2]])
    session_idx = clock.trading_session_in_week or clock.calendar_weekday
    week_completion = clock.week_completion_with_today

    if session_idx == 1:
        # 周一：先看 本周(临时)+上周；不满足则 上周+前周。
        bar = _partial_week_bar(daily, asof, quote)
        state, m = _classify_current(bar, prev_bar, cfg, max(week_completion, 0.2), VolumeClock(), clock.observed_minutes) if bar else (NO_MOMENTUM, {})
        if state != ACTIVE_UP:
            prev_state, prev_metrics = _classify_completed(prev_bar, prev2_bar, cfg)
            return MomentumResult(prev_state, PREVIOUS_COMPLETED_WEEK, EVALUATED, **base,
                                  source_week=iso_week_end(pd.Timestamp(completed.index[-1]).date()),
                                  valid_until=str(asof.date()), metrics=prev_metrics,
                                  notes=["legacy周一回退：上周+前周", "重建版待取证校准"])
        return MomentumResult(state, CURRENT_WEEK, EVALUATED, **base,
                              source_week=iso_week_end(asof.date()), metrics=m,
                              notes=["legacy重建版待取证校准"])

    if session_idx == 2:
        rows = current_week_rows(daily, asof)
        day1 = rows[[pd.Timestamp(x).date() < asof.date() for x in rows.index]]
        day1_bar = _week_bar(day1) if not day1.empty else None
        bar = _partial_week_bar(daily, asof, quote)
        if day1_bar is not None and bar is not None:
            prev_state, _ = _classify_completed(prev_bar, prev2_bar, cfg)
            if (prev_state == ACTIVE_UP and day1_bar["close"] < day1_bar["open"]
                    and bar["close"] < bar["open"] and bar["volume"] < day1_bar["volume"]):
                return MomentumResult(PULLBACK_WEAKENING, CURRENT_WEEK, EVALUATED, **base,
                                      source_week=iso_week_end(asof.date()),
                                      metrics={"day1_volume": day1_bar["volume"], "day2_volume": bar["volume"]},
                                      notes=["legacy周二双阴缩量", "重建版待取证校准"])

    bar = _partial_week_bar(daily, asof, quote)
    if bar is None:
        return MomentumResult(NO_MOMENTUM, NONE_ORIGIN, INSUFFICIENT, **base)
    state, metrics = _classify_current(bar, prev_bar, cfg, week_completion, VolumeClock(), clock.observed_minutes)
    if session_idx in (3, 4) and clock.evidence_level == "L1":
        # 旧投影口径仅作记录：当日已实现涨幅外推到5日（不参与状态判定）。
        day_realized = safe_pct_change(bar["close"], bar["open"])
        metrics["legacy_projected_week_pct"] = round(day_realized * 5.0, 3)
        metrics["legacy_projection_note"] = "旧口径记录用，禁止作为收益预测"
    return MomentumResult(state, CURRENT_WEEK, EVALUATED, **base,
                          source_week=iso_week_end(asof.date()), metrics=metrics,
                          notes=["legacy重建版待取证校准"])


_MODES = {
    "revised_weekday": revised_weekday,
    "unified": unified,
    "legacy_weekday": legacy_weekday,
}


def weekly_momentum(daily: pd.DataFrame, asof: datetime, config: dict,
                    quote: Quote | None = None, mode: str | None = None) -> MomentumResult:
    """按配置模式分发周级量价动能评估。"""
    chosen = mode or config.get("decision", {}).get("weekly_momentum_mode", "revised_weekday")
    fn = _MODES.get(chosen)
    if fn is None:
        raise ValueError(f"未知 weekly_momentum 模式: {chosen}")
    return fn(daily, asof, config, quote)
