#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_posneg_path.py — posneg_v1 第一块: path/形态层全量 (2026-09-21).

输入(冻结): lifecycle_stage4_v1_full(T1/T2/T3/end_reason) + adjustment_v1 因子表
            + baostock per_stock + TDX 日历(与 retcalc 同序)
输出: output/research/posneg_v1/path_layer.csv.gz
      每突破 episode(27,422): path_family/subtype/NH/TR/RC/D/E/D_atr/
      buckets/group_eventual/group_asof_20d/structure_broken_asof_20d/cutoff
守恒门禁: group_eventual 四值和==27,422; group_asof_20d 同;
      path_family 六类计数; right_censored(path) 与窗口不完整数一致
"""
import glob
import gzip
import json
import struct
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))

from stock_selector.research.posneg_path import (              # noqa: E402
    EPS, atr_pct_prev, below_break_bucket, classify_path, drawdown_bucket,
    group_asof, group_labels)

SRC = ROOT / "data/adjustment_baostock/per_stock"
OUT = ROOT / "output/research/posneg_v1"


def load_factor_index():
    F = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        next(f)
        for line in f:
            c, d, uc, hc, Fv = line.split(",")
            F.setdefault(c, {})[d] = float(Fv)
    return F


def load_stock(code, Fidx):
    p = json.load(gzip.open(SRC / f"{code}.json.gz", "rt"))
    u = {r[0]: (float(r[1]), float(r[2]), float(r[3]), float(r[4])) for r in p["unadj"]}  # o,h,l,c
    b = Path(f"/root/tdx_data/vipdoc/{code.split('.')[0]}/lday/"
             f"{code.replace('.', '')}.day").read_bytes()
    tdx = []
    for i in range(len(b) // 32):
        d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        tdx.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
    dates = [d for d in tdx if d in u and d in Fidx.get(code, {})]
    if not dates:
        raise ValueError(f"{code} empty calendar")
    return dates, u, Fidx[code]


def main():
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    Fidx = load_factor_index()
    import duckdb
    files = sorted(glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/partitions/*/*.parquet")))
    cur = duckdb.connect().execute(f"""
        SELECT code, lifecycle_id, breakout_day, first_pullback_day,
               reattack_days, end_day, end_reason, right_censored
        FROM read_parquet({files!r}) WHERE breakout_day IS NOT NULL""")
    rows = cur.fetchall()
    print(f"突破段: {len(rows)}", flush=True)

    cache = {}
    out = []
    n_atr_null = 0
    fam_cnt = Counter()
    ge_cnt = Counter()
    ga_cnt = Counter()
    EXCL = set(json.loads((ROOT / "config/adjustment_v1_exclusions.json").read_text())["excluded"])
    n_excl = 0
    for code6, lid, bo, t2, t3s, end_d, end_reason, rc in rows:
        code = ("sh." if str(code6)[0] == "6" else "sz.") + str(code6)
        if code in EXCL or code not in Fidx:
            n_excl += 1
            out.append({"code": code, "lifecycle_id": lid,
                        "breakout_day": str(bo)[:10], "status": "excluded_by_adjustment_decision"})
            continue
        if code not in cache:
            try:
                cache[code] = load_stock(code, Fidx)
            except Exception as e:
                raise RuntimeError(f"非排除股 {code} 加载失败: {e}") from e
        dates, u, Fd = cache[code]
        bo_d = str(bo)[:10]
        if bo_d not in dates or bo_d not in Fd:
            raise RuntimeError(f"{code} 突破日 {bo_d} 不在日历/F表")
        bp = dates.index(bo_d)
        last = len(dates) - 1
        p_bo = u[bo_d][3] * Fd[bo_d]
        window = [u[dates[j]][3] * Fd[dates[j]] for j in range(bp + 1, min(bp + 21, last + 1))]
        complete = bp + 20 <= last
        cp = classify_path(p_bo, window, complete)
        cutoff = dates[bp + 20] if complete else dates[last]
        t3 = str(t3s).split("|")[0] if t3s else None
        ge = group_labels(str(t2)[:10] if t2 else None, t3, bool(rc))
        ga = group_asof(str(t2)[:10] if t2 else None, t3,
                        cutoff if complete else None)
        broken = None
        if end_reason == "structure_break" and str(end_d)[:10] <= cutoff:
            broken = True
        elif complete:
            broken = False
        atrp = atr_pct_prev(dates, bp, {d: u[d][1] for d in dates},
                            {d: u[d][2] for d in dates},
                            {d: u[d][3] for d in dates}, Fd)
        d_atr = (cp["D"] / atrp) if (cp["D"] is not None and atrp) else None
        n_atr_null += d_atr is None
        fam_cnt[cp["family"]] += 1
        ge_cnt[ge] += 1
        ga_cnt[ga] += 1
        out.append({
            "code": code, "lifecycle_id": lid, "breakout_day": bo_d,
            "path_family": cp["family"], "path_subtype": cp["subtype"],
            "NH": cp["NH"], "TR": cp["TR"], "RC": cp["RC"],
            "D": cp["D"], "E": cp["E"], "D_atr": d_atr,
            "drawdown_bucket_abs": drawdown_bucket(cp["D"]) if cp["D"] is not None else None,
            "below_break_bucket_abs": (below_break_bucket(cp["E"])
                                       if cp["family"] == "never_reclaim" else None),
            "group_eventual": ge, "group_asof_20d": ga,
            "structure_broken_asof_20d": broken,
            "cutoff_day": cutoff, "window_complete": complete,
            "P_bo_adj": p_bo,
        })
        if len(out) % 5000 < 1000:
            print(f"[{len(out)}] {time.time()-t0:.0f}s fam={dict(fam_cnt)}", flush=True)

    import csv
    fieldnames = sorted({k for r in out for k in r})
    with gzip.open(OUT / "path_layer.csv.gz", "wt", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out)

    ge_sum = sum(v for k, v in ge_cnt.items())
    ga_sum = sum(v for k, v in ga_cnt.items())
    report = {
        "n_rows": len(out), "n_excluded": n_excl, "n_breakout_evaluated": ge_sum,
        "conservation": {
            "group_eventual_sum": ge_sum, "group_eventual_expected": 27422,
            "group_eventual_detail": dict(ge_cnt),
            "group_asof_20d_sum": ga_sum, "group_asof_detail": dict(ga_cnt),
            "path_family_detail": dict(fam_cnt),
            "pass": ge_sum == 27422 - n_excl and ga_sum == 27422 - n_excl,
            "note": "排除股段(裁决排除)不计标签; 非排除全部恰居一类由构造保证+六情形测试覆盖",
        },
        "n_atr_null": n_atr_null,
        "elapsed_s": round(time.time() - t0, 1),
    }
    (OUT / "PATH_LAYER_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(report["conservation"], ensure_ascii=False)[:400])
    print(f"→ {OUT}/path_layer.csv.gz | ATR null {n_atr_null} | {time.time()-t0:.0f}s")
    sys.exit(0 if report["conservation"]["pass"] else 1)


if __name__ == "__main__":
    main()
