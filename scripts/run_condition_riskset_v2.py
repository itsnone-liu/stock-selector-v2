#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_riskset_v2.py — 任务二 P0: 独立映射+共同风险集合+S3 配对覆盖预检(2026-09-22 授权).

授权(九轮复审): 修正独立股票映射+重建共同风险集合+无结果变量的配对覆盖预检;
不运行收益比较/预测模型/回测。

P0 修复:
- 旧 l1 流失源于 identify 事件名单映射(结果相关筛选)——改用冻结股票库
  (data/adjustment_baostock/per_stock 文件名主键, 5,240 独立于事件数据)
- 重建两组共同合格风险集合; 重核流失台账; 294,722/27,310 保留为旧审计结果

S3 配对覆盖预检(无结果变量; 对照事后突破不剔除):
- 每交易日 d: 合格风险集 = active(anchor<=d<终点) ∩ 当日月池 in ∩ 有日线
- 事件组=当日首突(bo==d); 对照组=同日合格未突破(含此后突破者)
- 统计: 配对日(事件>=1 且对照>=10)/每股贡献日数分布(S2 校正输入)/折分布
终点: 有 bo=[anchor,bo); 无 bo=[anchor, min(end_day, anchor+120))。
"""
from __future__ import annotations

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
import duckdb  # noqa: E402
import multiperiod_lib as _mpl  # noqa: E402
from multiperiod_lib import load_price_series  # noqa: E402
from forward_y40_lib import market_calendar, obs_bucket  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"


def independent_code_map() -> dict[str, str]:
    """独立映射: 冻结股票库 per_stock 文件名主键(不依赖 identify 事件名单)。"""
    m = {}
    for f in (ROOT / "data/adjustment_baostock/per_stock").glob("*.json.gz"):
        full = f.name[:-8]                       # sz.000001
        m[full.split(".")[-1]] = full
    return m


def main():
    t0 = time.time()
    cmap = independent_code_map()
    print(f"独立映射(冻结库主键): {len(cmap)} 股 | {time.time()-t0:.0f}s", flush=True)

    con = duckdb.connect()
    files = glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/**/*.parquet"),
                      recursive=True)
    df = con.execute(f"""
        select code, lifecycle_id, anchor_day, breakout_day, end_day,
               end_reason, right_censored
        from read_parquet({files!r})""").fetchall()
    seen, conflict = {}, 0
    for code, lid, anchor, bo, end, reason, rc in df:
        prev = seen.get(lid)
        if prev is not None and prev != (code, anchor, bo, end, reason, rc):
            conflict += 1
        seen[lid] = (code, anchor, bo, end, reason, rc)
    assert conflict == 0, f"lifecycle_id 冲突 {conflict}"
    print(f"生命周期: {len(seen)} | 冲突 {conflict} | {time.time()-t0:.0f}s", flush=True)

    # 月池 in 按日
    pool_in = defaultdict(dict)
    want = {v[0].split(".")[-1] if "." in v[0] else v[0] for v in seen.values()}
    with open(PANEL / "universe_state_panel.csv") as f:
        import csv
        for r in csv.DictReader(f):
            if r["code"] in want:
                pool_in[r["code"]][r["date"]] = (r["monthly_pool_state"] == "in")

    mdates, _ = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    led = Counter()
    risk_by_day = defaultdict(set)          # d -> set(6位码)
    n_first_break = 0
    per_stock_days = Counter()              # 股票贡献风险日数(S2 校正输入)
    bo_days_used = 0
    for lid, (code, anchor, bo, end, reason, rc) in seen.items():
        c6 = code.split(".")[-1] if "." in code else code
        full = cmap.get(c6)
        if full is None:
            led["l1_not_in_frozen_library"] += 1
            continue
        if anchor not in mpos:
            led["l2_anchor_not_in_calendar"] += 1
            continue
        a_i = mpos[anchor]
        if bo and bo in mpos:
            s_i = mpos[bo] + 1     # 事件组资格含首突当日(d 收盘确认突破, 当日仍属风险集合)
        elif bo:
            led["l3_bo_not_in_calendar"] += 1
            s_i = min(mpos.get(end, len(mdates)), a_i + 120, len(mdates) - 1)
        else:
            s_i = min(mpos.get(end, len(mdates)), a_i + 120, len(mdates) - 1)  # end 日已退出, 不含
        try:
            dayset = set(load_price_series(full).keys())
        except FileNotFoundError:
            led["l4_price_missing"] += 1
            continue
        pin = pool_in.get(c6, {})
        added_days = []
        for d in mdates[a_i:s_i]:
            if d in dayset and pin.get(d):
                added_days.append(d)
        for d in added_days:
            risk_by_day[d].add(c6)
        per_stock_days[c6] += len(added_days)
        if bo and bo in dayset:
            n_first_break += 1
            bo_days_used += 1
        elif bo:
            # bo 日不在个股价格集: 区分 因子缺失致跳过 vs 行情无该日行
            j = json.load(gzip.open(ROOT / f"data/adjustment_baostock/per_stock/{full}.json.gz", "rt"))
            has_row = any(r[0] == bo for r in j["unadj"])
            led["l6a_bo_day_factor_missing" if has_row else "l6b_bo_day_no_quote_row"] += 1
    # 冻结库全量(5,240)暴露因子缺失(identify 4,760 子集时为0)——不再硬断言,
    # 按九轮复审 P1 精神: 缺失→load_price_series 跳过该日(不生成价格),
    # 缺失规模入台账披露, 不静默
    fac_missing = _mpl._FACTOR_SKIP_COUNT  # 模块对象读当前值
    if fac_missing:
        print(f"[披露] 复权因子缺失行 {fac_missing} (冻结库全量; 相关日已跳过不生成价格)", flush=True)
    n_risk_days = sum(len(s) for s in risk_by_day.values())
    print(f"共同风险集(独立映射): {n_risk_days:,} 股票-日 | 首突 {n_first_break:,} | "
          f"台账 {dict(led)} | {time.time()-t0:.0f}s", flush=True)

    # S3 配对覆盖预检(无结果变量)
    # 事件日: 当日首突(需要每日首突集合)——重扫一遍 bo 日
    event_by_day = defaultdict(set)
    for lid, (code, anchor, bo, end, reason, rc) in seen.items():
        c6 = code.split(".")[-1] if "." in code else code
        if bo and cmap.get(c6) and bo in mpos:
            # 首突日计入事件组当且仅当该股当日仍在共同风险集(资格一致)
            if c6 in risk_by_day.get(bo, set()):
                event_by_day[bo].add(c6)
    paired_days = 0
    paired_days_by_fold = Counter()
    ev_sizes, ctrl_sizes = [], []
    for d, evs in sorted(event_by_day.items()):
        ctrls = risk_by_day[d] - evs          # 对照=同日合格未突破(含此后突破者)
        if len(evs) >= 1 and len(ctrls) >= 10:
            paired_days += 1
            paired_days_by_fold[obs_bucket(d)] += 1
            ev_sizes.append(len(evs))
            ctrl_sizes.append(len(ctrls))
    rep = {
        "audit": "MULTIPERIOD_CONDITION_RISKSET_V2", "date": "2026-09-22",
        "y40_read": False,
        "code_map_source": "frozen per_stock filename keys (independent of identify)",
        "n_frozen_library": len(cmap),
        "n_lifecycles": len(seen), "record_conflicts": conflict,
        "common_riskset_stock_days": n_risk_days,
        "riskset_window_def": "有bo段[anchor,bo](含首突日); 无bo段[anchor,min(end,anchor+120))(不含end日)",
        "n_distinct_risk_days": len(risk_by_day),
        "first_break_in_common_riskset": sum(len(s) for s in event_by_day.values()),
        "first_break_total_incl_outside": n_first_break,
        "attrition_ledger_v2": dict(led),
        "factor_missing_price_rows_disclosed": fac_missing,
        "old_stage0_numbers": {"risk_stock_days_poolin": 294722,
                               "first_break_day_events": 27310,
                               "note": "旧审计结果保留; l1=identify 事件名单映射(结果相关), v2 不再使用"},
        "s3_pairing_precheck": {
            "rule": "配对日=当日首突>=1 且 同日合格对照>=10(不同股票); 对照含此后突破者不剔除",
            "n_paired_days": paired_days,
            "paired_days_by_fold": dict(paired_days_by_fold),
            "event_group_size_p50": float(np.median(ev_sizes)) if ev_sizes else None,
            "event_group_size_max": int(max(ev_sizes)) if ev_sizes else None,
            "ctrl_group_size_p50": float(np.median(ctrl_sizes)) if ctrl_sizes else None,
            "per_stock_risk_days_p50": float(np.median(list(per_stock_days.values()))),
            "per_stock_risk_days_p90": float(np.percentile(list(per_stock_days.values()), 90)),
            "per_stock_risk_days_max": int(max(per_stock_days.values())),
            "note": "每股贡献日分布=S2 双聚类(股票块)校正输入; 无结果变量参与"},
        "factor_missing_handling": f"skipped_not_silent(不默认F=1); 共 {fac_missing} 行已披露",
        "first_break_attrition_v2": dict(led),
    }
    # 缺失分布审计(十轮复审): 按股票/按月/事件组 vs 对照组
    import gzip as _gz
    fac_by_stock = {}
    for f in (ROOT / "data/adjustment_baostock/per_stock").glob("*.json.gz"):
        full = f.name[:-8]
        j = json.load(_gz.open(f, "rt"))
        ft = _mpl._factor_by_code().get(full, {})
        n_missing = sum(1 for r in j["unadj"] if r[0] not in ft)
        if n_missing:
            fac_by_stock[full] = n_missing
    top_stocks = sorted(fac_by_stock.items(), key=lambda kv: -kv[1])[:10]
    # 反向索引: c6 -> 风险集内出现日
    risk_by_day_by_code = defaultdict(set)
    for d, codes in risk_by_day.items():
        for c6 in codes:
            risk_by_day_by_code[c6].add(d)
    # 事件组/对照组当日在共同风险集中但当日价格因缺失被跳过的股票-日
    # (每股一次预计算, 避免逐股票-日重读 json)
    miss_days_by_stock = {}
    for f in (ROOT / "data/adjustment_baostock/per_stock").glob("*.json.gz"):
        full = f.name[:-8]
        j = json.load(_gz.open(f, "rt"))
        ft = _mpl._factor_by_code().get(full, {})
        md = {r[0] for r in j["unadj"] if r[0] not in ft}
        if md:
            miss_days_by_stock[full] = md
    days_by_c6 = {c6: ds for c6, ds in
                  ((k.split(".")[-1], set(v)) for k, v in _mpl._SERIES_CACHE.items())}
    missing_in_riskset = 0
    for full, md in miss_days_by_stock.items():
        c6 = full.split(".")[-1]
        have_days = days_by_c6.get(c6, set())
        for d in risk_by_day_by_code.get(c6, ()):  # 该股在风险集内的日
            if d in md and d not in have_days:
                missing_in_riskset += 1
    rep["factor_missing_dist"] = {
        "n_stocks_with_missing": len(fac_by_stock),
        "top10_stocks": [[k, v] for k, v in top_stocks],
        "riskset_stock_days_with_price_skipped": missing_in_riskset,
        "note": "分布按股票/风险集内股票-日; 事件组首突日缺失见 first_break_attrition_v2.l6a"}
    # Q-B Y40 窗口资格(不读 Y40 数值): d+40 在指数日历内才可能完整
    data_end = mdates[-1]
    win_eligible_days = 0
    win_eligible_in_b19_22 = 0
    paired_in_b19_22 = 0
    for d, evs in sorted(event_by_day.items()):
        ctrls = risk_by_day[d] - evs
        if len(evs) >= 1 and len(ctrls) >= 10:
            if mpos[d] + 40 < len(mdates):
                win_eligible_days += 1
                b = obs_bucket(d)
                if b in (19, 20, 21, 22):
                    win_eligible_in_b19_22 += 1
            if obs_bucket(d) in (19, 20, 21, 22):
                paired_in_b19_22 += 1
    rep["s3_pairing_precheck"]["paired_days_in_b19_22"] = paired_in_b19_22
    rep["s3_pairing_precheck"]["y40_window_eligible_days"] = win_eligible_days
    rep["s3_pairing_precheck"]["y40_window_eligible_in_b19_22"] = win_eligible_in_b19_22
    rep["s3_pairing_precheck"]["y40_note"] = ("窗口资格=配对日且 d+40 在指数日历内(不读 Y40 值); "
                                              "价格级缺失处理沿用 Y40 冻结口径于主检验执行")
    (OUT / "MULTIPERIOD_CONDITION_RISKSET_V2.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"S3 预检: 配对日 {paired_days} | 折分布 {dict(paired_days_by_fold)} | "
          f"每股日 p50/p90/max={rep['s3_pairing_precheck']['per_stock_risk_days_p50']:.0f}/"
          f"{rep['s3_pairing_precheck']['per_stock_risk_days_p90']:.0f}/"
          f"{rep['s3_pairing_precheck']['per_stock_risk_days_max']} | {time.time()-t0:.0f}s", flush=True)
    print(f"→ MULTIPERIOD_CONDITION_RISKSET_V2.json")


if __name__ == "__main__":
    main()
