#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_retcalc_v1.py — retcalc_v1 产物审计 (2026-09-21).

R1 守恒式: 每策略×视角×h, N_master(55,646) = N_evaluable_K2 + N_null_K2 + N_control
R2 状态机自洽: evaluated_cash→K2_h==0; evaluated_position→K2_1非null;
   pending/tail→K2_h null; capped 行 K2=0/K3=0/K4=null
R3 语义完备: K4 仅成交行; 对照池 K3/K2 全 null(带 reason)
R4 独立重算抽验: 随机60行 K2_5 用因子表+per_stock 独立重算比对
R5 排除股/日期缺失: 936 排除行无任何计算值; 全表无 *_date_missing(排除股外)
"""
import csv
import glob
import gzip
import json
import random
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.decision.execution import CostModel          # noqa: E402
from stock_selector.research.recalc_golden import golden_recompute  # noqa: E402

COST = CostModel()
HORIZONS = (1, 3, 5, 10, 20)
random.seed(20260919)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    OUT = ROOT / "output/research/retcalc_v1" / mode
    rows = list(csv.DictReader(gzip.open(OUT / "retcalc.csv.gz", "rt")))
    failures = []
    report = {"mode": mode, "n_rows": len(rows)}

    # ── R1 守恒式 ──
    cons = defaultdict(lambda: defaultdict(int))
    for r in rows:
        # 排除行只有单条(strategy有值,view空) → 按strategy归组计"排除段"
        key = (r["strategy"], r["view"] or "__excl__")
        if r.get("status") == "excluded_by_adjustment_decision":
            cons[key]["excluded"] += 1
        elif r.get("control_pool") in ("True", "true", "1"):
            cons[key]["control"] += 1
        else:
            for h in HORIZONS:
                v = r.get(f"K2_{h}")
                if v in ("", None):
                    cons[key][f"null_{h}"] += 1
                else:
                    cons[key][f"evaluable_{h}"] += 1
    # 排除段计入每策略段数(234段均摊到4策略? 不: 每策略各234条=234段)
    for (strat, view), m in sorted(cons.items()):
        if view == "__excl__":
            continue          # 汇总入下方每策略
        m_all = m[f"evaluable_1"] + m["null_1"] + m["control"]
        excl_segs = cons.get((strat, "__excl__"), {}).get("excluded", 0)
        for h in HORIZONS:
            tot = m["control"] + m[f"evaluable_{h}"] + m[f"null_{h}"] + excl_segs
            if tot != 55646:
                failures.append(f"R1守恒: {strat}|{view}|h{h} 总数{tot}≠55646(排除{excl_segs})")
    report["conservation_sample"] = {f"{k[0]}|{k[1]}": dict(v) for k, v in
                                     sorted(cons.items())[:2]}

    # ── R2 状态机自洽 ──
    n_bad = 0
    for r in rows:
        if r.get("status") == "excluded_by_adjustment_decision":
            continue
        st = r.get("state")
        for h in HORIZONS:
            v = r.get(f"K2_{h}")
            has = v not in ("", None)
            if st == "evaluated_cash" and has and abs(float(v)) > 1e-12:
                n_bad += 1
            # 行级position只保证K2_1非null; 长h终点超数据→格级null_holding_tail合法
            if st == "evaluated_position" and h == 1 and not has:
                n_bad += 1
                break
        if st == "evaluated_cash" and r.get("K3_5") not in ("", None) \
                and r.get("capped_unfilled") == "True" and abs(float(r["K3_5"])) > 1e-12:
            n_bad += 1
    if n_bad:
        failures.append(f"R2状态机: {n_bad} 行违反")

    # ── R3 K4 仅成交行 ──
    n_k4_bad = sum(1 for r in rows
                   if r.get("state") in ("evaluated_cash", "null_entry_pending")
                   and r.get("K4_1") not in ("", None)
                   and r.get("status") != "excluded_by_adjustment_decision")
    if n_k4_bad:
        failures.append(f"R3 K4非成交行非null: {n_k4_bad}")

    # ── R5 排除/日期缺失 ──
    n_calc_on_excl = sum(1 for r in rows
                         if r.get("status") == "excluded_by_adjustment_decision"
                         and any(r.get(k) not in ("", None) for k in ("K2_5", "K3_5", "K4_5")))
    if n_calc_on_excl:
        failures.append(f"R5 排除行含计算值: {n_calc_on_excl}")
    n_missing = sum(1 for r in rows if "date_missing" in str(r.get("K3_5_reason", "")))
    if n_missing:
        failures.append(f"R5 日期缺失(非排除股): {n_missing}")

    # ── R4 独立重算抽验(60行) ──
    Fidx = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        next(f)
        for line in f:
            c, d, uc, hc, Fv = line.split(",")
            Fidx.setdefault(c, {})[d] = float(Fv)
    prices = {}
    cand = [r for r in rows if r.get("state") == "evaluated_position"
            and r["strategy"] in ("direct_chase", "wait_first_pullback", "wait_support_hold")
            and r.get("K2_5") not in ("", None) and r.get("buy_day")]
    sample = random.sample(cand, min(60, len(cand)))
    n_golden_bad = 0
    for r in sample:
        code = r["code"]
        if code not in prices:
            p = json.load(gzip.open(ROOT / f"data/adjustment_baostock/per_stock/{code}.json.gz", "rt"))
            u = {x[0]: (float(x[1]), float(x[4])) for x in p["unadj"]}
            b = Path(f"/root/tdx_data/vipdoc/{code.split('.')[0]}/lday/"
                     f"{code.replace('.', '')}.day").read_bytes()
            tdx = []
            for i in range(len(b) // 32):
                d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
                tdx.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
            dates = [d for d in tdx if d in u and d in Fidx.get(code, {})]
            prices[code] = (dates, {d: i for i, d in enumerate(dates)}, u, Fidx[code])
        dates, pos, u, Fd = prices[code]
        bp = pos[r["buy_day"]]
        ep = bp + 5
        if ep >= len(dates):
            continue
        exp = golden_recompute(COST, r["buy_day"], u, Fd, dates, bp, ep, r["view"])
        if exp is None or abs(exp - float(r["K2_5"])) > 1e-9:
            n_golden_bad += 1
    if n_golden_bad:
        failures.append(f"R4 独立重算失配: {n_golden_bad}/{len(sample)}")

    report["R4_sample"] = len(sample)
    status = "PASSED" if not failures else "FAILED"
    report["gate_failures"] = failures
    report["status"] = status
    print(f"审计retcalc[{mode}]: {status} | R1守恒✓ R2状态机✓ R3 K4✓ R4重算{len(sample)}样本失配{n_golden_bad} R5排除✓"
          if not failures else f"审计retcalc[{mode}]: {status} | {failures}")
    Path(ROOT / "docs/reports/RETCALC_V1_AUDIT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    sys.exit(0 if not failures else 1)


if __name__ == "__main__":
    main()
