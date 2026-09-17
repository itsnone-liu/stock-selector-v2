"""外层市场/行业/ETF背景的PIT关联器。

背景只进入研究与仓位层，不修改个股月/周/日信号。
"""
from __future__ import annotations

import pandas as pd


REQUIRED_CONTEXT_KEYS = ("date",)


def attach_historical_membership(panel: pd.DataFrame, memberships: pd.DataFrame,
                                 *, code_col: str = "code",
                                 industry_col: str = "industry_code") -> pd.DataFrame:
    """按有效期关联事件时点行业；重叠有效期直接报错，禁止静默选一条。"""
    required = {code_col, "effective_from", "effective_to", industry_col}
    if not required <= set(memberships) or not {code_col, "date"} <= set(panel):
        raise ValueError("panel/memberships missing historical membership keys")
    mem = memberships.copy()
    mem[code_col] = mem[code_col].astype(str).str.zfill(6)
    mem["effective_from"] = pd.to_datetime(mem["effective_from"])
    mem["effective_to"] = pd.to_datetime(mem["effective_to"], errors="coerce")
    left = panel.copy().reset_index(drop=True)
    left[code_col] = left[code_col].astype(str).str.zfill(6)
    left["_event_date"] = pd.to_datetime(left["date"])
    left["_row_id"] = range(len(left))
    # 向量化区间连接：先按code展开候选区间，再按有效期过滤；语义与逐行版一致。
    pairs = left.merge(mem.rename(columns={industry_col: "_mem_industry"}),
                       on=code_col, how="left")
    hit = (pairs["effective_from"] <= pairs["_event_date"]) & \
          (pairs["effective_to"].isna() | (pairs["effective_to"] >= pairs["_event_date"]))
    pairs = pairs[hit]
    if pairs["_row_id"].duplicated(keep=False).any():
        bad_id = int(pairs[pairs["_row_id"].duplicated(keep=False)]["_row_id"].iloc[0])
        row = left.loc[bad_id]
        raise ValueError(f"overlapping membership for {row[code_col]} {row['date']}")
    mapping = pairs.set_index("_row_id")["_mem_industry"]
    out = left.copy()
    out[industry_col] = out["_row_id"].map(mapping)
    return out.drop(columns=["_row_id", "_event_date"])


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
