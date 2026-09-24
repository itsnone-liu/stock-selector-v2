#!/usr/bin/env python3
"""T5.3 operational state 治理候选（若采用）。

证据基础（t5_churn_audit，dev 2024+全样本）：
- C1 dwell=1 段的 98.0% 由次日 is_new_high_20d 布尔关闭导致
  （机械闪烁，非结构变化）；
- one-day reversal 10.4% vs any-change 38.3%（真实转移占主导）。

candidate_v1（Hysteresis，PIT：只读 <=t 的 raw 状态与当日证据）：
- C6 立即生效（§十五）：raw C6 -> operational C6 当日，无确认延迟；
- C1 hold：昨为 operational C1 且今日 raw ∈ {C0,C1} 且
  当日 dd <= delta-q75 且 dist_to_ref20 >= 0 -> 保持 C1；
  否则透传今日 raw（C2/C3/C4/C5/C6/C0 均为明确反向或独立信号）；
- 其余状态全部透传（零延迟）。

candidate_v2（对照，预期否决）：v1 + C5 需连续 2 日 raw C5 确认
（Confirmation 机制；报告 recognition_delay 成本）。

评价仅用状态工程质量指标（§十六）：reversal rate / median dwell /
switch count / semantic consistency / coverage / delay。
不读取任何 outcome 表。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))

OUT = ROOT / "output/research/t5/transition"
STATE = ROOT / "output/research/t5/state"

Q75 = "q75"   # dd 的 delta-conditioned q75（与 raw C2 阈值同源）


def load_devq():
    d = json.loads((STATE / "t5_state_definition.json").read_text())
    return d["dev_quantiles"]["drawdown_from_peak_log"]


def assign_operational(cs: pd.DataFrame, dq, version: str):
    """逐事件顺序扫描（PIT）。cs 需含 ev_ 证据列。"""
    cs = cs.sort_values(["event_id", "delta_day"]).reset_index(drop=True)
    op = cs["final_candidate_state"].tolist()
    evs = cs.to_dict("records")
    prev_idx = None
    hold_c1 = False
    c5_run = 0
    out = []
    last_eid = None
    prev_raw = None
    for i, r in enumerate(evs):
        eid = r["event_id"]
        if eid != last_eid:
            hold_c1, c5_run, last_eid = False, 0, eid
            prev_raw = None
        raw = r["final_candidate_state"]
        if r["state_assignable"] is False or r[
                "state_assignable"] is np.False_ or not bool(
                    r["state_assignable"]):
            out.append(raw)      # STATE_UNAVAILABLE 透传（obs 层）
            hold_c1 = False
            c5_run = 0
            continue
        d = str(int(r["delta_day"]))
        dd = r.get("ev_drawdown_from_peak_log")
        dist20 = r.get("ev_dist_to_ref20")
        thr = dq.get(d, {}).get(Q75)
        # --- v1 核心：C1 hysteresis ---
        if version == "v1":
            if raw == "C1":
                out.append("C1")
                hold_c1 = True
            elif (hold_c1 and raw in ("C0",)
                  and dd is not None and thr is not None
                  and dist20 is not None
                  and dd <= thr and dist20 >= 0):
                out.append("C1")          # hold：结构完整+损伤未扩
            else:
                out.append(raw)
                hold_c1 = (raw == "C1")
        # --- v2：v1 + C5 confirmation（对照，报告延迟成本）---
        else:
            if raw == "C5":
                c5_run += 1
                out.append("C5" if c5_run >= 2 else (
                    prev_raw if prev_raw is not None else "C0"))
            else:
                c5_run = 0
                if raw == "C1":
                    out.append("C1")
                    hold_c1 = True
                elif (hold_c1 and raw in ("C0",)
                      and dd is not None and thr is not None
                      and dist20 is not None
                      and dd <= thr and dist20 >= 0):
                    out.append("C1")
                else:
                    out.append(raw)
                    hold_c1 = (raw == "C1")
        prev_raw = raw
    cs = cs.copy()
    cs[f"operational_state_{version}"] = out
    return cs


def state_engineering_metrics(cs, col):
    s = cs[col]
    prev = cs.groupby("event_id")[col].shift(1)
    nxt = cs.groupby("event_id")[col].shift(-1)
    change = prev.notna() & (prev != s)
    rev = (prev.notna() & nxt.notna() & (prev == nxt) & (s != prev))
    # dwell（中位）
    is_new = (s != prev) | prev.isna()
    rid = is_new.cumsum()
    dwell = cs.groupby(rid)[col].agg(["first", "size"])
    return {
        "one_day_reversal_rate": float(rev.mean()),
        "any_change_rate": float(change.mean()),
        "median_dwell_C1": float(dwell[dwell["first"] == "C1"][
            "size"].median()),
        "median_dwell_all": float(dwell["size"].median()),
        "n_C1": int((s == "C1").sum()),
        "switch_count": int(change.sum()),
    }


def main():
    cs = pd.read_parquet(STATE / "t5_candidate_state_daily.parquet")
    dq = load_devq()
    res = {}
    for v in ("v1", "v2"):
        out = assign_operational(cs, dq, v)
        keep = ["event_id", "delta_day", "final_candidate_state",
                f"operational_state_{v}", "segment",
                "state_assignable", "ev_drawdown_from_peak_log",
                "ev_dist_to_ref20"]
        out[keep].to_parquet(
            OUT / f"t5_operational_state_daily_{v}.parquet",
            index=False)
        m = state_engineering_metrics(out, f"operational_state_{v}")
        res[v] = m
        print(v, json.dumps(m, indent=1))
    base = state_engineering_metrics(
        cs.rename(columns={"final_candidate_state": "raw"}), "raw")
    print("raw", json.dumps(base, indent=1))
    res["raw"] = base
    defn = {
        "code_version": "t5_3_operational_candidate_v1",
        "mechanism": "hysteresis(C1) + immediate C6; all other raw "
                     "states pass through with zero delay",
        "c1_hold_rule": ("prev operational==C1 and raw in {C0} and "
                         "dd<=delta_q75 and dist_to_ref20>=0 -> stay "
                         "C1 (PIT: only <=t info)"),
        "c6_rule": "raw C6 -> operational C6 same day (mandatory "
                   "immediate, sec.15)",
        "v2_extra": "C5 requires 2 consecutive raw C5 (confirmation; "
                    "reported as delay-cost contrast, expected reject)",
        "evaluation": "state-engineering metrics only; no outcome "
                      "access (AST-gated)",
        "metrics": res,
    }
    (OUT / "t5_operational_state_definition.json").write_text(
        json.dumps(defn, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
