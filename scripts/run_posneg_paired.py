#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_posneg_paired.py — posneg_v1 策略配对比较 (spec §3+§6, 2026-09-21).

- 6 策略对 × 5 期限 × 2 视角 × K2/K3; K4 不进总体排名(spec 明令)
- S_AB = 双方可评价交集: K2=四态{position,cash}; K3=K3_h 双方非null
- delta_i = K_A − K_B (episode 级, date_block_key=breakout_day)
- 股票块/日期块各有放回 bootstrap 2000 次, percentile 95% CI
  (块和/块数预计算 + numpy 重抽, 数值同朴素实现)
- 稀疏门禁(裁定点G): n>=100, unique_stocks>=30, unique_dates>=30,
  各套块数>=30; 未达标→只描述不输出更优
- Holm 校正(族=同一 metric×view×h 的 6 对, 双侧, α=0.05);
  primary 通过 = 双块 CI 同向不跨0 AND Holm adj p < 0.05
"""
import csv
import gzip
import json
import sys
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/posneg_v1"
SEED = 20260919
BOOT = 2000
STRATS = ["direct_chase", "staged_entry", "wait_first_pullback", "wait_support_hold"]
HORIZONS = (1, 3, 5, 10, 20)
MIN_EVENTS, MIN_STOCKS, MIN_DATES, MIN_BLOCKS = 100, 30, 30, 30
GATES = {"min_events": MIN_EVENTS, "min_unique_stocks": MIN_STOCKS,
         "min_signal_dates": MIN_DATES, "min_bootstrap_blocks": MIN_BLOCKS,
         "bootstrap_repeats": BOOT, "confidence_level": 0.95,
         "interval_method": "percentile", "random_seed": SEED,
         "date_block_key": "breakout_day",
         "comparison_statistic": "paired_mean_difference"}


def boot_ci(deltas, keys, rng):
    """块和/块数预计算的有放回 bootstrap mean; percentile 95% CI + 双侧p."""
    agg = defaultdict(lambda: [0.0, 0])
    for d, k in zip(deltas, keys):
        a = agg[k]
        a[0] += d
        a[1] += 1
    sums = np.array([v[0] for v in agg.values()])
    cnts = np.array([v[1] for v in agg.values()], dtype=np.int64)
    nb = len(sums)
    idx = rng.integers(0, nb, size=(BOOT, nb))
    means = sums[idx].sum(axis=1) / cnts[idx].sum(axis=1)
    lo, hi = np.percentile(means, 2.5), np.percentile(means, 97.5)
    p = 2 * min(float((means <= 0).mean()), float((means >= 0).mean()))
    return float(lo), float(hi), min(p, 1.0), nb


def main():
    t0 = time.time()
    rows = list(csv.DictReader(gzip.open(OUT.parent / "retcalc_v1/full/retcalc.csv.gz", "rt")))
    path = {r["lifecycle_id"]: r for r in
            csv.DictReader(gzip.open(OUT / "path_layer.csv.gz", "rt"))}
    # episode 级载入: (view, strategy, metric, h) → {lid: value/None}
    # K2 可评价 = state∈{position,cash}; K3 可评价 = K3_h 非 null
    val = {v: {s: {} for s in STRATS} for v in ("close", "next")}
    for r in rows:
        if r.get("status") == "excluded_by_adjustment_decision":
            continue
        if r.get("control_pool") in ("True", "true", "1"):
            continue
        v, s = r["view"], r["strategy"]
        lid = r["lifecycle_id"]
        st_ok = r.get("state") in ("evaluated_position", "evaluated_cash")
        for h in HORIZONS:
            k2 = r.get(f"K2_{h}")
            val[v][s][("K2", h, lid)] = (float(k2) if (st_ok and k2 not in ("", None)) else None)
            k3 = r.get(f"K3_{h}")
            val[v][s][("K3", h, lid)] = (float(k3) if k3 not in ("", None) else None)
    # 突破段属性(code/breakout_day)一次性
    eps = {lid: (pl["code"], pl["breakout_day"]) for lid, pl in path.items()
           if pl.get("breakout_day")}
    print(f"载入 {time.time()-t0:.0f}s, 突破段 {len(eps)}", flush=True)

    results = []
    for view in ("close", "next"):
        for metric in ("K2", "K3"):
            for h in HORIZONS:
                fam = []
                per = {s: val[view][s] for s in STRATS}
                for a, b in combinations(STRATS, 2):
                    deltas, kc, kd = [], [], []
                    for lid in eps:
                        va = per[a].get((metric, h, lid))
                        vb = per[b].get((metric, h, lid))
                        if va is None or vb is None:
                            continue
                        deltas.append(va - vb)
                        c, d = eps[lid]
                        kc.append(c)
                        kd.append(d)
                    n = len(deltas)
                    rec = {"view": view, "metric": metric, "h": h, "pair": f"{a}|{b}",
                           "n_S_AB": n, "unique_stocks": len(set(kc)),
                           "unique_dates": len(set(kd)),
                           "mean_delta": (sum(deltas) / n) if n else None,
                           "n_K4_note": "K4 条件成交样本不进总体排名(spec 边界)"}
                    gate = (n >= MIN_EVENTS and len(set(kc)) >= MIN_STOCKS
                            and len(set(kd)) >= MIN_DATES)
                    if gate:
                        rng = np.random.default_rng(SEED + (1 if view == "close" else 2))
                        lo_c, hi_c, p_c, nb_c = boot_ci(deltas, kc, rng)
                        rng = np.random.default_rng(SEED + (3 if view == "close" else 4))
                        lo_d, hi_d, p_d, nb_d = boot_ci(deltas, kd, rng)
                        gate = gate and nb_c >= MIN_BLOCKS and nb_d >= MIN_BLOCKS
                        rec.update({"ci_stock_lo": lo_c, "ci_stock_hi": hi_c,
                                    "ci_date_lo": lo_d, "ci_date_hi": hi_d,
                                    "p_stock": p_c, "p_date": p_d,
                                    "n_stock_blocks": nb_c, "n_date_blocks": nb_d})
                        fam.append((rec, p_c, p_d, max(p_c, p_d)))
                    else:
                        fam.append((rec, None, None, None))   # 不可检验: 占位不拒绝
                    rec["sparse_gate_pass"] = gate
                    results.append(rec)
                # 合成 p = max(p_stock, p_date): 双块同时支持才显著(交集≤单块)
                # Holm 族固定 6 对: 稀疏不可检验的对 adj=1(不拒绝), 不缩小族
                fam.sort(key=lambda x: x[3] if x[3] is not None else 2.0)
                m = len(STRATS) * (len(STRATS) - 1) // 2       # 恒 6
                run_max = 0.0
                for rank, (rec, p_c, p_d, _pcomb) in enumerate(fam):
                    p = max(p_c, p_d) if (p_c is not None and p_d is not None) else 1.0
                    run_max = max(run_max, (m - rank) * p)
                    adj = min(1.0, run_max)
                    rec["p_combined"] = p
                    rec["holm_adj_p"] = adj
                    both_ci = (rec.get("ci_stock_lo") is not None
                               and ((rec["ci_stock_lo"] > 0 and rec["ci_date_lo"] > 0)
                                    or (rec["ci_stock_hi"] < 0 and rec["ci_date_hi"] < 0)))
                    rec["primary_pass"] = bool(rec["sparse_gate_pass"] and both_ci and adj < 0.05)
                    # spec §7: 复权验证通过前(现 audit_passed_with_exception)
                    # 分析层不输出"最优策略"结论字段 → 不设 better/胜者字段;
                    # 方向信息保留在双侧区间(lo>0 或 hi<0)供人工解读
                    rec["direction"] = None
                    if rec["primary_pass"]:
                        rec["direction"] = ("A>B" if (rec["ci_stock_lo"] > 0 and rec["ci_date_lo"] > 0)
                                            else "A<B")
                        rec["primary_note"] = "统计通过; 开发样本待时间外验证; 因子层 exception 未闭合, 暂不发布更优结论"
                    else:
                        rec["primary_note"] = ("sparse_gate_fail" if not rec["sparse_gate_pass"]
                                               else "CI跨0或Holm未过, 仅描述")
        print(f"[{view}] {time.time()-t0:.0f}s", flush=True)

    with open(OUT / "posneg_paired.json", "w") as f:
        json.dump({"gates": GATES, "results": results}, f, ensure_ascii=False, indent=1)
    npass = sum(1 for r in results if r.get("primary_pass"))
    print(f"配对比较: {len(results)} 格 | primary 通过 {npass} | {time.time()-t0:.0f}s")
    print(f"→ {OUT}/posneg_paired.json")


if __name__ == "__main__":
    main()
