"""同月周日结构内的正负事前特征差异与描述性收益分解。

不改信号，不把持有期信息当作事前预测变量，不声称因果归因。
"""
from __future__ import annotations

import pandas as pd

# spell_id仅是单股区间标识，不能作为跨股票结构分组；结构使用池龄。
STRUCTURE_COLUMNS = ("monthly_pool_spell_age", "weekly_base_pattern",
                     "weekly_weekday_path", "weekly_eligibility_state",
                     "daily_trigger_type")


def label_absolute_and_relative_outcomes(events: pd.DataFrame, horizon: int,
                                         neutral_band: float = .002) -> pd.DataFrame:
    out = events.copy()
    fwd, market, industry = f"fwd{horizon}", f"market_fwd{horizon}", f"industry_fwd{horizon}"
    if not {fwd, market, industry} <= set(out):
        raise ValueError("missing raw/market/industry forward outcome columns")
    def bucket(v):
        if pd.isna(v): return "unknown"
        return "positive" if v > neutral_band else "negative" if v < -neutral_band else "neutral"
    out[f"absolute_result_{horizon}"] = out[fwd].map(bucket)
    out[f"market_relative_result_{horizon}"] = (out[fwd] - out[market]).map(bucket)
    out[f"industry_relative_result_{horizon}"] = (out[fwd] - out[industry]).map(bucket)
    # 逐事件恒等式；汇总时不得宣称分项中位数相加。
    out[f"component_market_{horizon}"] = out[market]
    out[f"component_industry_vs_market_{horizon}"] = out[industry] - out[market]
    out[f"component_stock_vs_industry_{horizon}"] = out[fwd] - out[industry]
    return out


def within_structure_feature_contrast(events: pd.DataFrame, *, horizon: int,
                                      feature_columns: list[str],
                                      structure_columns: tuple[str, ...] = STRUCTURE_COLUMNS) -> pd.DataFrame:
    """同结构内绝对正/负组的事前特征分布及效应大小。"""
    leaked = [c for c in feature_columns if c.startswith("holding_context_")]
    if leaked:
        raise ValueError(f"holding-period context cannot be used as pre-signal features: {leaked}")
    label = f"absolute_result_{horizon}"
    if label not in events:
        events = label_absolute_and_relative_outcomes(events, horizon)
    groups = [c for c in structure_columns if c in events]
    rows = []
    for key, g in events.groupby(groups, dropna=False, sort=False):
        keys = key if isinstance(key, tuple) else (key,)
        base = dict(zip(groups, keys))
        for feature in feature_columns:
            pos = pd.to_numeric(g.loc[g[label] == "positive", feature], errors="coerce").dropna()
            neg = pd.to_numeric(g.loc[g[label] == "negative", feature], errors="coerce").dropna()
            rows.append({**base, "feature": feature, "positive_n": len(pos), "negative_n": len(neg),
                         "positive_median": pos.median() if len(pos) else None,
                         "negative_median": neg.median() if len(neg) else None,
                         "median_difference": (pos.median() - neg.median()) if len(pos) and len(neg) else None,
                         "positive_missing_rate": 1 - len(pos) / max(1, int((g[label] == "positive").sum())),
                         "negative_missing_rate": 1 - len(neg) / max(1, int((g[label] == "negative").sum()))})
    return pd.DataFrame(rows)


def component_means(events: pd.DataFrame, horizon: int,
                    group_columns: list[str]) -> pd.DataFrame:
    """同一事件集合上的均值分解；均值可加，中位数不作加总。"""
    x = label_absolute_and_relative_outcomes(events, horizon)
    cols = [f"component_market_{horizon}", f"component_industry_vs_market_{horizon}",
            f"component_stock_vs_industry_{horizon}", f"fwd{horizon}"]
    return x.groupby(group_columns, dropna=False)[cols].agg(["size", "mean", "median"])
