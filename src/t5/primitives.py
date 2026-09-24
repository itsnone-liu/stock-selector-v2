"""T5.1 逐日 primitives：价格 / 参与 / 效率 / 市场。

纯函数（numpy / 基础类型输入），不读未来：所有窗口只用 <= 当日序列。
个股"有效交易日"= 该股有行情行的日期（停牌日不在序列中）。
"""
from __future__ import annotations

import numpy as np

from t5.constants import LOAD_EPS, PRE20_BASE_EPS


# ---------------- 价格族（B 批） ----------------------------------------
def price_primitives(adj_valid: list, k_max: int = 5):
    """adj_valid: [(delta_day, adj_close) ...] 截至 t 的有效序列（含 t）。
    返回 dict：ret_k / cum / peak / dd / 等。"""
    t_delta, a_t = adj_valid[-1]
    out = {}
    for k in (1, 3, 5):
        if len(adj_valid) > k:
            out[f"ret_{k}d_log"] = float(np.log(a_t / adj_valid[-1 - k][1]))
        else:
            out[f"ret_{k}d_log"] = None
    out["cum_ret_from_t0_log"] = float(np.log(a_t / adj_valid[0][1]))
    rets = [np.log(a / adj_valid[0][1]) for _, a in adj_valid]
    peak = max(rets)
    out["post_t0_peak_ret_log"] = float(peak)
    out["drawdown_from_peak_log"] = float(peak - rets[-1])
    runmax = -np.inf
    mdd = 0.0
    for r in rets:
        runmax = max(runmax, r)
        mdd = max(mdd, runmax - r)
    out["max_dd_to_date_log"] = float(mdd)
    # 峰值日（最近一次达到峰值）
    peak_i = max(i for i, r in enumerate(rets) if r >= peak - 1e-15)
    out["days_since_peak"] = int(len(rets) - 1 - peak_i)
    # 自峰值日起连续低于峰值的交易日数（回调时长）
    pb = 0
    for r in reversed(rets):
        if r < peak - 1e-15:
            pb += 1
        else:
            break
    out["pullback_length_days"] = int(pb)
    return out


def dist_metrics(a_t, raw_t, ref20, ref60, adj_t0, raw_t0, peak_ret,
                 cum_ret):
    out = {}
    out["dist_to_ref20"] = float(raw_t / ref20 - 1.0) if (
        raw_t and ref20) else None
    out["dist_to_ref60"] = float(a_t / ref60 - 1.0) if (
        a_t and ref60) else None
    out["dist_to_t0_close"] = float(raw_t / raw_t0 - 1.0) if (
        raw_t and raw_t0) else None
    out["dist_to_running_peak_log"] = float(peak_ret - cum_ret) if (
        peak_ret is not None and cum_ret is not None) else None
    return out


def new_high_flag(adj_hist_pre20: list, a_t):
    """21 窗：当日 adj ≥ 前 20 个股交易日 adj 最大值。历史不足→None。"""
    if a_t is None:
        return None
    if len(adj_hist_pre20) < 20:
        return None
    return bool(a_t >= max(adj_hist_pre20))


def updown_days(pch_valid: list, k):
    """近 k 个股有效交易日的涨/跌天数（pch=复权涨跌幅）。不足→None。"""
    if len(pch_valid) < k:
        return None, None
    w = pch_valid[-k:]
    return int(sum(1 for x in w if x > 0)), int(sum(1 for x in w if x < 0))


# ---------------- 参与族（C 批） ----------------------------------------
def load_vs_base(value, base):
    if value is None or base is None or base <= PRE20_BASE_EPS:
        return None
    return float(value / base)


def load_change(load_now, load_then):
    if load_now is None or load_then is None:
        return None
    return float(load_now - load_then)


def contraction_expansion(recent3, prev3):
    """recent3/prev3: 近 3 日与前 3 日 turnover_load 均值（有效日）。"""
    if recent3 is None or prev3 is None:
        return None, None
    return (bool(recent3 < prev3), bool(recent3 > prev3))


# ---------------- 效率族（D 批） ----------------------------------------
def efficiency_signed(progress_log, load_sum, eps: float = LOAD_EPS):
    if progress_log is None or load_sum is None or load_sum < eps:
        return None
    return float(progress_log / load_sum)


# ---------------- 市场背景（D 批，冻结口径的轻包装） -------------------
def market_context(mkt_row_now, mkt_row_then_1, mkt_row_then_3):
    """mkt_row_*: T4.1 market_daily 行（含 breadth_5d/new_high/amount）。"""
    out = {"mkt_amount_yi": mkt_row_now["mkt_amount_yi"]}
    b_now = mkt_row_now.get("breadth_5d")
    n_now = mkt_row_now.get("new_high_20d_count")
    out["mkt_breadth_5d"] = b_now
    out["mkt_new_high_20d"] = n_now
    for k, prev in (("1d", mkt_row_then_1), ("3d", mkt_row_then_3)):
        b_prev = prev.get("breadth_5d") if prev is not None else None
        n_prev = (prev.get("new_high_20d_count")
                  if prev is not None else None)
        out[f"mkt_breadth_change_{k}"] = (
            float(b_now - b_prev) if (b_now is not None
                                      and b_prev is not None) else None)
        out[f"mkt_new_high_change_{k}"] = (
            int(n_now - n_prev) if (n_now is not None
                                    and n_prev is not None) else None)
    return out
