"""正负结果对比：事件抽样、路径标注、分层汇总与分块不确定性。

分析层只消费冻结信号/结果，不修改准入规则。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from stock_selector.research.path_classification import outcome_bucket, price_path


HORIZONS = (1, 2, 3, 5, 10, 15, 20)


def nonoverlapping_events(events: pd.DataFrame, horizon: int,
                          trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """按(code, signal_type)贪心保留至少相隔h个市场交易日的首次事件。"""
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    calendar = pd.DatetimeIndex(trading_days).sort_values().unique()
    position = {pd.Timestamp(d).normalize(): i for i, d in enumerate(calendar)}
    kept = []
    for _, g in events.sort_values("first_trigger_date").groupby(["code", "signal_type"], sort=False):
        last_pos = None
        for idx, r in g.iterrows():
            pos = position.get(pd.Timestamp(r["first_trigger_date"]).normalize())
            if pos is None:
                continue
            if last_pos is None or pos - last_pos >= horizon:
                kept.append(idx); last_pos = pos
    return events.loc[kept].copy().reset_index(drop=True)


def label_contrast_rows(df: pd.DataFrame, horizons=HORIZONS, *, delta: float = .002,
                        meaningful_mfe: float = .03, deep_mae: float = .04,
                        excess_prefix: str = "industry_excess") -> pd.DataFrame:
    out = df.copy()
    for h in horizons:
        fwd, mfe, mae = f"fwd{h}", f"mfe{h}_full", f"mae{h}_full"
        excess = f"{excess_prefix}{h}"
        if fwd not in out:
            continue
        out[f"result_{h}"] = [outcome_bucket(x if pd.notna(x) else None, delta)
                              for x in out.get(excess, out[fwd])]
        early_col = "fwd1" if h > 1 and "fwd1" in out else fwd
        mfe_values = out[mfe] if mfe in out else pd.Series(np.nan, index=out.index)
        mae_values = out[mae] if mae in out else pd.Series(np.nan, index=out.index)
        out[f"path_{h}"] = [
            price_path(fr if pd.notna(fr) else None,
                       er if pd.notna(er) else None,
                       mf if pd.notna(mf) else None,
                       ma if pd.notna(ma) else None,
                       positive_delta=delta, meaningful_mfe=meaningful_mfe, deep_mae=deep_mae)
            for fr, er, mf, ma in zip(out[fwd], out[early_col], mfe_values, mae_values)
        ]
    return out


def grouped_contrast(df: pd.DataFrame, group_cols: list[str], horizons=HORIZONS) -> pd.DataFrame:
    rows = []
    for key, g in df.groupby(group_cols, dropna=False):
        keys = key if isinstance(key, tuple) else (key,)
        base = dict(zip(group_cols, keys))
        for h in horizons:
            col = f"fwd{h}"
            if col not in g:
                continue
            v = pd.to_numeric(g[col], errors="coerce").dropna()
            row = {**base, "horizon": h, "events": len(g), "effective_n": len(v),
                   "stocks": g["code"].nunique() if "code" in g else None,
                   "dates": g["first_trigger_date"].nunique() if "first_trigger_date" in g else None,
                   "median": v.median() if len(v) else None,
                   "mean": v.mean() if len(v) else None,
                   "positive_rate": (v > 0).mean() if len(v) else None}
            result_col, path_col = f"result_{h}", f"path_{h}"
            if result_col in g:
                for name, n in g[result_col].value_counts(dropna=False).items():
                    row[f"result_{name}_n"] = int(n)
            if path_col in g:
                for name, n in g[path_col].value_counts(dropna=False).items():
                    row[f"path_{name}_n"] = int(n)
            rows.append(row)
    return pd.DataFrame(rows)


def block_bootstrap_median_diff(df: pd.DataFrame, value_col: str, treatment_col: str,
                                *, block_col: str, iterations: int = 500,
                                seed: int = 20260917) -> dict:
    """按股票或日期整块有放回抽样，估计处理组-对照组中位数差CI。"""
    valid = df.dropna(subset=[value_col, treatment_col, block_col])
    blocks = valid[block_col].unique()
    if len(blocks) < 2:
        return {"estimate": None, "ci_low": None, "ci_high": None, "blocks": len(blocks)}
    def diff(x):
        a = x[x[treatment_col].astype(bool)][value_col]
        b = x[~x[treatment_col].astype(bool)][value_col]
        return float(a.median() - b.median()) if len(a) and len(b) else np.nan
    estimate = diff(valid)
    rng = np.random.default_rng(seed)
    samples = []
    grouped = {b: valid[valid[block_col] == b] for b in blocks}
    for _ in range(iterations):
        draw = rng.choice(blocks, size=len(blocks), replace=True)
        x = pd.concat([grouped[b] for b in draw], ignore_index=True)
        samples.append(diff(x))
    arr = np.asarray(samples, dtype=float); arr = arr[~np.isnan(arr)]
    return {"estimate": estimate,
            "ci_low": float(np.quantile(arr, .025)) if len(arr) else None,
            "ci_high": float(np.quantile(arr, .975)) if len(arr) else None,
            "blocks": len(blocks), "iterations": iterations}
