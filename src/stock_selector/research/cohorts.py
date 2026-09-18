"""月→周→日递进研究总体与对照构造。

只派生研究标签，不改写任何个股信号。unknown永不进入明确失败对照。
"""
from __future__ import annotations

import pandas as pd

DAILY_SIGNALS = ("sv_legacy", "td_legacy")


def attach_daily_trigger(panel: pd.DataFrame,
                         signal_columns: tuple[str, ...] = DAILY_SIGNALS) -> pd.DataFrame:
    """日线触发三态：任一明确真=triggered；全部明确假=not_triggered；
    无真但存在未知（含部分未知）=unknown。触发是两标签的或，未知不得压成未触发。"""
    out = panel.copy()
    vals = out[list(signal_columns)]
    any_true = vals.fillna(False).astype(bool).any(axis=1)
    all_known_false = vals.notna().all(axis=1) & ~any_true
    out["daily_trigger_state"] = "unknown"
    out.loc[all_known_false, "daily_trigger_state"] = "not_triggered"
    out.loc[any_true, "daily_trigger_state"] = "triggered"
    out["daily_trigger_type"] = vals.apply(
        lambda r: "+".join(c for c in signal_columns if pd.notna(r[c]) and bool(r[c])) or None,
        axis=1)
    return out


def daily_increment_cohort(panel: pd.DataFrame) -> pd.DataFrame:
    """对照A：月池内且周线eligible，日线明确触发 vs 明确未触发。"""
    x = attach_daily_trigger(panel)
    if "monthly_provisional_state" not in x:
        raise ValueError("panel requires monthly_provisional_state")
    monthly = x["monthly_provisional_state"]
    x = x[(monthly == True) & (x["weekly_eligibility_state"] == "eligible")].copy()  # noqa:E712
    x = x[x["daily_trigger_state"] != "unknown"]
    x["cohort"] = x["daily_trigger_state"]
    return x


def weekly_state_within_daily_shape(panel: pd.DataFrame) -> pd.DataFrame:
    """对照B：固定日线形态，分别保留三种明确周线状态。"""
    x = attach_daily_trigger(panel)
    x = x[x["daily_trigger_state"] == "triggered"].copy()
    x = x[x["weekly_eligibility_state"].isin(["eligible", "observation", "excluded"])]
    x["cohort"] = x["weekly_eligibility_state"]
    return x


def weekly_direct_cohort(panel: pd.DataFrame) -> pd.DataFrame:
    """对照C：月池内直接研究周动能/效率，不以日线触发为入样条件。"""
    x = attach_daily_trigger(panel)
    if "monthly_provisional_state" not in x:
        raise ValueError("panel requires monthly_provisional_state")
    monthly = x["monthly_provisional_state"]
    x = x[(monthly == True) & x["weekly_eligibility_state"].isin(
        ["eligible", "observation", "excluded"])].copy()  # noqa:E712
    x["cohort"] = x["weekly_eligibility_state"]
    return x


def nonoverlapping_anchors(rows: pd.DataFrame, horizon: int,
                           *, group_columns=("code", "cohort")) -> pd.DataFrame:
    """按真实session_index保留非重叠锚点；不回写信号。"""
    if "session_index" not in rows:
        raise ValueError("nonoverlapping_anchors requires session_index")
    keep = []
    for _, group in rows.sort_values([*group_columns, "session_index"]).groupby(
            list(group_columns), dropna=False, sort=False):
        last = None
        for idx, row in group.iterrows():
            session = int(row["session_index"])
            if last is None or session - last >= horizon:
                keep.append(idx); last = session
    return rows.loc[keep].sort_values(["date", "code"]).reset_index(drop=True)
