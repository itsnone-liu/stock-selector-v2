"""V3 P4 事件研究基础：去重、路径分布、MAE/MFE与右尾贡献。

不做策略晋升判断；输出用于E2-E7统一统计。所有forward列必须由调用者在样本切分后生成。
"""
from __future__ import annotations

import pandas as pd

from stock_selector.research.outcomes import PRIMARY_HORIZONS


def deduplicate_events(events: pd.DataFrame, cluster_sessions: int = 5) -> pd.DataFrame:
    """同股票同事件类型在N个真实交易行内只保留簇首；必须提供session_index。"""
    if events.empty:
        return events.copy()
    if "session_index" not in events.columns:
        raise ValueError("deduplicate_events requires real trading session_index")
    e = events.sort_values(["code", "event_type", "detection_at"]).copy()
    keep = []
    for _, group in e.groupby(["code", "event_type"], sort=False):
        last_session = None
        for idx, row in group.iterrows():
            session = int(row["session_index"])
            if last_session is None or session - last_session > cluster_sessions:
                keep.append(idx)
                last_session = session
    return e.loc[keep].sort_values("detection_at").reset_index(drop=True)


def event_path_metrics(prices: pd.DataFrame, event_date: str, horizons=PRIMARY_HORIZONS) -> dict:
    """价格帧需含close/high/low；事件收盘为基准，之后交易行严格向前。"""
    p = prices.sort_index()
    loc = p.index.searchsorted(pd.Timestamp(event_date))
    if loc >= len(p) or pd.Timestamp(p.index[loc]).date() != pd.Timestamp(event_date).date():
        return {"status": "unknown", "reason": "event_session_missing"}
    base = float(p.iloc[loc]["close"])
    future = p.iloc[loc + 1: loc + max(horizons) + 1]
    out = {"status": "ok", "base_close": base,
           "mfe": float(future["high"].max() / base - 1) if len(future) else None,
           "mae": float(future["low"].min() / base - 1) if len(future) else None}
    for h in horizons:
        out[f"return_{h}d"] = (float(future.iloc[h - 1]["close"] / base - 1)
                                if len(future) >= h else None)
    return out


def distribution_summary(values: pd.Series) -> dict:
    x = pd.to_numeric(values, errors="coerce").dropna()
    if x.empty:
        return {"n": 0}
    total_positive = float(x.clip(lower=0).sum())
    threshold = float(x.quantile(.9))
    tail = float(x[x >= threshold].clip(lower=0).sum())
    return {"n": len(x), "mean": float(x.mean()), "median": float(x.median()),
            "p10": float(x.quantile(.1)), "p90": threshold,
            "positive_rate": float((x > 0).mean()),
            "top_decile_positive_contribution": (tail / total_positive
                                                   if total_positive > 0 else None)}
