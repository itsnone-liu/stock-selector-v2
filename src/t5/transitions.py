"""T5.3 状态转移构建（raw_state_v1 只读，不重算）。

纪律（任务书 §一/§五/§六/§七）：
- raw state 来自 af2dac7 冻结产品 t5_candidate_state_daily.parquet，
  本模块禁止重新赋值 C0–C6；
- 每个 origin 行恰有一条 1d destination；末行显式 TERMINAL
  （T5.1 冻结 termination_reason：LIFECYCLE_END / MAX_HORIZON，
  DATA_END 在 T5.1 实测为 0，不凭空造 "STRUCTURE_END"）；
- t→t+k（k=3,5）若 t+k 越过事件末行：destination = 该事件真实
  terminal reason（分母守恒，不记 missing）；
- dest_type ∈ {STATE, OBS_UNAVAILABLE, TERMINAL}；
  STATE_UNAVAILABLE 是 observation eligibility，绝不并入 C 态归一。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TERMINAL_PREFIX = "TERMINAL_"
DEST_TYPES = ("STATE", "OBS_UNAVAILABLE", "TERMINAL")


def build_edges(cs: pd.DataFrame, st_term: pd.DataFrame,
                horizons=(1, 3, 5)) -> pd.DataFrame:
    """cs: candidate_state_daily（含 final_candidate_state/state_reason）。
    st_term: state 表 (event_id, delta_day, termination_reason)。
    返回长表：每 origin 行 × 每 horizon 一条边。"""
    df = cs[["event_id", "delta_day", "final_candidate_state",
             "state_assignable"]].merge(
        st_term, on=["event_id", "delta_day"], how="left")
    by_ev = {eid: g.sort_values("delta_day") for eid, g in df.groupby(
        "event_id")}
    rows = []
    for eid, g in by_ev.items():
        deltas = g["delta_day"].to_numpy()
        states = g["final_candidate_state"].to_numpy()
        terms = g["termination_reason"].to_numpy()
        last = len(g) - 1
        term_reason = None
        for t_ in terms:
            if isinstance(t_, str) and t_:
                term_reason = t_
                break
        for i in range(len(g)):
            raw_t = states[i]
            for k in horizons:
                j = i + k
                if j <= last:
                    dest_state = states[j]
                    if dest_state == "STATE_UNAVAILABLE":
                        dt, dl = "OBS_UNAVAILABLE", "STATE_UNAVAILABLE"
                    else:
                        dt, dl = "STATE", dest_state
                else:
                    dt = "TERMINAL"
                    dl = TERMINAL_PREFIX + (term_reason or "UNKNOWN")
                rows.append({
                    "event_id": eid, "delta_day": int(deltas[i]),
                    "raw_state_t": raw_t,
                    "sparse_evidence": bool(raw_t == "C2"),
                    "state_assignable": bool(g["state_assignable"]
                                             .iloc[i]),
                    "horizon_k": k,
                    "dest_type": dt, "dest_label": dl,
                    "dest_is_last_row": bool(j >= last),
                })
    return pd.DataFrame(rows)


def transition_matrix(edges: pd.DataFrame, k: int,
                      origin_filter="assignable") -> pd.DataFrame:
    """1d/3d/5d 转移矩阵：origin=C0–C6（assignable），dest 全类。
    返回 counts + row-normalized 概率 + 守恒校验列。"""
    e = edges[(edges.horizon_k == k)]
    if origin_filter == "assignable":
        e = e[e.state_assignable.astype(bool)
              & (e.raw_state_t != "STATE_UNAVAILABLE")]
    m = (e.groupby(["raw_state_t", "dest_label"]).size()
         .rename("n").reset_index())
    tot = (e.groupby("raw_state_t").size().rename("n_total").reset_index())
    m = m.merge(tot, on="raw_state_t")
    m["p"] = m["n"] / m["n_total"]
    # 守恒：state + unavailable + terminal == total（分组和应等于 n_total）
    chk = m.groupby("raw_state_t").agg(
        sum_n=("n", "sum"), n_total=("n_total", "first"))
    m["conserved"] = m["raw_state_t"].map(
        (chk.sum_n == chk.n_total).to_dict())
    return m


def state_runs(cs: pd.DataFrame) -> pd.DataFrame:
    """连续相同 raw state 段（含 UNAVAILABLE 段，报告时分开）。"""
    cs = cs.sort_values(["event_id", "delta_day"])
    sh = cs.groupby("event_id")["final_candidate_state"]
    prev = sh.shift(1)
    is_new = (cs["final_candidate_state"] != prev) | prev.isna()
    cs = cs.assign(run_local=is_new.cumsum())
    g = cs.groupby(["event_id", "run_local"])
    runs = g.agg(
        state=("final_candidate_state", "first"),
        start_delta=("delta_day", "min"),
        end_delta=("delta_day", "max"),
        n=("delta_day", "size"),
        segment=("segment", "first"),
        exposure_class=("exposure_class", "first"),
    ).reset_index()
    runs["dwell_market_days"] = runs["end_delta"] - runs["start_delta"] + 1
    # entry/exit（事件内前后段的 state）
    runs = runs.sort_values(["event_id", "run_local"]).reset_index(
        drop=True)
    runs["entry_from_state"] = runs.groupby("event_id")[
        "state"].shift(1)
    runs["exit_to_state"] = runs.groupby("event_id")[
        "state"].shift(-1)
    return runs


def one_day_reversal(cs: pd.DataFrame) -> pd.DataFrame:
    """S[t-1]=S[t+1] 且 S[t]!=S[t-1]（冻结定义，任务书 §十）。"""
    cs = cs.sort_values(["event_id", "delta_day"]).reset_index(drop=True)
    s = cs["final_candidate_state"]
    prev = cs.groupby("event_id")["final_candidate_state"].shift(1)
    nxt = cs.groupby("event_id")["final_state_next"] if False else None
    nxt = cs.groupby("event_id")["final_candidate_state"].shift(-1)
    rev = (prev.notna() & nxt.notna() & (prev == nxt) & (s != prev))
    out = cs[["event_id", "delta_day", "final_candidate_state"]].copy()
    out["one_day_reversal"] = rev.fillna(False)
    out["prev_state"] = prev
    out["next_state"] = nxt
    return out
