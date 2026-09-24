"""T5.2 五状态轴（P/D/V/E/R）候选 primitive 清单与分箱定义。

只引用 T5.1 已冻结字段；本模块不含任何 outcome 引用。
轴语义（任务书 §三）：
P 价格推进 / D 损伤 / V 参与 / E 效率 / R 恢复。
"""
from __future__ import annotations

# 每轴候选 primitive（全部来自 t5_daily_state 冻结列）
AXES = {
    "P": {
        "cum_ret_from_t0_log": "T0 起累计对数收益",
        "ret_5d_log": "近 5 有效日对数收益",
        "ret_1d_log": "近 1 有效日对数收益",
        "dist_to_running_peak_log": "距运行峰值（log 差，<=0）",
        "dist_to_ref20": "距 ref20（raw 口径，结构位）",
        "is_new_high_20d": "21 窗新高",
        "new_high_count_since_t0": "T0 起创新高次数",
    },
    "D": {
        "drawdown_from_peak_log": "当前距 T0 后峰值",
        "max_dd_to_date_log": "截至当日最大峰谷差",
        "days_since_peak": "距最近峰值有效日数",
        "dist_to_ref20": "跌破 ref20 与否（结构损伤）",
    },
    "V": {
        "turnover_load_vs_prebreak": "换手 load（pre20 基数）",
        "volume_load_vs_prebreak": "量 load",
        "turnover_load_3d_mean": "3 日 load 均值",
        "turnover_contraction_3d": "3 日收缩",
        "turnover_expansion_3d": "3 日扩张",
        "turnover_load_change_3d": "3 日 load 变化",
    },
    "E": {
        "efficiency_signed_3": "3 日有符号效率（价格推进/参与）",
        "efficiency_signed_1": "1 日有符号效率",
        "efficiency_change_3": "效率 3 日变化",
        "marginal_progress_log": "边际推进（=ret_1d）",
    },
    "R": {
        # R 轴 = 历史损伤（<=state_date）+ 当前修复，由组合构造：
        "max_dd_to_date_log": "历史损伤深度（曾发生）",
        "drawdown_from_peak_log": "当前回撤（修复中则收窄）",
        "ret_3d_log": "近 3 有效日方向",
        "dist_to_running_peak_log": "距峰收窄程度",
    },
}

# 数值型候选（进入 delta dependency audit）
AUDIT_NUM = [
    "cum_ret_from_t0_log", "ret_1d_log", "ret_3d_log", "ret_5d_log",
    "drawdown_from_peak_log", "max_dd_to_date_log", "days_since_peak",
    "dist_to_ref20", "dist_to_ref60",
    "turnover_load_vs_prebreak", "volume_load_vs_prebreak",
    "turnover_load_3d_mean", "turnover_load_change_3d",
    "efficiency_signed_1", "efficiency_signed_3", "efficiency_change_3",
    "new_high_count_since_t0",
]

# 布尔/计数型（频数审计）
AUDIT_BOOL = ["is_new_high_20d", "turnover_contraction_3d",
              "turnover_expansion_3d"]

# 阈值来源四分类（任务书 §四）：
#   anchor     天然固定锚点（0 / 1 / 结构位）
#   frozen     已冻结无量纲比例
#   devquant   development-only delta-conditioned quantile
#   nodrift    证明无实质 delta drift 的固定阈值
THRESHOLD_SOURCE_KINDS = ("anchor", "frozen", "devquant", "nodrift")
