"""市场/行业日基准与相对收益（研究层）。

输入只需个股日收益长表；市场与行业基准均用同日横截面中位数，避免少数权重股支配。
"""
from __future__ import annotations

import pandas as pd


def daily_cross_section_benchmarks(returns: pd.DataFrame,
                                   industry_col: str = "industry_code") -> tuple[pd.DataFrame, pd.DataFrame]:
    required = {"code", "date", "return"}
    if not required <= set(returns):
        raise ValueError(f"returns require {sorted(required)}")
    x = returns.copy()
    x["date"] = pd.to_datetime(x["date"]).dt.date.astype(str)
    x["return"] = pd.to_numeric(x["return"], errors="coerce")
    valid = x.dropna(subset=["return"])
    market = valid.groupby("date", as_index=False).agg(
        market_return_med=("return", "median"),
        market_up_ratio=("return", lambda s: float((s > 0).mean())),
        market_down3_ratio=("return", lambda s: float((s <= -.03).mean())),
        market_n=("return", "size"),
    )
    if industry_col not in x:
        return market, pd.DataFrame(columns=["date", industry_col, "industry_return_med", "industry_up_ratio", "industry_n"])
    industry = valid.dropna(subset=[industry_col]).groupby(["date", industry_col], as_index=False).agg(
        industry_return_med=("return", "median"),
        industry_up_ratio=("return", lambda s: float((s > 0).mean())),
        industry_n=("return", "size"),
    )
    return market, industry


def forward_cross_section_benchmarks(prices: pd.DataFrame, horizons=(1, 2, 3, 5, 10, 15, 20),
                                     industry_col: str = "industry_code") -> tuple[pd.DataFrame, pd.DataFrame]:
    """由个股收盘长表生成每个起点的市场/行业前视中位收益。"""
    required = {"code", "date", "close"}
    if not required <= set(prices):
        raise ValueError(f"prices require {sorted(required)}")
    x = prices.copy().sort_values(["code", "date"])
    x["date"] = pd.to_datetime(x["date"]).dt.date.astype(str)
    for h in horizons:
        x[f"fwd{h}"] = x.groupby("code", sort=False)["close"].shift(-h) / x["close"] - 1
    market = x.groupby("date", as_index=False).agg(**{
        f"market_fwd{h}": (f"fwd{h}", "median") for h in horizons
    })
    if industry_col not in x:
        return market, pd.DataFrame(columns=["date", industry_col])
    industry = x.dropna(subset=[industry_col]).groupby(["date", industry_col], as_index=False).agg(**{
        f"industry_fwd{h}": (f"fwd{h}", "median") for h in horizons
    })
    return market, industry


def attach_relative_outcomes(outcomes: pd.DataFrame,
                             market_forward: pd.DataFrame,
                             industry_forward: pd.DataFrame | None,
                             horizons=(1, 2, 3, 5, 10, 15, 20),
                             industry_col: str = "industry_code") -> pd.DataFrame:
    """连接同起点前视基准并计算超额；连接缺失保持NaN，不过滤事件。"""
    left = outcomes.copy()
    left["date"] = pd.to_datetime(left["date"]).dt.date.astype(str)
    market = market_forward.copy()
    market["date"] = pd.to_datetime(market["date"]).dt.date.astype(str)
    if market["date"].duplicated().any():
        raise ValueError("market_forward must be unique by date")
    left = left.merge(market, on="date", how="left", validate="many_to_one")
    if industry_forward is not None:
        if industry_col not in left:
            raise ValueError(f"outcomes require {industry_col}")
        ind = industry_forward.copy()
        ind["date"] = pd.to_datetime(ind["date"]).dt.date.astype(str)
        if ind.duplicated(["date", industry_col]).any():
            raise ValueError("industry_forward must be unique by date+industry")
        left = left.merge(ind, on=["date", industry_col], how="left", validate="many_to_one")
    for h in horizons:
        stock = f"fwd{h}"
        if stock not in left:
            continue
        market_col = f"market_fwd{h}"
        industry_col_h = f"industry_fwd{h}"
        if market_col in left:
            left[f"market_excess{h}"] = left[stock] - left[market_col]
        if industry_col_h in left:
            left[f"industry_excess{h}"] = left[stock] - left[industry_col_h]
    return left
