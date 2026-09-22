#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_multiperiod_background_audit.py — 多周期背景覆盖审计(便宜诊断, 2026-09-21).

目的(用户 2026-09-21 建议): 在四模型(A0/A1/B0/B1)实验前, 先检查突破观察日
当时的月线池/周线结构/周线动能状态分布是否足够丰富, 能否检验背景差异。
若绝大多数事件背景几乎一样 → 明确承认识别范围不足, 不强行细分。

数据源: output/research/momentum_panel_v3(2024-01-02→2026-09-01, 5191 股,
日级; universe_state_panel=月池状态, signal_panel=周线证据)。
观察日状态=面板当日行(重新读取, 不用开段日状态)。
覆盖范围: 测试折 b19-b22(2024H2-2026H1); 桶<=18 面板不含, 仅计数披露。

量价拆分(用户要点): current_momentum 量价混合不可直接入 A1——
- 价格侧候选: weekly_passed(周线双轴通过), momentum_context_positive,
  weekly_base_pattern, weekly_veto, t_eff/l_eff/week_realized_pct(连续)
- 量能侧候选: volume_ratio_vs_prev_week / planned_prorated_volume_ratio(连续)
审计只统计分布, 不建模不检验(避免事后挑选)。
"""
import csv
import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"
from stock_selector.research.identify_features import eligibility_forward_v1  # noqa: E402
from forward_y40_lib import market_calendar  # noqa: E402  (sys.path 由下方加入)

sys.path.insert(0, str(ROOT / "scripts"))

NEED_UNI = ("code", "date", "monthly_pool_state")
NEED_SIG = ("code", "date", "weekly_passed", "weekly_veto", "weekly_base_pattern",
            "momentum_context_positive", "weekly_eligibility_state",
            "t_eff", "l_eff", "week_realized_pct", "prev_week_cc_pct",
            "volume_ratio_vs_prev_week", "planned_prorated_volume_ratio",
            "week_completion")


def fnum(v):
    return float(v) if v not in ("", None) else None


def main():
    t0 = time.time()
    mdates, _ = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    # 1) 事件集合(三时点, 活跃资格; 只统计面板覆盖期内的观察日)
    want = defaultdict(dict)          # code6 -> {date: (stage, y40_flag)}
    events_by_stage = {}
    for stage in ("breakout", "shrink", "stabilization"):
        rows = [r for r in csv.DictReader(gzip.open(OUT / f"identify_{stage}.csv.gz", "rt"))
                if eligibility_forward_v1(r)]
        kept = []
        for r in rows:
            d = r["obs_day"]
            if d in mpos and mpos[d] + 40 < len(mdates) and "2024-07-01" <= d <= "2026-03-31":
                c6 = r["code"].split(".")[-1]
                want[c6][d] = stage
                kept.append(r)
        events_by_stage[stage] = kept
        print(f"{stage}: 面板覆盖期内观察事件 {len(kept)}", flush=True)
    # 2) 扫面板
    uni, sig = {}, {}
    with open(PANEL / "universe_state_panel.csv") as f:
        for r in csv.DictReader(f):
            c6, d = r["code"], r["date"]
            if c6 in want and d in want[c6]:
                uni[(c6, d)] = r["monthly_pool_state"]
    with open(PANEL / "signal_panel.csv") as f:
        for r in csv.DictReader(f):
            c6, d = r["code"], r["date"]
            if c6 in want and d in want[c6]:
                sig[(c6, d)] = r
    print(f"面板命中: 月池 {len(uni)} | 周线证据 {len(sig)} | {time.time()-t0:.0f}s", flush=True)
    # 3) 分布统计(三时点分别 + 合计)
    report = {"audit": "multiperiod_background_coverage_v1",
              "panel": {"range": "2024-01-02→2026-09-01", "manifest": "momentum_panel_v3"},
              "note": ("观察日=面板当日行; b19-b22 且 40 日窗在面板内; "
                       "current_momentum 为量价混合, 拆分价格侧/量能侧分别统计"),
              "stages": {}}
    for stage in ("breakout", "shrink", "stabilization"):
        st = {"n": len(events_by_stage[stage])}
        cnt_m = Counter()
        cnt_wp = Counter(); cnt_wv = Counter(); cnt_bp = Counter()
        cnt_mc = Counter(); cnt_el = Counter()
        t_effs, l_effs, wrp, pv = [], [], [], []
        miss = Counter()
        for r in events_by_stage[stage]:
            c6, d = r["code"].split(".")[-1], r["obs_day"]
            u = uni.get((c6, d))
            if u is None:
                miss["monthly_state_missing"] += 1
            else:
                cnt_m[u] += 1
            srow = sig.get((c6, d))
            if srow is None:
                miss["weekly_evidence_missing"] += 1
                continue
            cnt_wp[srow["weekly_passed"]] += 1
            cnt_wv[srow["weekly_veto"]] += 1
            cnt_bp[srow["weekly_base_pattern"] or "(empty)"] += 1
            cnt_mc[srow["momentum_context_positive"] or "(empty)"] += 1
            cnt_el[srow["weekly_eligibility_state"] or "(empty)"] += 1
            for lst, col in ((t_effs, "t_eff"), (l_effs, "l_eff"),
                             (wrp, "week_realized_pct"), (pv, "volume_ratio_vs_prev_week")):
                v = fnum(srow[col])
                if v is not None:
                    lst.append(v)
        def q(v):
            if not v:
                return None
            a = np.array(v)
            return {"n": len(a), "p5": round(float(np.percentile(a, 5)), 3),
                    "p25": round(float(np.percentile(a, 25)), 3),
                    "p50": round(float(np.percentile(a, 50)), 3),
                    "p75": round(float(np.percentile(a, 75)), 3),
                    "p95": round(float(np.percentile(a, 95)), 3)}
        st.update({
            "monthly_pool_state": dict(cnt_m.most_common()),
            "weekly_passed": dict(cnt_wp.most_common()),
            "weekly_veto": dict(cnt_wv.most_common()),
            "weekly_base_pattern_top10": dict(cnt_bp.most_common(10)),
            "momentum_context_positive": dict(cnt_mc.most_common()),
            "weekly_eligibility_state": dict(cnt_el.most_common()),
            "price_side_continuous": {"t_eff": q(t_effs), "l_eff": q(l_effs),
                                      "week_realized_pct": q(wrp)},
            "volume_side_continuous": {"volume_ratio_vs_prev_week": q(pv)},
            "missing": dict(miss)})
        report["stages"][stage] = st
        print(f"{stage}: 月池 {dict(cnt_m.most_common())} | 周passed {dict(cnt_wp.most_common())} "
              f"| 缺失 {dict(miss)} | {time.time()-t0:.0f}s", flush=True)
    # 4) 交叉: 月池×周passed 格子占比(背景丰富性核心问题)
    cross = Counter()
    for c6, dd in want.items():
        for d in dd:
            u, srow = uni.get((c6, d)), sig.get((c6, d))
            if u and srow:
                cross[(u, srow["weekly_passed"])] += 1
    tot = sum(cross.values())
    report["cross_monthly_x_weekly_passed"] = {
        f"{k[0]}|{k[1]}": {"n": v, "share": round(v / tot, 4)}
        for k, v in cross.most_common()}
    (OUT / "MULTIPERIOD_BACKGROUND_AUDIT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(f"→ MULTIPERIOD_BACKGROUND_AUDIT.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
