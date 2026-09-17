"""外层市场/行业/ETF背景的PIT关联器。

背景只进入研究与仓位层，不修改个股月/周/日信号。
"""
from __future__ import annotations

import pandas as pd


REQUIRED_CONTEXT_KEYS = ("date",)


def join_market_context(panel: pd.DataFrame, market_daily: pd.DataFrame) -> pd.DataFrame:
    """按同日左连接市场背景；无背景行保持缺失，不删除个股事件。"""
    if "date" not in panel or "date" not in market_daily:
        raise ValueError("panel and market_daily require date")
    ctx = market_daily.copy()
    ctx["date"] = pd.to_datetime(ctx["date"]).dt.date.astype(str)
    left = panel.copy()
    left["date"] = pd.to_datetime(left["date"]).dt.date.astype(str)
    if ctx["date"].duplicated().any():
        raise ValueError("market context must have one row per date")
    return left.merge(ctx, on="date", how="left", validate="many_to_one")


def join_industry_context(panel: pd.DataFrame, industry_daily: pd.DataFrame,
                          industry_col: str = "industry_code") -> pd.DataFrame:
    """按(date,历史行业)左连接；行业必须是事件时点映射，不接受当前映射回填历史。"""
    keys = {"date", industry_col}
    if not keys <= set(panel) or not keys <= set(industry_daily):
        raise ValueError(f"both frames require {sorted(keys)}")
    ctx = industry_daily.copy(); left = panel.copy()
    ctx["date"] = pd.to_datetime(ctx["date"]).dt.date.astype(str)
    left["date"] = pd.to_datetime(left["date"]).dt.date.astype(str)
    if ctx.duplicated(["date", industry_col]).any():
        raise ValueError("industry context must have one row per (date, industry)")
    return left.merge(ctx, on=["date", industry_col], how="left", validate="many_to_one")
