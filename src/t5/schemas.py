"""T5.1 字段 schema 与机器可读 dictionary。

每个字段 7 元组：(batch, family, formula, available_at, denominator,
adjustment, missing_semantics)。available_at 恒 <= state_date（PIT）；
outcome 字段单独成表，不进 state。
"""
from __future__ import annotations

import json

from t5.constants import RULE_VERSION

# ---- state 表列（按批次） --------------------------------------------
IDX_COLS = [
    "event_id", "code", "breakout_day", "delta_day", "state_date",
    "row_present", "adj_available", "volume_valid", "termination_reason",
    # T4 继承（逐事件对账，不重算）
    "exposure_class", "participation_policy", "initial_risk_budget_class",
    "M_cell", "L_q", "R60", "year",
]

PRICE_COLS = [
    "close_adj", "close_raw",
    "ret_1d_log", "ret_3d_log", "ret_5d_log",
    "cum_ret_from_t0_log",
    "post_t0_peak_ret_log", "drawdown_from_peak_log", "max_dd_to_date_log",
    "dist_to_ref20", "dist_to_ref60", "dist_to_t0_close",
    "dist_to_running_peak_log", "days_since_peak",
    "is_new_high_20d", "new_high_count_since_t0",
    "up_days_3", "down_days_3", "up_days_5", "down_days_5",
    "pullback_length_days",
]

PARTICIPATION_COLS = [
    "turnover_load_vs_prebreak", "volume_load_vs_prebreak",
    "amount_load_vs_prebreak",
    "turnover_load_change_1d", "turnover_load_change_3d",
    "turnover_load_3d_mean", "turnover_load_3d_prev_mean",
    "turnover_contraction_3d", "turnover_expansion_3d",
]

EFFICIENCY_COLS = [
    "price_progress_1d_log", "price_progress_3d_log",
    "efficiency_signed_1", "efficiency_signed_3", "efficiency_change_3",
    "marginal_progress_log",
]

CONTEXT_COLS = [
    "mkt_breadth_5d", "mkt_breadth_change_1d", "mkt_breadth_change_3d",
    "mkt_new_high_20d", "mkt_new_high_change_1d", "mkt_new_high_change_3d",
    "mkt_amount_yi",               # 诊断 only，state_allowed=False
]

STATE_COLS = IDX_COLS + PRICE_COLS + PARTICIPATION_COLS + EFFICIENCY_COLS \
    + CONTEXT_COLS

# ---- outcome 表列 ------------------------------------------------------
OUTCOME_COLS = [
    "event_id", "delta_day",
] + [f"fwd_ret_{h}d_log" for h in (1, 3, 5, 10)] \
    + [f"complete_{h}d" for h in (1, 3, 5, 10)] \
    + [f"fwd_peak_ret_{h}d_log" for h in (5, 10)] \
    + [f"fwd_mdd_{h}d_log" for h in (5, 10)] \
    + [f"fwd_new_high_{h}d" for h in (5, 10)] \
    + [f"fwd_lose_ref20_{h}d" for h in (5, 10)] \
    + [f"complete_path_{h}d" for h in (5, 10)] \
    + [f"n_obs_{h}d" for h in (1, 3, 5, 10)]


def _entry(batch, family, formula, available_at, denom, adj, missing,
           state_allowed=True):
    return {"batch": batch, "family": family, "formula": formula,
            "available_at": available_at, "denominator": denom,
            "adjustment": adj, "missing_semantics": missing,
            "state_allowed": state_allowed}


