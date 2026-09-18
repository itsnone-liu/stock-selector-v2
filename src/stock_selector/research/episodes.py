"""将冻结状态表折叠为两类事件。

- 形态事件：日线标签自身连续成立；
- 策略事件：月线在池、周线eligible、日线触发首次同时成立。
unknown不结束已存在事件，但会把边界标记为不确定；明确out/非eligible/未触发才结束。
"""
from __future__ import annotations

import pandas as pd

INACTIVE = {False, 0, "0", "none", "observation", "excluded"}
UNKNOWN = {None, "unknown", "u"}


def build_episode_panel(panel: pd.DataFrame,
                        signal_columns: tuple[str, ...] = ("sv_legacy", "td_legacy")) -> pd.DataFrame:
    """兼容入口：构建日线形态事件。"""
    required = {"code", "date", *signal_columns}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"panel missing columns: {sorted(missing)}")
    rows: list[dict] = []
    for code, group in panel.sort_values(["code", "date"]).groupby("code", sort=False):
        for signal in signal_columns:
            current = None
            ordinal = 0
            uncertain = False
            for _, r in group.iterrows():
                value = r[signal]
                unknown = pd.isna(value) or value in UNKNOWN
                active = False if unknown else value not in INACTIVE
                day = r["date"]
                if unknown:
                    if current is not None:
                        uncertain = True
                    continue
                if active:
                    if current is None:
                        ordinal += 1
                        current = {"episode_id": f"{code}_{signal}_{ordinal}", "code": code,
                                   "signal_type": signal, "first_trigger_date": day,
                                   "last_trigger_date": day, "consecutive_confirmations": 1,
                                   "end_date": None, "end_reason": None,
                                   "boundary_uncertain": False}
                        uncertain = False
                    else:
                        current["last_trigger_date"] = day
                        current["consecutive_confirmations"] += 1
                        current["boundary_uncertain"] = uncertain
                elif current is not None:
                    current["end_date"] = day
                    current["end_reason"] = "signal_inactive"
                    current["boundary_uncertain"] = uncertain
                    rows.append(current); current = None; uncertain = False
            if current is not None:
                current["boundary_uncertain"] = uncertain
                rows.append(current)
    columns = ["episode_id", "code", "signal_type", "first_trigger_date",
               "last_trigger_date", "consecutive_confirmations", "end_date", "end_reason",
               "boundary_uncertain"]
    return pd.DataFrame(rows, columns=columns)


def build_strategy_episode_panel(signal_panel: pd.DataFrame,
                                 universe_state: pd.DataFrame,
                                 signal_columns: tuple[str, ...] = ("sv_legacy", "td_legacy")) -> pd.DataFrame:
    """构建完整策略条件首次同时成立的事件，不把事件结束解释为卖出。"""
    required_sig = {"code", "date", "weekly_eligibility_state", *signal_columns}
    required_uni = {"code", "date", "monthly_pool_state", "monthly_pool_spell_id", "data_status"}
    if required_sig - set(signal_panel) or required_uni - set(universe_state):
        raise ValueError("signal/universe panel missing strategy episode columns")
    left = universe_state.copy()
    left["code"] = left["code"].astype(str).str.zfill(6)
    sig = signal_panel[list(required_sig)].copy()
    sig["code"] = sig["code"].astype(str).str.zfill(6)
    x = left.merge(sig, on=["code", "date"], how="left", validate="one_to_one")
    rows = []
    for code, group in x.sort_values(["code", "date"]).groupby("code", sort=False):
        for signal in signal_columns:
            current = None; ordinal = 0; uncertain = False
            for _, r in group.iterrows():
                pool = r["monthly_pool_state"]
                weekly = r["weekly_eligibility_state"]
                value = r[signal]
                # 明确出池优先于因右表缺行造成的weekly/signal NaN；out不是unknown。
                explicit_pool_exit = pool == "out"
                unknown = (pool == "unknown" or
                           (pool == "in" and (pd.isna(weekly) or weekly == "unknown"
                                              or pd.isna(value) or value in UNKNOWN)))
                active = pool == "in" and weekly == "eligible" and bool(value) and not unknown
                day = r["date"]
                if explicit_pool_exit:
                    if current is not None:
                        current.update(end_date=day, end_reason="monthly_pool_exit",
                                       boundary_uncertain=uncertain)
                        rows.append(current); current = None; uncertain = False
                    continue
                if unknown:
                    if current is not None: uncertain = True
                    continue
                if active:
                    if current is None:
                        ordinal += 1
                        current = {"episode_id": f"{code}_strategy_{signal}_{ordinal}", "code": code,
                                   "signal_type": signal, "first_trigger_date": day,
                                   "last_trigger_date": day, "consecutive_confirmations": 1,
                                   "monthly_pool_spell_id": r["monthly_pool_spell_id"],
                                   "end_date": None, "end_reason": None, "boundary_uncertain": False}
                        uncertain = False
                    else:
                        current["last_trigger_date"] = day
                        current["consecutive_confirmations"] += 1
                        current["boundary_uncertain"] = uncertain
                elif current is not None:
                    if pool == "out": reason = "monthly_pool_exit"
                    elif weekly != "eligible": reason = "weekly_not_eligible"
                    else: reason = "daily_signal_inactive"
                    current.update(end_date=day, end_reason=reason, boundary_uncertain=uncertain)
                    rows.append(current); current = None; uncertain = False
            if current is not None:
                current["boundary_uncertain"] = uncertain; rows.append(current)
    columns = ["episode_id", "code", "signal_type", "first_trigger_date", "last_trigger_date",
               "consecutive_confirmations", "monthly_pool_spell_id", "end_date", "end_reason",
               "boundary_uncertain"]
    return pd.DataFrame(rows, columns=columns)
