"""事前可见背景与持有期实际冲击；两者禁止混列。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def attach_pre_context(events: pd.DataFrame, daily_context: pd.DataFrame,
                       *, value_columns: tuple[str, ...]) -> pd.DataFrame:
    """按事件日关联PIT可见背景，统一加pre_context_前缀。"""
    ctx = daily_context[["date", *value_columns]].copy()
    ctx["date"] = pd.to_datetime(ctx["date"]).dt.date.astype(str)
    if ctx["date"].duplicated().any():
        raise ValueError("daily_context must be unique by date")
    ctx = ctx.rename(columns={c: f"pre_context_{c}" for c in value_columns})
    left = events.copy(); left["date"] = pd.to_datetime(left["date"]).dt.date.astype(str)
    return left.merge(ctx, on="date", how="left", validate="many_to_one")


def holding_context_metrics(events: pd.DataFrame, daily_context: pd.DataFrame,
                            *, value_col: str, horizon: int) -> pd.DataFrame:
    """聚合事件后t+1..t+h实际背景；只用于事后路径解释。"""
    ctx = daily_context[["date", value_col]].copy().sort_values("date")
    ctx["date"] = pd.to_datetime(ctx["date"])
    values = pd.to_numeric(ctx[value_col], errors="coerce").to_numpy()
    dates = pd.DatetimeIndex(ctx["date"])
    rows = []
    for _, r in events.iterrows():
        d = pd.Timestamp(r["date"]); pos = dates.searchsorted(d, side="right")
        window = values[pos:pos + horizon]
        valid = window[~np.isnan(window)]
        complete = len(window) == horizon and len(valid) == horizon
        rows.append({"code": r["code"], "date": d.date().isoformat(),
                     f"holding_context_{value_col}_h{horizon}_sum": float(valid.sum()) if complete else None,
                     f"holding_context_{value_col}_h{horizon}_min": float(valid.min()) if complete else None,
                     f"holding_context_{value_col}_h{horizon}_n": int(len(valid)),
                     f"holding_context_{value_col}_h{horizon}_complete": complete})
    return pd.DataFrame(rows)
