#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_qa_coverage.py — Q-A 无结果变量覆盖审计(DESIGN_V3_QA §4).

只读取 bo/end/end_reason 日期与原因——不读任何价格/Y40/收益数值。
终点(Δ=5 主): 事件=bo∈[t+1,t+5]; 竞争=end∈(t,t+5] 且市场性退出;
同日并发竞争优先(保守); 删失=窗口届满/行政终止(data_end/max_observation
或窗尾超指数日历)。
"""
from __future__ import annotations

import glob
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "scripts"))
import duckdb  # noqa: E402
from forward_y40_lib import market_calendar, obs_bucket  # noqa: E402
from run_condition_riskset_v2 import independent_code_map  # noqa: E402
from multiperiod_lib import load_price_series  # noqa: E402
from collections import Counter  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"
FOLDS = (19, 20, 21, 22)
MARKET_EXITS = {"monthly_exit", "structure_break"}
ADMIN = {"data_end", "max_observation"}


def main():
    t0 = time.time()
    cmap = independent_code_map()
    con = duckdb.connect()
    files = glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/**/*.parquet"), recursive=True)
    df = con.execute(f"""
        select code, lifecycle_id, anchor_day, breakout_day, end_day, end_reason
        from read_parquet({files!r})""").fetchall()
    lc = {lid: (code, anchor, bo, end, reason) for code, lid, anchor, bo, end, reason in df}
    import csv
    pool_in = defaultdict(dict)
    want = {v[0].split(".")[-1] if "." in v[0] else v[0] for v in lc.values()}
    with open(PANEL / "universe_state_panel.csv") as f:
        for r in csv.DictReader(f):
            if r["code"] in want:
                pool_in[r["code"]][r["date"]] = (r["monthly_pool_state"] == "in")
    mdates, _ = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    n_md = len(mdates)

    obs_days_total = 0
    per_fold = {f: Counter() for f in FOLDS}
    all_fold = Counter()
    per_stock_days = []
    overlap_hist = Counter()   # 每股: 相邻观察日间隔<=5 的次数(窗重叠)
    n_bo_excluded = 0

    for lid, (code, anchor, bo, end, reason) in lc.items():
        c6 = code.split(".")[-1] if "." in code else code
        full = cmap.get(c6)
        if full is None or anchor not in mpos:
            continue
        a_i = mpos[anchor]
        s_i = mpos[bo] + 1 if (bo and bo in mpos) else min(mpos.get(end, n_md), a_i + 120, n_md - 1)
        try:
            dayset = set(load_price_series(full).keys())
        except FileNotFoundError:
            continue
        pin = pool_in.get(c6, {})
        days = [d for d in mdates[a_i:s_i] if d in dayset and pin.get(d)]
        bo_i = mpos[bo] if (bo and bo in mpos) else None
        end_i = mpos.get(end) if end in mpos else None
        mkt = reason in MARKET_EXITS
        stock_obs = 0
        prev_i = None
        for d in days:
            i = mpos[d]
            # Q-A 样本: 尚未突破(bo==t 日排除)
            if bo_i is not None and i >= bo_i:
                n_bo_excluded += 1
                continue
            stock_obs += 1
            obs_days_total += 1
            if prev_i is not None and i - prev_i <= 5:
                overlap_hist[i - prev_i] += 1
            prev_i = i
            b = obs_bucket(d)
            row = all_fold
            row["obs"] += 1
            if b in per_fold:
                row = per_fold[b]
                row["obs"] += 1
            # 终点判定(Δ=5)
            w_end = min(i + 5, n_md - 1)
            if i + 5 >= n_md:
                row["censor_admin"] += 1   # 行政: 指数日历末端不足窗
                continue
            ev_i = bo_i if bo_i is not None else None
            # 事件: bo 在 (i, i+5]
            ev = (ev_i is not None and i < ev_i <= i + 5)
            # 竞争: 市场性退出 end 在 (i, i+5]
            comp = (mkt and end_i is not None and i < end_i <= i + 5)
            if ev and comp:
                # 更早者; 同日并发竞争优先(保守)
                if end_i <= ev_i:
                    row["competing"] += 1
                else:
                    row["event"] += 1
            elif ev:
                row["event"] += 1
            elif comp:
                row["competing"] += 1
            else:
                # 无事件无市场退出: 退出日若在窗内(行政型)→行政删失; 否则窗口届满
                if end_i is not None and i < end_i <= i + 5:
                    row["censor_admin"] += 1
                else:
                    row["censor_window"] += 1
        if stock_obs:
            per_stock_days.append(stock_obs)

    ps = np.array(per_stock_days)
    rep = {"audit": "MULTIPERIOD_CONDITION_QA_COVERAGE", "date": "2026-09-22",
           "delta": 5, "no_outcome_variables": "只读 bo/end/end_reason 日期与原因; 无价格/Y40 数值",
           "riskset_recon": {"obs_days_total": obs_days_total,
                             "expected_riskset": 323031,
                             "bo_excluded_from_qa_sample": n_bo_excluded,
                             "qa_sample": obs_days_total,
                             "assert": obs_days_total + n_bo_excluded == 323031},
           "per_stock_obs_days": {"n_stocks": len(ps), "p50": float(np.percentile(ps, 50)),
                                  "p75": float(np.percentile(ps, 75)), "max": int(ps.max()),
                                  "mean": float(ps.mean())},
           "window_overlap_gap_hist": {str(k): int(v) for k, v in sorted(overlap_hist.items())},
           "by_fold": {str(f): dict(c) for f, c in per_fold.items()},
           "all_periods": dict(all_fold),
           "coverage_threshold": "每折 event 与 competing 均>=30(§4 门槛)",
           "event_rate_per_1000": {str(f): round(per_fold[f]["event"] / max(per_fold[f]["obs"], 1) * 1000, 2) for f in FOLDS}}
    assert rep["riskset_recon"]["assert"], f"对账失败: {obs_days_total}+{n_bo_excluded}!=323031"
    (OUT / "MULTIPERIOD_CONDITION_QA_COVERAGE.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"对账: 风险集 323,031 = Q-A 样本 {obs_days_total} + bo日排除 {n_bo_excluded} | {time.time()-t0:.0f}s")
    for f in FOLDS:
        c = per_fold[f]
        print(f"b{f}: obs {c['obs']:>6} event {c['event']:>5} comp {c['competing']:>5} "
              f"cens_win {c['censor_window']:>6} cens_admin {c['censor_admin']:>4} | 率/千 {rep['event_rate_per_1000'][str(f)]}")
    print(f"每股观察日: p50 {rep['per_stock_obs_days']['p50']:.0f} p75 {rep['per_stock_obs_days']['p75']:.0f} max {rep['per_stock_obs_days']['max']} | 股数 {len(ps)}")
    print("→ MULTIPERIOD_CONDITION_QA_COVERAGE.json")


if __name__ == "__main__":
    main()
