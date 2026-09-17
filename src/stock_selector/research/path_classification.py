"""结果分组和价格路径分类（分析层；不反写信号或生产逻辑）。"""
from __future__ import annotations


def outcome_bucket(excess_return: float | None, delta: float) -> str:
    """相对收益按预注册噪声带分正/中性/负；缺失保持unknown。"""
    if excess_return is None:
        return "unknown"
    if delta < 0:
        raise ValueError("delta must be non-negative")
    if excess_return > delta:
        return "positive"
    if excess_return < -delta:
        return "negative"
    return "neutral"


def price_path(final_return: float | None, early_return: float | None,
               mfe: float | None, mae: float | None,
               *, positive_delta: float, meaningful_mfe: float,
               deep_mae: float) -> str:
    """将期末结果和路径分开；阈值必须由研究协议预先给定。"""
    if any(v is None for v in (final_return, early_return, mfe, mae)):
        return "unknown"
    if final_return > positive_delta:
        if mae <= -abs(deep_mae):
            return "deep_drawdown_recovery"
        if early_return > 0:
            return "immediate_continuation"
        return "delayed_start"
    if mfe >= meaningful_mfe:
        return "spike_then_fade"
    return "direct_failure"
