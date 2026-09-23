#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_qa_descriptive.py — Q-A 描述性分析(2026-09-23 二十二层裁决 B, 一次).

B 口径: H2a/H2b 全部冻结定义不变, 只报组发生率与差值(描述);
不执行 40/20 日块 bootstrap; 不报 p/CI/Holm; 不作拒绝判断。
发生率 = 未来五日首次突破记录数 / 观察日数(竞争事件计入未发生突破的分母);
不是独立股票突破概率, 不代表因果效应。
含: 主分组(b22)/S3 Δ=1/S4 竞争口径对照/D2 其余三变量(训练折三分位)。
数据使用: 终点=bo/end 日期与原因; 特征=t 时点信息; 无 Y40/价格数值关联。
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
from forward_y40_lib import market_calendar, obs_bucket  # noqa: E402
from run_condition_riskset_v2 import independent_code_map  # noqa: E402
from run_condition_stage0_audit import monthly_states, weekly_states  # noqa: E402
from multiperiod_lib import load_price_series  # noqa: E402
from run_condition_qa_coverage import classify, MARKET_EXITS  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"
TRAIN, TEST = (19, 20, 21), 22


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

    train_feats = defaultdict(list)   # var -> 训练折特征值列表
    b22 = []                          # (day, feats{5 变量}, cls5, cls1, ev_date_in_window1?)
    for lid, (code, anchor, bo, end, reason) in sorted(lc.items()):
        c6 = code.split(".")[-1] if "." in code else code
        full = cmap.get(c6)
        if full is None or anchor not in mpos:
            continue
        a_i = mpos[anchor]
        s_i = mpos[bo] + 1 if (bo and bo in mpos) else min(mpos.get(end, n_md), a_i + 120, n_md - 1)
        try:
            closes = load_price_series(full)
        except FileNotFoundError:
            continue
        dayset = closes.keys()
        pin = pool_in.get(c6, {})
        days = [d for d in mdates[a_i:s_i] if d in dayset and pin.get(d)]
        bo_i = mpos[bo] if (bo and bo in mpos) else None
        end_i = mpos.get(end) if end in mpos else None
        mkt = reason in MARKET_EXITS
        for d in days:
            i = mpos[d]
            if bo_i is not None and i >= bo_i:
                continue
            cls5 = classify(i, bo_i, end_i, mkt, n_md)
            b = obs_bucket(d)
            mo = monthly_states(closes, d)
            we = weekly_states(closes, d)
            f5 = {"price_vs_monthly_ma6": mo.get("price_vs_monthly_ma6"),
                  "ma_spread_3_6": mo.get("ma_spread_3_6"),
                  "trend_len": mo.get("trend_len"),
                  "wk_close_vs_ma4": we.get("wk_close_vs_ma4"),
                  "wk_up_streak": we.get("wk_up_streak")}
            if b in TRAIN:
                for k, v in f5.items():
                    if v is not None and v == v:
                        train_feats[k].append(v)
            elif b == TEST:
                # Δ=1 终点: 窗 [t+1, t+1]
                cls1 = classify1(i, bo_i, end_i, mkt, n_md)
                b22.append((d, f5, cls5, cls1))
        if len(b22) and (len(b22) % 60000) == 0:
            print(f"b22 {len(b22):,} | {time.time()-t0:.0f}s", flush=True)

    thr = {}
    for k, vals in train_feats.items():
        thr[k] = tuple(float(np.percentile(vals, q)) for q in (100 / 3, 200 / 3)) if k != "wk_up_streak" else None
    thr["wk_up_streak"] = "档位 0/1/2/>=3 预固定(非分位)"


    rep = {"audit": "MULTIPERIOD_CONDITION_QA_DESCRIPTIVE", "date": "2026-09-23",
           "ruling": "二十二层裁决 B: 描述性/探索性; 无 p/CI/Holm; 无 bootstrap; 不作拒绝判断",
           "rate_definition": "未来五日首次突破记录数/观察日数; 竞争事件计入未发生突破的分母; 非独立股票突破概率, 非因果",
           "sample": "b22 测试折(阈值由 b19-21 训练折特征确定, 无泄漏)",
           "train_thresholds": {k: (list(v) if isinstance(v, tuple) else v) for k, v in thr.items()},
           "H2a_price_vs_monthly_ma6": summarize(rate_table("price_vs_monthly_ma6", b22, thr)),
           "H2b_wk_up_streak": summarize(rate_table("wk_up_streak", b22, thr)),
           "S3_delta1_H2a": summarize(rate_table("price_vs_monthly_ma6", b22, thr, "cls1")),
           "S3_delta1_H2b": summarize(rate_table("wk_up_streak", b22, thr, "cls1")),
           "S4_competing_in_denominator_H2a": summarize(s4_tables("price_vs_monthly_ma6", b22, thr)[0]),
           "S4_competing_excluded_H2a": summarize(s4_tables("price_vs_monthly_ma6", b22, thr)[1]),
           "D2_ma_spread_3_6": summarize(rate_table("ma_spread_3_6", b22, thr)),
           "D2_trend_len": summarize(rate_table("trend_len", b22, thr)),
           "D2_wk_close_vs_ma4": summarize(rate_table("wk_close_vs_ma4", b22, thr)),
           "S5": "保留方法验证事项, 不作统计证据(二十一轮)",
           "note": "结果出来后不根据正负方向追加假设或选择块长(裁决 B)"}
    (OUT / "MULTIPERIOD_CONDITION_QA_DESCRIPTIVE.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    for k in ("H2a_price_vs_monthly_ma6", "H2b_wk_up_streak"):
        print(k)
        for g, v in rep[k].items():
            print(f"  {g}: obs {v['obs']:,} ev {v['event']:,} comp {v['competing']:,} 率/日 {v['rate5_per_day']}")
    print("→ MULTIPERIOD_CONDITION_QA_DESCRIPTIVE.json")


def grp(k, v, thr):
    if v is None or v != v:
        return None
    if k == "wk_up_streak":
        return "s0" if v == 0 else ("s1" if v == 1 else ("s2" if v == 2 else "s3p"))
    q1, q2 = thr[k]
    return "low" if v < q1 else ("high" if v > q2 else "mid")


def rate_table(var, b22, thr, cls_key="cls5"):
    from collections import Counter, defaultdict
    tab = defaultdict(Counter)
    for d, f5, cls5, cls1 in b22:
        g = grp(var, f5[var], thr)
        if g is None:
            continue
        c = cls5 if cls_key == "cls5" else cls1
        tab[g]["obs"] += 1
        tab[g][c] = tab[g].get(c, 0) + 1
    return tab


def s4_tables(var, b22, thr):
    """S4: 竞争口径对照(竞争计分母[主] vs 竞争日剔除)。"""
    from collections import Counter, defaultdict
    tab_in = defaultdict(Counter)
    tab_ex = defaultdict(Counter)
    for d, f5, cls5, _ in b22:
        g = grp(var, f5[var], thr)
        if g is None:
            continue
        tab_in[g]["obs"] += 1
        tab_in[g][cls5] = tab_in[g].get(cls5, 0) + 1
        if cls5 != "competing":     # 剔除口径: 竞争日从分子分母同时剔除
            tab_ex[g]["obs"] += 1
            tab_ex[g][cls5] = tab_ex[g].get(cls5, 0) + 1
    return tab_in, tab_ex


def summarize(tab):
    out = {}
    for g, c in sorted(tab.items()):
        ev = c.get("event", 0)
        ob = c.get("obs", 0)
        out[g] = {"obs": ob, "event": ev, "competing": c.get("competing", 0),
                  "censor_window": c.get("censor_window", 0), "censor_admin": c.get("censor_admin", 0),
                  "rate5_per_day": round(ev / ob, 5) if ob else None}
    return out


def classify1(i, bo_i, end_i, mkt, n_md):
    """Δ=1: 窗 [t+1, t+1] 最早终点(结构同 classify)."""
    if i + 1 >= n_md:
        return "censor_admin"
    obs_last = i + 1
    ev_i = bo_i if (bo_i is not None and i < bo_i <= obs_last) else None
    cp_i = end_i if (mkt and end_i is not None and i < end_i <= obs_last) else None
    ae_i = end_i if (not mkt and end_i is not None and i < end_i <= obs_last) else None
    prio = {"competing": 0, "censor_admin": 1, "event": 2}
    cands = [x for x in ((ev_i, "event"), (cp_i, "competing"), (ae_i, "censor_admin")) if x[0] is not None]
    if cands:
        cands.sort(key=lambda x: (x[0], prio[x[1]]))
        return cands[0][1]
    return "censor_window"


if __name__ == "__main__":
    main()
