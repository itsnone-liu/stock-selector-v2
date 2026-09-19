"""阶段二：回调特征与事件去重（缩量回踩买点的事实层）。

语义冻结（docs/plans/STAGED_RESEARCH_PLAN_20260919.md §六）：
只定义事实，不规定仓位；只输出事件事实与 outcome 标签，不输出买卖信号。

研究范围：
- 只在月线池内（monthly_pool_state=='in'）的日线段上识别回调；
- 周线状态来自阶段一双轴表（trend_structure/current_momentum，按 ISO 周对齐）；
- 出池强制结束当前事件（pool_exit）——池外不产生、不延续事件。

事件定义（去重核心）：
同一股票自「缩量回调开始」起，到下列任一终点，只形成一个事件：
- new_high          重新创新高（close >= 事件起点近20日最高收盘）
- volume_breakdown  放量跌破支撑（量>=veto_ratio*前5日均量 且 close<支撑*0.99）
- structure_break   对齐周线趋势结构转 broken
- pool_exit         出月线池
- timeout           超最长观察期（默认 40 交易日）
- data_end          数据窗口结束（右删失）
事件结束次日起才允许开新事件；事件内任意多缩量日不产生新事件。

日线状态（每日明细旁路表保留全部事实）：
- 缩量回调开始：价格回落(较近20日最高收盘) + 缩量(量<min_volume_ratio*前5日均量)
  + 周线结构未破(intact/starting_to_damage) + 池内
- 触及支撑：low <= 支撑（支撑三类：ma10 / ma20 / 近期平台=近30日收盘20分位）
- 支撑止跌（候选主买点，不直接认定可买）：已触及支撑 S 后首个
  close >= S 且 close > 前收 的交易日
- 回调失败：放量跌破支撑 / 周线结构破坏（进入结束路径）

距离口径（三类同时记录，不预设哪个对）：
- 真实距离 dist_pct = (close/支撑 - 1)*100（首次触线时点）
- 波动标准化 dist_atr = dist_pct / (ATR14/close*100)（以事件起点 ATR 计）
- 固定 1% 参照 touch_within_1pct = |dist_pct| <= 1.0（原版均线距离口径）

PIT 合规：特征只用截至当日数据；forward 收益仅从止跌日起计算、
只写入事件表 outcome 字段（5/10/20 日），绝不进入每日特征。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd

RULE_VERSION = "pullback_stage2_v1"

WEEK_TREND_OK = ("intact", "starting_to_damage")

# 事件结束原因（右删失单独标注）
END_REASONS = ("new_high", "volume_breakdown", "structure_break",
               "pool_exit", "timeout", "data_end")

DAILY_COLUMNS = [
    "code", "date", "event_id", "in_pool",
    "week_trend", "week_momentum",
    "volume_ratio", "drawdown_from_high20_pct",
    "ma10", "ma20", "platform",
    "dist_ma10_pct", "dist_ma20_pct", "dist_platform_pct",
    "touched_ma10", "touched_ma20", "touched_platform",
    "shrink_volume",  # 当日缩量（量比 < min_volume_ratio）
]

EVENT_COLUMNS = [
    "code", "event_id", "first_day", "lowest_day", "lowest_close",
    "stabilization_day", "stabilization_support",
    "touched_ma10", "touched_ma20", "touched_platform",
    "end_day", "end_reason",
    "days_total", "days_to_low", "max_drawdown_pct",
    "min_volume_ratio_in_event",
    "dist_at_touch_pct", "dist_at_touch_atr", "touch_within_1pct",
    "outcome_ret_5", "outcome_ret_10", "outcome_ret_20",
    "outcome_new_high_within_20",
]


@dataclass
class PullbackConfig:
    min_volume_ratio: float = 0.8     # 缩量阈值（config.surge 复用）
    veto_ratio: float = 1.5           # 放量阈值（config.surge 复用）
    ma_windows: tuple = (10, 20)
    platform_lookback: int = 30
    platform_quantile: float = 0.20
    high_lookback: int = 20
    max_observation_days: int = 40
    outcome_horizons: tuple = (5, 10, 20)
    breakdown_tolerance: float = 0.99  # 跌破支撑 1% 容差（原版参照口径）

    @classmethod
    def from_config(cls, config: dict) -> "PullbackConfig":
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


def _prepare_features(daily: pd.DataFrame, cfg: PullbackConfig) -> pd.DataFrame:
    """预计算全部日线特征列（只含截至当日的信息）。"""
    df = daily.copy()
    df["prior5_vol"] = df["volume"].rolling(5).mean().shift(1)
    df["volume_ratio"] = df["volume"] / df["prior5_vol"]
    df["shrink_volume"] = df["volume_ratio"] < cfg.min_volume_ratio
    df["high20"] = df["close"].rolling(cfg.high_lookback).max()
    df["drawdown_from_high20_pct"] = df.apply(
        lambda r: _pct(r["close"], r["high20"]) if r["high20"] else 0.0, axis=1)
    for w in cfg.ma_windows:
        df[f"ma{w}"] = df["close"].rolling(w).mean()
    df["platform"] = (df["close"].rolling(cfg.platform_lookback)
                      .quantile(cfg.platform_quantile))
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14).mean()
    for name in ("ma10", "ma20", "platform"):
        df[f"dist_{name}_pct"] = df.apply(
            lambda r, s=name: _pct(r["close"], r[s]) if r[s] else 0.0, axis=1)
        df[f"touched_{name}"] = df["low"] <= df[name]
    df["close_up"] = df["close"] > prev_close
    return df


def _align_week_axis(daily_index: pd.DatetimeIndex, week_map: dict) -> tuple:
    """日线 -> 所在 ISO 周的双轴状态（池内周必有；缺周回退最近已知）。"""
    trends, momentums = [], []
    last = (None, None)
    for ts in daily_index:
        key = _iso_week_key(ts)
        if key in week_map:
            last = week_map[key]
        trends.append(last[0])
        momentums.append(last[1])
    return trends, momentums


def classify_pullback(code: str, daily: pd.DataFrame,
                      week_map: dict, pool_mask: dict,
                      cfg: PullbackConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """单股票：跑回调状态机，返回 (事件表 1行/事件, 每日明细表)。

    week_map: ISO周 -> (trend_structure, current_momentum)
    pool_map: date(YYYY-MM-DD) -> bool 池内
    """
    df = _prepare_features(daily, cfg)
    df["week_trend"], df["week_momentum"] = _align_week_axis(df.index, week_map)
    df["in_pool"] = [bool(pool_mask.get(ts.strftime("%Y-%m-%d"), False))
                     for ts in df.index]

    daily_rows, events = [], []
    cur = None  # 当前事件 dict

    def _close_event(pos: int, reason: str) -> None:
        nonlocal cur
        e = cur
        ts = df.index[pos]
        row = df.iloc[pos]
        e["end_day"] = ts.strftime("%Y-%m-%d")
        e["end_reason"] = reason
        e["days_total"] = pos - e["_start_pos"]
        e["days_to_low"] = e["_low_pos"] - e["_start_pos"]
        e["max_drawdown_pct"] = _pct(e["lowest_close"], e["_start_high20"])
        # outcome：仅从止跌日起算 forward（PIT：写入事件表，不进日线特征）
        stb = e.get("stabilization_day")
        if stb is not None:
            loc = e["_stb_pos"]
            base = df.iloc[loc]["close"]
            high_ref = e["_start_high20"]
            for h in cfg.outcome_horizons:
                j = loc + h
                r = df.iloc[j]["close"] if j < len(df) else None
                e[f"outcome_ret_{h}"] = _pct(r, base) if r is not None else None
            window = df.iloc[loc + 1: loc + 1 + cfg.outcome_horizons[-1]]
            e["outcome_new_high_within_20"] = bool(
                len(window) and (window["close"] >= high_ref).any())
        for k in ("_start_high20", "_last_support", "_start_pos",
                  "_low_pos", "_stb_pos"):
            e.pop(k, None)
        events.append(e)
        cur = None

    for pos, (ts, row) in enumerate(df.iterrows()):
        dstr = ts.strftime("%Y-%m-%d")
        trend = row["week_trend"]
        if cur is not None:
            # ---- 事件内逐日事实 ----
            touched = {s: bool(row[f"touched_{s}"]) for s in
                       ("ma10", "ma20", "platform")}
            for s in ("ma10", "ma20", "platform"):
                if touched[s]:
                    cur[f"touched_{s}"] = True
                    if cur.get("dist_at_touch_pct") is None:
                        cur["dist_at_touch_pct"] = float(row[f"dist_{s}_pct"])
                        atr_pct = (row["atr14"] / row["close"] * 100.0
                                   if row["atr14"] else None)
                        cur["dist_at_touch_atr"] = (
                            cur["dist_at_touch_pct"] / atr_pct
                            if atr_pct else None)
                        cur["touch_within_1pct"] = (
                            abs(cur["dist_at_touch_pct"]) <= 1.0)
                    cur["_last_support"] = s
            if row["close"] < cur["_low"]:
                cur["_low"] = row["close"]
                cur["lowest_day"] = dstr
                cur["lowest_close"] = float(row["close"])
                cur["_low_pos"] = pos
            if pd.notna(row["volume_ratio"]):
                cur["min_volume_ratio_in_event"] = min(
                    cur["min_volume_ratio_in_event"],
                    float(row["volume_ratio"]))
            # 止跌：已触支撑 S 且 close>=S 且收高（候选主买点，不是信号）
            if (cur.get("stabilization_day") is None
                    and cur.get("_last_support") is not None):
                s = cur["_last_support"]
                if row["close_up"] and row["close"] >= row[s]:
                    cur["stabilization_day"] = dstr
                    cur["stabilization_support"] = s
                    cur["_stb_pos"] = pos
        elif (row["in_pool"] and trend in WEEK_TREND_OK
                and bool(row["shrink_volume"])
                and pd.notna(row["drawdown_from_high20_pct"])
                and row["drawdown_from_high20_pct"] < 0
                and pd.notna(row["ma20"])):
            # ---- 开新事件：缩量回调开始（价格回落+缩量+周线未破+池内）----
            cur = {
                "code": code,
                "event_id": f"{code}_{dstr}",
                "first_day": dstr,
                "lowest_day": dstr, "lowest_close": float(row["close"]),
                "stabilization_day": None, "stabilization_support": None,
                "touched_ma10": False, "touched_ma20": False,
                "touched_platform": False,
                "end_day": None, "end_reason": None,
                "days_to_low": None, "max_drawdown_pct": None,
                "min_volume_ratio_in_event": (
                    float(row["volume_ratio"])
                    if pd.notna(row["volume_ratio"]) else None),
                "dist_at_touch_pct": None, "dist_at_touch_atr": None,
                "touch_within_1pct": None,
                "outcome_ret_5": None, "outcome_ret_10": None,
                "outcome_ret_20": None,
                "outcome_new_high_within_20": None,
                "_start_high20": float(row["high20"]),
                "_start_pos": pos,
                "_low": float(row["close"]),
                "_low_pos": pos,
                "_stb_pos": None,
                "_last_support": None,
            }
        # ---- 当日明细（含事件结束日：结束是事件的一部分）----
        if cur is not None:
            daily_rows.append({
                "code": code, "date": dstr, "event_id": cur["event_id"],
                "in_pool": bool(row["in_pool"]),
                "week_trend": row["week_trend"],
                "week_momentum": row["week_momentum"],
                "volume_ratio": (float(row["volume_ratio"])
                                 if pd.notna(row["volume_ratio"]) else None),
                "drawdown_from_high20_pct": float(row["drawdown_from_high20_pct"]),
                "ma10": float(row["ma10"]) if pd.notna(row["ma10"]) else None,
                "ma20": float(row["ma20"]) if pd.notna(row["ma20"]) else None,
                "platform": float(row["platform"]) if pd.notna(row["platform"]) else None,
                "dist_ma10_pct": float(row["dist_ma10_pct"]),
                "dist_ma20_pct": float(row["dist_ma20_pct"]),
                "dist_platform_pct": float(row["dist_platform_pct"]),
                "touched_ma10": bool(row["touched_ma10"]),
                "touched_ma20": bool(row["touched_ma20"]),
                "touched_platform": bool(row["touched_platform"]),
                "shrink_volume": bool(row["shrink_volume"]),
            })
        # ---- 终点判定（顺序即优先级；在明细记录之后）----
        if cur is not None:
            if not row["in_pool"]:
                _close_event(pos, "pool_exit")
            elif trend == "broken":
                _close_event(pos, "structure_break")
            else:
                sup = row[cur["_last_support"]] if cur.get("_last_support") else None
                if (sup and pd.notna(row["volume_ratio"])
                        and row["volume_ratio"] >= cfg.veto_ratio
                        and not row["close_up"]
                        and row["close"] < sup * cfg.breakdown_tolerance):
                    _close_event(pos, "volume_breakdown")
                elif row["close"] >= cur["_start_high20"]:
                    _close_event(pos, "new_high")
                elif pos - cur["_start_pos"] > cfg.max_observation_days:
                    _close_event(pos, "timeout")

    if cur is not None:  # 窗口结束仍未终局：右删失
        _close_event(len(df) - 1, "data_end")

    ev_df = pd.DataFrame(events, columns=EVENT_COLUMNS) if events else \
        pd.DataFrame(columns=EVENT_COLUMNS)
    d_df = pd.DataFrame(daily_rows, columns=DAILY_COLUMNS)
    return ev_df, d_df
