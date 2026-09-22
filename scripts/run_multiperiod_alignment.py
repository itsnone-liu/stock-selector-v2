#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_multiperiod_alignment.py — 多周期设计前置对齐审计 v1.1(2026-09-22).

遵用户复审(2026-09-22 二轮): 以 build_events() 主样本(完整窗口, 排除末端
删失与停牌近似)为左表; 61,807 条资格总体(eligibility_forward_v1)单独统计。
口径: ①阶段事件数(分时点计数) ②股票-日期组合数(去重分母)——分开报告。
identify_codes(非冻结股票清单)改名, 冻结库对账另行读取真实清单。
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
    # 1) 左表: build_events() 主样本(完整窗口主分析; 停牌近似/末端删失另行计数)
    from forward_y40_lib import build_events
    events, eligible_n = {}, {}
    for stage in ("breakout", "shrink", "stabilization"):
        main, sens, censored = build_events(stage)
        rows_all = [r for r in csv.DictReader(gzip.open(OUT / f"identify_{stage}.csv.gz", "rt"))
                    if eligibility_forward_v1(r)]
        eligible_n[stage] = len(rows_all)
        events[stage] = main
        print(f"{stage}: 主样本 {len(main)} | 资格总体 {len(rows_all)} | "
              f"停牌近似 {len(sens)} | 末端删失 {len(censored)}", flush=True)
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
    # identify_codes: identify 文件出现的 code(非冻结股票清单, 仅覆盖核对用)
    identify_codes = set()
    for stage in ("breakout", "shrink", "stabilization"):
        with gzip.open(OUT / f"identify_{stage}.csv.gz", "rt") as f:
            for r in csv.DictReader(f):
                identify_codes.add(r["code"].split(".")[-1])
    inter = identify_codes & panel_codes
    print(f"股票覆盖: 面板 {len(panel_codes)} | identify_codes {len(identify_codes)} | 交集 {len(inter)}"
          f" | identify 不在面板 {len(identify_codes - panel_codes)} | {time.time()-t0:.0f}s", flush=True)
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
        "stage_events_main": n_ev, "stage_events_main_sum": sum(n_ev.values()),
        "stage_events_eligible": eligible_n,
        "stage_events_eligible_sum": sum(eligible_n.values()),
        "stock_day_pairs": len(stock_days),
        "note": ("主样本=build_events 完整窗口; 资格总体=eligibility_forward_v1 全量"
                 "(含末端删失+停牌近似); 阶段事件分时点计数; 股票-日期组合=去重分母")}
    report["out_of_panel_range"] = {k: v for k, v in oor.items()}
    report["fold_distribution_b19_b22"] = {
        st: {f"b{b}": fold_stat[st].get(b, 0) for b in FOLDS} for st in fold_stat}
    report["in_range_missing"] = {st: dict(m) for st, m in miss.items()}
    report["coverage"] = {
        "panel_codes": len(panel_codes), "identify_codes": len(identify_codes),
        "intersection": len(inter), "identify_not_in_panel": len(identify_codes - panel_codes),
        "panel_not_in_identify": len(panel_codes - identify_codes),
        "note": "identify_codes≠冻结股票清单(5,240); 库级对账需读真实冻结清单, 本审计未做"}
    (OUT / "MULTIPERIOD_ALIGNMENT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report["counts"], ensure_ascii=False))
    print(json.dumps(report["fold_distribution_b19_b22"], ensure_ascii=False))
    print(json.dumps(report["in_range_missing"], ensure_ascii=False))
    print(json.dumps(report["out_of_panel_range"], ensure_ascii=False))
    print(f"→ MULTIPERIOD_ALIGNMENT.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
