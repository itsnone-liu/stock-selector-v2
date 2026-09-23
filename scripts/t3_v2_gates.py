#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t3_v2_gates.py — Gate A（任务二 y40 复算一致）+ Gate C（high×F 对账）。

Gate A：以 forward_y40_lib.build_events("breakout")（任务二冻结代码+冻结输入）
为参考实现，逐事件比对 y40：
  - comparable 集合一致性（identify_breakout 27,310 行 → 全窗主样本）
  - 删失/可标性判定一致性
  - y40 数值 max_abs_diff <= 1e-12（浮点逐位镜像公式）
差异只报告，不迎合。

Gate C：调整因子对账。全量逐股：
  - close×F vs hfq_close、high×F vs hfq_high（相对误差分布、最大差异）
  - 事件日 TDX close vs 库 close（两数据源一致性，事件级抽查为全量）
产出：y40_recalc_diff.{json,parquet}、high_f_reconcile.json。
"""
from __future__ import annotations

import gzip
import json
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import forward_y40_lib as fy  # noqa: E402  任务二冻结参考实现
from stock_selector.research import t3_v2 as tv  # noqa: E402

OUT = ROOT / "output/research/t3_v2"


def gate_id() -> dict:
    print("[GateID] 主键唯一性 + 映射保留")
    ev = pd.read_parquet(OUT / "event_master.parquet")
    res = {
        "rows": int(len(ev)),
        "breakout_event_id_unique": bool(ev["breakout_event_id"].is_unique),
        "code6_len6_all": bool((ev["code"].str.len() == 6).all()),
        "date_format_ok": bool(ev["breakout_day"].str.match(
            r"^\d{4}-\d{2}-\d{2}$").all()),
        "lifecycle_id_nonnull": int(ev["lifecycle_id"].notna().sum()),
        "mapping_cols_present": [c for c in (
            "lifecycle_id", "anchor_day", "end_day", "end_reason",
            "pullback_event_ids") if c in ev.columns],
    }
    res["verdict"] = "PASS" if (res["breakout_event_id_unique"]
                                and res["code6_len6_all"]
                                and res["date_format_ok"]) else "FAIL"
    print(json.dumps(res, ensure_ascii=False))
    return res


def gate_a() -> dict:
    print("[GateA] 参考实现 forward_y40_lib.build_events('breakout')")
    main_l, sens_l, stats = fy.build_events("breakout")
    ref = {(e["code"].split(".")[1].zfill(6), e["obs_day"]): e
           for e in main_l}
    ref_sens_keys = {(e["code"].split(".")[1].zfill(6), e["obs_day"])
                     for e in sens_l}
    lab = pd.read_parquet(OUT / "event_labels.parquet")
    lab["code"] = lab["breakout_event_id"].str.split("_").str[0]
    lab["t0"] = lab["breakout_event_id"].str.split("_").str[1]

    ref_keys, my_keys = set(ref), set(zip(lab["code"], lab["t0"]))
    both = ref_keys & my_keys
    diff_rows, max_diff, n_cmp = [], 0.0, 0
    disagree_avail = 0
    for (code, t0) in sorted(both):
        e = ref[(code, t0)]
        row = lab[(lab["code"] == code) & (lab["t0"] == t0)].iloc[0]
        mine = row["y40_mkt_excess_log"]
        theirs = e["y40"]
        # ref main 事件天然全窗（build_events 仅 full_path 进 main）
        avail_ok = row["censored_reason_h40"] == "none"
        if not avail_ok:
            disagree_avail += 1
        if theirs is None or mine is None or pd.isna(mine):
            if (theirs is None) != (mine is None or pd.isna(mine)):
                diff_rows.append({"code": code, "t0": t0,
                                  "ref_y40": theirs, "my_y40": None
                                  if pd.isna(mine) else float(mine)})
            continue
        d = abs(float(mine) - float(theirs))
        n_cmp += 1
        max_diff = max(max_diff, d)
        if d > 1e-12:
            diff_rows.append({"code": code, "t0": t0, "ref_y40": theirs,
                              "my_y40": float(mine), "abs_diff": d})
    res = {
        "reference": "forward_y40_lib.build_events('breakout') 任务二冻结实现",
        "identify_breakout_rows": stats.get("n_rows"),
        "ref_stats": {k: stats.get(k) for k in (
            "excl_not_active", "data_end_censored", "obs_day_no_price",
            "window_all_missing", "imputed_last_available", "endpoint_gap",
            "full_path", "n_main_after_dedup", "n_sens_after_dedup",
            "dup_same_day_same_stock")},
        "ref_events_main": len(main_l),
        "my_events": int(len(lab)),
        "comparable_intersection": len(both),
        "ref_only": sorted(f"{c}_{d}" for c, d in (ref_keys - my_keys))[:50],
        "ref_only_n": len(ref_keys - my_keys),
        "my_only_n": len(my_keys - ref_keys),
        "my_only": sorted(f"{c}_{d}" for c, d in (my_keys - ref_keys))[:50],
        "numeric_compared": n_cmp,
        "max_abs_diff": max_diff,
        "tolerance": 1e-12,
        "avail_disagreements": disagree_avail,
        "diff_rows_n": len(diff_rows),
    }
    sens = pd.read_parquet(OUT / "event_labels_sensitivity.parquet")
    my_sens40 = set(zip(
        sens["breakout_event_id"].str.split("_").str[0],
        sens["breakout_event_id"].str.split("_").str[1]))
    res["sens_cross"] = {
        "ref_sens_n": len(ref_sens_keys),
        "my_sens_any_h_n": len(sens),
        "ref_sens_in_my_sens": len(ref_sens_keys & my_sens40),
        "ref_sens_in_my_main": len(ref_sens_keys - my_sens40 - set()),
    }
    res["verdict"] = "PASS" if (
        max_diff <= 1e-12 and n_cmp > 0 and not diff_rows
        and disagree_avail == 0) else "FAIL"
    pd.DataFrame(diff_rows).to_parquet(
        OUT / "y40_recalc_diff.parquet", index=False)
    (OUT / "y40_recalc_diff.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: res[k] for k in (
        "ref_events_main", "my_events", "comparable_intersection",
        "ref_only_n", "my_only_n", "numeric_compared", "max_abs_diff",
        "avail_disagreements", "verdict")}, ensure_ascii=False))
    return res


def gate_c() -> dict:
    print("[GateC] high×F / close×F 对账 hfq（方法论：每股常数比检验）")
    # 事实：close×F / hfq_close 为每股常数（F 与 hfq 基准日归一不同，
    # 收益/比值完全等价）。Gate C 检验：①每股内常数性（无日期错位/单位
    # 跳变）②close 与 high 的常数一致（F 对 OHLC 均匀适用）③事件日
    # TDX close 与库 close 一致。
    factors = tv.load_factor_cache(OUT)
    ev = pd.read_parquet(OUT / "event_master.parquet")
    ev_days = set(zip(ev["code"], ev["breakout_day"]))
    n_rows = n_stk = 0
    n_skip = 0
    worst_dev = 0.0
    bad_stk = []
    const_hist = []
    tdx_ev_checked = tdx_ev_ok = 0
    for code6 in sorted({c for c, _ in ev_days}):
        pref = "sh." if code6.startswith(("6", "9")) else "sz."
        fp = ROOT / f"data/adjustment_baostock/per_stock/{pref}{code6}.json.gz"
        if not fp.exists():
            continue
        j = json.load(gzip.open(fp, "rt"))
        F = factors.get(f"{pref}{code6}", {})
        un = {r[0]: r for r in j["unadj"]}
        hfq = {r[0]: r for r in j["hfq"]}
        tdx_close = {}
        tdx_fp = Path(f"/root/tdx_data/vipdoc/{pref.rstrip('.')}/lday/"
                      f"{pref.replace('.', '')}{code6}.day")
        if tdx_fp.exists():
            b = tdx_fp.read_bytes()
            for i in range(len(b) // 32):
                d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
                dd = f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}"
                # TDX .day: date/open/high/low/close(+16)/amount/vol
                tdx_close[dd] = struct.unpack(
                    "<i", b[i * 32 + 16:i * 32 + 20])[0] / 100.0
        rc_l, rh_l = [], []
        for d, r in un.items():
            if d not in F or d not in hfq:
                n_skip += 1
                continue
            f = F[d]
            rc_l.append(float(r[4]) * f / float(hfq[d][4]))
            rh_l.append(float(r[2]) * f / float(hfq[d][2]))
            if (code6, d) in ev_days and d in tdx_close:
                tdx_ev_checked += 1
                tdx_ev_ok += abs(tdx_close[d] - float(r[4])) <= 1e-6
        if len(rc_l) < 2:
            continue
        n_rows += len(rc_l)
        n_stk += 1
        rc, rh = np.array(rc_l), np.array(rh_l)
        const = float(np.median(rc))
        dev_c = float(np.max(np.abs(rc / const - 1.0)))
        dev_h = float(np.max(np.abs(rh / const - 1.0)))
        worst_dev = max(worst_dev, dev_c, dev_h)
        const_hist.append({"code": code6, "const": const,
                           "n_days": len(rc_l)})
        if dev_c > 1e-8 or dev_h > 1e-8:
            bad_stk.append({"code": code6, "const": const, "dev_close": dev_c,
                            "dev_high": dev_h, "n_days": len(rc_l)})
    res = {
        "scope": "事件股全量逐日（close×F/hfq 与 high×F/hfq 每股常数性）",
        "stocks_checked": n_stk,
        "rows_compared": n_rows,
        "rows_factor_or_hfq_missing": n_skip,
        "per_stock_constant_median_of_const": float(np.median(
            [h["const"] for h in const_hist])),
        "const_range": [float(min(h["const"] for h in const_hist)),
                        float(max(h["const"] for h in const_hist))],
        "worst_within_stock_deviation": worst_dev,
        "tolerance": 1e-8,
        "bad_stocks_n": len(bad_stk),
        "bad_stocks_sample": bad_stk[:50],
        "interpretation": ("close×F/hfq 为每股常数（基准日归一差异，"
                           "收益层完全等价）；Gate C 验证常数性而非 |r-1|"),
        "eventday_tdx_vs_lib_close_checked": tdx_ev_checked,
        "eventday_tdx_vs_lib_close_ok": tdx_ev_ok,
        "verdict": "PASS" if (worst_dev <= 1e-8 and not bad_stk
                              and tdx_ev_ok == tdx_ev_checked
                              and tdx_ev_checked > 0) else "FAIL",
    }
    (OUT / "high_f_reconcile.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str))
    print(json.dumps({k: res[k] for k in (
        "stocks_checked", "rows_compared", "worst_within_stock_deviation",
        "bad_stocks_n", "eventday_tdx_vs_lib_close_checked",
        "eventday_tdx_vs_lib_close_ok", "verdict")}))
    return res


if __name__ == "__main__":
    out = {"gate_id": gate_id(), "gate_a": gate_a(), "gate_c": gate_c()}
    print(json.dumps({k: v["verdict"] for k, v in out.items()}))
