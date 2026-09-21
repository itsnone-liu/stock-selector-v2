#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_posneg_panel.py — posneg_panel + posneg_summary (spec §7, 2026-09-21).

posneg_panel = retcalc_v1 全部行 × path 层(episode 级) + strategy + view
    + R_net(因子比式, 即 K2/K3/K4 列) + 行级四态 + 口径专属 completion:
      K3 → window_complete(突破锚定 outcome_20d_complete 同源);
      K2/K4 → 四态状态机(K2 state 列); excluded/对照池行如实携带标记
posneg_summary = 形态(group_asof_20d/group_eventual)×path_family×策略×视角
    ×期限 的 K2/K3 效应量与计数(探索性分层, 主标签=group_asof_20d);
    删失率逐格披露; K4 仅计数不比较
"""
import csv
import gzip
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/posneg_v1"
HORIZONS = (1, 3, 5, 10, 20)


def main():
    t0 = time.time()
    path = {r["lifecycle_id"]: r for r in
            csv.DictReader(gzip.open(OUT / "path_layer.csv.gz", "rt"))}
    PATH_FIELDS = ["path_family", "path_subtype", "D", "E", "D_atr",
                   "drawdown_bucket_abs", "below_break_bucket_abs",
                   "group_eventual", "group_asof_20d",
                   "structure_broken_asof_20d", "cutoff_day", "window_complete"]
    n_out = 0
    with gzip.open(OUT / "posneg_panel.csv.gz", "wt", newline="") as fo:
        w = None
        with gzip.open(OUT.parent / "retcalc_v1/full/retcalc.csv.gz", "rt") as fi:
            for r in csv.DictReader(fi):
                pl = path.get(r["lifecycle_id"], {})
                for f in PATH_FIELDS:
                    r[f] = pl.get(f, "")
                # 逐期限完成状态(h 级): K2 可评价=四态{position,cash} 且 K2_h 值在;
                # K3/K4 可评价=对应值非 null; 未完成即该期限删失
                st = r.get("state", "")
                st_ok = st in ("evaluated_position", "evaluated_cash")
                for h in HORIZONS:
                    r[f"K2_{h}_eval"] = st_ok and r.get(f"K2_{h}") not in ("", None)
                    r[f"K3_{h}_eval"] = r.get(f"K3_{h}") not in ("", None)
                    r[f"K4_{h}_eval"] = r.get(f"K4_{h}") not in ("", None)
                if w is None:
                    w = csv.DictWriter(fo, fieldnames=list(r.keys()))
                    w.writeheader()
                w.writerow(r)
                n_out += 1
    print(f"panel: {n_out} 行 {time.time()-t0:.0f}s", flush=True)

    # summary: 分层聚合(主标签 group_asof_20d; 附 group_eventual)
    agg = defaultdict(lambda: {"n": 0, "n_pos_state": 0, "n_cash": 0,
                               "n_tail": 0, "n_pending": 0,
                               "sum": defaultdict(float), "n_eval": defaultdict(int)})
    with gzip.open(OUT / "posneg_panel.csv.gz", "rt") as f:
        for r in csv.DictReader(f):
            if r.get("status") == "excluded_by_adjustment_decision":
                continue
            if r.get("control_pool") in ("True", "true", "1"):
                continue                       # 对照池不进策略比较分层
            key = (r["group_asof_20d"] or "unknown", r["path_family"] or "none",
                   r["strategy"], r["view"])
            a = agg[key]
            a["n"] += 1
            st = r.get("state")
            if st == "evaluated_position":
                a["n_pos_state"] += 1
            elif st == "evaluated_cash":
                a["n_cash"] += 1
            elif st == "null_holding_tail":
                a["n_tail"] += 1
            elif st == "null_entry_pending":
                a["n_pending"] += 1
            for h in HORIZONS:
                v2 = r.get(f"K2_{h}")
                st_ok = st in ("evaluated_position", "evaluated_cash")
                if st_ok and v2 not in ("", None):
                    a["sum"][("K2", h)] += float(v2)
                    a["n_eval"][("K2", h)] += 1
                v3 = r.get(f"K3_{h}")
                if v3 not in ("", None):
                    a["sum"][("K3", h)] += float(v3)
                    a["n_eval"][("K3", h)] += 1
                v4 = r.get(f"K4_{h}")        # K4 条件成交: 仅计数不比较
                if v4 not in ("", None):
                    a["n_eval"][("K4", h)] += 1
    summary = []
    for (g, fam, s, v), a in sorted(agg.items()):
        # K4 口径拆分(2026-09-21 复审): 成交率分母=全部;
        # 成交内窗口删失率分母=已成交(position+tail), 未成交不混入
        n_filled = a["n_pos_state"] + a["n_tail"]
        row = {"group_asof_20d": g, "path_family": fam, "strategy": s, "view": v,
               "n": a["n"], "n_position": a["n_pos_state"], "n_cash": a["n_cash"],
               "n_tail": a["n_tail"], "n_pending": a["n_pending"],
               "fill_rate": n_filled / a["n"] if a["n"] else None}
        for h in HORIZONS:
            n2, s2 = a["n_eval"][("K2", h)], a["sum"][("K2", h)]
            n3, s3 = a["n_eval"][("K3", h)], a["sum"][("K3", h)]
            row[f"K2_mean_{h}"] = s2 / n2 if n2 else None
            row[f"K2_n_{h}"] = n2
            row[f"censored_rate_K2_{h}"] = 1 - n2 / a["n"] if a["n"] else None
            row[f"K3_mean_{h}"] = s3 / n3 if n3 else None
            row[f"K3_n_{h}"] = n3
            row[f"K4_n_{h}"] = a["n_eval"][("K4", h)]
            row[f"censored_rate_K3_{h}"] = 1 - n3 / a["n"] if a["n"] else None
            row[f"K4_window_censored_rate_{h}"] = (
                1 - a["n_eval"][("K4", h)] / n_filled) if n_filled else None
        row["exploratory"] = True      # 分层为探索性; 无区间不比较
        summary.append(row)
    with open(OUT / "posneg_summary.json", "w") as f:
        json.dump({"layers": "group_asof_20d × path_family × strategy × view",
                   "rows": summary, "note": "K4 条件成交样本仅计数不比较; 分层探索性无区间",
                   "adjustment_exception": "因子层 audit_passed_with_exception 未闭合, 不发布最优结论"},
                  f, ensure_ascii=False, indent=1)
    print(f"summary: {len(summary)} 格 | {time.time()-t0:.0f}s → posneg_summary.json")


if __name__ == "__main__":
    main()
