"""T3 V6：状态条件下的四种入场执行研究（execution_policy_v1）。

语义契约（开工令 2026-09 + legacy 审计 execution_policy_definition_v1.json）：
- 四策略语义逐项继承 STAGE4 spec §5-§11 / STAGE5 v7.1（entry_replay_
  stage4_v5 冻结实现），本模块只换执行价层（T3 冻结库 baostock unadj，
  含 open）与收益层（F 因子比式，复权）；
- Primary 执行时钟 = signal 日收盘确认 → 次一市场日开盘成交
  （fill_date > signal_date 恒成立）；same_close 仅 diagnostic；
- Policy-level（A）与 trigger-conditioned（B）两类 estimand 分离；
  27,422×4×2(窗) 完整机会矩阵，未触发=真实策略结果；
- 双 outcome clock：entry-relative（fill+5/10/20）与 event-relative
  （T0+10/20/40 统一终点，未入资金现金 0 + not_entered）；
- origin_state=V5 tau0 compact（跨策略公平背景）；entry_state=fill 日
  compact（post-origin selection，只做解释）；七态不排序；
- 等待策略 trigger 语义=legacy：突破后首个 pullback_v2 回调事件内的
  首个缩量日 / stabilization_day；staged 30/30/40，T1 不受 3.5% 上限；
- 决策窗口 T0+10（primary）/ T0+20（预登记 sensitivity）：全部入场动作
  的 signal 日 ≤ T0+window 市场日；
- 涨跌停/停牌近似（approximate_limit_ratio，daily-bar execution proxy）；
- 统计：event-level paired delta（同终点 K3 型天然配对）、股票块+日期块
  （breakout_day）双 cluster bootstrap percentile 区间、Holm 族内 6 对、
  裁定点G 稀疏门禁；2024-2026 年度分层只称 internal temporal robustness。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from math import erfc, sqrt

import numpy as np
import pandas as pd

from stock_selector.decision.execution import (
    EXECUTION_MODEL_VERSION, CostModel, execution_feasibility, limit_ratio,
)
from stock_selector.research import t3_v2 as v2
from stock_selector.research import t3_v3 as v3

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "output/research/t3_v6"

RULE_VERSION = "execution_policy_v1"
STATE_DEP = "compact_state_v1@t3_v5"
POLICIES = ("direct_chase_capped", "wait_first_pullback",
            "wait_support_hold", "staged_entry")
POLICY_LABELS = {
    "direct_chase_capped": "直接追入(capped 3.5%)",
    "wait_first_pullback": "首次缩量回调",
    "wait_support_hold": "支撑止跌",
    "staged_entry": "分批进入(30/30/40)",
}
WINDOWS = (10, 20)                    # primary=10, sensitivity=20（预登记）
ENTRY_HORIZONS = (5, 10, 20)          # clock A：fill 起算
EVENT_HORIZONS = (10, 20, 40)         # clock B：T0 统一终点
CHASE_CAP_PCT = 3.5
TRANCHE_W = {"t1": 0.30, "t2": 0.30, "t3": 0.40}
CAPITAL = 100_000.0

# 裁定点G（STAGE5 §6 v6 冻结）
BOOT_B = 2000
BOOT_SEED = 20260919
GATES = {"min_events": 100, "min_unique_stocks": 30,
         "min_signal_dates": 30, "min_bootstrap_blocks": 30}

STATUS_LEVELS = (
    "entered", "capped_not_entered", "no_pullback_in_window",
    "not_triggered_in_window", "no_shrink_day", "no_stabilization",
    "triggered_but_unfillable", "sample_end", "data_gap",
)


def sha_row(d: dict) -> str:
    j = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(j.encode()).hexdigest()


# ---------------------------------------------------------------- 数据层
def load_stock_exec(code_pfx: str, factor_dates: dict) -> dict:
    """baostock unadj + open + F 因子（执行层最小切片，纯原始价）。"""
    import gzip
    j = json.load(gzip.open(
        ROOT / f"data/adjustment_baostock/per_stock/{code_pfx}.json.gz", "rt"))
    dates = [r[0] for r in j["unadj"]]

    def num(v):
        return None if v in (None, "") else float(v)

    return {
        "dates": dates,
        "dpos": {d: i for i, d in enumerate(dates)},
        "o": {r[0]: num(r[1]) for r in j["unadj"]},
        "c": {r[0]: float(r[4]) for r in j["unadj"]},
        "F": factor_dates.get(code_pfx, {}),
    }


# ---------------------------------------------------------------- 成交
def fill_attempt(ex: dict, code: str, sig_day: str, mdates, mpos,
                 cost: CostModel) -> dict:
    """signal 日次一市场日开盘成交尝试（legacy _next_fill 语义）。

    下一市场日个股无行情 = 停牌，不滑到复牌日。一字涨停近似
    （approximate_limit_ratio）保守判不可成交。返回完整 fillability 字段。
    """
    out = {"signal_date": sig_day,
           "intended_fill_date": None, "actual_fill_date": None,
           "fill_available": False, "fill_price": None,
           "open_valid": False, "suspended_before_fill": False,
           "one_price_limit_like": False,
           "fill_delay_days": None, "not_filled_reason": None,
           "gap_from_signal_close": None, "fill_proxy": "next_valid_open"}
    mp = mpos[sig_day]
    if mp + 1 >= len(mdates):
        out["not_filled_reason"] = "sample_end"
        return out
    nd = mdates[mp + 1]
    out["intended_fill_date"] = nd
    out["fill_delay_days"] = 1
    ip = ex["dpos"].get(nd)
    if ip is None:
        out["suspended_before_fill"] = True
        out["not_filled_reason"] = "missing_bar_or_suspended"
        return out
    op = ex["o"].get(nd)
    pc = ex["c"].get(sig_day)
    if op is None or op <= 0 or pc is None or pc <= 0:
        out["not_filled_reason"] = "missing_open_or_suspended"
        return out
    out["open_valid"] = True
    ratio = limit_ratio(code)
    tol = max(0.001, pc * 0.0015)
    if op >= pc * (1 + ratio) - tol:
        out["one_price_limit_like"] = True
        out["not_filled_reason"] = "open_limit_up_buy_blocked"
        return out
    out["fill_available"] = True
    out["actual_fill_date"] = nd
    out["fill_price"] = cost.fill_price(op, "buy")
    out["gap_from_signal_close"] = op / pc - 1.0
    return out


def _mark_value(ex: dict, day: str, side: str, cost: CostModel):
    """终点日估值：无行（停牌）沿最后可得行 carried（mark-to-market 惯例，
    非成交）。返回 (sell_fill_raw, F_exit, day_used, carried) 或 None。"""
    if day in ex["c"] and day in ex["F"]:
        px, f, used = ex["c"][day], ex["F"][day], day
    else:
        from bisect import bisect_right
        i = bisect_right(ex["dates"], day) - 1
        used = None
        while i >= 0:
            d = ex["dates"][i]
            if d in ex["c"] and d in ex["F"]:
                used = d
                break
            i -= 1
        if used is None:
            return None
        px, f = ex["c"][used], ex["F"][used]
    slip_px = px if side == "same" else cost.fill_price(px, side)
    return slip_px, f, used, used != day


def _leg_net(cost: CostModel, notional: float, buy_fill_raw: float,
             F_entry: float, sell_fill_raw: float, F_exit: float,
             sell_day: str) -> float | None:
    """STAGE5 §5.3 因子比式净收益（分红送转全部由因子比承载）。"""
    if buy_fill_raw <= 0 or F_entry <= 0 or F_exit <= 0:
        return None
    gross = notional * (sell_fill_raw * F_exit) / (buy_fill_raw * F_entry)
    sell_fee = cost.fees(gross, "sell", pd.Timestamp(sell_day).date())["total"]
    buy_fee = cost.fees(notional, "buy",
                        pd.Timestamp(sell_day).date())["total"]  # 近似日
    return (gross - sell_fee) / (notional + buy_fee) - 1.0


def _adj_path(ex: dict, d0: str, d1: str):
    """[d0,d1] 市场窗口内可得复权收盘 [(day, c*F)]，升序（bisect 切片）。"""
    from bisect import bisect_left
    i0 = bisect_left(ex["dates"], d0)
    out = []
    for d in ex["dates"][i0:]:
        if d > d1:
            break
        if d in ex["c"] and d in ex["F"]:
            out.append((d, ex["c"][d] * ex["F"][d]))
    return out


def _window_days(ex, mpos, mdates, p_from, p_to):
    """市场日窗口 [p_from, p_to]（位置）内的个股可得日 [(mpos, adj)]。"""
    if p_to >= len(mdates):
        p_to = len(mdates) - 1
    d0, d1 = mdates[p_from], mdates[p_to]
    from bisect import bisect_left
    i0 = bisect_left(ex["dates"], d0)
    out = []
    for d in ex["dates"][i0:]:
        if d > d1:
            break
        if d in ex["c"] and d in ex["F"]:
            out.append((mpos[d], ex["c"][d] * ex["F"][d]))
    return out


# ---------------------------------------------------------------- 单事件模拟
def _svd_get(states, eid, tau):
    return states.get((eid, tau))  # (compact, structure, participation, load)


def simulate_event(ev: dict, ex: dict, pb_first: dict | None,
                   shrink_days: list, mdates, mpos, mclose,
                   cost: CostModel, svd_states,
                   windows=WINDOWS) -> list[dict]:
    """一个 breakout 事件 × 4 policy × 双窗 的机会矩阵行 + 明细。"""
    eid, code, t0 = ev["breakout_event_id"], ev["code"], ev["breakout_day"]
    ip0 = ex["dpos"].get(t0)
    if ip0 is None:
        return [], []                     # T0 行缺失：不应发生（事件宇宙已冻结）
    mp0 = mpos[t0]
    bo_close = ex["c"][t0]
    f0v = ex["F"].get(t0)
    bo_adj = bo_close * f0v if f0v else None   # F 缺失：执行层照常，收益层 null
    prev_close = ex["c"][ex["dates"][ip0 - 1]] if ip0 > 0 else None
    sig_gain = (bo_close / prev_close - 1.0) * 100.0 if prev_close else None
    st0 = _svd_get(svd_states, eid, 0)

    # legacy 触发原料：首个 (T0, end_day] 内回调事件
    end_day = ev["end_day"]
    trig = None                         # (shrink_day, stab_day, reattack_day)
    if pb_first is not None:
        sd_day = next((d for d in shrink_days), None)
        trig = {"shrink": sd_day, "stab": pb_first.get("stabilization_day"),
                "reattack": None}
        rd = str(ev.get("reattack_days") or "").split("|")
        ri = str(ev.get("reattack_pullback_event_ids") or "").split("|")
        for rday, rid in zip(rd, ri):
            if rid == pb_first["event_id"]:
                trig["reattack"] = rday or None
                break

    def tau_of(day: str) -> int:
        return mpos[day] - mp0

    def svd_at(day: str):
        return _svd_get(svd_states, eid, mpos[day] - mp0)

    def in_window(day, w):
        return day is not None and mpos[day] - mp0 <= w

    def fill_leg(sig_day, tag, w, pol):
        """一次成交尝试 + 状态采集。返回 (fill dict, tau)。"""
        f = fill_attempt(ex, code, sig_day, mdates, mpos, cost)
        f["tranche_id"] = tag
        f["window"] = w
        f["policy"] = pol
        if f["fill_available"]:
            f["state_at_fill"] = svd_at(f["actual_fill_date"])
        attempts_all.append(f)
        return f, (mpos[sig_day] - mp0)

    rows = []
    attempts_all = []
    for w in windows:
        win_end_day = mdates[min(mp0 + w, len(mdates) - 1)]
        pb_in_win = pb_first is not None and \
            in_window(pb_first["first_day"], w)

        for policy in POLICIES:
            legs = []                   # (fill, weight)
            status, reason = None, None
            wait_days = None
            trigger_day = None

            if policy == "direct_chase_capped":
                trigger_day = t0
                if sig_gain is not None and sig_gain > CHASE_CAP_PCT:
                    status = "capped_not_entered"
                    reason = "chase_gain_cap_exceeded"
                else:
                    f, _ = fill_leg(t0, "t1", w, policy)
                    if f["fill_available"]:
                        legs.append((f, 1.0))
                        status = "entered"
                    else:
                        status = "triggered_but_unfillable"
                        reason = f["not_filled_reason"]
                wait_days = 0

            elif policy in ("wait_first_pullback", "wait_support_hold"):
                key = "shrink" if policy == "wait_first_pullback" else "stab"
                td = trig.get(key) if trig else None
                if td is not None and not in_window(td, w):
                    td = None            # 触发在窗口之后 = 窗内未触发
                trigger_day = td if td else (pb_first["first_day"]
                                             if pb_in_win else None)
                if not pb_in_win:
                    status, reason = "no_pullback_in_window", None
                elif td is not None:
                    f, _ = fill_leg(td, "t1", w, policy)
                    if f["fill_available"]:
                        legs.append((f, 1.0))
                        status = "entered"
                    else:
                        status = "triggered_but_unfillable"
                        reason = f["not_filled_reason"]
                else:
                    status = ("no_shrink_day"
                              if key == "shrink" else "no_stabilization")
                wait_days = (mpos[trigger_day] - mp0
                             if td is not None else None)

            else:                        # staged_entry
                trigger_day = t0
                f1, _ = fill_leg(t0, "t1", w, policy)
                if f1["fill_available"]:
                    legs.append((f1, TRANCHE_W["t1"]))
                # T2/T3：窗口内触发才执行（决策窗作用于全部入场动作）
                t2d = trig.get("shrink") if trig else None
                if t2d is not None and in_window(t2d, w):
                    f2, _ = fill_leg(t2d, "t2", w, policy)
                    if f2["fill_available"]:
                        legs.append((f2, TRANCHE_W["t2"]))
                    t3d = trig.get("reattack") if trig else None
                    if t3d is not None and in_window(t3d, w):
                        f3, _ = fill_leg(t3d, "t3", w, policy)
                        if f3["fill_available"]:
                            legs.append((f3, TRANCHE_W["t3"]))
                if legs:
                    status = "entered"
                else:
                    status = "triggered_but_unfillable"
                    reason = f1["not_filled_reason"]
                wait_days = 0

            entered = status == "entered"
            wsum = sum(wt for _, wt in legs)
            first_fill_day = min((f["actual_fill_date"] for f, _ in legs),
                                 default=None)

            # ---- clock B：event-relative 统一终点（未入现金 0）----
            clock_b = {}
            for h in EVENT_HORIZONS:
                hp = mp0 + h
                hday = mdates[hp] if hp < len(mdates) else None
                complete = hday is not None and hday <= v2.DATASET_END
                ret, carried, valuation_day = None, None, None
                if complete and not legs:
                    ret, carried = 0.0, False
                    valuation_day = hday
                elif complete:
                    mv = _mark_value(ex, hday, "sell", cost)
                    if mv is None:
                        ret = None
                    else:
                        sell_px, f_exit, vday, carr = mv
                        carried, valuation_day = carr, vday
                        port = 1.0 - wsum
                        ok = True
                        for f, wt in legs:
                            fp = mpos[f["actual_fill_date"]]
                            if fp > hp:
                                continue               # 终点后才成交 → 现金
                            if fp == hp:
                                # v7.1 边界：恰终点日成交 → 成交瞬间估值，
                                # 价格收益 0，仅计费用
                                leg = _leg_net(
                                    cost, CAPITAL * wt, f["fill_price"],
                                    ex["F"][f["actual_fill_date"]],
                                    f["fill_price"],
                                    ex["F"][f["actual_fill_date"]], hday)
                            else:
                                leg = _leg_net(
                                    cost, CAPITAL * wt, f["fill_price"],
                                    ex["F"][f["actual_fill_date"]],
                                    sell_px, f_exit, hday)
                            if leg is None:
                                ok = False
                                break
                            port += wt * (1.0 + leg)
                        ret = (port - 1.0) * 100.0 if ok else None
                clock_b[h] = {"ret_net": ret, "complete": complete,
                              "carried": carried, "valuation_day":
                              valuation_day}

            # ---- 未入场行的 missed / avoided 账（窗内 + event-clock 路径）
            missed_win = miss_post_max = miss_post_min = None
            if not entered and bo_adj:
                path = _adj_path(ex, t0, win_end_day)
                if path:
                    missed_win = (max(a for _, a in path) / bo_adj - 1.0) * 100
                p40 = _adj_path(ex, t0, mdates[min(mp0 + 40, len(mdates) - 1)])
                if p40:
                    miss_post_max = (max(a for _, a in p40) / bo_adj
                                     - 1.0) * 100
                    miss_post_min = (min(a for _, a in p40) / bo_adj
                                     - 1.0) * 100

            row = {
                "breakout_event_id": eid, "code": code,
                "lifecycle_id": ev["lifecycle_id"], "policy": policy,
                "window": w, "status": status,
                "not_filled_reason": reason,
                "signal_day_trigger": trigger_day,
                "trigger_found_in_window": bool(
                    (policy == "direct_chase_capped")
                    or (policy == "staged_entry")
                    or (trig is not None
                        and in_window(trig.get(
                            "shrink" if policy == "wait_first_pullback"
                            else "stab"), w))),
                "wait_days": wait_days,
                "sig_gain_pct": sig_gain,
                "first_fill_day": first_fill_day,
                "first_fill_tau": (mpos[first_fill_day] - mp0
                                   if first_fill_day else None),
                "n_tranches_filled": len(legs),
                "fraction_invested": wsum if entered else 0.0,
                "origin_state": st0[0] if st0 else None,
                "origin_structure": st0[1] if st0 else None,
                "origin_participation": st0[2] if st0 else None,
                "origin_turnover_load": st0[3] if st0 else None,
                "entry_state": _svd_get(
                    svd_states, eid, mpos[first_fill_day] - mp0
                )[0] if (entered and first_fill_day
                         and _svd_get(svd_states, eid,
                                      mpos[first_fill_day] - mp0)) else None,
                "entry_turnover_load": (
                    _svd_get(svd_states, eid, mpos[first_fill_day] - mp0)[3]
                    if (entered and first_fill_day
                         and _svd_get(svd_states, eid,
                                      mpos[first_fill_day] - mp0))
                    else None),
                "not_entered": not entered,
                "adj_factor_missing_t0": bo_adj is None,
                "missed_upside_in_window_pct": missed_win,
                "post_window_max_pct": miss_post_max,
                "post_window_min_pct": miss_post_min,
                "t0_year": t0[:4],
                "rule_version": RULE_VERSION,
            }
            # exposure / cash days + clock B 收益列
            exp_days = 0.0
            for h in EVENT_HORIZONS:
                row[f"ret_net_event_h{h}"] = clock_b[h]["ret_net"]
                row[f"complete_event_h{h}"] = clock_b[h]["complete"]
                row[f"carried_event_h{h}"] = clock_b[h]["carried"]
            for f, wt in legs:
                fp = mpos[f["actual_fill_date"]]
                exp_days += wt * max(
                    0, min(mp0 + 40, len(mdates) - 1) - fp)
            row["exposure_days_w40"] = exp_days
            row["cash_days_w40"] = 40.0 - exp_days
            # clock A（entered only）：fill 起算
            for h in ENTRY_HORIZONS:
                for suf in ("", "_sc"):
                    row[f"ret_net_entry_h{h}{suf}"] = None
                    row[f"complete_entry_h{h}{suf}"] = False
                row[f"mfe_entry_h{h}"] = None
                row[f"mae_entry_h{h}"] = None
                row[f"mdd_entry_h{h}"] = None
                row[f"new_high_entry_h{h}"] = None
                row[f"mkt_excess_entry_h{h}"] = None
            if entered:
                _entry_clock(row, ex, ev, mdates, mpos, mp0, legs, bo_adj,
                             cost, first_fill_day, mclose)
            rows.append(row)
            row["_legs"] = [(f, wt) for f, wt in legs]
    return rows, attempts_all


def _entry_clock(row, ex, ev, mdates, mpos, mp0, legs, bo_adj, cost,
                 first_fill_day, mclose):
    """clock A：从实际成交日（首笔）起 +5/+10/+20；same-close 诊断列。

    staged 用资金加权组合（终点=首笔 fill+h，legacy 共同终点语义）；
    未到终点批现金。MFE/MAE/MDD/new_high 为组合净值口径（staged 专用
    口径与全仓不可直接比较，legacy 同纪律）。
    """
    fp0 = mpos[first_fill_day]
    f0 = next(f for f, wt in legs
              if f["actual_fill_date"] == first_fill_day)
    wsum = sum(wt for _, wt in legs)
    sc_sig = f0["signal_date"]
    sc_px = ex["c"].get(sc_sig)
    bases = [(mpos[f["actual_fill_date"]], ex["o"][f["actual_fill_date"]],
              wt, f["fill_price"], ex["F"].get(f["actual_fill_date"], 0.0))
             for f, wt in legs]
    for h in ENTRY_HORIZONS:
        endp = fp0 + h
        endday = mdates[endp] if endp < len(mdates) else None
        complete = endday is not None and endday <= v2.DATASET_END
        row[f"complete_entry_h{h}"] = complete
        if complete:
            mv = _mark_value(ex, endday, "sell", cost)
            if mv is not None:
                sell_px, f_exit, _, _ = mv
                port = 1.0 - wsum
                for lp, lopen, wt, lpx, lfe in bases:
                    if lp > endp:
                        continue
                    if lp == endp:
                        # 恰终点日成交：成交瞬间估值，价格收益 0
                        leg = _leg_net(cost, CAPITAL * wt, lpx, lfe, lpx,
                                       lfe, endday)
                    else:
                        leg = _leg_net(cost, CAPITAL * wt, lpx, lfe,
                                       sell_px, f_exit, endday)
                    if leg is not None:
                        port += wt * (1.0 + leg)
                row[f"ret_net_entry_h{h}"] = (port - 1.0) * 100.0
            if sc_px and sc_px > 0 and endday in ex["c"] \
                    and endday in ex["F"]:
                row[f"complete_entry_h{h}_sc"] = True
                r = _leg_net(cost, CAPITAL, cost.fill_price(sc_px, "buy"),
                             ex["F"][sc_sig], cost.fill_price(
                                 ex["c"][endday], "sell"),
                             ex["F"][endday], endday)
                row[f"ret_net_entry_h{h}_sc"] = r * 100.0 if r is not None \
                    else None
        # 市场超额（对数）：首笔成交腿（含滑点因子比）vs 市场指数同期
        if complete:
            import math
            endday_m = float(mclose[endp]) if endp < len(mclose) else None
            fday_m = float(mclose[fp0]) if fp0 < len(mclose) else None
            lp0, _, _, lpx, lfe = bases[0]
            mv_e = _mark_value(ex, endday, "sell", cost)
            if (endday_m and fday_m and fday_m > 0 and lpx > 0 and lfe > 0
                    and mv_e is not None):
                row[f"mkt_excess_entry_h{h}"] = (
                    math.log((mv_e[0] * mv_e[1]) / (lpx * lfe))
                    - math.log(endday_m / fday_m)) * 100.0
        # MFE/MAE/MDD（组合净值，起点=fill 开盘）
        wd = _window_days(ex, mpos, mdates, fp0, fp0 + h)
        if wd:
            vals = []
            for tau, adj in wd:
                # 未到 fill 日的腿 = 现金（分批在途不得提前扣减净值）
                live = [(lp, lopen, wt) for lp, lopen, wt, _, _ in bases
                        if lp <= tau and lopen and lopen > 0]
                v = 1.0 - sum(wt for _, _, wt in live)
                for lp, lopen, wt in live:
                    fe = ex["F"].get(mdates[lp], 0.0)
                    v += wt * (adj / (lopen * fe) if fe > 0 else 1.0)
                vals.append(v)
            peak, mdd = -1e18, 0.0
            for v in vals:
                peak = max(peak, v)
                mdd = min(mdd, v / max(peak, 1e-12) - 1.0)
            row[f"mfe_entry_h{h}"] = (max(vals) - 1.0) * 100.0
            row[f"mae_entry_h{h}"] = (min(vals) - 1.0) * 100.0
            row[f"mdd_entry_h{h}"] = mdd * 100.0
        # new high：fill 后 1..h 市场日 close_adj >= 突破复权收盘
        row[f"new_high_entry_h{h}"] = (
            any(tau > fp0 and adj >= bo_adj for tau, adj in wd)
            if complete else None)
    return row


# ---------------------------------------------------------------- 主构建
def build_context(events):
    """公共重 IO：pullback 索引 + V5 状态切片（双跑共享，纯只读）。"""
    pev, shrink = load_pb_inputs()
    return pb_index_for_events(events, pev, shrink), load_svd_states()


def load_pb_inputs():
    """pullback_v2 事件与缩量日明细 → 每事件三元组索引。"""
    import glob
    import pyarrow.parquet as pq
    ev_files = sorted(glob.glob(str(
        ROOT / "output/research/lifecycle_v1/pullback_v2/events/partitions"
        "/**/*.parquet"), recursive=True))
    dl_files = sorted(glob.glob(str(
        ROOT / "output/research/lifecycle_v1/pullback_v2/daily/partitions"
        "/**/*.parquet"), recursive=True))
    pev = pd.concat([pq.read_table(f).to_pandas()[
        ["code", "event_id", "first_day", "end_day",
         "stabilization_day"]] for f in ev_files], ignore_index=True)
    shrink = set()
    for f in dl_files:
        t = pq.read_table(f, columns=["event_id", "date",
                                      "shrink_volume"]).to_pandas()
        for eid, d, sv in zip(t.event_id, t.date, t.shrink_volume):
            if sv:
                shrink.add((eid, str(d)))
    pev["event_id"] = pev["event_id"].astype(str)
    pev["first_day"] = pev["first_day"].astype(str)
    pev["end_day"] = pev["end_day"].astype(str)
    pev["stabilization_day"] = pev["stabilization_day"].astype(object)
    return pev, shrink


def pb_index_for_events(events, pev, shrink):
    """每 lifecycle 的首个 (T0, end_day] 回调事件 + 其缩量日列表。"""
    pev_by_code = {}
    for r in pev.itertuples(index=False):
        pev_by_code.setdefault(r.code, []).append(r)
    shrink_by_event = {}
    for eid, d in shrink:
        shrink_by_event.setdefault(eid, []).append(d)
    idx = {}
    for r in events.itertuples(index=False):
        cands = [e for e in pev_by_code.get(r.code, [])
                 if r.breakout_day < e.first_day <= r.end_day]
        if not cands:
            continue
        e = min(cands, key=lambda x: x.first_day)
        sd = sorted(d for d in shrink_by_event.get(e.event_id, [])
                    if r.breakout_day < d <= r.end_day)
        idx[r.breakout_event_id] = (e, sd)
    return idx


def load_svd_states():
    """V5 状态切片：tau<=12（origin=0 + fill/trigger 最晚 T0+11）。"""
    svd = pd.read_parquet(
        ROOT / "output/research/t3_v5/state_vector_daily.parquet",
        columns=["breakout_event_id", "tau", "compact_state",
                 "structure_state", "participation_state",
                 "turnover_load_to_tau", "source_date"])
    svd = svd[svd["tau"] <= 12]
    out = {}
    for r in svd.itertuples(index=False):
        if pd.notna(r.source_date):
            out[(r.breakout_event_id, int(r.tau))] = (
                r.compact_state, r.structure_state, r.participation_state,
                None if pd.isna(r.turnover_load_to_tau)
                else float(r.turnover_load_to_tau))
    return out


def attach_reattack(events):
    """从 lifecycle 分区补 reattack_days / reattack_pullback_event_ids。"""
    import glob
    import pyarrow.parquet as pq
    files = sorted(glob.glob(str(
        ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full"
        "/partitions/**/*.parquet"), recursive=True))
    lc = pd.concat([pq.read_table(
        f, columns=["code", "breakout_day", "reattack_days",
                    "reattack_pullback_event_ids"]).to_pandas()
        for f in files], ignore_index=True)
    lc["breakout_event_id"] = lc["code"].astype(str).str.zfill(6) + "_" \
        + lc["breakout_day"].astype(str)
    lc = lc[lc["breakout_day"].notna()].set_index("breakout_event_id")
    ev = events.set_index("breakout_event_id")
    ev["reattack_days"] = lc["reattack_days"].reindex(ev.index)
    ev["reattack_pullback_event_ids"] = lc[
        "reattack_pullback_event_ids"].reindex(ev.index)
    return ev.reset_index()


def build_all(events, factors, mdates, mpos, mclose, ctx=None,
              log=print) -> dict:
    cost = CostModel()
    if ctx is None:
        ctx = build_context(events)
    pb_idx, svd_states = ctx
    evs = events.to_dict("records")
    rows, entries, tranches, fills = [], [], [], []
    import time
    t0 = time.time()
    cache = {}
    for n, ev in enumerate(evs):
        pref = v3.stock_prefix(ev["code"])
        ex = cache.get(pref)
        if ex is None:
            ex = load_stock_exec(pref, factors)
            cache[pref] = ex
        pb_first, sd = pb_idx.get(ev["breakout_event_id"], (None, []))
        if pb_first is not None:
            pb_first = {"event_id": pb_first.event_id,
                        "first_day": pb_first.first_day,
                        "stabilization_day": (
                            None if pd.isna(pb_first.stabilization_day)
                            else str(pb_first.stabilization_day))}
        rs, attempts = simulate_event(ev, ex, pb_first, sd, mdates, mpos,
                                      mclose, cost, svd_states)
        for row in rs:
            legs = row.pop("_legs")
            rows.append(row)
            pol_att = [f for f in attempts
                       if f.get("window") == row["window"]
                       and f.get("policy") == row["policy"]]
            if row["status"] == "entered":
                f0 = legs[0][0]
                entries.append({
                    "breakout_event_id": row["breakout_event_id"],
                    "code": row["code"], "policy": row["policy"],
                    "window": row["window"],
                    "fill_date": f0["actual_fill_date"],
                    "fill_price": f0["fill_price"],
                    "gap_from_signal_close_pct": (
                        f0["gap_from_signal_close"] * 100.0
                        if f0["gap_from_signal_close"] is not None else None),
                    "fill_proxy": "next_valid_open_daily_bar",
                    "wait_days": row["wait_days"],
                    "origin_state": row["origin_state"],
                    "entry_state": row["entry_state"],
                    "entry_turnover_load": row["entry_turnover_load"],
                    "ret_net_entry_h5": row["ret_net_entry_h5"],
                    "ret_net_entry_h10": row["ret_net_entry_h10"],
                    "ret_net_entry_h20": row["ret_net_entry_h20"],
                    "mfe_entry_h20": row["mfe_entry_h20"],
                    "mae_entry_h20": row["mae_entry_h20"],
                    "mdd_entry_h20": row["mdd_entry_h20"],
                    "new_high_entry_h20": row["new_high_entry_h20"],
                    "mkt_excess_entry_h20": row["mkt_excess_entry_h20"],
                    "ret_net_entry_h20_sc": row["ret_net_entry_h20_sc"],
                })
            wmap = {(f["tranche_id"], f["signal_date"]): wt
                    for f, wt in legs}
            for f in pol_att:
                fills.append({
                    "breakout_event_id": row["breakout_event_id"],
                    "code": row["code"], "policy": row["policy"],
                    "window": row["window"],
                    "weight": wmap.get((f["tranche_id"], f["signal_date"])),
                    **{k: f.get(k) for k in (
                        "tranche_id", "signal_date",
                        "intended_fill_date", "actual_fill_date",
                        "fill_available", "fill_price", "open_valid",
                        "suspended_before_fill", "one_price_limit_like",
                        "fill_delay_days", "not_filled_reason",
                        "gap_from_signal_close", "fill_proxy")},
                    "state_at_fill": (
                        f["state_at_fill"][0]
                        if f.get("state_at_fill") else None),
                    "turnover_load_at_fill": (
                        f["state_at_fill"][3]
                        if f.get("state_at_fill") else None),
                })
        if (n + 1) % 2000 == 0:
            log(f"[v6] simulated {n + 1}/{len(evs)} events "
                f"{time.time() - t0:.0f}s")
    mat = pd.DataFrame(rows)
    mat = mat.copy()
    # 剩余现金（成交批视角）
    fill_df = pd.DataFrame(fills)
    return {"matrix": mat,
            "entries": pd.DataFrame(entries),
            "fillability": fill_df,
            "tranches": (fill_df[fill_df["fill_available"].astype(bool)]
                         .reset_index(drop=True)
                         if len(fill_df) else fill_df)}


# ---------------------------------------------------------------- 统计
def paired_contrasts(mat, B=BOOT_B, seed=BOOT_SEED):
    """event-level paired delta（clock B 同终点天然配对）+ 股票/日期双块
    cluster bootstrap percentile CI + Holm（族=(cohort,window,horizon)）。

    cohort：all + structure×participation 四格（primary）；origin 七态
    （exploratory，照算但不进 primary 排名）。等待策略未入=现金 0 计入
    delta（policy-level 语义）。
    """
    pairs = [(a, b) for i, a in enumerate(POLICIES)
             for b in POLICIES[i + 1:]]
    def _cohorts(mw):
        cs = {"all": pd.Series(True, index=mw.index)}
        for s in ("intact", "broken"):
            for p in ("normal", "elevated"):
                cs[f"{s}_{p}"] = ((mw["origin_structure"] == s)
                                  & (mw["origin_participation"] == p))
        for st in sorted(mw["origin_state"].dropna().unique()):
            cs[f"origin:{st}"] = mw["origin_state"] == st
        return cs

    out = []
    for w in WINDOWS:
        mw = mat[mat["window"] == w]
        cohorts = _cohorts(mw)
        for h in EVENT_HORIZONS:
            col = f"ret_net_event_h{h}"
            piv = mw.pivot(index="breakout_event_id", columns="policy",
                           values=col)
            for cname, mask in cohorts.items():
                ids = mw[mask]["breakout_event_id"].unique()
                sub = piv[piv.index.isin(ids)]
                sub = sub.dropna(axis=0, how="any")
                if not len(sub):
                    continue
                meta = mw[mw["breakout_event_id"].isin(sub.index)]
                mstock = meta.drop_duplicates("breakout_event_id").code
                mdate = meta.drop_duplicates("breakout_event_id")[
                    "breakout_event_id"].str.slice(7)
                stock_code = pd.factorize(mstock)[0]
                date_code = pd.factorize(mdate)[0]
                fam = []
                for i, (a, b) in enumerate(pairs):
                    d = (sub[a] - sub[b]).to_numpy(dtype=float)
                    d = d[np.isfinite(d)]
                    if not len(d):
                        continue
                    obs = float(np.mean(d))
                    # 双块 bootstrap
                    key = f"{seed}|{cname}|w{w}|h{h}|{i}"
                    sd_seed = int(hashlib.sha256(
                        key.encode()).hexdigest()[:8], 16)
                    sc = _block_boot(d, stock_code, sd_seed, B)
                    dc = _block_boot(d, date_code, sd_seed + 1, B)
                    fam.append({
                        "cohort": cname, "window": w, "horizon": h,
                        "policy_a": a, "policy_b": b, "n": len(d),
                        "n_stocks": len(set(mstock)), "n_dates": len(
                            set(mdate)),
                        "mean_delta": obs,
                        "ci_stock_lo": sc[0], "ci_stock_hi": sc[1],
                        "ci_date_lo": dc[0], "ci_date_hi": dc[1],
                        "both_consistent": bool(
                            (sc[0] > 0 and dc[0] > 0)
                            or (sc[1] < 0 and dc[1] < 0)),
                    })
                # Holm 族内 6 对（双侧：|CI 不跨 0| 双块一致才计显著）
                fam = _holm(fam)
                out.extend(fam)
    return pd.DataFrame(out)


def _block_boot(d, codes, seed, B):
    rng = np.random.default_rng(seed)
    K = int(codes.max()) + 1
    ar = np.arange(len(d))
    means = np.empty(B)
    for i in range(B):
        cnt = np.bincount(rng.integers(0, K, K), minlength=K)
        sel = np.repeat(ar, cnt[codes])
        means[i] = d[sel].mean()
    return float(np.percentile(means, 2.5)), float(
        np.percentile(means, 97.5))


def _holm(fam):
    """族内 Holm：p 值近似=正态 z（mean/SE of bootstrap 不存则用区间判定
    的秩近似）。此处按区间双侧判定给 p∈{近似}：完全不跨 0 双块一致才
    候选显著，Holm 顺序按 |mean_delta| 排序。"""
    cand = [r for r in fam if r["both_consistent"]
            and r["n"] >= GATES["min_events"]
            and r["n_stocks"] >= GATES["min_unique_stocks"]
            and r["n_dates"] >= GATES["min_signal_dates"]]
    cand.sort(key=lambda r: -abs(r["mean_delta"]))
    m = len(fam)
    for r in fam:
        r["holm_pass"] = False
        r["sparse_gate_ok"] = bool(
            r["n"] >= GATES["min_events"]
            and r["n_stocks"] >= GATES["min_unique_stocks"]
            and r["n_dates"] >= GATES["min_signal_dates"])
    used = 0
    for r in cand:
        # 近似 p：由区间宽度反推（保守 0.5*exp(-)），用确定性近似
        span_s = r["ci_stock_hi"] - r["ci_stock_lo"]
        se = max(span_s / 3.92, 1e-9)
        z = abs(r["mean_delta"]) / se
        p = erfc(z / sqrt(2.0))
        if p <= 0.05 / (m - used):
            r["holm_pass"] = True
            used += 1
        else:
            break
    return fam


def no_entry_accounting(mat):
    """§6：未入场计账表（per policy × window）。"""
    rows = []
    for w in WINDOWS:
        for p in POLICIES:
            m = mat[(mat["window"] == w) & (mat["policy"] == p)]
            n = len(m)
            ent = m[m["status"] == "entered"]
            rows.append({
                "policy": p, "window": w, "n": n,
                "entry_rate": len(ent) / n,
                "no_entry_rate": 1 - len(ent) / n,
                "median_wait_days": (
                    ent["wait_days"].median()
                    if "wait_days" in ent and len(ent) else None),
                **{f"P_entry_by_tau{t}": (
                    (m["first_fill_tau"] <= t).mean() if len(m) else None)
                    for t in (5, 10, 20)},
                "status_mix": m["status"].value_counts().to_dict(),
                "median_missed_upside_in_window_pct": m[
                    "missed_upside_in_window_pct"].median(),
                "median_fraction_invested": m["fraction_invested"].median(),
            })
    return pd.DataFrame(rows)


def attrition_table(mat):
    rows = []
    for w in WINDOWS:
        for p in POLICIES:
            m = mat[(mat["window"] == w) & (mat["policy"] == p)]
            vc = m["status"].value_counts()
            rows.append({"window": w, "policy": p, **{
                k: int(vc.get(k, 0)) for k in STATUS_LEVELS}})
    return pd.DataFrame(rows)


def grid_cohort_label(row):
    s, p = row["origin_structure"], row["origin_participation"]
    if s is None or p is None:
        return None
    return (("intact" if s == "intact" else "impaired")
            + ("_lowload" if p == "normal" else "_highload"))


# ---------------------------------------------------------------- 前瞻台账
LEDGER_COLUMNS = (
    "asof_date", "breakout_event_id", "code", "policy", "origin_state",
    "trigger_status", "trigger_date", "intended_fill_date",
    "actual_fill_date", "fill_price", "policy_version", "state_version",
    "input_manifest_hash", "note", "row_sha256", "prev_sha256",
)


def ledger_row_hash(d: dict) -> str:
    payload = {k: d.get(k) for k in LEDGER_COLUMNS
               if k not in ("row_sha256", "prev_sha256")}
    return sha_row(payload)


def ledger_append(path: Path, rows: list[dict]) -> None:
    prev = ""
    if path.exists():
        old = pd.read_parquet(path)
        prev = str(old.iloc[-1]["row_sha256"]) if len(old) else ""
    new = []
    for r in rows:
        d = dict(r)
        d["prev_sha256"] = prev
        d["row_sha256"] = ledger_row_hash(d)
        prev = d["row_sha256"]
        new.append(d)
    add = pd.DataFrame(new, columns=LEDGER_COLUMNS)
    out = add if not path.exists() else pd.concat(
        [pd.read_parquet(path), add], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)


def verify_ledger_chain(path: Path) -> dict:
    led = pd.read_parquet(path)
    prev = ""
    bad = 0
    asof_ok = True
    last_asof = ""
    for r in led.itertuples(index=False):
        d = {c: getattr(r, c) for c in LEDGER_COLUMNS}
        if d["prev_sha256"] != prev or \
                d["row_sha256"] != ledger_row_hash(d):
            bad += 1
        if d["asof_date"] <= last_asof:
            asof_ok = False
        last_asof = max(last_asof, d["asof_date"])
        prev = d["row_sha256"]
    return {"rows": len(led), "hash_chain_mismatches": bad,
            "asof_monotonic": asof_ok}
