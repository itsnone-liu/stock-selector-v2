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
    """单 episode 三时点构造(独立可测).

    life_row = (code, breakout_day, first_pullback_day, prep_start,
                t3_first_day, end_day, right_censored, pullback_event_ids)
    2026-09-21 第三轮复审修订:
    - t2 观察日 = 突破后首个有效回调(pullback_event_ids 中 > breakout 最早;
      first_pullback_day 可早于突破日[准备期回调], 不得作时点2)
    - 标签可得日按目标分离: la_path=突破+20交易日; la_ge=G3→T3 首日,
      完整 G1/G2→生命周期 end_day, 不确定→None(label_uncertain)
    - 复权基准统一: p_bo/post_hi/plow 全用 P_adj(修 raw/P_adj 混除)
    - pred_legal_path: 观察日<=la_path 才可预测 20 日结局
    """
    (code, bo_d, t2_orig, ps_d, t3_first, end_day, rc, pev) = life_row
    dates, u, Fd, _nvm, vmd = cache_row
    if bo_d not in dates:
        raise RuntimeError(f"{code} {lid} 突破日不在日历")
    bp = dates.index(bo_d)
    # 突破后首个有效回调: 事件 id 形如 code_YYYY-MM-DD
    t2_eff = None
    if pev:
        for ev in pev.split("|"):
            d_ = ev.split("_", 1)[1] if "_" in ev else None
            if d_ and d_ > bo_d:
                t2_eff = d_ if (t2_eff is None or d_ < t2_eff) else t2_eff
    audit = {"t2_orig_le_bo": bool(t2_orig and t2_orig <= bo_d),
             "t2_eff_from_events": t2_eff is not None}
    # 标签可得日(按目标)
    la_path = pl["cutoff_day"]                     # path/asof_20d: 突破+20交易日
    ge = pl["group_eventual"]
    if ge == "G3":
        la_ge = t3_first                           # T3 首次形成时
    elif ge in ("G1", "G2"):
        la_ge = end_day                            # 生命周期终结才定类
    else:
        la_ge = None                               # unknown_censored
    label_uncertain = (ge == "unknown_censored"
                       or pl["path_family"] == "right_censored")
    label = {
        "lifecycle_id": lid, "code": code, "breakout_day": bo_d,
        "label_available_day_path": la_path,
        "label_available_day_ge": la_ge,
        "split_path": split_semiannual(la_path),
        "split_ge": split_semiannual(la_ge) if la_ge else None,
        "path_family": pl["path_family"], "path_subtype": pl["path_subtype"],
        "D": pl["D"], "E": pl["E"], "D_atr": pl["D_atr"],
        "group_eventual": ge, "group_asof_20d": pl["group_asof_20d"],
        "structure_broken_asof_20d": pl["structure_broken_asof_20d"],
        "label_uncertain": label_uncertain, "dev_sample": True,
        "audit_t2_orig_le_bo": audit["t2_orig_le_bo"],
    }
    dO = {d: u[d][0] for d in dates}
    dH = {d: u[d][1] for d in dates}
    dL = {d: u[d][2] for d in dates}
    dC = {d: u[d][3] for d in dates}
    dV = {d: u[d][4] for d in dates}
    p_bo_adj = dC[bo_d] * Fd[bo_d]                 # 复权基准(统一)
    prep_days = ((bp - dates.index(ps_d)) if (ps_d and ps_d in dates) else None)  # bo−ps 正数
    r1 = ObsFrame(dates, bp, dO, dH, dL, dC, dV, Fd)
    row1 = {**label, "obs_day": bo_d, "obs_vol_missing": bool(vmd.get(bo_d)),
            "pred_legal_path": bo_d <= la_path,
            **feat_breakout(r1, prep_days)}
    row2 = row3 = None
    if t2_eff and t2_eff in dates and dates.index(t2_eff) > bp:
        sp = dates.index(t2_eff)
        post_hi = max(dC[d] * Fd[d] for d in dates[bp + 1:sp + 1]) if sp > bp else None
        r2 = ObsFrame(dates, sp, dO, dH, dL, dC, dV, Fd)
        row2 = {**label, "obs_day": t2_eff, "obs_vol_missing": bool(vmd.get(t2_eff)),
                "pred_legal_path": t2_eff <= la_path,
                **feat_shrink(r2, p_bo_adj, bp, post_hi)}
        if stab_fd and stab_fd in dates and dates.index(stab_fd) >= sp:
            fp = dates.index(stab_fd)
            plow = min(dL[d] * Fd[d] for d in dates[sp:fp + 1])
            r3 = ObsFrame(dates, fp, dO, dH, dL, dC, dV, Fd)
            row3 = {**label, "obs_day": stab_fd, "obs_vol_missing": bool(vmd.get(stab_fd)),
                    "pred_legal_path": stab_fd <= la_path,
                    **feat_stabilization(r3, p_bo_adj, plow)}
    return {"breakout": row1, "shrink": row2, "stabilization": row3,
            "audit": audit}


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
    for code6, lid, bo, t2, ps, t3s, ed, rc, pev in duckdb.connect().execute(f"""
            SELECT code, lifecycle_id, breakout_day, first_pullback_day,
                   preparation_start, reattack_days, end_day, right_censored,
                   pullback_event_ids
            FROM read_parquet({lfiles!r}) WHERE breakout_day IS NOT NULL""").fetchall():
        life[lid] = (("sh." if str(code6)[0] == "6" else "sz.") + str(code6),
                     str(bo)[:10], str(t2)[:10] if t2 else None,
                     str(ps)[:10] if ps else None,
                     str(t3s).split("|")[0] if t3s else None,
                     str(ed)[:10] if ed else None, bool(rc),
                     str(pev) if pev else None)
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
    audit_tot = {"t2_orig_le_bo": 0, "t2_orig_le_bo_and_no_post_bo_event": 0,
                 "label_uncertain": 0, "stab_pred_illegal": 0}
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
        a = r["audit"]
        audit_tot["t2_orig_le_bo"] += a["t2_orig_le_bo"]
        if a["t2_orig_le_bo"] and not a["t2_eff_from_events"]:
            audit_tot["t2_orig_le_bo_and_no_post_bo_event"] += 1
        if r["breakout"]["label_uncertain"]:
            audit_tot["label_uncertain"] += 1
        if r["stabilization"] and not r["stabilization"]["pred_legal_path"]:
            audit_tot["stab_pred_illegal"] += 1
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
        buckets = Counter(str((r.get("split_path"), r.get("split_ge"))) for r in rs)
        report[name] = {"n": len(rs), "split_buckets": dict(sorted(buckets.items())),
                        "path_families": dict(Counter(r["path_family"] for r in rs))}
    report["vol_missing_per_unique_stock_total"] = sum(per_stock_vol_missing.values())
    report["vol_missing_unique_stocks_affected"] = sum(1 for v in per_stock_vol_missing.values() if v)
    report["obs_rows_with_vol_missing"] = {k: sum(1 for r in rs if r.get("obs_vol_missing"))
                                           for k, rs in rows.items()}
    report["audit"] = audit_tot
    report["split_basis"] = ("按目标分离: split_path=la_path(bo+20交易日)/"
                             "split_ge=la_ge(G3:T3首日; G1/G2:end_day); "
                             "观察日门禁=ObsFrame 截断; pred_legal_path 门禁")
    report["note"] = ("dev_sample=True 全部; 逐半年滚动: train<=bucket_k, test=k+1; "
                      "标签仅结果列; max_gain 已删除(未来最高价)")
    (OUT / "IDENTIFY_BUILD_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({k: v["n"] for k in ("breakout","shrink","stabilization") for v in [report[k]]}, ensure_ascii=False))
    print(f"→ identify_{{breakout,shrink,stabilization}}.csv.gz | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
