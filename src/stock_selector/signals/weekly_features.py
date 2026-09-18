"""周线特征与旧版规则复刻（P0 语义恢复）。

来源锁定（SOURCE_LOCK）：
- legacy_eod v4.0：/root/.hermes/hermes-agent/week_surge.py（LEGACY_FORENSICS.md 引用版）
  - 形态B（双阳效率）：tc/lc 为两周涨幅%，tv_ratio=本周量/上周量，
    t_eff=|tc|/tv_ratio，l_eff=|lc|，要求 t_eff > l_eff（无独立量比门槛）。
  - 形态A（阴转阳）：前周阴（close<=open）+本周阳（close>open），无任何量比要求。
  - 周三/周四：部分周按已过交易日数折算（涨幅/days×5、量/days×5）后与上周比较；
    形态A无量比要求优先，形态B用折算值算效率。
  - 周一：最近两个完整周形态判定（不看本周）。
  - 周二：先过周一门槛，再看本周一/周二日线三情形（涨保留/跌涨保留/双阴须缩量）。
  - veto v4.0：最后周 bar 收阴 且 amount(缺则 volume) > 前4周均值×1.5。
- 旧折算分母固定 5（日历星期语义），短周修正属于 optimized 差异，不在本文件混入。
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.calendar import aggregate_weekly, completed_week_rows, current_week_rows
from stock_selector.signals.contracts import UNKNOWN, WeekBar, WeeklyEvidence

LEGACY_PRORATION_BASE = 5  # 旧代码固定按 5 日折算（复刻，不修正）


# ---------- 原始指标（纯函数，先于任何判定） ----------

def dual_yang_efficiency(tw_open: float, tw_close: float, tw_vol: float,
                         pw_open: float, pw_close: float, pw_vol: float) -> dict:
    """形态B核心：双阳 + 效率提升。逐字段复刻旧 check_dual_yang。"""
    this_yang = tw_close > tw_open
    last_yang = pw_close > pw_open
    tc = (tw_close - tw_open) / tw_open * 100 if tw_open else 0.0
    lc = (pw_close - pw_open) / pw_open * 100 if pw_open else 0.0
    tv_ratio = (tw_vol / pw_vol) if pw_vol and pw_vol > 0 else 1.0
    t_eff = abs(tc) / tv_ratio if tv_ratio > 0 else 0.0
    l_eff = abs(lc) / 1.0
    passed = bool(this_yang and last_yang and t_eff > l_eff)
    return {
        "this_yang": this_yang, "last_yang": last_yang,
        "tc": round(tc, 4), "lc": round(lc, 4),
        "tv_ratio": round(tv_ratio, 4), "t_eff": round(t_eff, 4), "l_eff": round(l_eff, 4),
        "passed": passed,
    }


def reversal_check(tw_open: float, tw_close: float, pw_open: float, pw_close: float) -> dict:
    """形态A：前周阴 + 本周阳（无量比要求）。"""
    this_yang = tw_close > tw_open
    prev_yin = pw_close <= pw_open
    tc = (tw_close - tw_open) / tw_open * 100 if tw_open else 0.0
    return {"this_yang": this_yang, "prev_yin": prev_yin,
            "passed": bool(this_yang and prev_yin), "tc": round(tc, 4)}


def bearish_heavy_veto(week_bars: pd.DataFrame, lookback: int = 4, threshold: float = 1.5) -> tuple[bool, dict]:
    """veto v4.0：最后周 bar 收阴 且 amount(优先)/volume > 前 lookback 周均值×threshold。

    week_bars 最后一行为待检查的周（可为部分周）；前 lookback 行为基线。
    """
    if week_bars is None or len(week_bars) < lookback + 1:
        return False, {"note": "insufficient_weeks"}
    last = week_bars.iloc[-1]
    prev = week_bars.iloc[-(lookback + 1):-1]
    metric_col = "amount" if "amount" in week_bars.columns else "volume"
    if metric_col not in week_bars.columns:
        return False, {"note": "no_metric"}
    if prev[metric_col].isna().any() or last[metric_col] is None or pd.isna(last[metric_col]):
        return False, {"note": "metric_missing"}
    last_metric = float(last[metric_col])
    prev_mean = float(prev[metric_col].mean())
    bearish = float(last["close"]) < float(last["open"])
    heavy = prev_mean > 0 and last_metric > prev_mean * threshold
    metrics = {"metric": metric_col, "last_metric": round(last_metric, 2),
               "prev_mean": round(prev_mean, 2), "threshold": threshold,
               "bearish": bool(bearish), "heavy": bool(heavy)}
    return bool(bearish and heavy), metrics


# ---------- 周K构建 ----------

def _week_bar_from_rows(rows: pd.DataFrame) -> WeekBar | None:
    if rows is None or rows.empty:
        return None
    amount = float(rows["amount"].sum()) if "amount" in rows.columns else None
    return WeekBar(
        open=float(rows["open"].iloc[0]), high=float(rows["high"].max()),
        low=float(rows["low"].min()), close=float(rows["close"].iloc[-1]),
        volume=float(rows["volume"].sum()), amount=amount,
        sessions=len(rows), complete=False,
    )



def completed_weeks(daily: pd.DataFrame, as_of: datetime, min_weeks: int = 2,
                    weekly_full: pd.DataFrame | None = None) -> pd.DataFrame:
    """as_of 所在自然周之前的完整周（W-FRI 重采样）。

    weekly_full：预计算的整段周线（面板批量用），按周末边界切片，避免逐事件重采样。
    """
    if weekly_full is not None and len(weekly_full):
        ts = pd.Timestamp(as_of)
        monday = ts - pd.Timedelta(days=ts.weekday())
        sliced = weekly_full[weekly_full.index < monday]
        return sliced.tail(max(min_weeks, 8))
    prior = completed_week_rows(daily, as_of)
    if prior is None or prior.empty:
        return pd.DataFrame()
    weekly = aggregate_weekly(prior)
    return weekly.tail(max(min_weeks, 8))


def partial_week_bar(daily: pd.DataFrame, as_of: datetime) -> WeekBar | None:
    """本周截至 as_of 的部分周K（含当日）。"""
    rows = current_week_rows(daily, as_of)
    return _week_bar_from_rows(rows)



def early_week_comparison_evidence(daily: pd.DataFrame, as_of: datetime,
                                   planned_sessions: int | None) -> dict:
    """周一/周二的同进度与真实计划交易日折算证据；不参与当前准入。

    周 alignment 用 W-FRI 交易日周（aggregate_weekly 自动跳过休市空周），
    不用日历周：春节/国庆休市周会导致日历"上周/上上周"零交易日而误报缺失。
    """
    current = current_week_rows(daily, as_of)
    if current is None or current.empty:
        return {"note": "current_week_missing"}
    ts = pd.Timestamp(as_of).normalize()
    current = current[current.index <= ts]  # PIT防御：不假设调用方已截断
    if current.empty:
        return {"note": "current_week_missing"}
    n = len(current)
    prior = completed_week_rows(daily, as_of)
    weekly = aggregate_weekly(prior)
    if weekly is None or weekly.empty:
        return {"sessions": n, "note": "same_progress_insufficient"}
    end1 = weekly.index[-1]
    prev_full = prior[prior.index > end1 - pd.Timedelta(days=7)]
    previous = prev_full.head(n)
    tw, pw_same = _week_bar_from_rows(current), _week_bar_from_rows(previous)
    if tw is None or pw_same is None or len(previous) < n:
        return {"sessions": n, "note": "same_progress_insufficient"}
    current_ret, prev_same_ret = tw.change_pct, pw_same.change_pct
    same_vol_ratio = tw.volume / pw_same.volume if pw_same.volume > 0 else None
    planned = int(planned_sessions or LEGACY_PRORATION_BASE)
    planned_ret, planned_vol = current_ret / n * planned, tw.volume / n * planned
    prev_full_vol = float(prev_full["volume"].sum()) if len(prev_full) else 0.0
    # 收盘对收盘口径（2026-09-17裁定）：本周至今收盘 vs 上一交易周收盘；
    # 上一交易周同进度收盘 vs 再上一交易周收盘。历史交易周不足→None，不猜。
    prev_week_last_close = (float(prev_full["close"].iloc[-1])
                            if len(prev_full) else None)
    prev2_last_close = None
    if len(weekly) >= 2:
        end2 = weekly.index[-2]
        prev2_full = prior[(prior.index > end2 - pd.Timedelta(days=7)) & (prior.index <= end2)]
        if len(prev2_full):
            prev2_last_close = float(prev2_full["close"].iloc[-1])
    cc_current = ((float(current["close"].iloc[-1]) / prev_week_last_close - 1) * 100
                  if prev_week_last_close else None)
    cc_prev_same = ((float(previous["close"].iloc[-1]) / prev2_last_close - 1) * 100
                    if prev2_last_close else None)
    out = {
        "sessions": n, "planned_sessions": planned,
        "current_return_pct": round(current_ret, 4),
        "prev_same_progress_return_pct": round(prev_same_ret, 4),
        "same_progress_return_delta_pct": round(current_ret - prev_same_ret, 4),
        "cc_current_return_pct": round(cc_current, 4) if cc_current is not None else None,
        "cc_prev_same_progress_return_pct": round(cc_prev_same, 4) if cc_prev_same is not None else None,
        "cc_same_progress_return_delta_pct": (round(cc_current - cc_prev_same, 4)
                                              if cc_current is not None and cc_prev_same is not None else None),
        "same_progress_volume_ratio": round(same_vol_ratio, 4) if same_vol_ratio is not None else None,
        "planned_prorated_return_pct": round(planned_ret, 4),
        "planned_prorated_volume_ratio": round(planned_vol / prev_full_vol, 4) if prev_full_vol > 0 else None,
        "evidence_strength": round(n / planned, 4) if planned > 0 else None,
    }
    if n >= 2:
        mon, tue = current.iloc[0], current.iloc[-1]
        mon_drop = max(float(mon["open"]) - float(mon["close"]), 0.0)
        tue_recovery = max(float(tue["close"]) - float(tue["open"]), 0.0)
        out["tuesday_recovery_ratio"] = round(tue_recovery / mon_drop, 4) if mon_drop > 0 else None
        out["tuesday_closes_above_monday_close"] = bool(float(tue["close"]) > float(mon["close"]))
    return out


# ---------- 收盘对收盘动能上下文（2026-09-17 裁定口径） ----------

def close_close_context(weekly_completed: pd.DataFrame,
                        partial: WeekBar | None) -> dict | None:
    """所有比较用当期收盘 vs 前一期收盘，不用开盘（规避跳空/低开）。

    - prev_week_cc_pct: 上一完整周收盘/上上周收盘-1
    - prev2_week_cc_pct: 上上周收盘/再上周收盘-1（不足三周=None）
    - momentum_context_positive: 前两周 cc 均>0（任一未知→None，不猜）
    - partial_week_cc_pct: 本周至今收盘/上一完整周收盘-1
    - theory_stagnation_flag: 仅上涨早周计算——折算(cc/sessions×5)量>上周量
      且折算cc涨幅<上周cc涨幅×0.8 → 滞涨（部分周约束只用于排滞涨）。
    """
    if weekly_completed is None or len(weekly_completed) < 2 or partial is None:
        return None
    pw_close = float(weekly_completed.iloc[-1]["close"])
    pw2_close = float(weekly_completed.iloc[-2]["close"])
    prev_cc = (pw_close / pw2_close - 1) * 100 if pw2_close else None
    prev2_cc = None
    if len(weekly_completed) >= 3:
        pw3_close = float(weekly_completed.iloc[-3]["close"])
        prev2_cc = (pw2_close / pw3_close - 1) * 100 if pw3_close else None
    partial_cc = (partial.close / pw_close - 1) * 100 if pw_close else None
    context_positive = (None if prev_cc is None or prev2_cc is None
                        else bool(prev_cc > 0 and prev2_cc > 0))
    stagnation = None
    if partial_cc is not None and partial_cc > 0 and partial.sessions and prev_cc is not None:
        sessions = partial.sessions
        scaled_cc = partial_cc / sessions * LEGACY_PRORATION_BASE
        scaled_vol = partial.volume / sessions * LEGACY_PRORATION_BASE
        prev_vol = float(weekly_completed.iloc[-1]["volume"])
        stagnation = bool(scaled_vol > prev_vol and prev_cc > 0
                          and scaled_cc < prev_cc * 0.8)
    return {"prev_week_cc_pct": round(prev_cc, 4) if prev_cc is not None else None,
            "prev2_week_cc_pct": round(prev2_cc, 4) if prev2_cc is not None else None,
            "partial_week_cc_pct": round(partial_cc, 4) if partial_cc is not None else None,
            "momentum_context_positive": context_positive,
            "theory_stagnation_flag": stagnation}


# ---------- 星期分支（legacy_eod v4.0 复刻） ----------

def evaluate_monday(weekly_completed: pd.DataFrame, partial: WeekBar | None = None) -> dict:
    """周一：旧代码 tw=weekly.iloc[-1]（含当日的部分周K），pw=iloc[-2]（上一完整周）。

    差分校正：旧 resample('W-FRI') 在周一EOD时最后一根=当日单日部分周，
    不是两个完整周——按旧代码实际行为复刻。
    """
    if weekly_completed is None or len(weekly_completed) < 2 or partial is None:
        return {"passed": None, "base_pattern": UNKNOWN,
                "weekday_path": "monday", "components": {"note": "insufficient_weeks"}}
    tw_open, tw_close, tw_vol = partial.open, partial.close, partial.volume
    pw = weekly_completed.iloc[-1]
    eff = dual_yang_efficiency(tw_open, tw_close, tw_vol,
                               float(pw["open"]), float(pw["close"]), float(pw["volume"]))
    rev = reversal_check(tw_open, tw_close, float(pw["open"]), float(pw["close"]))
    pattern = "none"
    passed = False
    if eff["passed"]:
        pattern = "double_positive_efficiency_improved"
        passed = True
    elif rev["passed"]:
        pattern = "negative_to_positive"
        passed = True
    return {"passed": passed, "base_pattern": pattern,
            "weekday_path": "monday",
            "components": {"dual_yang": eff, "reversal": rev,
                           "tw_sessions": partial.sessions}}


def evaluate_tuesday(weekly_completed: pd.DataFrame, daily: pd.DataFrame, as_of: datetime,
                     partial: WeekBar | None = None) -> dict:
    """周二：先过周一门槛（部分周语义），再看本周一/周二三情形。"""
    monday = evaluate_monday(weekly_completed, partial=partial)
    out = {"passed": None, "base_pattern": monday.get("base_pattern", UNKNOWN),
           "weekday_path": "tuesday_gate_failed", "components": {"monday": monday}}
    if monday.get("passed") is None:
        out["weekday_path"] = "tuesday_gate_unknown"
        out["components"]["note"] = "周二前置周线证据不足"
        return out
    if monday.get("passed") is False:
        return out
    rows = current_week_rows(daily, as_of)
    if rows is None or len(rows) < 1:
        out["weekday_path"] = "tuesday_no_daily"
        out["passed"] = None
        out["components"]["note"] = "本周日线缺失"
        return out
    # 周二分支要求两个本周交易日；节后周二若是本周首个交易日，不得伪装成周一。
    rows = rows[rows.index <= pd.Timestamp(as_of)]
    if len(rows) < 2:
        out["weekday_path"] = "tuesday_first_session"
        out["components"]["note"] = "周二为本周首个交易日，日线分支证据不足"
        return out
    mon = rows.iloc[-2]
    mon_change = (float(mon["close"]) - float(mon["open"])) / float(mon["open"]) * 100 if mon["open"] else 0.0
    tue = rows.iloc[-1]
    tue_change = (float(tue["close"]) - float(tue["open"])) / float(tue["open"]) * 100 if tue["open"] else 0.0
    comp = {"monday_change_pct": round(mon_change, 4), "tuesday_change_pct": round(tue_change, 4)}
    if mon_change > 0:
        out.update(passed=True, weekday_path="tuesday_A", components={**out["components"], **comp})
    elif mon_change <= 0 and tue_change > 0:
        out.update(passed=True, weekday_path="tuesday_B", components={**out["components"], **comp})
    else:
        tue_vol, mon_vol = float(tue["volume"]), float(mon["volume"])
        comp.update(tuesday_volume=tue_vol, monday_volume=mon_vol,
                    shrink_ratio=round(tue_vol / mon_vol, 4) if mon_vol > 0 else None)
        if tue_vol < mon_vol:
            out.update(passed=True, weekday_path="tuesday_C", components={**out["components"], **comp})
        else:
            out.update(passed=False, weekday_path="tuesday_C_failed_volume",
                       components={**out["components"], **comp})
    return out


def evaluate_midweek(daily: pd.DataFrame, weekly_completed: pd.DataFrame, as_of: datetime) -> dict:
    """周三/周四：部分周（本周一至 as_of）vs 上一完整周，按已过交易日数折算。

    复刻旧 check_surge_wednesday_thursday：
    - 形态A：本周阳+上周阴（用未折算原始值判断阴阳），无量比要求；
    - 形态B：双阳+效率提升，用折算值（涨幅/days×5、量/days×5）。
    - 排除滞涨：折算量>上周量 且 折算涨幅<上周涨幅×0.8 → 剔除。
    """
    rows = current_week_rows(daily, as_of)
    if rows is None or len(rows) < 2 or weekly_completed is None or len(weekly_completed) < 1:
        return {"passed": None, "base_pattern": UNKNOWN, "weekday_path": "midweek_partial",
                "components": {"note": "insufficient_data"}}
    tw = _week_bar_from_rows(rows)
    pw = weekly_completed.iloc[-1]
    days = tw.sessions
    this_change = tw.change_pct
    this_change_scaled = this_change / days * LEGACY_PRORATION_BASE
    this_vol_scaled = tw.volume / days * LEGACY_PRORATION_BASE
    pw_change = (float(pw["close"]) - float(pw["open"])) / float(pw["open"]) * 100 if pw["open"] else 0.0
    pw_vol = float(pw["volume"])
    comp = {
        "sessions": days, "realized_change_pct": round(this_change, 4),
        "scaled_change_pct": round(this_change_scaled, 4),
        "prev_week_change_pct": round(pw_change, 4),
        "scaled_volume": round(this_vol_scaled, 2), "prev_week_volume": round(pw_vol, 2),
        "proration": f"/{days}×{LEGACY_PRORATION_BASE} (legacy fixed-5)",
    }
    if not tw.is_yang:
        return {"passed": False, "base_pattern": "none", "weekday_path": "midweek_partial", "components": comp}
    rev = reversal_check(tw.open, tw.close, float(pw["open"]), float(pw["close"]))
    # 差分校正：旧代码形态B的 tc 用折算涨幅（close_scaled），量用折算量
    scaled_close = tw.open + (tw.close - tw.open) / days * LEGACY_PRORATION_BASE
    eff = dual_yang_efficiency(tw.open, scaled_close, this_vol_scaled,
                               float(pw["open"]), float(pw["close"]), pw_vol)
    comp.update(reversal=rev, dual_yang_scaled=eff)
    # 排除滞涨（旧代码原文顺序：先排除滞涨再评分）
    if this_vol_scaled > pw_vol and this_change_scaled < pw_change * 0.8:
        comp["stagnation_excluded"] = True
        return {"passed": False, "base_pattern": "none", "weekday_path": "midweek_partial",
                "components": comp}
    # 旧顺序：形态A优先（无量比要求），形态B次之
    if rev["passed"]:
        return {"passed": True, "base_pattern": "negative_to_positive",
                "weekday_path": "midweek_partial", "components": comp}
    if eff["passed"]:
        return {"passed": True, "base_pattern": "double_positive_efficiency_improved",
                "weekday_path": "midweek_partial", "components": comp}
    return {"passed": False, "base_pattern": "none", "weekday_path": "midweek_partial",
            "components": comp}


def evaluate_friday(daily: pd.DataFrame, weekly_completed: pd.DataFrame, as_of: datetime) -> dict:
    """周五：本周（含周五）vs 上一完整周，完整周对比。"""
    rows = current_week_rows(daily, as_of)
    if rows is None or rows.empty or weekly_completed is None or len(weekly_completed) < 1:
        return {"passed": None, "base_pattern": UNKNOWN, "weekday_path": "completed_week",
                "components": {"note": "insufficient_data"}}
    tw = _week_bar_from_rows(rows)
    pw = weekly_completed.iloc[-1]
    eff = dual_yang_efficiency(tw.open, tw.close, tw.volume,
                               float(pw["open"]), float(pw["close"]), float(pw["volume"]))
    rev = reversal_check(tw.open, tw.close, float(pw["open"]), float(pw["close"]))
    comp = {"dual_yang": eff, "reversal": rev,
            "this_change_pct": round(tw.change_pct, 4),
            "prev_change_pct": round((float(pw["close"]) - float(pw["open"])) / float(pw["open"]) * 100 if pw["open"] else 0.0, 4)}
    # 旧顺序：周五形态A优先、形态B次之（标签归属与旧一致）
    if rev["passed"]:
        return {"passed": True, "base_pattern": "negative_to_positive",
                "weekday_path": "completed_week", "components": comp}
    if eff["passed"]:
        return {"passed": True, "base_pattern": "double_positive_efficiency_improved",
                "weekday_path": "completed_week", "components": comp}
    return {"passed": False, "base_pattern": "none", "weekday_path": "completed_week",
            "components": comp}



def derive_weekly_eligibility(ev: WeeklyEvidence) -> tuple[str, str]:
    """从Legacy证据纯派生Theory准入四态，不改 passed（保留源码差分语义）。

    2026-09-17 裁定叠加：
    - 周二B（反红）→ observation（不再是暂定eligible）；
    - 前两周cc正向时：早周下跌（部分周cc<=0）不做部分周硬约束 → observation；
    - 上涨早周用部分周约束识别滞涨 → theory_stagnation_flag → excluded。
    """
    # 可独立确认的负向证据优先；Legacy未知不能覆盖明确风险。
    if ev.veto_flag:
        return "excluded", "bearish_heavy_veto"
    comps = ev.components or {}
    # 所有可独立确认的负向证据先于门槛映射。
    if comps.get("stagnation_excluded"):
        return "excluded", "stagnation_excluded"
    if ev.theory_stagnation_flag:
        return "excluded", "theory_stagnation_partial_week"
    if ev.weekday_path == "tuesday_C_failed_volume":
        return "excluded", "tuesday_double_down_not_shrinking"
    if ev.weekday_path == "tuesday_gate_failed":
        # 周二旧门槛明确未过：这是已知条件不满足，不是数据不足；
        # Theory保持观察，不把Legacy失败擅自升级成排除。
        return "observation", "tuesday_legacy_gate_failed"
    if ev.passed is None:
        return UNKNOWN, "insufficient_evidence"
    if ev.weekday_path == "tuesday_B":
        return "observation", "tuesday_reversal_observation"
    # 旧源码会“保留”的待观察/卖压衰减，不等于Theory交易准入。
    if ev.weekday_path in {"tuesday_pending", "tuesday_C"}:
        return "observation", f"{ev.weekday_path}_legacy_hold"
    is_early_week = (ev.weekday_path == "monday"
                     or str(ev.weekday_path).startswith("tuesday"))
    if is_early_week and ev.momentum_context_positive is True:
        if ev.partial_week_cc_pct is not None and ev.partial_week_cc_pct <= 0:
            # 前期动能正向下的早周下跌：不放量跌→观察；放量跌已被veto排除。
            return "observation", "down_day_no_partial_constraint"
        if ev.passed:
            return "eligible", f"legacy_{ev.base_pattern}_{ev.weekday_path}"
        return "observation", f"up_day_legacy_not_passed_{ev.weekday_path}"
    if ev.passed:
        return "eligible", f"legacy_{ev.base_pattern}_{ev.weekday_path}"
    return "observation", f"legacy_not_passed_{ev.weekday_path}"


def evaluate_weekly(snapshot, source_variant: str = "legacy_eod",
                    weekly_full: pd.DataFrame | None = None) -> WeeklyEvidence:
    """统一入口：按星期分支复刻旧周线判定，输出连续证据+判定+组件。

    snapshot: signals.contracts.MarketSnapshot
    weekly_full: 预计算周线（批量加速，语义等价）
    """
    daily = snapshot.daily
    as_of = snapshot.as_of
    weekly_completed = completed_weeks(daily, as_of, weekly_full=weekly_full)
    partial = partial_week_bar(daily, as_of)

    ev = WeeklyEvidence(code=snapshot.code, as_of=as_of)
    if partial is not None:
        ev.realized_return_pct = round(partial.change_pct, 4)
        ev.volume_cumulative = partial.volume
        ev.amount_cumulative = partial.amount
        ev.week_sessions = partial.sessions
    ev.week_completion = snapshot.week_completion

    # veto：最后周 bar（=当前部分周）收阴且放量
    if weekly_completed is not None and len(weekly_completed) >= 4 and partial is not None:
        frame = pd.concat([weekly_completed, pd.DataFrame([{
            "open": partial.open, "high": partial.high, "low": partial.low,
            "close": partial.close, "volume": partial.volume,
            **({"amount": partial.amount} if partial.amount is not None else {}),
        }])])
        ev.veto_flag, ev.veto_metrics = bearish_heavy_veto(frame)

    cc_ctx = close_close_context(weekly_completed, partial)
    if cc_ctx is not None:
        ev.prev_week_cc_pct = cc_ctx["prev_week_cc_pct"]
        ev.prev2_week_cc_pct = cc_ctx["prev2_week_cc_pct"]
        ev.partial_week_cc_pct = cc_ctx["partial_week_cc_pct"]
        ev.momentum_context_positive = cc_ctx["momentum_context_positive"]
        if snapshot.calendar_weekday in (1, 2):
            ev.theory_stagnation_flag = cc_ctx["theory_stagnation_flag"]

    wd = snapshot.calendar_weekday
    if wd == 1:
        res = evaluate_monday(weekly_completed, partial=partial)
    elif wd == 2:
        res = evaluate_tuesday(weekly_completed, daily, as_of, partial=partial)
    elif wd in (3, 4):
        res = evaluate_midweek(daily, weekly_completed, as_of)
    else:
        res = evaluate_friday(daily, weekly_completed, as_of)

    ev.passed = res.get("passed")
    ev.base_pattern = res.get("base_pattern", UNKNOWN)
    ev.weekday_path = res.get("weekday_path", UNKNOWN)
    ev.legacy_gate_status = ("failed" if ev.weekday_path == "tuesday_gate_failed" else
                             "passed" if ev.passed is True else
                             "failed" if ev.passed is False else "insufficient")
    note = (res.get("components") or {}).get("note")
    ev.evidence_status = ("insufficient" if ev.passed is None and note else
                          "complete" if wd == 5 else
                          "partial" if partial is not None else "insufficient")
    # 差分校正：旧 check_weekly_surge 在分发层先跑 veto，veto=True 一票否决
    if ev.veto_flag:
        ev.notes.append("周线放量阴线 veto（v4.0 一票否决，对照组保留标记）")
        if ev.passed:
            ev.passed = False
            ev.notes.append("veto_overridden_branch_pass")
    early = early_week_comparison_evidence(
        daily, as_of, snapshot.planned_sessions_this_week
    ) if wd in (1, 2) else {}
    ev.components = {
        **res.get("components", {}),
        **({"theory_early_week_evidence": early} if early else {}),
        **({"close_close_context": cc_ctx} if cc_ctx is not None else {}),
        "source_variant": source_variant,
        "calendar_weekday": wd,
        "session_ordinal_in_week": snapshot.session_ordinal_in_week,
        "planned_sessions_this_week": snapshot.planned_sessions_this_week,
        "short_week": (snapshot.planned_sessions_this_week or 5) < 5,
    }
    ev.eligibility_state, ev.eligibility_reason = derive_weekly_eligibility(ev)
    if early:
        ev.same_progress_return_delta_pct = early.get("same_progress_return_delta_pct")
        ev.cc_same_progress_return_delta_pct = early.get("cc_same_progress_return_delta_pct")
        ev.same_progress_volume_ratio = early.get("same_progress_volume_ratio")
        ev.planned_prorated_return_pct = early.get("planned_prorated_return_pct")
        ev.planned_prorated_volume_ratio = early.get("planned_prorated_volume_ratio")
        ev.early_week_evidence_strength = early.get("evidence_strength")
        ev.tuesday_recovery_ratio = early.get("tuesday_recovery_ratio")
    # 效率连续量（供研究，非判定）
    eff = None
    comps = res.get("components", {})
    if isinstance(comps.get("dual_yang"), dict):
        eff = comps["dual_yang"]
    elif isinstance(comps.get("dual_yang_scaled"), dict):
        eff = comps["dual_yang_scaled"]
    if eff:
        ev.efficiency_this_week = eff.get("t_eff")
        ev.efficiency_prev_week = eff.get("l_eff")
        ev.efficiency_delta = round((eff.get("t_eff") or 0) - (eff.get("l_eff") or 0), 4)
        ev.volume_ratio_vs_prev_week = eff.get("tv_ratio")
        ev.efficiency_comparison_basis = "partial_prorated" if "dual_yang_scaled" in comps else "full_week"
    if ev.veto_flag:
        ev.notes.append("周线放量阴线 veto（v4.0 对照组保留）")
    return ev
