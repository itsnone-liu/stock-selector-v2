"""第四批（阶段三研究）：行情生命周期事件。

语义契约（docs/plans/STAGE4_LIFECYCLE_ENTRY_REPLAY_SPEC.md，冻结）：
- 生命周期是事件路径而非线性流水线：preparation/breakout/confirmation/
  pullback/reattack/divergence/decay 可跳过，pullback→reattack 可循环；
- 每只股票同一生命周期唯一 lifecycle_id（md5，非序号），每日状态
  不得重复计为独立行情；
- 回调阶段消费 pullback_v2 事件（按窗口包含），不重跑第二套去重
  状态机——两套引擎必然漂移；
- reattack = 某次回调事件开始后的首次重新突破前 20 日高（可以就是该
  事件 new_high 结束日）；每次独立回调至多一次，记录对应事件编号；
- preparation/breakout/confirmation/divergence/decay 只记首次成立日，
  连续满足不重复追加；
- 终止原因枚举固定，优先级固定（同日并发时按此分诊）：
  pool_gap > monthly_exit > structure_break > max_observation > data_end；
- data_end 是右删失（right_censored=true），不是行情失败；
- 全部判定只使用截至当日收盘的证据；周线双轴按当日对齐（与
  pullback_features._align_week_axis 同一语义源）。
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from stock_selector.research.panel_store import stable_event_id
from stock_selector.research.pullback_features import _align_week_axis

RULE_VERSION = "lifecycle_stage4_v1"

WEEK_TREND_OK = ("intact", "starting_to_damage")

STAGES = ("preparation", "breakout", "confirmation", "pullback",
          "reattack", "divergence", "decay", "end")
END_REASONS = ("monthly_exit", "structure_break", "max_observation",
               "pool_gap", "data_end")

LIFECYCLE_COLUMNS = [
    "code", "lifecycle_id", "anchor_day",
    "preparation_start", "breakout_day", "confirmation_day",
    "first_pullback_day", "reattack_days", "reattack_pullback_event_ids",
    "divergence_day", "decay_day",
    "stage_sequence", "n_pullback_reattack_cycles",
    "end_day", "end_reason",
    "end_monthly_exit", "end_structure_break", "end_data_end",
    "right_censored", "days_total", "max_gain_from_anchor_pct",
    "pullback_event_ids",
]


@dataclass(frozen=True)
class LifecycleConfig:
    breakout_lookback: int = 20      # 与 pullback high_lookback 同源，不另设阈值
    max_observation_days: int = 120  # 生命周期级观察上限（回调的 40 是事件级）
    pool_gap_tolerance: int = 5      # 池状态 None 连续容忍（三态：in/out/None）

    @classmethod
    def from_config(cls, config) -> "LifecycleConfig":
        surge = getattr(getattr(config, "surge", None), "high_lookback", None)
        return cls(breakout_lookback=int(surge) if surge else 20)


def _prior_max(close: pd.Series, lookback: int) -> pd.Series:
    """当日之前的 lookback 收盘最高（排除当日，shift(1)）。"""
    return close.rolling(lookback).max().shift(1)


def classify_lifecycle(code: str, daily: pd.DataFrame, week_rows: list,
                       pool_state, pullback_events,
                       cfg: LifecycleConfig | None = None) -> pd.DataFrame:
    """单股生命周期分类。

    参数
    ----
    daily: 升序日线（含 open/close/high/low/volume），索引为 DatetimeIndex；
    week_rows: [(date, trend, momentum)] 升序，每交易日一行（同双轴表契约）；
    pool_state: date -> "in" | "out" | None 三态映射（Series 或 dict）；
    pullback_events: 该股 pullback_v2 事件（dict 或 DataFrame 行），
        至少含 event_id/first_day/end_day（"YYYY-MM-DD"）；
    cfg: LifecycleConfig。

    返回 1 行/生命周期的 DataFrame（LIFECYCLE_COLUMNS）。
    """
    cfg = cfg or LifecycleConfig()
    if len(daily) < cfg.breakout_lookback + 1:
        return pd.DataFrame(columns=LIFECYCLE_COLUMNS)

    trends, momentums = _align_week_axis(daily.index, week_rows)
    prior_max = _prior_max(daily["close"], cfg.breakout_lookback)

    # 回调事件按 first_day 升序，转成 (pos, end_pos, event_id) 便于窗口包含
    idx_pos = {ts.strftime("%Y-%m-%d"): i for i, ts in enumerate(daily.index)}
    pb_sorted = sorted(
        ({"event_id": str(e["event_id"]),
          "first_pos": idx_pos.get(str(e["first_day"]), -1),
          "end_pos": idx_pos.get(str(e["end_day"]), -1)}
         for e in pullback_events), key=lambda x: x["first_pos"])
    pb_sorted = [e for e in pb_sorted if e["first_pos"] >= 0]

    get_pool = (pool_state.get if hasattr(pool_state, "get")
                else (lambda d: None))

    out_rows: list[dict] = []
    cur: dict | None = None
    gap_run = 0
    pb_i = 0          # 下一个待消费的回调事件
    pb_pending = None # 最近开始、尚未被 reattack 消费的回调事件 id

    def _regime_ok(i: int) -> bool:
        return (get_pool(daily.index[i].strftime("%Y-%m-%d")) == "in"
                and trends[i] in WEEK_TREND_OK)

    for i, ts in enumerate(daily.index):
        if i < cfg.breakout_lookback:
            continue  # warmup 未满不得开段（§1）
        dstr = ts.strftime("%Y-%m-%d")
        pool = get_pool(dstr)
        trend = trends[i]

        # ---- 终止检查（优先级固定，先于阶段记录）----
        if cur is not None:
            reason = None
            if pool is None:
                gap_run += 1
                if gap_run > cfg.pool_gap_tolerance:
                    reason = "pool_gap"
            else:
                gap_run = 0
                if pool == "out":
                    reason = "monthly_exit"
                elif trend == "broken":
                    reason = "structure_break"
            # session_count 含 anchor：end_pos - anchor_pos + 1 >= 上限时结束
            if (reason is None
                    and i - cur["_anchor_pos"] + 1 >= cfg.max_observation_days):
                reason = "max_observation"
            if reason is not None:
                _close_lifecycle(cur, i, reason, out_rows, daily)
                cur = None
                gap_run = 0
                continue

        # ---- 生命周期开启 ----
        if cur is None:
            if not _regime_ok(i):
                continue
            prior = prior_max.iloc[i]
            is_break = bool(pd.notna(prior)
                            and daily["close"].iloc[i] > prior)
            cur = {
                "code": code, "anchor_day": dstr, "_anchor_pos": i,
                "preparation_start": None if is_break else dstr,
                "breakout_day": dstr if is_break else None,
                "confirmation_day": None,
                "first_pullback_day": None, "reattack_days": [],
                "reattack_event_ids": [],
                "divergence_day": None, "decay_day": None,
                "stage_seq": ["breakout"] if is_break else ["preparation"],
                "pullback_event_ids": [], "_anchor_close":
                    float(daily["close"].iloc[i]),
                "_breakout_close": float(daily["close"].iloc[i]) if is_break
                else None,
            }
            pb_pending = None
        else:
            # ---- 进行中：突破 / 再上攻（同一规则，排除当日的前高）----
            prior = prior_max.iloc[i]
            if pd.notna(prior) and daily["close"].iloc[i] > prior:
                if cur["breakout_day"] is None:
                    cur["breakout_day"] = dstr
                    cur["_breakout_close"] = float(daily["close"].iloc[i])
                    cur["stage_seq"].append("breakout")
                elif pb_pending is not None:
                    cur["reattack_days"].append(dstr)
                    cur["reattack_event_ids"].append(pb_pending)
                    cur["stage_seq"].append("reattack")
                    pb_pending = None

        # ---- 开段当日与进行中统一执行的当日阶段（§2 同日并存）----
        # 开段日确认/再上攻天然不成立：dstr==breakout_day（不严格后一日）、
        # 开段时 pb_pending 必为 None；分歧/衰减/回调关联不因开段漏记。

        # 确认：突破日之后首个不低于突破收盘的日子
        if (cur["confirmation_day"] is None
                and cur["breakout_day"] is not None
                and dstr > cur["breakout_day"]
                and daily["close"].iloc[i] >= cur["_breakout_close"]):
            cur["confirmation_day"] = dstr
            cur["stage_seq"].append("confirmation")

        # 回调事件进入窗口（消费 pullback_v2，不重检测）
        while (pb_i < len(pb_sorted)
                and pb_sorted[pb_i]["first_pos"] <= i):
            ev = pb_sorted[pb_i]
            if ev["first_pos"] >= cur["_anchor_pos"]:
                if cur["first_pullback_day"] is None:
                    cur["first_pullback_day"] = daily.index[
                        ev["first_pos"]].strftime("%Y-%m-%d")
                cur["stage_seq"].append("pullback")
                cur["pullback_event_ids"].append(ev["event_id"])
                pb_pending = ev["event_id"]
            pb_i += 1

        # 高位分歧 / 动能衰减（周线轴，当日对齐）
        if (cur["divergence_day"] is None
                and momentums[i] == "heavy_volume_decline"
                and trend in WEEK_TREND_OK):
            cur["divergence_day"] = dstr
            cur["stage_seq"].append("divergence")
        if cur["decay_day"] is None and trend == "starting_to_damage":
            cur["decay_day"] = dstr
            cur["stage_seq"].append("decay")

    # 窗口尾部仍 active -> 右删失（不是失败）
    if cur is not None:
        _close_lifecycle(cur, len(daily) - 1, "data_end", out_rows, daily)

    return pd.DataFrame(out_rows, columns=LIFECYCLE_COLUMNS)


def _close_lifecycle(cur: dict, end_pos: int, reason: str,
                     out_rows: list, daily: pd.DataFrame) -> None:
    seg = daily.iloc[cur["_anchor_pos"]:end_pos + 1]
    row = {
        "code": cur["code"],
        "lifecycle_id": stable_event_id(
            [cur["code"]], [cur["anchor_day"]], RULE_VERSION)[0],
        "anchor_day": cur["anchor_day"],
        "preparation_start": cur["preparation_start"],
        "breakout_day": cur["breakout_day"],
        "confirmation_day": cur["confirmation_day"],
        "first_pullback_day": cur["first_pullback_day"],
        "reattack_days": "|".join(cur["reattack_days"]) or None,
        "reattack_pullback_event_ids":
            "|".join(cur["reattack_event_ids"]) or None,
        "divergence_day": cur["divergence_day"],
        "decay_day": cur["decay_day"],
        "stage_sequence": "|".join(cur["stage_seq"] + ["end"]),
        "n_pullback_reattack_cycles": len(cur["reattack_days"]),
        "end_day": daily.index[end_pos].strftime("%Y-%m-%d"),
        "end_reason": reason,
        "end_monthly_exit": reason == "monthly_exit",
        "end_structure_break": reason == "structure_break",
        "end_data_end": reason == "data_end",
        "right_censored": reason == "data_end",
        "days_total": end_pos - cur["_anchor_pos"],
        "max_gain_from_anchor_pct": (
            (float(seg["close"].max()) / cur["_anchor_close"] - 1.0) * 100.0
            if len(seg) else 0.0),
        "pullback_event_ids": "|".join(cur["pullback_event_ids"]) or None,
    }
    out_rows.append(row)
