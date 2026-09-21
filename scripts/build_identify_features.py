#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_identify_features.py — identify 三时点数据集 (spec §4, 2026-09-21).

时点1 identify_breakout_day: 全部突破段, 观察日=breakout_day
时点2 identify_first_shrink_day: 有 first_pullback_day 的段, 观察日=该日
        (首个缩量回调日; 只加当日缩量/支撑距离, 禁止止跌确认信息)
时点3 identify_stabilization_day: wait_support_hold close 视角实际成交段,
        观察日=fill_date_close(止跌确认日; 加当日确认信号)
标签(仅结果列): path_family/subtype/D/E/D_atr/group_*/structure_broken;
        行情基准 = path 层窗口(P_adj), 与特征隔离
切分: split_bucket = split_semiannual(breakout_day)(0=2015H1);
      全部行标 dev_sample=True(开发样本, 时间外验证用)
"""
import csv
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
OUT = ROOT / "output/research/posneg_v1"

from stock_selector.research.identify_features import (   # noqa: E402
    ObsFrame, feat_breakout, feat_shrink, feat_stabilization, split_semiannual)

SRC = ROOT / "data/adjustment_baostock/per_stock"


def load_stock(code, Fidx):
    p = json.load(gzip.open(SRC / f"{code}.json.gz", "rt"))
    u, n_vmiss = {}, 0
    for r in p["unadj"]:                            # o,h,l,c,v
        u[r[0]] = (float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                   float(r[5]) if r[5] else 0.0)
        if not r[5]:
            n_vmiss += 1
    p["_n_vol_missing"] = n_vmiss                   # 披露: 停牌/缺失行置0
    b = Path(f"/root/tdx_data/vipdoc/{code.split('.')[0]}/lday/"
             f"{code.replace('.', '')}.day").read_bytes()
    tdx = []
    for i in range(len(b) // 32):
        d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        tdx.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
    dates = [d for d in tdx if d in u and d in Fidx.get(code, {})]
    if not dates:
        raise ValueError(f"{code} empty calendar")
    return dates, u, Fidx[code], p.get("_n_vol_missing", 0)


def main():
    t0 = time.time()
    F = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        next(f)
        for line in f:
            c, d, uc, hc, Fv = line.split(",")
            F.setdefault(c, {})[d] = float(Fv)

    import duckdb
    lfiles = sorted(glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/partitions/*/*.parquet")))
    life = {}
    for code6, lid, bo, t2, ps, mg in duckdb.connect().execute(f"""
            SELECT code, lifecycle_id, breakout_day, first_pullback_day,
                   preparation_start, max_gain_from_anchor_pct
            FROM read_parquet({lfiles!r}) WHERE breakout_day IS NOT NULL""").fetchall():
        life[lid] = (("sh." if str(code6)[0] == "6" else "sz.") + str(code6),
                     str(bo)[:10], str(t2)[:10] if t2 else None,
                     (str(ps)[:10] if ps else None), mg)
    v5f = sorted(glob.glob(str(ROOT / "output/research/lifecycle_v1/entry_replay_v5_full/partitions/*/*.parquet")))
    stab = {}
    for lid, fd in duckdb.connect().execute(f"""
            SELECT lifecycle_id, fill_date_close FROM read_parquet({v5f!r})
            WHERE strategy='wait_support_hold' AND fill_status_close='filled'""").fetchall():
        stab[lid] = str(fd)[:10]

    path = {r["lifecycle_id"]: r for r in
            csv.DictReader(gzip.open(OUT / "path_layer.csv.gz", "rt"))}
    EXCL = set(json.loads((ROOT / "config/adjustment_v1_exclusions.json").read_text())["excluded"])
    print(f"载入 {time.time()-t0:.0f}s: 段 {len(life)} 确认段 {len(stab)}", flush=True)

    rows = {"breakout": [], "shrink": [], "stabilization": []}
    miss_f = []
    cache = {}
    vol_missing_total = [0]
    for lid, pl in path.items():
        if pl.get("status"):
            continue
        code, bo_d, t2_d, ps_d, mg = life[lid]
        if code in EXCL:
            continue
        if code not in F:
            miss_f.append(code)
            continue
        if code not in cache:
            cache[code] = load_stock(code, F)
        dates, u, Fd, nvm = cache[code]
        vol_missing_total[0] += nvm
        if bo_d not in dates:
            raise RuntimeError(f"{code} {lid} 突破日不在日历")
        bp = dates.index(bo_d)
        label = {
            "lifecycle_id": lid, "code": code, "breakout_day": bo_d,
            "path_family": pl["path_family"], "path_subtype": pl["path_subtype"],
            "D": pl["D"], "E": pl["E"], "D_atr": pl["D_atr"],
            "group_eventual": pl["group_eventual"], "group_asof_20d": pl["group_asof_20d"],
            "structure_broken_asof_20d": pl["structure_broken_asof_20d"],
            "split_bucket": split_semiannual(bo_d), "dev_sample": True,
        }
        dO = {d: u[d][0] for d in dates}
        dH = {d: u[d][1] for d in dates}
        dL = {d: u[d][2] for d in dates}
        dC = {d: u[d][3] for d in dates}
        dV = {d: u[d][4] for d in dates}
        prep_days = ((dates.index(ps_d) - dates.index(bo_d)) if (ps_d and ps_d in dates) else None)
        # 时点1
        fr = ObsFrame(dates, bp, dO, dH, dL, dC, dV, Fd)
        rows["breakout"].append({**label, "obs_day": bo_d,
                                 **feat_breakout(fr, prep_days, mg)})
        # 时点2
        if t2_d and t2_d in dates:
            sp = dates.index(t2_d)
            post_hi = max(dC[d] for d in dates[bp + 1:sp + 1]) if sp > bp else None
            fr2 = ObsFrame(dates, sp, dO, dH, dL, dC, dV, Fd)
            rows["shrink"].append({**label, "obs_day": t2_d,
                                   **feat_shrink(fr2, dC[bo_d], bp, post_hi)})
            # 时点3
            fd = stab.get(lid)
            if fd and fd in dates and dates.index(fd) >= sp:
                fp = dates.index(fd)
                plow = min(dL[d] for d in dates[sp:fp + 1])
                fr3 = ObsFrame(dates, fp, dO, dH, dL, dC, dV, Fd)
                rows["stabilization"].append({**label, "obs_day": fd,
                                              **feat_stabilization(fr3, dC[bo_d], plow)})
        if (len(rows["breakout"]) % 6000) < 1:
            print(f"[{len(rows['breakout'])}] {time.time()-t0:.0f}s", flush=True)

    if miss_f:
        raise RuntimeError(f"因子缺失非排除股: {sorted(set(miss_f))[:10]}")
    n_vol_missing = sum(c[3] for c in cache.values())
    report = {}
    for name, rs in rows.items():
        flds = sorted({k for r in rs for k in r})
        with gzip.open(OUT / f"identify_{name}.csv.gz", "wt", newline="") as f:
            w = csv.DictWriter(f, fieldnames=flds)
            w.writeheader()
            w.writerows(rs)
        buckets = Counter(r["split_bucket"] for r in rs)
        report[name] = {"n": len(rs), "split_buckets": dict(sorted(buckets.items())),
                        "path_families": dict(Counter(r["path_family"] for r in rs))}
    report["volume_missing_rows_filled_zero"] = vol_missing_total[0]
    report["note"] = ("dev_sample=True 全部; 逐半年滚动时间外验证: "
                      "train<=bucket_k, test=bucket_k+1; 标签仅结果列")
    (OUT / "IDENTIFY_BUILD_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["n"] for k, v in report.items() if isinstance(v, dict)}, ensure_ascii=False))
    print(f"→ identify_{{breakout,shrink,stabilization}}.csv.gz | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
