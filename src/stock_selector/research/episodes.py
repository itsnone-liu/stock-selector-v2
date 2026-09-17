"""将冻结的每日信号状态表折叠为事件表。

只做计数去重，不使用未来收益，也不改变每日信号。
"""
from __future__ import annotations

import pandas as pd


INACTIVE = {False, 0, "0", "none", "observation", "excluded"}
UNKNOWN = {None, "unknown", "u"}


def build_episode_panel(panel: pd.DataFrame, signal_columns: tuple[str, ...] = ("sv_legacy", "td_legacy")) -> pd.DataFrame:
    required = {"code", "date", *signal_columns}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"panel missing columns: {sorted(missing)}")
    rows: list[dict] = []
    for code, group in panel.sort_values(["code", "date"]).groupby("code", sort=False):
        for signal in signal_columns:
            current = None
            ordinal = 0
            for _, r in group.iterrows():
                value = r[signal]
                unknown = pd.isna(value) or value in UNKNOWN
                active = False if unknown else value not in INACTIVE
                day = r["date"]
                if unknown:
                    # unknown不结束已存在事件，也不计确认天数。
                    continue
                if active:
                    if current is None:
                        ordinal += 1
                        current = {
                            "episode_id": f"{code}_{signal}_{ordinal}", "code": code,
                            "signal_type": signal, "first_trigger_date": day,
                            "last_trigger_date": day, "consecutive_confirmations": 1,
                            "end_date": None, "end_reason": None,
                        }
                    else:
                        current["last_trigger_date"] = day
                        current["consecutive_confirmations"] += 1
                elif current is not None:
                    current["end_date"] = day
                    current["end_reason"] = "signal_inactive"
                    rows.append(current)
                    current = None
            if current is not None:
                rows.append(current)
    return pd.DataFrame(rows)
