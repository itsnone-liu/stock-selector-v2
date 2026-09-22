#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_multiperiod_alignment.py — 多周期设计前置对齐审计 v1.1(2026-09-22).

遵用户复审: 以已封存 forward_y40_association_v1 主分析事件(不截断)为左表,
核对观察日背景面板匹配率/缺失率/各折分布, 并检查面板股票库与冻结库覆盖关系。
口径: ①阶段事件数(分时点计数, 同股同日多阶段各计一次) ②股票-日期组合数
(交叉表分母)——两者分开报告不混称事件总数。
"""
import csv
import gzip
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research.identify_features import eligibility_forward_v1  # noqa: E402
from forward_y40_lib import market_calendar, fold_start, obs_bucket  # noqa: E402

FOLDS = (19, 20, 21, 22)


def main():
    t0 = time.time()
    mdates, _ = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    # 1) 左表: 主分析事件(全部活跃资格, 无日期截断)
    events = {}
    for stage in ("breakout", "shrink", "stabilization"):
        rows = [r for r in csv.DictReader(gzip.open(OUT / f"identify_{stage}.csv.gz", "rt"))
                if eligibility_forward_v1(r)]
        events[stage] = rows
        print(f"{stage}: 主分析事件 {len(rows)}", flush=True)
    # 面板覆盖期
    import datetime as dt
    p_lo, p_hi = "2024-01-02", "2026-09-01"
    # 2) 面板股票库覆盖
    panel_codes = set()
    with open(PANEL / "universe_state_panel.csv") as f:
        for r in csv.DictReader(f):
            panel_codes.add(r["code"])
            if len(panel_codes) % 500000 == 0:
                pass
    # 冻结股票库: identify 文件中出现的全部 code(主分析+非主分析)
    frozen_codes = set()
    for stage in ("breakout", "shrink", "stabilization"):
        with gzip.open(OUT / f"identify_{stage}.csv.gz", "rt") as f:
            for r in csv.DictReader(f):
                frozen_codes.add(r["code"].split(".")[-1])
    inter = frozen_codes & panel_codes
    print(f"股票库: 面板 {len(panel_codes)} | 冻结(identify 全 code) {len(frozen_codes)} | 交集 {len(inter)}"
          f" | 冻结不在面板 {len(frozen_codes - panel_codes)} | {time.time()-t0:.0f}s", flush=True)
    # 3) 观察日匹配(左表事件 → 面板当日行)
    want = defaultdict(set)   # code6 -> {date}
    for stage, rows in events.items():
        for r in rows:
            want[r["code"].split(".")[-1]].add(r["obs_day"])
    uni, sig = {}, {}
    with open(PANEL / "universe_state_panel.csv") as f:
        for r in csv.DictReader(f):
            c6, d = r["code"], r["date"]
            if d in want.get(c6, ()):
                uni[(c6, d)] = r["monthly_pool_state"]
    with open(PANEL / "signal_panel.csv") as f:
        for r in csv.DictReader(f):
            c6, d = r["code"], r["date"]
            if d in want.get(c6, ()):
                sig[(c6, d)] = True
    print(f"面板行命中: 月池 {len(uni)} | 周线 {len(sig)} | {time.time()-t0:.0f}s", flush=True)
    # 4) 口径+分折
    report = {"audit": "multiperiod_alignment_v1_1", "panel": {"range": f"{p_lo}→{p_hi}"}}
    stock_days = set()
    n_ev = {}
    fold_stat = defaultdict(Counter)   # (stage) -> Counter by bucket
    oor = Counter()
    miss = defaultdict(Counter)
    for stage, rows in events.items():
        n_ev[stage] = len(rows)
        for r in rows:
            c6, d = r["code"].split(".")[-1], r["obs_day"]
            stock_days.add((c6, d))
            in_panel_range = p_lo <= d <= p_hi
            if not in_panel_range:
                oor[stage] += 1
                continue
            b = obs_bucket(d)
            fold_stat[stage][b] += 1
            if (c6, d) not in uni:
                miss[stage]["monthly_row_missing"] += 1
            if (c6, d) not in sig:
                miss[stage]["signal_row_missing"] += 1
    report["counts"] = {
        "stage_events": n_ev, "stage_events_sum": sum(n_ev.values()),
        "stock_day_pairs": len(stock_days),
        "note": "阶段事件=分时点计数; 股票-日期组合=去重分母(交叉表用); 不混称"}
    report["out_of_panel_range"] = {k: v for k, v in oor.items()}
    report["fold_distribution_b19_b22"] = {
        st: {f"b{b}": fold_stat[st].get(b, 0) for b in FOLDS} for st in fold_stat}
    report["in_range_missing"] = {st: dict(m) for st, m in miss.items()}
    report["coverage"] = {
        "panel_codes": len(panel_codes), "frozen_codes": len(frozen_codes),
        "intersection": len(inter), "frozen_not_in_panel": len(frozen_codes - panel_codes),
        "panel_not_in_frozen": len(panel_codes - frozen_codes)}
    (OUT / "MULTIPERIOD_ALIGNMENT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report["counts"], ensure_ascii=False))
    print(json.dumps(report["fold_distribution_b19_b22"], ensure_ascii=False))
    print(json.dumps(report["in_range_missing"], ensure_ascii=False))
    print(json.dumps(report["out_of_panel_range"], ensure_ascii=False))
    print(f"→ MULTIPERIOD_ALIGNMENT.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