def build_dictionary() -> dict:
    d = {
        "rule_version": RULE_VERSION,
        "index": {
            "event_id": _entry("A", "idx", "T4 冻结 breakout_event_id",
                               "T0", None, None, "不可缺失"),
            "delta_day": _entry("A", "idx",
                                "市场交易日序号相对 T0（0 起，与 V3 tau 同源）",
                                "state_date 当日", None, None,
                                "0..min(40, lifecycle_end) 连续"),
            "state_date": _entry("A", "idx", "mdates[i0+delta_day]",
                                 "当日收盘", None, None,
                                 "超过数据集末尾则行不存在"),
            "row_present": _entry("A", "idx", "state_date ∈ 个股交易日集",
                                  "当日", None, None,
                                "False=停牌/无行情，不补值"),
            "termination_reason": _entry("A", "idx",
                                         "MAX_HORIZON/LIFECYCLE_END/DATA_END",
                                         "事件末行", None, None,
                                         "仅末行非空"),
            "exposure_class": _entry("A", "idx", "T4.5 E_class 继承",
                                     "T0", None, None, "缺证据事件为 E0"),
            "participation_policy": _entry("A", "idx", "T4.6 映射继承",
                                           "T0", None, None, "同上"),
            "code": _entry("A", "idx", "股票代码（6 位）", "T0", None,
                           None, "不可缺失"),
            "breakout_day": _entry("A", "idx", "T0 日期", "T0", None,
                                   None, "不可缺失"),
            "adj_available": _entry("A", "idx",
                                    "当日复权因子可用且 close 有效",
                                    "当日", None, None, "False→价格列 None"),
            "volume_valid": _entry("A", "idx", "当日成交额>0（有效行情）",
                                   "当日", None, None, "False→参与列 None"),
            "M_cell": _entry("A", "idx", "T4.4 市场 cell 继承", "T0",
                             None, None, "可为 NaN（缺证据）"),
            "L_q": _entry("A", "idx", "T4.4 流动性四分位继承", "T0",
                          None, None, "同上"),
            "R60": _entry("A", "idx", "T4.4 60 日趋势位继承", "T0",
                          None, None, "同上"),
            "year": _entry("A", "idx", "T0 年份", "T0", None, None,
                           "不可缺失"),
            "initial_risk_budget_class": _entry("A", "idx",
                                                "T4.6 档位继承", "T0",
                                                None, None, "同上"),
        },
        "price": {
            "close_adj": _entry("B", "price", "unadj_close×factor",
                                "收盘", None, "后复权因子 baostock",
                                "因子缺失→None"),
            "ret_{1,3,5}d_log": _entry(
                "B", "price", "log(adj_t/adj_{t-k})，k 个个股有效交易日",
                "收盘", None, "复权",
                "窗口内任一日缺行情→None"),
            "cum_ret_from_t0_log": _entry("B", "price",
                                          "log(adj_t/adj_T0)", "收盘",
                                          None, "复权", "T0 或当日缺→None"),
            "post_t0_peak_ret_log": _entry(
                "B", "price", "max log(adj[T0..t]/adj_T0)（as-of，不回填）",
                "收盘", None, "复权", "无有效日→None"),
            "drawdown_from_peak_log": _entry(
                "B", "price", "post_t0_peak_ret − cum_ret", "收盘",
                None, "复权", "同上"),
            "max_dd_to_date_log": _entry(
                "B", "price", "截至当日最大峰谷差（V3 同口径）", "收盘",
                None, "复权", "None"),
            "dist_to_ref20": _entry(
                "B", "price", "close_raw/ref20_raw − 1（T0 冻结 ref20）",
                "收盘", None, "raw（V3 同款）", "ref20 缺→None"),
            "dist_to_ref60": _entry(
                "B", "price", "adj/ref60_adj − 1（T0 冻结）", "收盘",
                None, "复权", "ref60 缺→None"),
            "is_new_high_20d": _entry(
                "B", "price", "adj_t ≥ 前 20 个股交易日 adj 最大值（21 窗）",
                "收盘", None, "复权", "历史不足/缺→None"),
            "close_raw": _entry("B", "price", "未复权收盘", "收盘",
                                None, "raw", "缺→None"),
            "dist_to_t0_close": _entry("B", "price", "raw_t/raw_T0 − 1",
                                       "收盘", None, "raw", "缺→None"),
            "dist_to_running_peak_log": _entry(
                "B", "price", "运行峰值收益 − 当日累计（log 差）",
                "收盘", None, "复权", "None"),
            "days_since_peak": _entry("B", "price",
                                      "距最近达到 T0 起峰值的有效日数",
                                      "收盘", None, "复权", "None"),
            "new_high_count_since_t0": _entry(
                "B", "price", "T0 起严格超过此前运行峰的次数（V3 口径）",
                "收盘", None, "复权", "None"),
            "up_days_{3,5}": _entry(
                "B", "price", "近 k 个股有效交易日上涨/下跌天数",
                "收盘", None, "复权 pctchg 口径", "不足 k 日→None"),
            "down_days_{3,5}": _entry(
                "B", "price", "同 up_days，下跌方向", "收盘", None,
                "复权", "不足 k 日→None"),
            "pullback_length_days": _entry(
                "B", "price", "自最近峰值日起连续低于峰值的交易日数",
                "收盘", None, "复权", "None"),
        },
        "participation": {
            "turnover_load_vs_prebreak": _entry(
                "C", "participation", "turn_t / pre20_turn_base（T4.2 冻结）",
                "收盘", "事件级 pre20 换手均值（T0 前固定，冻结）",
                "turn 为 baostock 换手率", "当日或基数缺→None"),
            "volume/amount_load_vs_prebreak": _entry(
                "C", "participation", "vol/amt_t / pre20 基数",
                "收盘", "事件级 pre20 均值（冻结）", "raw",
                "当日无效或基数缺→None"),
            "volume_load_vs_prebreak": _entry(
                "C", "participation", "vol_t / pre20_volume_base",
                "收盘", "事件级 pre20 均值（冻结）", "raw",
                "当日无效或基数缺→None"),
            "amount_load_vs_prebreak": _entry(
                "C", "participation", "amt_t / pre20_amount_base",
                "收盘", "事件级 pre20 均值（冻结）", "raw",
                "当日无效或基数缺→None"),
            "turnover_load_change_{1,3}d": _entry(
                "C", "participation", "load_t − load_{t-k}", "收盘",
                "同上", "同上", "任一端缺→None"),
            "turnover_load_3d_mean": _entry(
                "C", "participation", "近 3 有效日 load 均值", "收盘",
                "同上", "同上", "不足 3 日→None"),
            "turnover_load_3d_prev_mean": _entry(
                "C", "participation", "前 3 有效日 load 均值", "收盘",
                "同上", "同上", "不足 6 日→None"),
            "turnover_contraction/expansion_3d": _entry(
                "C", "participation",
                "近 3 日 load 均值 < / > 前 3 日 load 均值", "收盘",
                "同上", "同上", "任一窗缺→None"),
        },
        "efficiency": {
            "price_progress_{1,3}d_log": _entry(
                "D", "efficiency", "k 日 log 收益（=ret_{k}d_log）",
                "收盘", None, "复权", "窗口缺→None"),
            "efficiency_signed_{1,3}": _entry(
                "D", "efficiency",
                "price_progress_k / Σ_{k日} turnover_load（分母<0.01→None）",
                "收盘", "k 日 turnover_load 之和（LOAD_EPS 冻结下限）",
                "复权价格×raw 换手", "分母不足或价格缺→None"),
            "efficiency_change_3": _entry(
                "D", "efficiency", "eff_signed_1(t) − eff_signed_1(t−3)",
                "收盘", "同上", "同上", "任一端缺→None"),
            "marginal_progress_log": _entry(
                "D", "efficiency", "price_progress_1d_log（确定性差分）",
                "收盘", None, "复权", "缺→None"),
        },
        "context": {
            "mkt_breadth_change_{1,3}d": _entry(
                "D", "context", "breadth_5d(t) − breadth_5d(t−k)",
                "收盘", None, None, "任一端缺→None"),
            "mkt_new_high_change_{1,3}d": _entry(
                "D", "context", "new_high_20d_count 差分", "收盘",
                None, "复权", "任一端缺→None"),
            "mkt_breadth_5d": _entry(
                "D", "context", "T4.1 市场日 pct_up 5 日均（冻结口径）",
                "收盘", None, None, "历史不足→None"),
            "mkt_breadth_change_{1,3}d": _entry(
                "D", "context", "breadth_5d(t) − breadth_5d(t−k)",
                "收盘", None, None, "任一端缺→None"),
            "mkt_new_high_20d": _entry(
                "D", "context", "T4.1 市场 20 日新高股票数（当日）",
                "收盘", None, "复权", "None"),
            "mkt_new_high_change_{1,3}d": _entry(
                "D", "context", "计数差分", "收盘", None, "复权",
                "任一端缺→None"),
            "mkt_amount_yi": _entry(
                "D", "context", "全市场成交额（亿元）", "收盘", None, None,
                "None", state_allowed=False),
        },
        "outcome": {
            "fwd_ret_{1,3,5,10}d_log": _entry(
                "E", "outcome", "log(adj(t+h)/adj_t)，h 个股有效交易日",
                "未来（仅结果表）", None, "复权",
                "窗口不完整→None + complete=False"),
            "complete_{1,3,5,10}d": _entry(
                "E", "outcome", "窗口内有效日数 >= h", "未来", None,
                None, "False 表示 censored 非 0"),
            "complete_path_{5,10}d": _entry(
                "E", "outcome", "路径窗完整标志", "未来", None, None,
                "同上"),
            "n_obs_{1,3,5,10}d": _entry(
                "E", "outcome", "窗口内实际有效日数", "未来", None,
                None, "0..h"),
            "fwd_peak_ret_{5,10}d_log": _entry(
                "E", "outcome", "窗内最大 log 收益", "未来", None,
                "复权", "窗口不完整→None"),
            "fwd_mdd_{5,10}d_log": _entry(
                "E", "outcome", "窗内峰谷差（V3 口径）", "未来", None,
                "复权", "窗口不完整→None"),
            "fwd_new_high_{5,10}d": _entry(
                "E", "outcome", "∃ 未来 adj > 截至当日运行峰值",
                "未来", None, "复权", "窗口不完整→None"),
            "fwd_lose_ref20_{5,10}d": _entry(
                "E", "outcome", "∃ 未来 raw < ref20（T0 冻结）",
                "未来", None, "raw", "ref20 缺→None"),
            "fwd_peak/mdd_{5,10}d_log": _entry(
                "E", "outcome", "窗内峰值收益 / 峰谷差（V3 口径）",
                "未来", None, "复权", "同上"),
            "fwd_new_high_{5,10}d": _entry(
                "E", "outcome", "窗内 ∃ adj > 截至当日运行峰值", "未来",
                None, "复权", "同上"),
            "fwd_lose_ref20_{5,10}d": _entry(
                "E", "outcome", "窗内 ∃ raw < ref20（T0 冻结）", "未来",
                None, "raw", "同上"),
        },
    }
    return d


def dump_dictionary(path) -> None:
    with open(path, "w") as f:
        json.dump(build_dictionary(), f, ensure_ascii=False, indent=2)
