#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_identify_features.py — identify 三时点数据集 (spec §4, 2026-09-21 修订).

复审修订(2026-09-21 第二轮):
- 删除未来最高价特征 max_gain_from_anchor(生命周期终结才可知=泄漏)
- prep_days = 突破日 − 准备期起点(正数, 方向修正)
- 特征一律复权价 P_adj=raw×F(ObsFrame 内完成)
- 标签可获得日双重门禁: split_bucket 按 label_available_day(=path cutoff)
- volume 缺失≠真实零量: 行级 obs_vol_missing 标记; 唯一股级+观察行级统计
时点:
- breakout: 全部突破段(观察日=breakout_day)
- shrink: 有 first_pullback_day 段(观察日=该日; 无止跌确认信息)
- stabilization: wait_support_hold close 成交段(观察日=fill_date_close)
标签(path_*/D/E/group_*/structure_broken)仅结果列。dev_sample=True 全标。
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
    """→ (dates, u, Fd, n_vol_missing, vol_missing_days)."""
    p = json.load(gzip.open(SRC / f"{code}.json.gz", "rt"))
    u, n_vmiss, miss = {}, 0, {}
    for r in p["unadj"]:                            # o,h,l,c,v
        vm = not r[5]                               # 缺失≠真实零量
        u[r[0]] = (float(r[1]), float(r[2]), float(r[3]), float(r[4]),
                   0.0 if vm else float(r[5]))
        if vm:
            n_vmiss += 1
            miss[r[0]] = True
    b = Path(f"/root/tdx_data/vipdoc/{code.split('.')[0]}/lday/"
             f"{code.replace('.', '')}.day").read_bytes()
    tdx = []
    for i in range(len(b) // 32):
        d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        tdx.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
    Fd = Fidx.get(code, {})
    dates = [d for d in tdx if d in u and d in Fd]
    if not dates:
        raise ValueError(f"{code} empty calendar")
    return dates, u, Fd, n_vmiss, miss


def process_episode(lid, pl, life_row, stab_fd, cache_row):
    """单 episode 三时点构造(独立可测: 端到端未来篡改验证入口).

    life_row=(code, breakout_day, first_pullback_day, prep_start)
    cache_row=(dates, u, Fd, n_vol_missing, vol_missing_days)
    返回 {"breakout": row, "shrink": row|None, "stabilization": row|None}
    """
    code, bo_d, t2_d, ps_d = life_row
    dates, u, Fd, _nvm, vmd = cache_row
    if bo_d not in dates:
        raise RuntimeError(f"{code} {lid} 突破日不在日历")
    bp = dates.index(bo_d)
    la_day = pl["cutoff_day"]                        # 标签可获得日(双重门禁)
    label = {
        "lifecycle_id": lid, "code": code, "breakout_day": bo_d,
        "label_available_day": la_day,
        "path_family": pl["path_family"], "path_subtype": pl["path_subtype"],
        "D": pl["D"], "E": pl["E"], "D_atr": pl["D_atr"],
        "group_eventual": pl["group_eventual"], "group_asof_20d": pl["group_asof_20d"],
        "structure_broken_asof_20d": pl["structure_broken_asof_20d"],
        "split_bucket": split_semiannual(la_day), "dev_sample": True,
    }
    dO = {d: u[d][0] for d in dates}
    dH = {d: u[d][1] for d in dates}
    dL = {d: u[d][2] for d in dates}
    dC = {d: u[d][3] for d in dates}
    dV = {d: u[d][4] for d in dates}
    prep_days = ((bp - dates.index(ps_d)) if (ps_d and ps_d in dates) else None)  # bo−ps 正数
    r1 = ObsFrame(dates, bp, dO, dH, dL, dC, dV, Fd)
    row1 = {**label, "obs_day": bo_d, "obs_vol_missing": bool(vmd.get(bo_d)),
            **feat_breakout(r1, prep_days)}
    row2 = row3 = None
    if t2_d and t2_d in dates:
        sp = dates.index(t2_d)
        post_hi = max(dC[d] for d in dates[bp + 1:sp + 1]) if sp > bp else None
        r2 = ObsFrame(dates, sp, dO, dH, dL, dC, dV, Fd)
        row2 = {**label, "obs_day": t2_d, "obs_vol_missing": bool(vmd.get(t2_d)),
                **feat_shrink(r2, dC[bo_d], bp, post_hi)}
        if stab_fd and stab_fd in dates and dates.index(stab_fd) >= sp:
            fp = dates.index(stab_fd)
            plow = min(dL[d] for d in dates[sp:fp + 1])
            r3 = ObsFrame(dates, fp, dO, dH, dL, dC, dV, Fd)
            row3 = {**label, "obs_day": stab_fd, "obs_vol_missing": bool(vmd.get(stab_fd)),
                    **feat_stabilization(r3, dC[bo_d], plow)}
    return {"breakout": row1, "shrink": row2, "stabilization": row3}


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
    for code6, lid, bo, t2, ps in duckdb.connect().execute(f"""
            SELECT code, lifecycle_id, breakout_day, first_pullback_day,
                   preparation_start
            FROM read_parquet({lfiles!r}) WHERE breakout_day IS NOT NULL""").fetchall():
        life[lid] = (("sh." if str(code6)[0] == "6" else "sz.") + str(code6),
                     str(bo)[:10], str(t2)[:10] if t2 else None,
                     str(ps)[:10] if ps else None)
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
    per_stock_vol_missing = {}
    for lid, pl in path.items():
        if pl.get("status"):
            continue
        life_row = life[lid]
        code = life_row[0]
        if code in EXCL:
            continue
        if code not in F:
            miss_f.append(code)
            continue
        if code not in cache:
            cache[code] = load_stock(code, F)
            per_stock_vol_missing[code] = cache[code][3]
        try:
            r = process_episode(lid, pl, life_row, stab.get(lid), cache[code])
        except Exception as e:
            raise RuntimeError(f"非排除段 {lid} {code} 构造失败: {e}") from e
        for k in ("breakout", "shrink", "stabilization"):
            if r[k]:
                rows[k].append(r[k])
        if (len(rows["breakout"]) % 6000) < 1:
            print(f"[{len(rows['breakout'])}] {time.time()-t0:.0f}s", flush=True)

    if miss_f:
        raise RuntimeError(f"因子缺失非排除股: {sorted(set(miss_f))[:10]}")
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
    report["vol_missing_per_unique_stock_total"] = sum(per_stock_vol_missing.values())
    report["vol_missing_unique_stocks_affected"] = sum(1 for v in per_stock_vol_missing.values() if v)
    report["obs_rows_with_vol_missing"] = {k: sum(1 for r in rs if r.get("obs_vol_missing"))
                                           for k, rs in rows.items()}
    report["split_basis"] = "label_available_day(=path cutoff_day); 观察日门禁=ObsFrame 截断"
    report["note"] = ("dev_sample=True 全部; 逐半年滚动: train<=bucket_k, test=k+1; "
                      "标签仅结果列; max_gain 已删除(未来最高价)")
    (OUT / "IDENTIFY_BUILD_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["n"] for k in ("breakout","shrink","stabilization") for v in [report[k]]}, ensure_ascii=False))
    print(f"→ identify_{{breakout,shrink,stabilization}}.csv.gz | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
