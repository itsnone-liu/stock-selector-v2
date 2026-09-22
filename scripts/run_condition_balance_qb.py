#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_balance_qb.py — Q-B 同日五变量平衡表(2026-09-22 十一轮批准; 无结果变量).

规则(十一轮复审):
- 样本: 配对日(事件>=1 且对照>=10 不同股票)上的同日事件组(bo==d, 在共同风险集)
  vs 对照组(同日合格未突破, 含此后突破者不剔除)
- 五变量: price_vs_monthly_ma6/ma_spread_3_6/trend_len_completed/
  wk_close_vs_ma4/wk_up_streak(数值口径; 档位仅描述)
- 每日: 组均值/缺失率/标准化差异 SMD=(m_e-m_c)/sqrt((v_e+v_c)/2)
- 呈现: 按月桶(b18-b23)与原四测试折(b19-b22)分层——避免大样本日期主导;
  总体混合表仅附录并标注偏倚; 不根据平衡表挑选变量(先门槛后家族)
"""
from __future__ import annotations

import glob
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "scripts"))
import duckdb  # noqa: E402
import multiperiod_lib as _mpl  # noqa: E402
from multiperiod_lib import load_price_series  # noqa: E402
from forward_y40_lib import market_calendar, obs_bucket  # noqa: E402
from run_condition_stage0_audit import monthly_states, weekly_states  # noqa: E402
from run_condition_riskset_v2 import independent_code_map  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"
VARS = ["price_vs_monthly_ma6", "ma_spread_3_6", "trend_len_completed",
        "wk_close_vs_ma4", "wk_up_streak"]


def feats_for(code_full, d, closes):
    mo = monthly_states(closes, d)
    we = weekly_states(closes, d)
    return {**{k: mo.get(k) for k in ("price_vs_monthly_ma6", "ma_spread_3_6", "trend_len_completed")},
            **{k: we.get(k) for k in ("wk_close_vs_ma4", "wk_up_streak")}}


def main():
    t0 = time.time()
    cmap = independent_code_map()
    con = duckdb.connect()
    files = glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/**/*.parquet"), recursive=True)
    df = con.execute(f"""
        select code, lifecycle_id, anchor_day, breakout_day, end_day
        from read_parquet({files!r})""").fetchall()
    lc = {}
    for code, lid, anchor, bo, end in df:
        lc[lid] = (code, anchor, bo, end)
    pool_in = defaultdict(dict)
    want = {v[0].split(".")[-1] if "." in v[0] else v[0] for v in lc.values()}
    import csv
    with open(PANEL / "universe_state_panel.csv") as f:
        for r in csv.DictReader(f):
            if r["code"] in want:
                pool_in[r["code"]][r["date"]] = (r["monthly_pool_state"] == "in")
    mdates, _ = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    risk_by_day = defaultdict(set)
    for lid, (code, anchor, bo, end) in lc.items():
        c6 = code.split(".")[-1] if "." in code else code
        full = cmap.get(c6)
        if full is None or anchor not in mpos:
            continue
        a_i = mpos[anchor]
        s_i = mpos[bo] + 1 if (bo and bo in mpos) else min(mpos.get(end, len(mdates)), a_i + 120, len(mdates) - 1)
        try:
            dayset = set(load_price_series(full).keys())
        except FileNotFoundError:
            continue
        pin = pool_in.get(c6, {})
        for d in mdates[a_i:s_i]:
            if d in dayset and pin.get(d):
                risk_by_day[d].add(c6)
    event_by_day = defaultdict(set)
    for lid, (code, anchor, bo, end) in lc.items():
        c6 = code.split(".")[-1] if "." in code else code
        if bo and cmap.get(c6) and bo in mpos and c6 in risk_by_day.get(bo, set()):
            event_by_day[bo].add(c6)
    print(f"共同风险集重建完成 | {time.time()-t0:.0f}s", flush=True)

    paired = [(d, evs, risk_by_day[d] - evs) for d, evs in sorted(event_by_day.items())
              if len(evs) >= 1 and len(risk_by_day[d] - evs) >= 10]
    feat_cache = {}
    day_rows = []
    for d, evs, ctrls in paired:
        grp = {}
        for label, codes in (("ev", evs), ("ct", ctrls)):
            vals = defaultdict(list)
            n_miss = 0
            for c6 in codes:
                key = (c6, d)
                if key not in feat_cache:
                    closes = load_price_series(cmap[c6])
                    feat_cache[key] = feats_for(cmap[c6], d, closes)
                fv = feat_cache[key]
                for v in VARS:
                    x = fv.get(v)
                    if x is None or x != x:
                        n_miss += 1
                    else:
                        vals[v].append(float(x))
            grp[label] = (vals, len(codes), n_miss)
        row = {"day": d, "bucket": obs_bucket(d), "n_ev": grp["ev"][1], "n_ct": grp["ct"][1]}
        for v in VARS:
            ev_vals, ct_vals = grp["ev"][0][v], grp["ct"][0][v]
            if len(ev_vals) >= 2 and len(ct_vals) >= 2:
                m_e, m_c = float(np.mean(ev_vals)), float(np.mean(ct_vals))
                v_e, v_c = float(np.var(ev_vals, ddof=1)), float(np.var(ct_vals, ddof=1))
                pooled = (v_e + v_c) / 2
                smd = (m_e - m_c) / np.sqrt(pooled) if pooled > 0 else 0.0
                row[v] = {"smd": round(smd, 4), "miss_ev": grp["ev"][1] - len(ev_vals),
                          "miss_ct": grp["ct"][1] - len(ct_vals),
                          "mean_ev": round(m_e, 4), "mean_ct": round(m_c, 4)}
            else:
                row[v] = None
        day_rows.append(row)
        if len(day_rows) % 100 == 0:
            print(f"{len(day_rows)}/{len(paired)} 日 | {time.time()-t0:.0f}s", flush=True)

    # 分层汇总: 按月桶 + b19-b22 + 全区间(附, 标注)
    def summ(rows, label):
        out = {"scope": label, "n_days": len(rows)}
        for v in VARS:
            smds = [r[v]["smd"] for r in rows if r.get(v)]
            out[v] = {"smd_p25": round(float(np.percentile(smds, 25)), 3) if smds else None,
                      "smd_p50": round(float(np.median(smds)), 3) if smds else None,
                      "smd_p75": round(float(np.percentile(smds, 75)), 3) if smds else None,
                      "miss_ev_total": sum(r[v]["miss_ev"] for r in rows if r.get(v)),
                      "miss_ct_total": sum(r[v]["miss_ct"] for r in rows if r.get(v))}
        return out

    by_bucket = {b: summ([r for r in day_rows if r["bucket"] == b], f"bucket_{b}")
                 for b in sorted({r["bucket"] for r in day_rows})}
    b19_22 = summ([r for r in day_rows if r["bucket"] in (19, 20, 21, 22)], "b19_b22")
    overall = summ(day_rows, "ALL_MIXED 附录(大样本日期主导偏倚, 不得单独引用)")
    rep = {"audit": "MULTIPERIOD_CONDITION_BALANCE_QB", "date": "2026-09-22",
           "y40_read": False,
           "design": "Q-B 同日事件组 vs 合格未突破对照; SMD=(m_ev-m_ct)/sqrt((v_ev+v_ct)/2); 按日计算后按层汇总",
           "n_paired_days": len(paired),
           "by_bucket": by_bucket, "b19_b22": b19_22, "overall_mixed_appendix": overall,
           "per_day_rows": day_rows,
           "note": "平衡表用于评估比较可行性; 不据此挑选变量(先门槛后家族原则)"}
    (OUT / "MULTIPERIOD_CONDITION_BALANCE_QB.json").write_text(json.dumps(rep, ensure_ascii=False))
    print(f"→ MULTIPERIOD_CONDITION_BALANCE_QB.json | {time.time()-t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
