"""周线双轴状态（第二批：趋势结构 × 当前动能）——只输出事实与状态，不决定仓位。

方案依据 docs/plans/STAGED_RESEARCH_PLAN_20260919.md 第五节（阶段一）。
原"允许/观察/排除"资格字段保持不动；本模块并行新增双轴旁路表。

两轴定义（stage1_v1，冻结）：
- trend_structure 趋势结构（中期结构是否仍成立；只看完整周序列，无盘中）：
    insufficient_evidence  完整周数 < 2
    broken                 prev1.close < prev2.low（跌破前一周低点）
                           或连续 >=2 个完整周放量下跌
    starting_to_damage     未 broken 且（prev1 阴线且低点下移，或
                           prev1 单周放量下跌待确认）
    intact                 其余（未观察到受损证据）
- current_momentum 当前动能（当周资金推动与卖压变化；按星期分支）：
    heavy_volume_decline   放量阴线（折算量比 >= veto 1.5）
    healthy_pullback       阴线但缩量（折算量比 < 0.8）且结构未 broken
    recovering             前周阴（缩量回调/下跌背景）+ 当周转阳收上前周收盘
    strengthening          阳线、收上前周收盘、折算量比 >= 0.8
    weakening              阴线量不缩（0.8..1.5）或阳线停滞（收不上前周收盘）
    unclear                证据不足或矛盾

星期口径（与现有 weekly_momentum revised/legacy 同源）：
- 周一：以上周+前周完整周为基础，本周首日只增证据（当日内放量阴线可否决）；
  未否决时沿用上一完整周分类（evidence_completeness=carry_previous_week）。
- 周二三路径：up_cont 上涨延续 / down_recover 下跌后恢复 / decline_pressure_fade
  双阴缩量卖压衰减；不满足则落通用部分周评估。
- 周三四：价格只留已实现值，量按周完成度折算。
- 周五（或短周末日收盘后）：完整周判定（量不折算），week_final_confirm。
- 节假日短周：planned_sessions 取市场日历该 ISO 周真实计划交易日数。

阈值复用 config surge（min_projected_volume_ratio=0.8 /
bearish_turnover_veto_ratio=1.5 / form_a_volume_exempt 仅完整周侧同 legacy），
不引入新的任意阈值。全部特征只用 <=当日 数据（严禁未来数据）；
跨周双阳恢复效率 = 当周已实现涨幅 / |前周跌幅|。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TREND_INTACT = "intact"
TREND_DAMAGE = "starting_to_damage"
TREND_BROKEN = "broken"
TREND_INSUFFICIENT = "insufficient_evidence"

MOM_STRENGTHENING = "strengthening"
MOM_RECOVERING = "recovering"
MOM_HEALTHY_PULLBACK = "healthy_pullback"
MOM_UNCLEAR = "unclear"
MOM_WEAKENING = "weakening"
MOM_HEAVY_DECLINE = "heavy_volume_decline"

# 完整周四分类（与 weekly_momentum._classify_completed 语义对齐的旁路口径）
WEEK_ACTIVE_UP = "active_up"
WEEK_SHRINKING_DECLINE = "shrinking_decline"
WEEK_HEAVY_DECLINE = "heavy_volume_decline"
WEEK_FLAT = "flat"

RULE_VERSION = "state_axes_stage1_v1"


@dataclass
class AxesConfig:
    min_volume_ratio: float = 0.8
    veto_ratio: float = 1.5

    @classmethod
    def from_config(cls, config: dict) -> "AxesConfig":
        surge = config.get("surge", {})
        return cls(
            min_volume_ratio=float(surge.get("min_projected_volume_ratio", 0.8)),
            veto_ratio=float(surge.get("bearish_turnover_veto_ratio", 1.5)),
        )


def _pct(a: float, b: float) -> float:
    return (a / b - 1.0) * 100.0 if b else 0.0


def _iso_week_key(ts: pd.Timestamp) -> str:
    y, w, _ = ts.isocalendar()
    return f"{y}-W{w:02d}"


def _week_frame(daily: pd.DataFrame, calendar: pd.DatetimeIndex) -> pd.DataFrame:
    """按 ISO 周聚合周K，并带市场日历的计划交易日数（节假日短周真实计划）。

    daily 需为升序 DatetimeIndex；calendar 为完整市场交易日历（升序）。
    """
    rows = []
    cal_weeks = {}
    for ts in calendar:
        cal_weeks.setdefault(_iso_week_key(pd.Timestamp(ts)), []).append(ts)
    df = daily[["open", "high", "low", "close", "volume"]].copy()
    df["week"] = [_iso_week_key(ts) for ts in df.index]
    for week, g in df.groupby("week", sort=True):
        planned = len(cal_weeks.get(week, []))
        rows.append({
            "week": week,
            "start": g.index[0],
            "end": g.index[-1],
            "open": float(g["open"].iloc[0]),
            "high": float(g["high"].max()),
            "low": float(g["low"].min()),
            "close": float(g["close"].iloc[-1]),
            "volume": float(g["volume"].sum()),
            "planned_sessions": planned if planned else len(g),
        })
    return pd.DataFrame(rows)


def _classify_week(bar: dict, prev: dict | None, cfg: AxesConfig,
                   form_a_exempt: bool = True) -> str:
    """完整周四分类（EOD 旁路口径，与 weekly_momentum 同阈值）。"""
    if prev is None:
        return WEEK_FLAT
    prev_vol = float(prev["volume"])
    ratio = bar["volume"] / prev_vol if prev_vol > 0 else 0.0
    bearish = bar["close"] < bar["open"]
    prev_bearish = prev["close"] < prev["open"]
    above_prev_close = bar["close"] > float(prev["close"])
    if bearish and ratio >= cfg.veto_ratio:
        return WEEK_HEAVY_DECLINE
    if bearish and ratio < cfg.min_volume_ratio:
        return WEEK_SHRINKING_DECLINE
    if (not bearish) and above_prev_close and (
            (form_a_exempt and prev_bearish) or ratio >= cfg.min_volume_ratio):
        return WEEK_ACTIVE_UP
    return WEEK_FLAT


def trend_structure(prev1: dict | None, prev2: dict | None,
                    consecutive_heavy: int, cfg: AxesConfig) -> tuple[str, str]:
    """Axis 1：中期趋势结构（只看完整周）。返回 (state, reason)。"""
    if prev1 is None or prev2 is None:
        return TREND_INSUFFICIENT, "completed_weeks_lt_2"
    if consecutive_heavy >= 2:
        return TREND_BROKEN, f"consecutive_heavy_decline_weeks={consecutive_heavy}"
    if float(prev1["close"]) < float(prev2["low"]):
        return TREND_BROKEN, "prev_week_close_below_prev2_low"
    p1_bear = float(prev1["close"]) < float(prev1["open"])
    low_down = float(prev1["low"]) < float(prev2["low"])
    if p1_bear and low_down:
        return TREND_DAMAGE, "bearish_week_with_lower_low"
    if _classify_week(prev1, prev2, cfg) == WEEK_HEAVY_DECLINE:
        return TREND_DAMAGE, "single_heavy_volume_decline_week"
    return TREND_INTACT, "no_damage_evidence"


def _partial_classify(cbar: dict, prev1: dict, cfg: AxesConfig,
                      completion: float, prev1_class: str,
                      trend: str) -> tuple[str, str]:
    """通用部分周分类（周三四/周五；价格已实现、量折算）。"""
    prev_vol = float(prev1["volume"])
    ratio = (cbar["volume"] / completion) / prev_vol if (prev_vol > 0 and 0 < completion <= 1) \
        else (cbar["volume"] / prev_vol if prev_vol > 0 else 0.0)
    bearish = cbar["close"] < cbar["open"]
    above = cbar["close"] > float(prev1["close"])
    if bearish and ratio >= cfg.veto_ratio:
        return MOM_HEAVY_DECLINE, f"prorated_volume_ratio={ratio:.2f}>=veto"
    if bearish and ratio < cfg.min_volume_ratio:
        if trend == TREND_BROKEN:
            return MOM_WEAKENING, "shrinking_decline_but_structure_broken"
        return MOM_HEALTHY_PULLBACK, f"shrinking_decline_ratio={ratio:.2f}"
    if (not bearish) and above:
        if prev1_class in (WEEK_SHRINKING_DECLINE, WEEK_HEAVY_DECLINE):
            return MOM_RECOVERING, "turn_up_after_decline_week"
        if ratio >= cfg.min_volume_ratio:
            return MOM_STRENGTHENING, f"up_with_volume_ratio={ratio:.2f}"
        return MOM_WEAKENING, "up_but_volume_below_min"
    if not bearish:
        return MOM_WEAKENING, "stall_below_prev_week_close"
    return MOM_UNCLEAR, "mixed_evidence"


def classify_stock_axes(daily: pd.DataFrame, calendar: pd.DatetimeIndex,
                        cfg: AxesConfig, min_history: int = 130) -> pd.DataFrame:
    """每股每天一行双轴旁路表（只含 <=当日 证据）。

    daily: 该股升序日线（TdxStore.daily）；calendar: 市场交易日历。
    返回列为 AXES_COLUMNS 的 DataFrame（不足 min_history 直接空表）。
    """
    if daily is None or len(daily) < min_history:
        return pd.DataFrame(columns=AXES_COLUMNS)
    daily = daily.sort_index()
    weeks = _week_frame(daily, calendar)
    if len(weeks) < 2:
        return pd.DataFrame(columns=AXES_COLUMNS)

    # 每周相对前一周的分类 + 尾部连续放量下跌计数（滚动，只用过往周）
    week_class: dict[str, str] = {}
    heavy_run: dict[str, int] = {}
    run = 0
    for i, row in weeks.reset_index(drop=True).iterrows():
        prev = weeks.iloc[i - 1] if i > 0 else None
        cls = _classify_week(row.to_dict(), (prev.to_dict() if prev is not None else None), cfg)
        week_class[row["week"]] = cls
        run = run + 1 if cls == WEEK_HEAVY_DECLINE else 0
        heavy_run[row["week"]] = run

    out: list[dict] = []
    wi = 0  # weeks 行指针：end < 当日 的最大前缀 = 已完成周
    for ts, day in daily.iterrows():
        ts = pd.Timestamp(ts)
        # 推进完成周指针
        while wi < len(weeks) and pd.Timestamp(weeks.iloc[wi]["end"]) < ts:
            wi += 1
        week = weeks.iloc[wi] if wi < len(weeks) else None
        if week is None or _iso_week_key(ts) != week["week"]:
            continue  # 不应发生（week_frame 由 daily 派生）
        # 当前周截至当日的部分K
        in_week = daily[(daily.index >= pd.Timestamp(week["start"]))
                        & (daily.index <= ts)]
        cbar = {"open": float(in_week["open"].iloc[0]),
                "close": float(in_week["close"].iloc[-1]),
                "volume": float(in_week["volume"].sum())}
        planned = int(week["planned_sessions"])
        session = int((in_week.index <= ts).sum())
        completion = session / planned if planned else 1.0

        prev1 = weeks.iloc[wi - 1].to_dict() if wi >= 1 else None
        prev2 = weeks.iloc[wi - 2].to_dict() if wi >= 2 else None
        prev1_class = week_class.get(prev1["week"]) if prev1 else None
        prev2_class = week_class.get(prev2["week"]) if prev2 else None
        heavy = heavy_run.get(prev1["week"], 0) if prev1 else 0

        trend, trend_reason = trend_structure(prev1, prev2, heavy, cfg)

        if prev1 is None:
            mom, mom_reason, path, comp = (MOM_UNCLEAR, "no_completed_week",
                                           "early", "insufficient")
        elif session == 1:
            # 周一：完整周基础 + 当日只增证据（放量阴否决）
            day_open = float(day["open"])
            ratio = cbar["volume"] / float(prev1["volume"]) if float(prev1["volume"]) > 0 else 0.0
            if day["close"] < day_open and ratio >= cfg.veto_ratio:
                mom, mom_reason = MOM_HEAVY_DECLINE, "monday_intraday_heavy_decline_veto"
                path, comp = "monday_veto", "intraday_veto"
            else:
                carry = {WEEK_ACTIVE_UP: MOM_STRENGTHENING,
                         WEEK_SHRINKING_DECLINE: MOM_HEALTHY_PULLBACK,
                         WEEK_HEAVY_DECLINE: MOM_WEAKENING,
                         WEEK_FLAT: MOM_UNCLEAR}.get(prev1_class, MOM_UNCLEAR)
                mom, mom_reason = carry, f"carry_{prev1_class}"
                path, comp = "monday_carry", "carry_previous_week"
        elif session == 2:
            day1 = in_week.iloc[0]
            d1_bear = float(day1["close"]) < float(day1["open"])
            d2_bear = float(day["close"]) < float(day["open"])
            d1_vol = float(in_week["volume"].iloc[0])
            d2_vol = float(day["volume"])
            above = cbar["close"] > float(prev1["close"])
            if d1_bear and d2_bear and d2_vol < d1_vol:
                mom, mom_reason = MOM_HEALTHY_PULLBACK, "tuesday_double_bear_shrinking"
                path, comp = "decline_pressure_fade", "partial_week"
            elif (not d1_bear) or (not d2_bear):
                if above:
                    if prev1_class in (WEEK_SHRINKING_DECLINE, WEEK_HEAVY_DECLINE):
                        mom, mom_reason = MOM_RECOVERING, "tuesday_recovery_path"
                    else:
                        mom, mom_reason = MOM_STRENGTHENING, "tuesday_up_continuation"
                    path = "down_recover" if d1_bear else "up_cont"
                else:
                    mom, mom_reason = MOM_WEAKENING, "tuesday_no_reclaim_prev_close"
                comp = "partial_week"
            else:
                mom, mom_reason = _partial_classify(cbar, prev1, cfg, completion,
                                                    prev1_class or WEEK_FLAT, trend)
                path, comp = "mid_partial", "partial_week"
        else:
            mom, mom_reason = _partial_classify(cbar, prev1, cfg, completion,
                                                prev1_class or WEEK_FLAT, trend)
            is_final = session >= planned
            path = "full_week_confirm" if is_final else "mid_partial"
            comp = "full_week_confirm" if is_final else "partial_week"

        rec_eff = None
        if mom == MOM_RECOVERING and prev1 is not None:
            prev_drop = float(prev1["open"]) - float(prev1["close"])
            realized = _pct(cbar["close"], cbar["open"])
            rec_eff = round(realized / prev_drop, 4) if prev_drop > 0 else None

        prev_vol1 = float(prev1["volume"]) if prev1 else None
        prorated_ratio = (round(cbar["volume"] / completion / prev_vol1, 4)
                          if prev_vol1 and prev_vol1 > 0 and 0 < completion <= 1
                          else (round(cbar["volume"] / prev_vol1, 4)
                                if prev_vol1 and prev_vol1 > 0 else None))
        out.append({
            "date": ts.date().isoformat(),
            "iso_week": week["week"],
            "session_ordinal_in_week": session,
            "planned_sessions_this_week": planned,
            "week_completion": round(completion, 4),
            "trend_structure": trend,
            "trend_structure_reason": trend_reason,
            "current_momentum": mom,
            "momentum_reason": mom_reason,
            "weekday_path": path,
            "evidence_completeness": comp,
            "prev_week_class": prev1_class,
            "prev2_week_class": prev2_class,
            "consecutive_heavy_decline_weeks": heavy,
            "week_realized_pct": round(_pct(cbar["close"], cbar["open"]), 4),
            "prorated_volume_ratio_vs_prev_week": prorated_ratio,
            "above_prev_week_close": bool(cbar["close"] > float(prev1["close"])) if prev1 else None,
            "cross_week_recovery_eff": rec_eff,
            "comparison_basis": (f"{prev1['week']}_vs_{prev2['week']}"
                                 if prev1 and prev2 else None),
        })
        del in_week
    df = pd.DataFrame(out)
    if len(df):
        df.insert(0, "code", "")
    return df


AXES_COLUMNS = [
    "code", "date", "iso_week", "session_ordinal_in_week",
    "planned_sessions_this_week", "week_completion",
    "trend_structure", "trend_structure_reason",
    "current_momentum", "momentum_reason",
    "weekday_path", "evidence_completeness",
    "prev_week_class", "prev2_week_class",
    "consecutive_heavy_decline_weeks",
    "week_realized_pct", "prorated_volume_ratio_vs_prev_week",
    "above_prev_week_close", "cross_week_recovery_eff",
    "comparison_basis",
]


def classify_stock(code: str, daily: pd.DataFrame, calendar: pd.DatetimeIndex,
                   cfg: AxesConfig, min_history: int = 130) -> pd.DataFrame:
    df = classify_stock_axes(daily, calendar, cfg, min_history=min_history)
    if len(df):
        df["code"] = str(code)
    return df[AXES_COLUMNS] if len(df) else df
