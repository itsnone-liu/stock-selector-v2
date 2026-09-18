"""递进研究对照定义；生成设计矩阵，不执行收益裁决。"""
from __future__ import annotations

import pandas as pd

from stock_selector.research.cohorts import (daily_increment_cohort,
                                             nonoverlapping_anchors,
                                             weekly_direct_cohort,
                                             weekly_state_within_daily_shape)


def build_progressive_comparisons(panel: pd.DataFrame, horizons=(1, 2, 3, 5, 10, 15, 20)) -> dict[str, pd.DataFrame]:
    """输出三个理论问题的全部状态日与逐期限非重叠样本。"""
    bases = {
        "daily_increment_within_monthly_weekly": daily_increment_cohort(panel),
        "weekly_state_within_daily_shape": weekly_state_within_daily_shape(panel),
        "weekly_direct_within_monthly": weekly_direct_cohort(panel),
    }
    out = {}
    for name, base in bases.items():
        out[f"{name}__all"] = base
        for h in horizons:
            groups = ("code", "cohort")
            if name == "weekly_state_within_daily_shape":
                groups = ("code", "daily_trigger_type", "cohort")
            out[f"{name}__nonoverlap_h{h}"] = nonoverlapping_anchors(
                base, h, group_columns=groups)
    return out
