#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_match_precheck.py — Q-B 背景匹配+共同支持预检(2026-09-22 十二轮批准; 无结果变量).

冻结设计(DESIGN_V2 §5.4):
- 匹配变量(事前): wk_up_streak 档位(0/1/2+)精确 + wk_close_vs_ma4 caliper
  标准化距离 |Δ|/sd_ct(当日对照池SD) ≤ 0.2
- 同日 1:1 最近邻无放回, 全局距离升序贪心(确定性)
- 预检输出: 事件保留率/匹配后五变量 SMD(达标线|SMD|<0.1)/有效日数/逐桶覆盖
- 不读取 Y40 数值; 共同支持=匹配天然实现+事件 wk_close_vs_ma4 范围∩对照
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
from multiperiod_lib import load_price_series  # noqa: E402
from forward_y40_lib import market_calendar, obs_bucket  # noqa: E402
from run_condition_stage0_audit import monthly_states, weekly_states  # noqa: E402
from run_condition_riskset_v2 import independent_code_map  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"
VARS = ["price_vs_monthly_ma6", "ma_spread_3_6", "trend_len_completed",
        "wk_close_vs_ma4", "wk_up_streak"]
CALIPER = 0.2


def main():
    t0 = time.time()
    cmap = independent_code_map()
    con = duckdb.connect()
    files = glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/**/*.parquet"), recursive=True)
    df = con.execute(f"""
        select code, lifecycle_id, anchor_day, breakout_day, end_day
        from read_parquet({files!r})""").fetchall()
    lc = {lid: (code, anchor, bo, end) for code, lid, anchor, bo, end in df}
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
    print(f"风险集重建 | {time.time()-t0:.0f}s", flush=True)

    paired_days = [d for d, evs in sorted(event_by_day.items())
                   if len(evs) >= 1 and len(risk_by_day[d] - evs) >= 10]
    feat_cache = {}

    def get_feats(c6, d):
        key = (c6, d)
        if key not in feat_cache:
            closes = load_price_series(cmap[c6])
            mo = monthly_states(closes, d)
            we = weekly_states(closes, d)
            feat_cache[key] = {**{k: mo.get(k) for k in ("price_vs_monthly_ma6", "ma_spread_3_6", "trend_len_completed")},
                               **{k: we.get(k) for k in ("wk_close_vs_ma4", "wk_up_streak")}}
        return feat_cache[key]

    n_events_total = n_events_matched = 0
    day_rows = []
    for d in paired_days:
        evs = sorted(event_by_day[d])
        ctrls = sorted(risk_by_day[d] - set(evs))
        sd = None
        ct_ma4 = [get_feats(c, d)["wk_close_vs_ma4"] for c in ctrls]
        ct_ma4 = [x for x in ct_ma4 if x is not None and x == x]
        if len(ct_ma4) >= 2:
            sd = float(np.std(ct_ma4, ddof=1))
        pairs = []
        if sd and sd > 0:
            # 全局距离升序贪心, 档位精确匹配
            cand = []
            for e in evs:
                fe = get_feats(e, d)
                if fe["wk_up_streak"] is None or fe["wk_close_vs_ma4"] is None:
                    continue
                st_e = 2 if fe["wk_up_streak"] >= 2 else int(fe["wk_up_streak"])
                for c in ctrls:
                    fc = get_feats(c, d)
                    if fc["wk_up_streak"] is None or fc["wk_close_vs_ma4"] is None:
                        continue
                    st_c = 2 if fc["wk_up_streak"] >= 2 else int(fc["wk_up_streak"])
                    if st_e != st_c:
                        continue
                    dist = abs(fe["wk_close_vs_ma4"] - fc["wk_close_vs_ma4"]) / sd
                    if dist <= CALIPER:
                        cand.append((dist, e, c))
            cand.sort()
            used_e, used_c = set(), set()
            for dist, e, c in cand:
                if e not in used_e and c not in used_c:
                    used_e.add(e)
                    used_c.add(c)
                    pairs.append((e, c))
        n_events_total += len(evs)
        n_events_matched += len(pairs)
        row = {"day": d, "bucket": obs_bucket(d), "n_ev": len(evs), "n_matched": len(pairs),
               "n_ct": len(ctrls)}
        # 匹配后五变量 SMD(配对样本)
        for v in VARS:
            ev_vals, ct_vals = [], []
            for e, c in pairs:
                fe, fc = get_feats(e, d).get(v), get_feats(c, d).get(v)
                if fe is not None and fe == fe and fc is not None and fc == fc:
                    ev_vals.append(float(fe))
                    ct_vals.append(float(fc))
            if len(ev_vals) >= 2:
                v_e = float(np.var(ev_vals, ddof=1))
                v_c = float(np.var(ct_vals, ddof=1))
                pooled = (v_e + v_c) / 2
                if pooled > 0:
                    row[v] = {"smd": round((float(np.mean(ev_vals)) - float(np.mean(ct_vals))) / np.sqrt(pooled), 4),
                              "n": len(ev_vals)}
                else:
                    row[v] = {"smd": None, "n": len(ev_vals)}  # 零方差: 不记 0(十二轮修正)
            else:
                row[v] = None
        day_rows.append(row)
        if len(day_rows) % 100 == 0:
            print(f"{len(day_rows)}/{len(paired_days)} 日 保留率 {n_events_matched}/{n_events_total} | {time.time()-t0:.0f}s", flush=True)

    def summ(rows, label):
        out = {"scope": label, "n_days": len(rows),
               "n_events_total": sum(r["n_ev"] for r in rows),
               "n_events_matched": sum(r["n_matched"] for r in rows),
               "days_with_match": sum(1 for r in rows if r["n_matched"] >= 1)}
        for v in VARS:
            smds = [r[v]["smd"] for r in rows if r.get(v) and r[v]["smd"] is not None]
            out[v] = {"n_valid_days": len(smds),
                      "smd_p50": round(float(np.median(smds)), 3) if smds else None,
                      "smd_p25": round(float(np.percentile(smds, 25)), 3) if smds else None,
                      "smd_p75": round(float(np.percentile(smds, 75)), 3) if smds else None,
                      "n_zero_var_days_excluded": sum(1 for r in rows if r.get(v) and r[v]["smd"] is None)}
        return out

    rep = {"audit": "MULTIPERIOD_CONDITION_MATCH_PRECHECK", "date": "2026-09-22",
           "y40_read": False,
           "design": f"同日1:1最近邻无放回全局贪心; wk_up_streak档位精确 + wk_close_vs_ma4 caliper {CALIPER}SD; 达标线|SMD|<0.1",
           "n_paired_days": len(paired_days),
           "overall": summ(day_rows, "ALL"),
           "b19_b22": summ([r for r in day_rows if r["bucket"] in (19, 20, 21, 22)], "b19_b22"),
           "by_bucket": {b: summ([r for r in day_rows if r["bucket"] == b], f"b{b}")
                         for b in sorted({r["bucket"] for r in day_rows})},
           "per_day_rows": day_rows}
    (OUT / "MULTIPERIOD_CONDITION_MATCH_PRECHECK.json").write_text(json.dumps(rep, ensure_ascii=False))
    o = rep["overall"]
    print(f"保留率: {o['n_events_matched']}/{o['n_events_total']} = {o['n_events_matched']/o['n_events_total']*100:.1f}% | "
          f"有匹配日 {o['days_with_match']}/{o['n_days']} | {time.time()-t0:.0f}s", flush=True)
    print("→ MULTIPERIOD_CONDITION_MATCH_PRECHECK.json")


if __name__ == "__main__":
    main()
