#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""posneg_path.py — 批次5 path/形态层核心 (STAGE5 v7.2 §1+§2, 2026-09-21).

§2 事件序(精确, eps=1e-9):
    strict_new_high = P_adj > P_bo×(1+eps);  reclaim = P_adj >= P_bo
    NH=窗内首个strict_new_high日; TR=窗内argmin(P_adj)日;
    RC=首个日序>TR的reclaim日(不含TR当日); D=max(0,1-min(P[1:20])/P_bo);
    E=max(0,1-P_adj(end)/P_bo)
决策树(首次命中即停, 六类互斥完备, 无θ):
    1 窗口不完整→right_censored; 2 窗内从未reclaim→never_reclaim;
    3 RC存在: NH不存在→reclaim_no_new_high; NH>=TR→pullback_new_high;
              NH<TR→high_then_pullback_reclaimed;
    4 RC不存在但曾reclaim→reclaim_then_fade
subtype: never_reclaim 内 E>0.15→breakout_failure 否则 breakout_unconfirmed

§1 双时点标签(T1=breakout_day, T2=first_pullback_day, T3=reattack 首日):
    group_eventual: censored且T3→G3; censored且(T1或T2)无T3→unknown_censored;
                    complete→无T2=G1/有T2无T3=G2/有T3=G3
    group_asof_20d: 仅 breakout+20 完整观察(outcome_20d_complete)时按同规则
                    截至 cutoff 判定, 否则 unknown_censored
structure_broken_asof_20d: cutoff=min(breakout+20交易日, last_day);
    break_date<=cutoff→true; 窗口完整未破→false; 不完整未破→null
"""
from __future__ import annotations

EPS = 1e-9
SUBTYPE_THETA = 0.15


def classify_path(p_bo: float, window: list[float], complete: bool
                  ) -> dict:
    """窗口 P_adj 序列(突破后第1..20交易日) → path_family/subtype/D/E/事件日.

    window 长度应为 20(complete=True); 不完整时按可得窗口判 right_censored。
    返回 dict: family, subtype, NH, TR, RC(1-based 日序, None=不存在), D, E。
    """
    n = len(window)
    if not complete or n < 20:
        return {"family": "right_censored", "subtype": None,
                "NH": None, "TR": None, "RC": None,
                "D": None, "E": None}
    strict = [p > p_bo * (1 + EPS) for p in window]
    reclaim = [p >= p_bo for p in window]
    nh = next((i + 1 for i, s in enumerate(strict) if s), None)
    tr = min(range(n), key=lambda i: window[i]) + 1        # argmin(首个最小)
    rc = next((i + 1 for i in range(n) if i + 1 > tr and reclaim[i]), None)
    d = max(0.0, 1.0 - min(window[:20]) / p_bo)
    e = max(0.0, 1.0 - window[-1] / p_bo)
    if not any(reclaim):
        fam = "never_reclaim"
    elif rc is not None:
        if nh is None:
            fam = "reclaim_no_new_high"
        elif nh >= tr:
            fam = "pullback_new_high"
        else:
            fam = "high_then_pullback_reclaimed"
    else:
        fam = "reclaim_then_fade"
    sub = None
    if fam == "never_reclaim":
        sub = "breakout_failure" if e > SUBTYPE_THETA else "breakout_unconfirmed"
    return {"family": fam, "subtype": sub, "NH": nh, "TR": tr, "RC": rc,
            "D": d, "E": e}


def group_labels(t2_day: str | None, t3_day: str | None,
                 right_censored: bool) -> str:
    """group_eventual(spec §1 确定算法)."""
    if right_censored:
        if t3_day is not None:
            return "G3"                     # 已确定, 不会再变
        return "unknown_censored"           # T1/T2 已现或只有 T1, 未来可能变
    if t3_day is not None:
        return "G3"
    if t2_day is not None:
        return "G2"
    return "G1"


def group_asof(t2_day: str | None, t3_day: str | None,
               cutoff_day: str | None) -> str:
    """group_asof_20d: cutoff=None(窗口不完整)→unknown_censored;
    否则按截至 cutoff 已出现的 T2/T3 判 G1/G2/G3."""
    if cutoff_day is None:
        return "unknown_censored"
    if t3_day is not None and t3_day <= cutoff_day:
        return "G3"
    if t2_day is not None and t2_day <= cutoff_day:
        return "G2"
    return "G1"


def atr_pct_prev(dates: list[str], bo_pos: int, high: dict, low: dict,
                 close: dict, F: dict) -> float | None:
    """ATR%_prev = ATR14_adj / P_adj(突破前一日). 前14日不全→None."""
    i = bo_pos - 1
    if i < 14:
        return None
    trs = []
    for j in range(i - 13, i + 1):
        h_, l_ = high[dates[j]] * F[dates[j]], low[dates[j]] * F[dates[j]]
        c_, cp = close[dates[j]] * F[dates[j]], close[dates[j - 1]] * F[dates[j - 1]]
        trs.append(max(h_, cp) - min(l_, cp))
    atr = sum(trs) / 14.0
    p_prev = close[dates[i]] * F[dates[i]]
    if p_prev <= 0:
        return None
    return atr / p_prev


def drawdown_bucket(d: float) -> str:
    return "le3pct" if d <= 0.03 else ("3to10pct" if d <= 0.10 else "gt10pct")


def below_break_bucket(e: float) -> str:
    return "le15pct" if e <= 0.15 else "gt15pct"
