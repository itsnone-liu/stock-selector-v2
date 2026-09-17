"""P1 信号面板：月线主池全量事件（未过滤周/日信号）。

方案 §六：每个研究时点对当时月线多头池内的所有股票生成周线+日线证据，
未触发也保留（对照组），缺失=unknown 不压成 false。特征面板先冻结落盘，
收益关联只发生在 outcomes 阶段。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from stock_selector.calendar import aggregate_weekly
from stock_selector.signals.daily_features import evaluate_daily
from stock_selector.signals.pre_signal_features import pre_signal_features
from stock_selector.signals.snapshot import build_snapshot
from stock_selector.signals.weekly_features import evaluate_weekly
from stock_selector.strategies.trend import monthly_trend

PANEL_VERSION = "momentum_panel_v2_contract"
SIGNAL_RULESET = "legacy_reconstructed_v1_eod"  # Legacy verdict source; Theory eligibility is a separate field


def panel_config_hash(config: dict) -> str:
    return hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _monthly_bull_pit(daily: pd.DataFrame, as_of: datetime, config: dict) -> bool:
    frame = daily[daily.index <= pd.Timestamp(as_of)]
    if frame is None or len(frame) < 120:
        return False
    try:
        res = monthly_trend(frame, config)
    except Exception:
        return False
    return bool(res.passed)


def _precompute_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """每股一次的月度聚合（PIT 快速路径的基块）。"""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    if "amount" in daily.columns:
        agg["amount"] = "sum"
    return daily.resample("ME").agg(agg).dropna(subset=["open", "close"])


def _monthly_series_fast(monthly_full: pd.DataFrame, daily: pd.DataFrame,
                         pos: int, as_of: datetime) -> list[float] | None:
    """as_of 时点的月收盘序列 = 完整月收盘 + 当月部分月收盘（=截至 as_of 的最后收盘）。

    与 monthly_trend(frame≤as_of) 的 close 序列等价（该函数只用 close）。
    """
    ts = pd.Timestamp(as_of)
    month_start = ts.to_period("M").to_timestamp()
    n_completed = int((monthly_full.index < month_start).sum())
    if n_completed == 0 or pos == 0:
        return None
    closes = monthly_full["close"].to_numpy()[:n_completed].tolist()
    closes.append(float(daily.iloc[pos - 1]["close"]))
    return closes


def _monthly_bull_from_closes(closes: list[float] | None, config: dict) -> bool | None:
    """月线状态纯函数：None=证据不足，False=明确不满足，True=满足。"""
    if closes is None or len(closes) < max(int(config["monthly"].get("min_bars", 20)), 20):
        return None
    import numpy as np

    arr = np.asarray(closes, dtype=float)
    ma5, ma10, ma20 = arr[-5:].mean(), arr[-10:].mean(), arr[-20:].mean()
    if any(pd.isna(v) for v in (ma5, ma10, ma20)):
        return None
    change = (arr[-1] / arr[-2] - 1) * 100 if len(arr) >= 2 else 0.0
    if change < -float(config["monthly"].get("max_last_month_drop_pct", 8.0)):
        return False
    if config["monthly"].get("require_ma_bull", True) and not (ma5 > ma10 > ma20):
        return False
    return True


def _monthly_states_fast(daily: pd.DataFrame, monthly_full: pd.DataFrame,
                         pos: int, as_of: datetime, config: dict) -> dict:
    ts = pd.Timestamp(as_of)
    month_start = ts.to_period("M").to_timestamp()
    completed_closes = monthly_full.loc[monthly_full.index < month_start, "close"].astype(float).tolist()
    provisional_closes = _monthly_series_fast(monthly_full, daily, pos, as_of)
    completed = _monthly_bull_from_closes(completed_closes, config)
    provisional = _monthly_bull_from_closes(provisional_closes, config)
    return {
        "monthly_completed_state": completed,
        "monthly_provisional_state": provisional,
        "monthly_state_changed_this_month": (
            provisional != completed if provisional is not None and completed is not None else None
        ),
    }


def _monthly_bull_fast(daily: pd.DataFrame, monthly_full: pd.DataFrame,
                       pos: int, idx: pd.DatetimeIndex, as_of: datetime, config: dict) -> bool:
    """与 _monthly_bull_pit 同语义的快速路径（池准入仍按临时月状态）。"""
    state = _monthly_states_fast(daily, monthly_full, pos, as_of, config)["monthly_provisional_state"]
    return bool(state)


def _tri_cell(value) -> str:
    """2×2研究格保留unknown，不把None静默压成0。"""
    if value is None or pd.isna(value):
        return "u"
    return "1" if bool(value) else "0"


def _evidence_row(code: str, daily: pd.DataFrame, as_of: datetime, weekly_full: pd.DataFrame,
                  monthly_states: dict | None = None) -> dict | None:
    snap = build_snapshot(code, as_of, daily)
    if not snap.has_current_bar:
        return None
    wev = evaluate_weekly(snap, source_variant="legacy_eod", weekly_full=weekly_full)
    dev = evaluate_daily(snap)
    daily_values = [dev.legacy_labels.get(k) for k in (
        "shrinking_volume_acceleration", "two_day_acceleration")]
    daily_trigger = None if all(v is None for v in daily_values) else any(bool(v) for v in daily_values)
    prior = pre_signal_features(snap)
    row = {
        "code": code,
        "date": as_of.date().isoformat(),
        "evidence_level": snap.evidence_level,
        "session_ordinal_in_week": snap.session_ordinal_in_week,
        "planned_sessions_this_week": snap.planned_sessions_this_week,
        **(monthly_states or {}),
        # 周线连续证据
        "week_realized_pct": wev.realized_return_pct,
        "t_eff": wev.efficiency_this_week,
        "l_eff": wev.efficiency_prev_week,
        "eff_delta": wev.efficiency_delta,
        "volume_ratio_vs_prev_week": wev.volume_ratio_vs_prev_week,
        "same_progress_return_delta_pct": wev.same_progress_return_delta_pct,
        "same_progress_volume_ratio": wev.same_progress_volume_ratio,
        "planned_prorated_return_pct": wev.planned_prorated_return_pct,
        "planned_prorated_volume_ratio": wev.planned_prorated_volume_ratio,
        "early_week_evidence_strength": wev.early_week_evidence_strength,
        "tuesday_recovery_ratio": wev.tuesday_recovery_ratio,
        "week_completion": wev.week_completion,
        # 周线判定
        "weekly_base_pattern": wev.base_pattern,
        "weekly_weekday_path": wev.weekday_path,
        "weekly_passed": wev.passed,
        "weekly_eligibility_state": wev.eligibility_state,
        "weekly_eligibility_reason": wev.eligibility_reason,
        "weekly_veto": wev.veto_flag,
        # 日线证据
        "r_today_pct": dev.r_today,
        "r_yesterday_pct": dev.r_yesterday,
        "return_acceleration_pct": dev.return_acceleration,
        "volume_ratio_vs_prev": dev.volume_ratio_vs_prev,
        "activity_state": dev.optimized_labels.get("activity_state"),
        "atr14_prev": dev.atr14_previous,
        "atr_normalized_move": dev.atr_normalized_move,
        # 原版标签（上限前/后分开）
        "sv_raw": dev.raw_pattern_matched.get("shrinking_volume_acceleration_raw"),
        "sv_legacy": dev.legacy_labels.get("shrinking_volume_acceleration"),
        "td_raw": dev.raw_pattern_matched.get("two_day_acceleration_raw"),
        "td_legacy": dev.legacy_labels.get("two_day_acceleration"),
        "cap_passed": dev.legacy_labels.get("return_cap_passed"),
        "sv_continuation": dev.optimized_labels.get("SV_continuation"),
        "sv_rebound": dev.optimized_labels.get("SV_rebound"),
        "acc_continuation": dev.optimized_labels.get("acceleration_continuation"),
        "acc_rebound": dev.optimized_labels.get("acceleration_rebound"),
        # 协同格：unknown不得压成false；日线两个标签均未知时才是u。
        "weekly_daily_cell": f"{_tri_cell(wev.passed)}_{_tri_cell(daily_trigger)}",
        **prior,
    }
    return row


def build_panel(store, codes: list[str], dates: list[datetime], config: dict,
                min_history: int = 130) -> tuple[pd.DataFrame, dict]:
    """对 (codes × dates) 生成月线池内全量证据行。"""
    rows: list[dict] = []
    stats = {"stocks": 0, "stocks_with_data": 0, "monthly_pool_hits": 0, "rows": 0,
             "missing_current_bar": 0, "panel_version": PANEL_VERSION,
             "signal_ruleset": SIGNAL_RULESET}
    for code in codes:
        daily = store.daily(str(code))
        if daily is None or len(daily) < min_history:
            continue
        stats["stocks_with_data"] += 1
        daily = daily.sort_index()
        weekly_full = aggregate_weekly(daily)
        monthly_full = _precompute_monthly(daily)
        idx = pd.DatetimeIndex(daily.index)
        for as_of in dates:
            day = pd.Timestamp(as_of).normalize()
            pos = idx.searchsorted(day, side="right")
            if pos == 0 or idx[pos - 1] != day:
                continue
            monthly_states = _monthly_states_fast(daily, monthly_full, pos, as_of, config)
            if not monthly_states["monthly_provisional_state"]:
                continue
            stats["monthly_pool_hits"] += 1
            row = _evidence_row(str(code), daily, as_of, weekly_full,
                                monthly_states=monthly_states)
            if row is None:
                stats["missing_current_bar"] += 1
                continue
            rows.append(row)
        stats["stocks"] += 1
    stats["rows"] = len(rows)
    return pd.DataFrame(rows), stats


def attach_outcomes(store, panel: pd.DataFrame,
                    horizons=(1, 2, 3, 5, 10, 15, 20)) -> pd.DataFrame:
    """对已冻结的 signal_panel 关联未来收益（独立阶段，禁止反向引用）。"""
    from stock_selector.research.outcomes import next_day_outcomes, next_week_outcomes, same_week_remaining

    if panel.empty:
        return panel
    out_rows: list[dict] = []
    cache: dict[str, pd.DataFrame] = {}
    for _, r in panel.iterrows():
        code = r["code"]
        if code not in cache:
            daily = store.daily(code)
            cache[code] = daily.sort_index() if daily is not None else None
        daily = cache[code]
        if daily is None:
            continue
        d = pd.Timestamp(r["date"]).date()
        o1 = next_day_outcomes(daily, d, horizons=horizons)
        ow = next_week_outcomes(daily, d)
        wr = same_week_remaining(daily, d)
        sig = {"signal_id": f"{r['code']}_{r['date']}", "code": r["code"], "date": r["date"],
               "weekly_passed": r.get("weekly_passed"), "sv_legacy": r.get("sv_legacy"),
               "td_legacy": r.get("td_legacy"), "weekly_daily_cell": r.get("weekly_daily_cell"),
               "t_eff": r.get("t_eff"), "eff_delta": r.get("eff_delta"),
               "weekday_path": r.get("weekly_weekday_path")}
        out_rows.append({**sig, **o1, **ow, **wr})
    return pd.DataFrame(out_rows)
