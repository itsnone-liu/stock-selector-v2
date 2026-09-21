#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_adjustment_v3.py — adjustment_v1 严格门禁审计 v3 (2026-09-21, 响应第二轮审查)。

对 v2 的四处静默放行修复 + 行级对账 + 冻结基准核对。只读: 本程序不改写任何冻结文件。

  G0  冻结基准核对(只读): universe_frozen.json 自身 codes_sha256 重算==记录;
      per_stock 根哈希 / fetch_manifest sha256 / factor_table sha256 重算==冻结记录
  G1  universe 闭合: manifest 集合==frozen codes(差集列出); n_ok==count; n_fail==0;
      冻结清单与现扫描不一致 → 直接失败(不自动重冻结)
  G2  全量文件 SHA256 复核(ok+fail 全部, 孤儿/缺失分开)
  G3  结构校验(原始列表直查): 日期唯一/升序/close>0; n_rows==len(unadj)==len(hfq);
      两套日期集合相等
  G4  TDX 价格闭合: 本地 .day 缺失 → gate_failures(不再空 dict 放行);
      逐股+总体覆盖率门禁(对账日/窗口日 ≥ 99%)
  G5  u×F==h 浮点重建(定位: 恒等式级自洽, 不构成独立验证; 独立对账在 G5b)
  G5b 因子表对账: missing_keys/duplicate_keys/extra_keys/validated_rows/skipped_rows;
      validated_rows == expected_rows 严格相等; 源加载失败计 gate_failures(v2 全量绕过修复)
  G6  候选/确认分离: bs_candidates / bs_confirmed_by_sina(逐日∩) / bs_unconfirmed(明细)
      / sina_only_events / sina_load_failures(→gate_failures); 分段行动日=全候选∪sina(保守)
  G7  OHLC 分层抽验 60 只

