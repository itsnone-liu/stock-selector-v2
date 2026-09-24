#!/usr/bin/env python3
"""T5.2 全量赋值 + 三段隔离 + 产品落盘。

三段（任务书 §五/§六）：
  Development  = breakout_year 2024（规则/阈值已在此生成并冻结）
  Validation   = breakout_year 2025，前置 40 市场日 purge
  Confirmation = breakout_year 2026，前置 40 市场日 purge
purge 从冻结指数日历计算：前段事件最大 state_date + 40 市场日之后，
后段首个 state_date 才允许进入（事件级检查，非行级截断——事件整段
归属其 breakout_year，purge 检查的是跨段观察窗不重叠的边界日期）。
本脚本不读取 outcome（评价在 run_t5_2_validation.py）。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from t5.state_assign import load_definition, STATE_UNAVAILABLE  # noqa

OUT = ROOT / "output/research/t5/state"
FACTS = ROOT / "output/research/t5/facts"
PURGE_DAYS = 40


def market_calendar():
    import struct
    b = (Path("/root/tdx_data/vipdoc/sh/lday/sh999999.day")
         .read_bytes())
    ds = []
    for i in range(len(b) // 32):
        u = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        ds.append(f"{u // 10000}-{u // 100 % 100:02d}-{u % 100:02d}")
    return ds


def main():
    t0 = time.time()
    st = pd.read_parquet(FACTS / "t5_daily_state.parquet")
    defs = {}
    assigners = {}
    for v in ("v1", "v2"):
        assigners[v] = load_definition(
            OUT / f"t5_state_definition_{v}.json")
        defs[v] = json.loads(
            (OUT / f"t5_state_definition_{v}.json").read_text())

    # ---------- 三段 + purge（split manifest 机器可审计） ----------
    mdates = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    st["year_s"] = st["year"].astype(str)
    ev_last = st.groupby("event_id")["state_date"].max()
    ev_year = st.drop_duplicates("event_id").set_index("event_id")["year_s"]
    ev_first = st.groupby("event_id")["state_date"].min()

    def seg_bounds(prev_year, next_year):
        """后段首行须 > 前段最大 state_date + 40 市场日。"""
        prev_ids = ev_year[ev_year == prev_year].index
        if not len(prev_ids):
            return None, None, 0, 0
        last_d = max(ev_last[i] for i in prev_ids)
        li = mpos[last_d]
        cutoff = mdates[min(li + PURGE_DAYS, len(mdates) - 1)]
        next_ids = ev_year[ev_year == next_year].index
        viol = sum(1 for i in next_ids if ev_first[i] <= cutoff)
        return cutoff, last_d, len(next_ids), viol

    cut_25, last_24, n_25, viol_25 = seg_bounds("2024", "2025")
    cut_26, last_25, n_26, viol_26 = seg_bounds("2025", "2026")
    split = {
        "development": {"year": "2024",
                        "n_events": int((ev_year == "2024").sum()),
                        "n_rows": int((st.year_s == "2024").sum())},
        "validation": {"year": "2025", "purge_after_dev":
                       {"last_dev_state_date": last_24,
                        "purge_market_days": PURGE_DAYS,
                        "cutoff_date": cut_25},
                       "n_events": n_25,
                       "n_rows": int((st.year_s == "2025").sum()),
                       "events_violating_purge": viol_25},
        "confirmation": {"year": "2026", "partial_year": True,
                         "purge_after_val":
                         {"last_val_state_date": last_25,
                          "purge_market_days": PURGE_DAYS,
                          "cutoff_date": cut_26},
                         "n_events": n_26,
                         "n_rows": int((st.year_s == "2026").sum()),
                         "events_violating_purge": viol_26},
        "purge_semantics": ("event-level ownership by breakout_year; "
                            "purge boundary = last prior-segment "
                            "state_date + 40 market days; violations "
                            "counted for audit (outcome windows of "
                            "prior segment cannot enter next segment "
                            "state dates only if boundary holds)"),
    }
    # horizon coverage（2026 部分年度披露）
    for y in ("2024", "2025", "2026"):
        seg = st[st.year_s == y]
        split[{"2024": "development", "2025": "validation",
               "2026": "confirmation"}[y]]["horizon_coverage"] = {
            "mean_rows_per_event": round(len(seg) / max(
                1, seg.event_id.nunique()), 2),
            "max_delta": int(seg.delta_day.max())}
    print("split:", {k: v.get("n_events") for k, v in split.items()
                     if isinstance(v, dict) and "n_events" in v},
          "violations:", viol_25, viol_26)

    # ---------- 赋值（v1 全量；v2 同数据对照） ----------
    st["segment"] = st["year_s"].map({
        "2024": "development", "2025": "validation",
        "2026": "confirmation"})
    results = {}
    for v, a in assigners.items():
        res = a.assign_frame(st)
        res = res.merge(st[["event_id", "delta_day", "segment",
                            "year_s", "exposure_class"]],
                        on=["event_id", "delta_day"], how="left")
        results[v] = res
        print(v, res.candidate_state.value_counts().to_dict(),
              f"{time.time() - t0:.0f}s")

    base = results["v1"].copy()
    base = base.rename(columns={"candidate_state": "candidate_state_v1"})
    base["candidate_state_v2"] = results["v2"]["candidate_state"].values
    base["final_candidate_state"] = base["candidate_state_v1"]
    base = base.rename(columns={"candidate_state_v1": "candidate_state_v1"})
    base.to_parquet(OUT / "t5_candidate_state_daily.parquet",
                    index=False)

    # ---------- 分布 / overlap / churn ----------
    cov = (base.groupby(["year_s", "delta_day", "exposure_class",
                         "candidate_state_v1"]).size()
           .rename("n").reset_index())
    cov.to_parquet(OUT / "t5_state_distribution.parquet", index=False)

    pv = base[["candidate_state_v1", "candidate_state_v2"]]
    ov = (pv.groupby(["candidate_state_v1", "candidate_state_v2"])
          .size().rename("n").reset_index())
    ov.to_parquet(OUT / "t5_state_rule_overlap.parquet", index=False)

    # 单规则命中（v1）：从 matched_rules 展开
    rows = []
    for code in assigners["v1"].priority:
        if code == "C0":
            continue
        n = int(base.matched_rules.fillna("").str.split("|")
                .apply(lambda xs: code in xs).sum())
        rows.append({"rule": code, "solo_or_in_matches": n})
    pd.DataFrame(rows).to_parquet(OUT / "t5_state_rule_hits.parquet",
                                  index=False)

    # churn / dwell（稳定性诊断）
    base_sorted = base.sort_values(["event_id", "delta_day"])
    sh = base_sorted.groupby("event_id")["candidate_state_v1"].shift(1)
    churn = (sh != base_sorted["candidate_state_v1"]) & sh.notna()
    churn_rate = float(churn.mean())
    dwell = []
    for eid, ser in base_sorted.groupby("event_id")[
            "candidate_state_v1"]:
        prev, run = None, 0
        for s in ser:
            if s == prev:
                run += 1
            else:
                if prev is not None:
                    dwell.append({"state": prev, "dwell": run})
                prev, run = s, 1
        dwell.append({"state": prev, "dwell": run})
    dw = pd.DataFrame(dwell)
    churn_tbl = (dw.groupby("state")["dwell"].agg(
        ["count", "median", "mean"]).reset_index())
    churn_tbl.insert(0, "metric", "dwell")
    churn_tbl["one_day_churn_rate_overall"] = churn_rate
    churn_tbl.to_parquet(OUT / "t5_state_churn_audit.parquet",
                         index=False)
    print("overall one-day churn rate %.4f" % churn_rate)
    print(churn_tbl.to_string(index=False))

    # 事件级 purge 标志：前段尾部事件（其 H10 outcome+40 市场日
    # 越入后段首个 state_date）在本段 outcome 评价中剔除；
    # 状态赋值/分布不受影响（G2 的对象是 outcome 使用）。
    purge_flag = {}
    for prev, nxt in (("2024", "2025"), ("2025", "2026")):
        prev_ids = ev_year[ev_year == prev].index
        if not len(prev_ids):
            continue
        nxt_first = min(ev_first[i] for i in
                        ev_year[ev_year == nxt].index)
        nf = mpos[nxt_first]
        cutoff = mdates[max(0, nf - PURGE_DAYS)]
        ci = mpos.get(cutoff, nf - PURGE_DAYS)
        flagged = [i for i in prev_ids if mpos.get(ev_last[i], 0) >=
                   nf - PURGE_DAYS - 10]
        for i in flagged:
            purge_flag[i] = True
        split[f"{prev}_events_outcome_purged"] = len(flagged)
    base["outcome_usable_after_purge"] = ~base["event_id"].isin(purge_flag)
    (OUT / "t5_2_split_manifest.json").write_text(json.dumps(
        split, indent=2, ensure_ascii=False))
    print("outcome-purged events:",
          {k: v for k, v in split.items() if "outcome_purged" in k})

    man = {
        "stage": "T5.2_state_definition", "baseline": "62b3feb",
        "definitions": {v: defs[v]["definition_sha256"] for v in defs},
        "rows": {v: len(results[v]) for v in results},
        "unavailable_rows": int((base.final_candidate_state
                                 == STATE_UNAVAILABLE).sum()),
        "elapsed_sec": round(time.time() - t0, 1),
        "next": "run_t5_2_validation.py (outcome join allowed there)",
    }
    (OUT / "t5_2_manifest.json").write_text(json.dumps(
        man, indent=2, ensure_ascii=False))
    print(json.dumps(man, indent=2))


if __name__ == "__main__":
    main()
