#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_stage0_audit.py — 多周期条件关系研究 阶段0 覆盖审计(2026-09-22 批准).

授权: 仅无结果变量参与的描述性审计(不碰 Y40 分组, 不跑预测模型/交互/收益比较)。
四项执行要求(2026-09-22 三轮复审):
 1 月线变量严格按观察日重建: 已完成月/临时月时间边界分开, 位置距离与均线
   发散度两种定义分开, 趋势时长口径明确(已完成月);
 2 Q2/Q3 对照总体: 风险集合审计(同资格+月池 in 下尚未突破的股票-日;
   每生命周期首突一次, 连续未突破日不重复计为独立事件);
 3 可检验性: 1000 事件/40 日仅初筛, 同时输出各折事件/有效日、独立股票数、
   生命周期数、≥10 证券日数、格子缺失率; 统计门槛留 v1.0;
 4 分布退化: 分类>95% 单值可终止; 连续变量报告原始唯一值/缺失/分位/跨度/
   同值集中度, 不先分位分桶再判退化。
"""
from __future__ import annotations

import csv
import glob
import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research.identify_features import eligibility_forward_v1  # noqa: E402
from forward_y40_lib import build_events, obs_bucket, fold_start  # noqa: E402
from run_forward_y40_association import FOLDS  # noqa: E402
from multiperiod_lib import load_price_series, _factor_by_code  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"


def month_key(d: str) -> str:
    return d[:7]


def monthly_states(closes: dict[str, float], obs_day: str) -> dict:
    """观察日重建(要求1): 已完成月=obs 所在月之前的整月; 临时月=当月截至 obs。

    已完成月收盘 = 该月最后交易日收盘; MA 皆基于已完成月收盘序列。
    """
    obs_m = month_key(obs_day)
    by_month: dict[str, float] = {}
    for d, c in closes.items():
        m = month_key(d)
        if m < obs_m:                       # 只用已完成月
            cur = by_month.get(m)
            if cur is None or d > cur[0]:
                by_month[m] = (d, c)
    months = sorted(by_month)
    mc = [by_month[m][1] for m in months]
    intramonth = None
    dmax = max((d for d in closes if month_key(d) == obs_m and d <= obs_day),
               default=None)
    if dmax is not None and months:
        intramonth = (closes[dmax], by_month[months[-1]][1])   # (当月截至obs收盘, 上月收盘)
    out = {}
    if len(mc) >= 6:
        ma3 = float(np.mean(mc[-3:]))
        ma6 = float(np.mean(mc[-6:]))
        out["price_vs_monthly_ma6"] = (mc[-1] / ma6 - 1.0) * 100.0   # 位置距离
        out["ma_spread_3_6"] = (ma3 - ma6) / ma6 * 100.0             # 均线间发散度
        out["ret_1m_completed"] = (mc[-1] / mc[-2] - 1.0) * 100.0
        out["ret_3m_completed"] = (mc[-1] / mc[-4] - 1.0) * 100.0
        streak = 0
        for i in range(len(mc) - 1, 5, -1):
            if mc[i] > np.mean(mc[i - 5:i + 1]):
                streak += 1
            else:
                break
        out["trend_len_completed"] = float(streak)                    # 连续月收盘>月MA6 的已完成月数
    if intramonth:
        c_cur, c_prev = intramonth
        out["intramonth_pct"] = (c_cur / c_prev - 1.0) * 100.0        # 临时月(截至obs)对照, 不混用
    return out


WEEK_FEATS = ("wk_close_vs_ma4", "wk_ret1", "wk_up_streak")


def weekly_states(closes: dict[str, float], obs_day: str) -> dict:
    """周线纯价格结构(已完成周=obs 所在周之前; 复用 multiperiod_lib 周键口径)。"""
    from multiperiod_lib import _iso_week_key
    obs_wk = _iso_week_key(obs_day)
    wk_last: dict = {}
    for d, c in closes.items():
        wk = _iso_week_key(d)
        if wk < obs_wk:
            cur = wk_last.get(wk)
            if cur is None or d > cur[0]:
                wk_last[wk] = (d, c)
    ws = sorted(wk_last)
    wc = [wk_last[w][1] for w in ws]
    out = {}
    if len(wc) >= 4:
        ma4 = float(np.mean(wc[-4:]))
        out["wk_close_vs_ma4"] = (wc[-1] / ma4 - 1.0) * 100.0
        out["wk_ret1"] = (wc[-1] / wc[-2] - 1.0) * 100.0
        streak = 0
        for i in range(len(wc) - 1, 0, -1):
            if wc[i] > wc[i - 1]:
                streak += 1
            else:
                break
        out["wk_up_streak"] = float(streak)
    return out


def dist_report(vals: list) -> dict:
    """要求4: 连续变量原始分布(不先分桶)。"""
    v = [x for x in vals if x is not None and np.isfinite(x)]
    if not v:
        return {"n": 0, "missing": len(vals)}
    a = np.array(v)
    uniq, cnt = np.unique(np.round(a, 6), return_counts=True)
    return {"n": len(a), "missing": len(vals) - len(a),
            "missing_rate": round((len(vals) - len(a)) / max(len(vals), 1), 4),
            "n_unique_round6": int(len(uniq)),
            "top_value_share": round(float(cnt.max() / len(a)), 4),
            "p5": round(float(np.percentile(a, 5)), 3), "p25": round(float(np.percentile(a, 25)), 3),
            "p50": round(float(np.percentile(a, 50)), 3), "p75": round(float(np.percentile(a, 75)), 3),
            "p95": round(float(np.percentile(a, 95)), 3),
            "span": round(float(a.max() - a.min()), 3)}


def main():
    t0 = time.time()
    _factor_by_code()                       # 缓存; 零缺失断言在 load 时由 build 路径保证
    # 主样本(三时点)观察日状态重算
    events = {ds: build_events(ds)[0] for ds in ("breakout", "shrink", "stabilization")}
    monthly_vals = defaultdict(list)
    weekly_vals = defaultdict(list)
    feat_rows = {}                          # (ds, i) -> dict(月+周特征)
    for ds, rows in events.items():
        by_code = defaultdict(set)
        for e in rows:
            by_code[e["code"]].add(e["obs_day"])
        cache = {}
        for code, days in by_code.items():
            try:
                closes = load_price_series(code)
            except FileNotFoundError:
                closes = {}
            for d in days:
                cache[(code, d)] = (monthly_states(closes, d), weekly_states(closes, d))
        for i, e in enumerate(rows):
            mo, we = cache[(e["code"], e["obs_day"])]
            feats = {**mo, **we}
            for k in ("intramonth_pct", "ma_spread_3_6", "price_vs_monthly_ma6",
                      "ret_1m_completed", "ret_3m_completed", "trend_len_completed"):
                monthly_vals[f"{ds}|{k}"].append(feats.get(k))   # None 计入缺失分母
            for k in WEEK_FEATS:
                weekly_vals[f"{ds}|{k}"].append(feats.get(k))
            feat_rows[(ds, i)] = feats
        print(f"{ds}: 状态重算完成 {len(rows)} | {time.time()-t0:.0f}s", flush=True)
    rep = {"audit": "MULTIPERIOD_CONDITION_STAGE0", "date": "2026-09-22",
           "monthly_dist": {k: dist_report(v) for k, v in sorted(monthly_vals.items())},
           "weekly_dist": {k: dist_report(v) for k, v in sorted(weekly_vals.items())}}
    # 要求3: 条件格子预览(描述性四分位桶, 非模型分组; 阈值若日后使用按训练折定)
    cells = {}
    for ds, rows in events.items():
        vals = [feat_rows[(ds, i)].get("price_vs_monthly_ma6") for i in range(len(rows))]
        valid = [v for v in vals if v is not None]
        q = np.percentile(valid, [25, 50, 75]) if valid else [0, 0, 0]
        cellstat = defaultdict(lambda: {"n": 0, "per_day": defaultdict(set), "stocks": set(),
                                        "lifecycles": set(), "by_fold": Counter()})
        for i, e in enumerate(rows):
            v = vals[i]
            if v is None:
                b = "NA"
            else:
                b = "q1" if v <= q[0] else "q2" if v <= q[1] else "q3" if v <= q[2] else "q4"
            st = feat_rows[(ds, i)].get("wk_up_streak")
            w = "NA" if st is None else ("0" if st == 0 else "1" if st == 1 else "2+")
            key = f"{b}|{w}"
            c = cellstat[key]
            c["n"] += 1
            c["per_day"][e["obs_day"]].add(e["code"])   # 有效日按不同股票计
            c["stocks"].add(e["code"])
            c["lifecycles"].add(e["lifecycle_id"])
            c["by_fold"][obs_bucket(e["obs_day"])] += 1
        def cellout(v):
            nd = sum(1 for cs in v["per_day"].values() if len(cs) >= 10)  # ≥10 只不同股票
            ok1000 = v["n"] >= 1000
            ok40 = nd >= 40
            return {"n": v["n"], "n_days_any": len(v["per_day"]),
                    "screen_rule_days": "distinct_stocks>=10",
                    "n_valid_days_min10stk": nd,
                    "n_stocks": len(v["stocks"]), "n_lifecycles": len(v["lifecycles"]),
                    "by_fold_b19_22": {f"b{b}": v["by_fold"].get(b, 0) for b in FOLDS},
                    "screen_1000ev_40day": "PASS" if (ok1000 and ok40) else
                    "FAIL(" + ("" if ok1000 else "n<1000 ") + ("" if ok40 else "validday<40") + ")"}
        cells[ds] = {"quartile_edges_desc_only": [round(float(x), 3) for x in q],
                     "screen_rule": "初筛: n>=1000 且 有效日(≥10证券)>=40; 不合并格子",
                     "cells": {k: cellout(v) for k, v in sorted(cellstat.items())}}
        print(f"{ds}: 格子预览完成 | {time.time()-t0:.0f}s", flush=True)
    rep["condition_cells_desc"] = cells
    # 要求2: 风险集合审计(对照总体)
    import duckdb
    con = duckdb.connect()
    files = glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/**/*.parquet"),
                      recursive=True)
    df = con.execute(f"""
        select code, lifecycle_id, anchor_day, breakout_day, end_day,
               end_reason, right_censored
        from read_parquet({files!r})""").fetchall()
    # 唯一性检查: 同 lifecycle_id 的起点/终点/信号日不得冲突(不静默覆盖)
    seen = {}
    conflict = 0
    for code, lid, anchor, bo, end, reason, rc in df:
        prev = seen.get(lid)
        if prev is not None and prev != (code, anchor, bo, end, reason, rc):
            conflict += 1
        seen[lid] = (code, anchor, bo, end, reason, rc)
    assert conflict == 0, f"lifecycle_id 记录冲突 {conflict} 条——风险集拒绝构建"
    lc = {lid: (code, anchor, bo, end, reason, rc) for lid, (code, anchor, bo, end, reason, rc) in seen.items()}
    n_bo = sum(1 for v in lc.values() if v[2])
    print(f"生命周期(全量事实表): {len(lc)} | 有 breakout_day {n_bo} | 冲突 {conflict} | {time.time()-t0:.0f}s", flush=True)
    # 6位码→带前缀码映射(identify 全 code 集)
    pref6 = {}
    for ds in ("breakout", "shrink", "stabilization"):
        with gzip.open(OUT / f"identify_{ds}.csv.gz", "rt") as f:
            for r in csv.DictReader(f):
                pref6.setdefault(r["code"].split(".")[-1], r["code"])
    # 月池 in 按日(面板)
    pool_in = defaultdict(dict)             # code -> {date: bool}
    want_codes = {v[0].split('.')[-1] if '.' in v[0] else v[0] for v in lc.values()}
    with open(PANEL / "universe_state_panel.csv") as f:
        for r in csv.DictReader(f):
            c6 = r["code"]
            if c6 in want_codes:
                pool_in[c6][r["date"]] = (r["monthly_pool_state"] == "in")
    # 风险日(P0-2 修正): 有突破段=[anchor, breakout_day); 未突破段=[anchor, min(end_day,
    # anchor+120 交易日预设观察上限)); 数据末尾右删失段单独披露
    from forward_y40_lib import market_calendar
    mdates, _ = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    risk_days = 0
    risk_stocks = set()
    risk_lifecycles = 0
    no_break_lifecycles = 0
    risk_lifecycles_nobreak = 0
    right_censored_lifecycles = 0
    first_break_events = 0
    dup_break = 0
    # 流失台账(五轮复审要求): 55,646→有效样本逐层对账
    led = Counter()
    for lid, (code, anchor, bo, end, reason, rc) in lc.items():
        c6 = code.split(".")[-1] if "." in code else code
        full = pref6.get(c6)
        if full is None:
            led["l1_code_map_missing" + ("_with_bo" if bo else "_without_bo")] += 1
            continue
        if anchor not in mpos:
            led["l2_anchor_not_in_calendar"] += 1
            continue
        a_i = mpos[anchor]
        if bo and bo in mpos:
            s_i = mpos[bo]                        # 突破信号日停止计入
            if bo not in mdates[0:mdates.index(mdates[-1]) + 1]:
                led["l3_bo_not_in_calendar"] += 1   # 不可达分支(防御)
        elif bo:
            led["l3_bo_not_in_calendar"] += 1
        else:
            no_break_lifecycles += 1
            cap = mpos.get(end, len(mdates)) if end else len(mdates) - 1
            s_i = min(cap, a_i + 120, len(mdates) - 1)   # 实际 end 与预设上限较早者
            if reason == "data_end" or rc:
                right_censored_lifecycles += 1
        closes_days = None
        try:
            closes_days = sorted(load_price_series(full).keys())
        except FileNotFoundError:
            led["l4_price_missing"] += 1
            continue
        dayset = set(closes_days)
        pin = pool_in.get(c6, {})
        added = 0
        for d in mdates[a_i:s_i]:
            if d in dayset and pin.get(d):
                added += 1
        if added:
            risk_days += added
            risk_stocks.add(code)
            risk_lifecycles += 1
            if not bo:
                risk_lifecycles_nobreak += 1
        elif not bo:
            led["l5_nobreak_no_pool_days"] += 1
        if bo:
            if bo in dayset:
                first_break_events += 1
            else:
                led["l6_bo_day_not_in_stock_prices"] += 1
    # 每生命周期突破次数(identify_breakout 主样本口径)
    bo_lc = Counter(e["lifecycle_id"] for e in events["breakout"])
    dup_break = sum(1 for v in bo_lc.values() if v > 1)
    import multiperiod_lib as _mpl
    assert _mpl._FACTOR_SKIP_COUNT == 0, f"复权因子缺失 {_mpl._FACTOR_SKIP_COUNT} 行(应=0)"  # 模块属性读当前值
    # 程序化对账断言(七轮复审: 文档纠错≠门禁; 必须实际执行的 assert)
    n_total_bo = sum(1 for v in lc.values() if v[2])
    n_total_nobo = len(lc) - n_total_bo
    assert n_total_bo == (led["l1_code_map_missing_with_bo"]
                          + led.get("l3_bo_not_in_calendar", 0)
                          + first_break_events
                          + led.get("l6_bo_day_not_in_stock_prices", 0)), "有bo段对账不闭合"
    assert n_total_nobo == (led["l1_code_map_missing_without_bo"]
                            + no_break_lifecycles), "未突破段对账不闭合"
    assert no_break_lifecycles == (led["l5_nobreak_no_pool_days"]
                                   + risk_lifecycles_nobreak), "27,935 拆分不闭合(l5 是子集)"
    rep["risk_set"] = {
        "attrition_reconciliation_assert": "executed(see asserts above)",
        "source": "lifecycle_stage4_v1_full(全量生命周期事实表; 非策略回放 signal)",
        "n_lifecycles_distinct": len(lc),
        "record_conflicts": conflict,
        "n_with_breakout_day": n_bo,
        "no_break_lifecycles": no_break_lifecycles,
        "no_break_right_censored": right_censored_lifecycles,
        "risk_stock_days_poolin": risk_days,
        "risk_stocks": len(risk_stocks),
        "risk_lifecycles_with_days": risk_lifecycles,
        "first_break_day_events": first_break_events,
        "breakout_events_per_lifecycle_gt1": dup_break,
        "attrition_ledger": dict(led),
        "attrition_total_dropped": int(sum(led.values())),
        "reconciliation": {
            "with_bo": f"{n_total_bo}_total = {led['l1_code_map_missing_with_bo']} l1 + {led.get('l3_bo_not_in_calendar', 0)} l3 + {first_break_events} first_break + {led.get('l6_bo_day_not_in_stock_prices', 0)} l6",
            "without_bo": f"{n_total_nobo}_total = {led['l1_code_map_missing_without_bo']} l1 + {no_break_lifecycles} entered (其中 l5={led['l5_nobreak_no_pool_days']} 为 entered 内无月池日子集)",
            "entered_split": f"{no_break_lifecycles} = {led['l5_nobreak_no_pool_days']} l5 + {risk_lifecycles_nobreak} 有风险日",
        },
        "note": ("风险日=生命周期 [anchor,breakout_day) 交易日∩当日月池in; 未突破段=[anchor, "
                 "min(end_day, anchor+120交易日)); 数据末尾右删失段已单独计数; "
                 "同 lifecycle_id 起终点冲突=0(断言); 无结果变量参与;"
                 "台账: l1 映射失败/l2 起点不在日历/l3 突破日不在日历/"
                 "l4 价格文件缺失/l5 未突破段无月池内交易日/l6 突破日不在个股日线")}
    print(f"风险集: {rep['risk_set']['risk_stock_days_poolin']} 股票-日 | "
          f"{first_break_events} 首突日 | 未突破段 {no_break_lifecycles}(右删失 {right_censored_lifecycles}) "
          f"| 重复突破 {dup_break} | 因子缺失断言过 | {time.time()-t0:.0f}s", flush=True)
    (OUT / "MULTIPERIOD_CONDITION_STAGE0.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"→ MULTIPERIOD_CONDITION_STAGE0.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