输出: docs/reports/ADJUSTMENT_V1_FETCH_AUDIT_V3.json; exit 0=passed / 1=failed
测试模式: --codes-file/--data-dir/--frozen/--ft/--no-g0 供故障注入沙盒使用。
"""
import argparse
import gzip
import hashlib
import json
import random
import struct
import sys
import time
from collections import Counter
from pathlib import Path

TOL_PRICE = 1e-4
TOL_INTERNAL = 1e-9
JUMP = 2e-4
TOL_DRIFT = 1e-4
TOL_OHLC = 1e-6
COVERAGE_MIN = 0.99
random.seed(20260921)

AP = argparse.ArgumentParser()
AP.add_argument("--data-dir", default="/root/project/workspace/stock-selector-v2/data/adjustment_baostock")
AP.add_argument("--sina-dir", default="/root/project/workspace/stock-selector-v2/data/adjustment_sina/factors")
AP.add_argument("--tdx-dir", default="/root/tdx_data/vipdoc")
AP.add_argument("--frozen", default="/root/project/workspace/stock-selector-v2/config/universe_frozen.json")
AP.add_argument("--excl", default="/root/project/workspace/stock-selector-v2/config/adjustment_v1_exclusions.json")
AP.add_argument("--ft", default="/root/project/workspace/stock-selector-v2/output/research/adjustment_v1/factor_table.csv.gz")
AP.add_argument("--out", default="/root/project/workspace/stock-selector-v2/docs/reports/ADJUSTMENT_V1_FETCH_AUDIT_V3.json")
AP.add_argument("--codes-file", default=None, help="故障注入/子集模式: 只审列出的代码(每股一行)")
AP.add_argument("--no-g0", action="store_true", help="沙盒: 跳过根哈希基准核对(数据被移位时用)")
AP.add_argument("--no-scan", action="store_true", help="沙盒: 跳过实时目录扫描校验(TDX 部分拷贝时用)")
AP.add_argument("--no-cov", action="store_true", help="沙盒: 跳过覆盖率门禁(TDX 部分拷贝时用)")


def sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_local_day(fp: Path) -> dict[str, float]:
    rows = {}
    b = fp.read_bytes()
    for i in range(len(b) // 32):
        d, o, h, l, c, amt, vol, res = struct.unpack("<IIIIIfIf", b[i * 32:(i + 1) * 32])
        rows[f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}"] = c / 100.0
    return rows


def main() -> int:
    a = AP.parse_args()
    t0 = time.time()
    SRC = Path(a.data_dir)
    SN = Path(a.sina_dir)
    TDX = Path(a.tdx_dir)
    FT = Path(a.ft)
    UNI_F = Path(a.frozen)
    OUT = Path(a.out)
    manifest = json.loads((SRC / "fetch_manifest.json").read_text())
    stocks: dict = manifest["stocks"]
    excl = set(json.loads(Path(a.excl).read_text())["excluded"])
    subset = set()
    if a.codes_file:
        subset = {x.strip() for x in Path(a.codes_file).read_text().splitlines() if x.strip()}

    report = {"audit_version": "v3.1-strict-gates-read-only",
              "mode": "subset" if subset else "full",
              "gate_failures": [], "gates": {}}

    # ---- G0 冻结基准核对 (只读; 重算==冻结记录) ----
    g0 = {"passed": True, "checks": []}
    if not a.no_g0:
        uni = json.loads(UNI_F.read_text())
        codes_payload = "\n".join(uni["codes"]) + "\n"
        g0_checks = [
            ("universe_frozen.codes_sha256",
             hashlib.sha256(codes_payload.encode()).hexdigest(), uni.get("codes_sha256")),
            ("universe_frozen.fetch_manifest_sha256",
             sha256_file(SRC / "fetch_manifest.json"), uni.get("fetch_manifest_sha256")),
            ("universe_frozen.factor_table_sha256",
             sha256_file(FT), uni.get("factor_table_sha256")),
        ]
        parts = [f"{c}:{stocks[c]['sha256']}" for c in sorted(stocks)]
        g0_checks.append(("universe_frozen.per_stock_root_sha256",
                          hashlib.sha256("\n".join(parts).encode()).hexdigest(),
                          uni.get("per_stock_root_sha256")))
        for name, recomputed, frozen_rec in g0_checks:
            if frozen_rec is None:   # 冻结清单未记录的基准 → 跳过并披露(不静默当通过)
                g0["checks"].append({"item": name, "status": "not_recorded"})
                continue
            ok = recomputed == frozen_rec
            g0["checks"].append({"item": name, "match": ok})
            if not ok:
                g0["passed"] = False
        if not g0["passed"]:
            report["gate_failures"].append("G0: 冻结基准哈希不符(数据或冻结清单被改动)")
    else:
        g0["checks"].append({"item": "skipped (--no-g0 沙盒模式)"})
    report["gates"]["G0_frozen_baselines"] = g0

    # ---- G1 universe 闭合 (只读; 不重冻结) ----
    uni = json.loads(UNI_F.read_text())   # a.no_g0 时也需读 frozen 供对账
    us_all = set(uni["codes"])
    scan_drift = None
    if not a.no_scan:   # 实时扫描校验: 冻结清单 vs 当前 TDX 目录扫描
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from fetch_adjustment_source import universe as scan_universe
        scan_now = set(scan_universe())
        scan_drift = {"n_scan": len(scan_now),
                      "new_since_frozen": sorted(scan_now - us_all)[:20],
                      "gone_since_frozen": sorted(us_all - scan_now)[:20]}
        if scan_now != us_all:
            report["gate_failures"].append(
                f"G1: 冻结清单与实时扫描不一致 (新增{len(scan_drift['new_since_frozen'])} "
                f"消失{len(scan_drift['gone_since_frozen'])}; 快照完整性要求目录未变)")
    ms = set(stocks)
    us = us_all if not subset else (us_all & subset)
    if subset:
        ms &= subset
    not_attempted = sorted(us - ms)
    extra = sorted(ms - us)
    n_ok = sum(1 for c, v in stocks.items() if v.get("status") == "ok" and (not subset or c in subset))
    n_fail = len(ms) - n_ok
    expected_count = uni["count"] if not subset else len(us)
    g1_ok = (not not_attempted and not extra and n_ok == expected_count and n_fail == 0)
    report["gates"]["G1_universe_closure"] = {
        "frozen_count": uni["count"], "manifest_n": len(ms),
        "n_ok": n_ok, "n_fail": n_fail,
        "not_attempted": not_attempted[:50], "n_not_attempted": len(not_attempted),
        "extra_in_manifest": extra[:50], "n_extra": len(extra),
        "require_n_fail_zero": True, "passed": g1_ok}
    if not g1_ok:
        report["gate_failures"].append(
            f"G1: universe 未闭合/存在失败 (未尝试{len(not_attempted)} 多余{len(extra)} "
            f"ok={n_ok}!={expected_count} fail={n_fail})")

    # ---- G2 全量文件 SHA256 ----
    hash_bad, hash_missing, orphan_files = [], [], []
    files = {f.name.removesuffix(".json.gz"): f for f in (SRC / "per_stock").glob("*.json.gz")}
    for code in sorted(ms):
        fp = files.get(code)
        if fp is None:
            hash_missing.append(code)
        elif sha256_file(fp) != stocks[code].get("sha256"):
            hash_bad.append(code)
    if not subset:
        orphan_files = sorted(set(files) - ms)
    g2_ok = not (hash_bad or hash_missing or orphan_files)
    report["gates"]["G2_file_sha256"] = {
        "checked": len(ms), "hash_mismatch": hash_bad[:50], "n_hash_mismatch": len(hash_bad),
        "file_missing": hash_missing[:50], "n_file_missing": len(hash_missing),
        "orphan_files": orphan_files[:20], "n_orphan": len(orphan_files), "passed": g2_ok}
    if not g2_ok:
        report["gate_failures"].append(
            f"G2: 哈希不符{len(hash_bad)} 缺失{len(hash_missing)} 孤儿{len(orphan_files)}")

    # ---- G3-G7 数据级 ----
    struct_bad, price_bad, internal_bad, drift_list = [], [], [], []
    g4_missing_local, sina_load_failures = [], []
    g6_stat = {"bs_candidates": 0, "bs_confirmed_by_sina": 0,
               "bs_unconfirmed_detail": [], "sina_only_events": 0,
               "sina_events_total": 0}
    coverage_pairs, coverage_rev = [], []
    rev_gap_by_year, rev_top_stocks = Counter(), []
    ok_codes = sorted(c for c in ms if stocks[c].get("status") == "ok")
    for i, code in enumerate(ok_codes):
        try:
            p = json.load(gzip.open(SRC / "per_stock" / f"{code}.json.gz", "rt"))
        except Exception as e:
            struct_bad.append({"code": code, "err": f"gzip/json: {str(e)[:50]}"})
            continue
        u_rows, h_rows = p.get("unadj", []), p.get("hfq", [])
        errs = []
        for name, rows in (("unadj", u_rows), ("hfq", h_rows)):
            ds = [r[0] for r in rows]
            if len(set(ds)) != len(ds):
                errs.append(f"{name}:duplicate_dates")
            if ds != sorted(ds):
                errs.append(f"{name}:not_ascending")
            if any((not r[4]) or float(r[4]) <= 0 for r in rows):
                errs.append(f"{name}:close<=0_or_empty")
        if p.get("n_rows") != len(u_rows) or p["n_rows"] != len(h_rows):
            errs.append(f"n_rows({p.get('n_rows')})!=len(unadj={len(u_rows)},hfq={len(h_rows)})")
        if {r[0] for r in u_rows} != {r[0] for r in h_rows}:
            errs.append("date_set_diff")
        if errs:
            struct_bad.append({"code": code, "errs": errs[:4]})
            continue
        u = {r[0]: float(r[4]) for r in u_rows}
        h = {r[0]: float(r[4]) for r in h_rows}
        days = sorted(u)
        # G4: TDX 缺文件 → fail (不再空dict放行)
        mkt, num = code.split(".")
        lfp = TDX / mkt / "lday" / f"{mkt}{num}.day"
        if not lfp.exists():
            g4_missing_local.append(code)
            local = {}
        else:
            local = read_local_day(lfp)
        li = {d: c for d, c in local.items() if days[0] <= d <= days[-1]}
        inter = sorted(set(li) & set(u))
        if li:
            coverage_pairs.append((len(inter), len(li)))
        coverage_rev.append((len(inter), len(u)))   # 反向: 源日期在TDX中的比例
        gap = sorted(set(u) - set(li))
        if gap:
            rev_top_stocks.append((code, len(gap)))
            for d_ in gap:
                rev_gap_by_year[d_[:4]] += 1
        bad = [d for d in inter if abs(li[d] - u[d]) > TOL_PRICE]
        miss = sorted(set(li) - set(u))
        if (bad or miss) and code not in excl:
            price_bad.append({"code": code, "n_mismatch": len(bad), "n_missing": len(miss),
                              "sample": [(d, li[d], u[d]) for d in bad[:2]]})
        # G5 浮点重建(恒等式级; 独立对账在 G5b)
        f_raw = {d: h[d] / u[d] for d in days}
        if any(abs(u[d] * f_raw[d] - h[d]) > TOL_INTERNAL * max(1.0, h[d]) for d in days):
            internal_bad.append(code)
        # G6 候选/确认分离
        sina_days = None
        try:
            sp = json.load(gzip.open(SN / f"{code}.json.gz", "rt"))
            sina_days = {e["date"] for e in sp.get("events", [])
                         if days[0] <= e["date"] <= days[-1]}
            g6_stat["sina_events_total"] += len(sina_days)
        except Exception:
            sina_load_failures.append(code)   # 独立确认通道断裂 → gate_failures
        bs_cand = set()
        prev_f = None
        for d in days:
            f = f_raw[d]
            if prev_f is not None and abs(f - prev_f) / max(prev_f, 1e-12) > JUMP:
                bs_cand.add(d)
            prev_f = f
        g6_stat["bs_candidates"] += len(bs_cand)
        if sina_days is not None:
            confirmed = bs_cand & sina_days
            g6_stat["bs_confirmed_by_sina"] += len(confirmed)
            unconf = sorted(bs_cand - sina_days)
            if unconf:
                g6_stat["bs_unconfirmed_detail"].append({"code": code, "dates": unconf[:6],
                                                         "n": len(unconf)})
            g6_stat["sina_only_events"] += len(sina_days - bs_cand)
        action_days = bs_cand | (sina_days or set())   # 保守: 全候选并入分段
        seg_start, seg_vals, prev_d, n_jump = days[0], [f_raw[days[0]]], days[0], 0
        for d in days[1:]:
            f = f_raw[d]
            if d in action_days:
                n_jump += 1
                lo, hi = min(seg_vals), max(seg_vals)
                if (hi - lo) / max(lo, 1e-12) > TOL_DRIFT:
                    drift_list.append({"code": code, "segment": [seg_start, prev_d],
                                       "f_range": [round(lo, 6), round(hi, 6)]})
                seg_start, seg_vals = d, [f]
            else:
                seg_vals.append(f)
            prev_d = d
        lo, hi = min(seg_vals), max(seg_vals)
        if (hi - lo) / max(lo, 1e-12) > TOL_DRIFT:
            drift_list.append({"code": code, "segment": [seg_start, days[-1]],
                               "f_range": [round(lo, 6), round(hi, 6)]})
        if (i + 1) % 1000 == 0:
            print(f"[{i+1}/{len(ok_codes)}] struct={len(struct_bad)} price={len(price_bad)} "
                  f"drift={len(drift_list)} sinaFail={len(sina_load_failures)} {time.time()-t0:.0f}s", flush=True)

    cov_ok = True
    cov_total = [sum(x for x, _ in coverage_pairs), sum(y for _, y in coverage_pairs)]
    if not a.no_cov and coverage_pairs:
        cov_ok = cov_total[0] / cov_total[1] >= COVERAGE_MIN
    report["gates"]["G3_structure"] = {"n_bad": len(struct_bad), "bad": struct_bad[:50],
                                       "passed": not struct_bad}
    cov_rev_total = [sum(x for x, _ in coverage_rev), sum(y for _, y in coverage_rev)]
    report["gates"]["G4_price_vs_tdx"] = {
        # 反向覆盖率=披露项(参照源TDX覆盖边界, 非 baostock 缺陷; 实测98.6%差异集中在
        # 2021上半年 TDX 本地库缺段)。正向(TDX窗口日必须存在于源+价格一致)为硬门禁。
        "coverage_reverse_disclosure": {
            "src_days_in_tdx": cov_rev_total[0], "src_days_total": cov_rev_total[1],
            "ratio": round(cov_rev_total[0] / cov_rev_total[1], 6) if cov_rev_total[1] else None,
            "gap_by_year": dict(rev_gap_by_year), "top_gap_stocks": rev_top_stocks[:20]},
        "n_bad_excl_known": len(price_bad), "bad": price_bad[:50],
        "missing_local_files": g4_missing_local[:50], "n_missing_local": len(g4_missing_local),
        "coverage": {"matched_days": cov_total[0], "window_days": cov_total[1],
                     "ratio": round(cov_total[0] / cov_total[1], 6) if cov_total[1] else None,
                     "min_ratio": COVERAGE_MIN},
        "excluded_by_decision_hits": sorted(excl & set(ok_codes)),
        "passed": not price_bad and not g4_missing_local and cov_ok}
    report["gates"]["G5_internal_rebuild"] = {
        "n_bad": len(internal_bad), "bad": internal_bad[:50],
        "disclaimer": "恒等式级浮点自检(h=unadj×(h/u)); 不构成独立验证, 独立对账见 G5b",
        "passed": not internal_bad}
    unconf_outside = [x for x in g6_stat["bs_unconfirmed_detail"] if x["code"] not in excl]
    report["gates"]["G6_factor_jump_candidates"] = {
        **g6_stat,
        "n_unconfirmed_outside_exclusion": len(unconf_outside),
        "unconfirmed_outside_detail": unconf_outside[:20],
        "bs_unconfirmed_detail": g6_stat["bs_unconfirmed_detail"][:30],
        "sina_load_failures": sina_load_failures[:50],
        "n_sina_load_failures": len(sina_load_failures),
        "segmentation": "行动日 = bs全候选(>2e-4) ∪ sina事件日(保守并集); 段内漂移>1e-4 即 fail",
        "intra_segment_drift": {"n": len(drift_list), "detail": drift_list[:30]},
        "passed": not drift_list and not sina_load_failures and not unconf_outside}
    if unconf_outside:
        report["gate_failures"].append(
            f"G6: 排除清单外未确认跳变候选{len(unconf_outside)}只(未获sina独立确认)")
    if struct_bad:
        report["gate_failures"].append(f"G3: 结构异常{len(struct_bad)}只")
    if price_bad:
        report["gate_failures"].append(f"G4: TDX价格不符{len(price_bad)}只")
    if g4_missing_local:
        report["gate_failures"].append(f"G4: 本地TDX文件缺失{len(g4_missing_local)}只")
    if not cov_ok:
        report["gate_failures"].append(
            f"G4: 覆盖率{cov_total[0]}/{cov_total[1]}<{COVERAGE_MIN}")

    if internal_bad:
        report["gate_failures"].append(f"G5: 浮点重建失败{len(internal_bad)}只")
    if drift_list:
        report["gate_failures"].append(f"G6: 段内因子漂移{len(drift_list)}段")
    if sina_load_failures:
        report["gate_failures"].append(
            f"G6: sina独立源加载失败{len(sina_load_failures)}只(确认通道断裂)")

    # ---- G7 OHLC 抽验 ----
    def board(c):
        n = c.split(".")[1]
        return ("科创" if n.startswith("68") else "创业" if n.startswith("30") else "主板")
    by: dict[str, list] = {}
    for c in ok_codes:
        by.setdefault(board(c), []).append(c)
    ohlc_bad, sample_n = [], 0
    for b, lst in sorted(by.items()):
        k = max(1, round(60 * len(lst) / len(ok_codes)))
        for code in random.sample(lst, min(k, len(lst))):
            sample_n += 1
            try:
                p = json.load(gzip.open(SRC / "per_stock" / f"{code}.json.gz", "rt"))
                u = {r[0]: [float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in p["unadj"]}
                h = {r[0]: [float(r[1]), float(r[2]), float(r[3]), float(r[4])] for r in p["hfq"]}
                for d in sorted(set(u) & set(h)):
                    f = h[d][3] / u[d][3] if u[d][3] > 0 else 0
                    if f <= 0:
                        continue
                    rel = max(abs(u[d][j] * f - h[d][j]) / max(h[d][j], 1e-9) for j in range(4))
                    o_, h_, l_, c_ = h[d]
                    if rel > TOL_OHLC or not (l_ <= o_ <= h_ and l_ <= c_ <= h_):
                        ohlc_bad.append({"code": code, "date": d, "max_rel_err": round(rel, 8)})
                        break
            except Exception as e:
                ohlc_bad.append({"code": code, "err": str(e)[:50]})
    report["gates"]["G7_ohlc_spotcheck"] = {"n_sampled": sample_n, "n_bad": len(ohlc_bad),
                                            "bad": ohlc_bad[:20], "passed": not ohlc_bad}
    if ohlc_bad:
        report["gate_failures"].append(f"G7: OHLC抽验异常{len(ohlc_bad)}/{sample_n}")

    # ---- G5b 因子表对账 (行级: missing/duplicate/extra/validated==expected; 加载失败→fail) ----
    expected_codes = [c for c in ok_codes if c not in excl]
    g5b = {"source_load_failures": [], "ft_rows": 0, "validated_rows": 0, "skipped_rows": 0,
           "missing_keys": [], "duplicate_keys": [], "extra_keys": []}
    expected_rows = 0
    src_map: dict[str, dict] = {}
    for code in expected_codes:
        try:
            p = json.load(gzip.open(SRC / "per_stock" / f"{code}.json.gz", "rt"))
            u0 = {r[0]: float(r[4]) for r in p["unadj"]}
            h0 = {r[0]: float(r[4]) for r in p["hfq"]}
            d0 = sorted(u0)
            base = h0[d0[0]] / u0[d0[0]]
            src_map[code] = {"u": u0, "h": h0, "base": base}
            expected_rows += len(d0)
        except Exception as e:
            g5b["source_load_failures"].append({"code": code, "err": str(e)[:40]})
    g5b["expected_rows"] = expected_rows
    if FT.exists():
        cur_code, seen_dates = None, set()
        ft_codes = set()
        block_seen: dict[str, int] = {}   # 全局代码块顺序: 重复块=绕过组内查重的路径
        order_pos = 0
        with gzip.open(FT, "rt") as f:
            next(f)
            for line in f:
                g5b["ft_rows"] += 1
                code, d, uc, hc, F = line.rstrip("\n").split(",")
                if code != cur_code:
                    if cur_code is not None:
                        if cur_code not in src_map and cur_code not in ft_codes:
                            g5b["extra_keys"].append(cur_code)
                        else:
                            sm0 = src_map.get(cur_code)
                            if sm0 and seen_dates != set(sm0["u"]):
                                g5b.setdefault("stock_date_set_diff", []).append(
                                    {"code": cur_code,
                                     "n_missing": len(set(sm0["u"]) - seen_dates),
                                     "n_extra": len(seen_dates - set(sm0["u"]))})
                    if code in block_seen:
                        g5b.setdefault("duplicate_blocks", []).append(
                            {"code": code, "block": block_seen[code]})
                    block_seen[code] = order_pos
                    order_pos += 1
                    cur_code, seen_dates = code, set()
                    ft_codes.add(code)
                if d in seen_dates:
                    g5b["duplicate_keys"].append(f"{code}@{d}")
                seen_dates.add(d)
                sm = src_map.get(code)
                if sm is None:
                    g5b["skipped_rows"] += 1   # extra/未知股的行: 无源可对 → 计入统计并 fail
                    continue
                su, sh_, base = sm["u"].get(d), sm["h"].get(d), sm["base"]
                if (su is None or sh_ is None
                        or abs(float(uc) - su) > 5.0001e-5
                        or abs(float(hc) - sh_) > 5.0001e-7
                        or abs(float(F) - (sh_ / su) / base) > 1e-9):
                    g5b.setdefault("row_mismatch", []).append(f"{code}@{d}")
                else:
                    g5b["validated_rows"] += 1
        if cur_code is not None:
            if cur_code not in src_map and cur_code not in ft_codes:
                g5b["extra_keys"].append(cur_code)
            else:
                sm0 = src_map.get(cur_code)
                if sm0 and seen_dates != set(sm0["u"]):
                    g5b.setdefault("stock_date_set_diff", []).append(
                        {"code": cur_code,
                         "n_missing": len(set(sm0["u"]) - seen_dates),
                         "n_extra": len(seen_dates - set(sm0["u"]))})
        ft_codes_in_src = {c for c in ft_codes if c in src_map}
        g5b["missing_keys"] = sorted(set(src_map) - ft_codes)
        g5b["extra_keys"] = sorted(set(ft_codes) - set(src_map))[:50]
        g5b["n_missing_keys"], g5b["n_duplicate_keys"], g5b["n_extra_keys"] = (
            len(g5b["missing_keys"]), len(g5b["duplicate_keys"]),
            len(set(ft_codes) - set(src_map)))
        g5b["passed"] = (not g5b["source_load_failures"] and not g5b["missing_keys"]
                         and not g5b["duplicate_keys"] and not g5b["extra_keys"]
                         and g5b["skipped_rows"] == 0
                         and g5b["validated_rows"] == g5b["expected_rows"]
                         and not g5b.get("row_mismatch")
                         and not g5b.get("duplicate_blocks")
                         and not g5b.get("stock_date_set_diff"))
    else:
        g5b["passed"] = False
        g5b["error"] = "factor_table.csv.gz 缺失"
    report["gates"]["G5b_factor_table"] = g5b
    if not g5b.get("passed", False):
        report["gate_failures"].append(
            f"G5b: 因子表对账未通过 (validated={g5b.get('validated_rows')}/"
            f"expected={g5b.get('expected_rows')} skipped={g5b.get('skipped_rows')} "
            f"missing={g5b.get('n_missing_keys', 0)} dup={g5b.get('n_duplicate_keys', 0)} "
            f"extra={g5b.get('n_extra_keys', 0)} loadFail={len(g5b.get('source_load_failures', []))})")

    report["status"] = "passed" if not report["gate_failures"] else "failed"
    # 2026-09-21 用户裁决: 人工公司行动核对未完成 → audit_passed_with_exception(开发可用, 非正式认证)
    report["verification_status"] = ("audit_passed_with_exception" if report["status"] == "passed"
                                     else "failed")
    report["verification_exception"] = ("STAGE5 §5.2 人工公司行动样本(股数/价值守恒)未完成; "
                                        "用于 retcalc_v1 开发与验证, 不授予 adjusted_verified")
    report["elapsed_s"] = round(time.time() - t0, 1)
    report["manifest_meta"] = {"adjustflag": {"unadj": "3", "hfq": "1"},
                               "fields": "date,open,high,low,close,volume,amount,turn,pctChg",
                               "date_range": "2021-01-01 ~ 2026-09-19",
                               "baostock_version": "0.9.30 (pip freeze)"}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    g6r = report["gates"]["G6_factor_jump_candidates"]
    print(f"审计v3[{report['mode']}]: {report['status'].upper()} | "
          f"G0{'✓' if report['gates']['G0_frozen_baselines']['passed'] else '✗'} "
          f"G1{'✓' if report['gates']['G1_universe_closure']['passed'] else '✗'} "
          f"G2{'✓' if report['gates']['G2_file_sha256']['passed'] else '✗'} "
          f"G3{len(struct_bad)} G4{len(price_bad)}+缺TDX{len(g4_missing_local)} "
          f"G5{len(internal_bad)} G5b:{g5b.get('validated_rows')}/{g5b.get('expected_rows')}"
          f"skip{g5b.get('skipped_rows')}miss{g5b.get('n_missing_keys', 0)} "
          f"G6候选{g6r['bs_candidates']}确认{g6r['bs_confirmed_by_sina']}未确认"
          f"{g6r['bs_candidates'] - g6r['bs_confirmed_by_sina']}漂移{len(drift_list)}"
          f"sinaFail{len(sina_load_failures)} G7{len(ohlc_bad)}/{sample_n} | "
          f"gate_failures={len(report['gate_failures'])} | {report['elapsed_s']}s")
    print(f"→ {OUT}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
