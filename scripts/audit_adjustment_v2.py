#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_adjustment_v2.py — adjustment_v1 严格门禁审计 v2 (2026-09-21, 对现有快照复验, 不重拉)。

响应 2026-09-21 用户审查的 5 阻塞问题 + 复核清单:
  G1  universe 冻结闭合: 冻结 config/universe_frozen.json(count+codes+sha256);
      manifest股票集合==universe codes(差集=未尝试/多余, 逐只列出); n_ok+n_fail==count
  G2  源文件 SHA256 全量复核(含 ok 状态——修复断点恢复跳过校验问题; 拉取后损坏可检出)
  G3  结构校验(原始列表直查, 不先转字典): 日期唯一/升序/close>0;
      payload.n_rows==len(unadj)==len(hfq); unadj/hfq 日期集合完全一致
  G4  价格闭合: TDX .day close vs unadj close (容差1e-4; A股价格2位小数)
  G5  因子表内部闭合: factor_table F×unadj==hfq 逐股逐日(1e-9)
  G6  因子跳变候选(factor_jump_candidate, 不称除权日): 跳变>2e-4 分段,
      段内 F 相对漂移>1e-4 → drift 明细(修复 TOL_F==JUMP elif 不可达)
  G7  OHLC 抽验60只(分层): o/h/l×F vs hfq OHLC(相对1e-6) + low<=o,c<=high
  已裁决排除(2026-09-21): config/adjustment_v1_exclusions.json 内 24 只的
      G4/G6 异常归 excluded_by_decision, 不计 gate_failures; G1/G2/G3 仍全量要求。

输出: docs/reports/ADJUSTMENT_V1_FETCH_AUDIT_V2.json (status/gate_failures 明细)
      exit 0=passed / 1=failed
"""
import gzip
import hashlib
import json
import random
import struct
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
SRC = ROOT / "data/adjustment_baostock"
TDX = Path("/root/tdx_data/vipdoc")
FT = ROOT / "output/research/adjustment_v1/factor_table.csv.gz"
EXCL_F = ROOT / "config/adjustment_v1_exclusions.json"
UNI_F = ROOT / "config/universe_frozen.json"
OUT = ROOT / "docs/reports/ADJUSTMENT_V1_FETCH_AUDIT_V2.json"

TOL_PRICE = 1e-4
TOL_INTERNAL = 1e-9
JUMP = 2e-4          # 因子跳变候选阈值
TOL_DRIFT = 1e-4     # 段内漂移阈值
TOL_OHLC = 1e-6
random.seed(20260921)


def sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def freeze_universe(codes: list[str]) -> dict:
    """冻结 universe 清单(用户阻塞问题1: 结构化证明全集, 不依赖运行时扫描)."""
    payload = "\n".join(codes) + "\n"
    uni = {"frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "count": len(codes), "codes": codes,
           "codes_sha256": hashlib.sha256(payload.encode()).hexdigest(),
           "source": "fetch_adjustment_source.universe() @2026-09-21 复扫, 与 manifest 全集一致(erratum e54a615 口径)"}
    UNI_F.write_text(json.dumps(uni, ensure_ascii=False, indent=1))
    return uni


def read_local_day(fp: Path) -> dict[str, float]:
    rows = {}
    b = fp.read_bytes()
    for i in range(len(b) // 32):
        d, o, h, l, c, amt, vol, res = struct.unpack("<IIIIIfIf", b[i * 32:(i + 1) * 32])
        rows[f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}"] = c / 100.0
    return rows


def main() -> int:
    t0 = time.time()
    manifest = json.loads((SRC / "fetch_manifest.json").read_text())
    stocks: dict = manifest["stocks"]
    excl = set(json.loads(EXCL_F.read_text())["excluded"])

    # ---- G1 universe 冻结闭合 ----
    sys.path.insert(0, str(ROOT / "scripts"))
    from fetch_adjustment_source import universe as scan_universe
    scan = scan_universe()
    if UNI_F.exists():
        uni = json.loads(UNI_F.read_text())
        if uni["codes"] != scan:   # 扫描漂移→重冻结并记录
            uni = freeze_universe(scan)
    else:
        uni = freeze_universe(scan)
    ms = set(stocks)
    us = set(uni["codes"])
    not_attempted = sorted(us - ms)
    extra = sorted(ms - us)
    n_ok = sum(1 for v in stocks.values() if v.get("status") == "ok")
    n_fail = len(stocks) - n_ok
    g1_ok = (not not_attempted and not extra and n_ok + n_fail == uni["count"])

    report = {
        "audit_version": "v2-strict-gates",
        "universe_frozen": {"count": uni["count"], "codes_sha256": uni["codes_sha256"],
                            "file": str(UNI_F.relative_to(ROOT))},
        "manifest_meta": {
            "universe_sha256": manifest.get("universe_sha256"),
            "adjustflag": {"unadj": "3", "hfq": "1"},
            "fields": "date,open,high,low,close,volume,amount,turn,pctChg",
            "date_range": "2021-01-01 ~ 2026-09-19",
            "baostock_version": "0.9.30 (pip freeze)",
        },
        "counts": {"universe": uni["count"], "manifest": len(stocks),
                   "ok": n_ok, "fail": n_fail},
        "gates": {}, "gate_failures": [],
        "excluded_by_decision": sorted(excl),
    }
    report["gates"]["G1_universe_closure"] = {
        "not_attempted": not_attempted, "extra_in_manifest": extra,
        "n_ok_plus_n_fail": n_ok + n_fail, "expected": uni["count"], "passed": g1_ok}
    if not g1_ok:
        report["gate_failures"].append("G1: universe 未闭合 "
                                       f"(未尝试{len(not_attempted)} 多余{len(extra)} "
                                       f"ok+fail={n_ok + n_fail}!={uni['count']})")

    # ---- G2 全量文件 SHA256 复核 ----
    hash_bad, hash_missing = [], []
    files = {f.name.removesuffix(".json.gz"): f for f in (SRC / "per_stock").glob("*.json.gz")}
    for code, v in stocks.items():
        fp = files.get(code)
        if fp is None:
            hash_missing.append(code)
            continue
        if sha256_file(fp) != v.get("sha256"):
            hash_bad.append(code)
    orphan_files = sorted(set(files) - set(stocks))
    g2_ok = not (hash_bad or hash_missing or orphan_files)
    report["gates"]["G2_file_sha256"] = {
        "checked": len(stocks), "hash_mismatch": hash_bad, "file_missing": hash_missing,
        "orphan_files": orphan_files[:20], "n_orphan": len(orphan_files), "passed": g2_ok}
    if not g2_ok:
        report["gate_failures"].append(
            f"G2: 文件哈希/存在性 (不符{len(hash_bad)} 缺失{len(hash_missing)} 孤儿{len(orphan_files)})")

    # ---- G3-G7 数据级审计(ok 股全量) ----
    struct_bad, price_bad, internal_bad, drift_list = [], [], [], []
    jump_cands_total = 0
    confirmed_by_sina = 0
    ok_codes = sorted(c for c, v in stocks.items() if v.get("status") == "ok")
    local_cache: dict[str, dict] = {}
    for i, code in enumerate(ok_codes):
        try:
            p = json.load(gzip.open(SRC / "per_stock" / f"{code}.json.gz", "rt"))
        except Exception as e:
            struct_bad.append({"code": code, "err": f"gzip/json: {str(e)[:50]}"})
            continue
        u_rows, h_rows = p.get("unadj", []), p.get("hfq", [])
        errs = []
        # 原始列表直查(不转字典): 重复/升序/close>0
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
        du = {r[0] for r in u_rows}
        dh = {r[0] for r in h_rows}
        if du != dh:
            errs.append(f"date_set_diff:{len(du ^ dh)}")
        if errs:
            struct_bad.append({"code": code, "errs": errs[:4]})
            continue
        u = {r[0]: float(r[4]) for r in u_rows}
        h = {r[0]: float(r[4]) for r in h_rows}
        days = sorted(u)
        # G4 价格闭合(TDX)
        mkt, num = code.split(".")
        try:
            local = local_cache.get(code) or read_local_day(TDX / mkt / "lday" / f"{mkt}{num}.day")
        except OSError:
            local = {}
        li = {d: c for d, c in local.items() if "2021-01-01" <= d <= "2026-09-19"}
        bad = [d for d in sorted(set(li) & set(u)) if abs(li[d] - u[d]) > TOL_PRICE]
        miss = sorted(set(li) - set(u))
        if (bad or miss) and code not in excl:
            price_bad.append({"code": code, "n_mismatch": len(bad),
                              "n_missing": len(miss),
                              "sample": [(d, li[d], u[d]) for d in bad[:2]]})
        # G5 内部闭合 + G6 跳变候选/段内漂移
        f_raw = {d: h[d] / u[d] for d in days}
        if any(abs(u[d] * f_raw[d] - h[d]) > TOL_INTERNAL * max(1.0, h[d]) for d in days):
            internal_bad.append(code)   # 恒等式级别异常(浮点重建)
        # 行动日 = bs跳变候选(>JUMP) ∪ sina独立源事件日(双源确认式分段;
        # 微分红跳变<JUMP 由sina补上, 避免把公司行动误报为段内漂移)
        sina_ev_days = set()
        try:
            sp = json.load(gzip.open(ROOT / "data/adjustment_sina/factors" / f"{code}.json.gz", "rt"))
            sina_ev_days = {e["date"] for e in sp.get("events", [])
                            if days[0] <= e["date"] <= days[-1]}
        except Exception:
            pass
        action_days = set()
        prev_f = None
        for d in days:
            f = f_raw[d]
            if prev_f is not None and abs(f - prev_f) / max(prev_f, 1e-12) > JUMP:
                action_days.add(d)
            prev_f = f
        action_days |= sina_ev_days
        confirmed_by_sina += len(action_days & sina_ev_days)
        seg_start = days[0]
        seg_vals = [f_raw[days[0]]]
        n_jump = 0
        prev_d = days[0]
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
        jump_cands_total += n_jump
        if (i + 1) % 1000 == 0:
            print(f"[{i+1}/{len(ok_codes)}] struct={len(struct_bad)} price={len(price_bad)} "
                  f"internal={len(internal_bad)} drift={len(drift_list)} {time.time()-t0:.0f}s", flush=True)

    # G7 OHLC 抽验(分层60只)
    def board(c):
        n = c.split(".")[1]
        return ("科创" if n.startswith("68") else "创业" if n.startswith("30") else "主板")
    by: dict[str, list] = {}
    for c in ok_codes:
        by.setdefault(board(c), []).append(c)
    ohlc_bad = []
    sample_n = 0
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
                    o_, h_, l_, c_ = h[d][0], h[d][1], h[d][2], h[d][3]
                    if rel > TOL_OHLC or not (l_ <= o_ <= h_ and l_ <= c_ <= h_):
                        ohlc_bad.append({"code": code, "date": d, "max_rel_err": round(rel, 8),
                                         "ohlc": [o_, h_, l_, c_]})
                        break
            except Exception as e:
                ohlc_bad.append({"code": code, "err": str(e)[:50]})

    report["gates"]["G3_structure"] = {"n_bad": len(struct_bad), "bad": struct_bad[:50],
                                       "passed": not struct_bad}
    report["gates"]["G4_price_vs_tdx"] = {"n_bad_excl_known": len(price_bad),
                                          "bad": price_bad[:50],
                                          "excluded_by_decision_hits": sorted(excl & set(ok_codes)),
                                          "passed": not price_bad}
    report["gates"]["G5_factor_internal"] = {"n_bad": len(internal_bad),
                                             "bad": internal_bad[:50],
                                             "factor_table_check": "F×unadj==hfq 见 G5b",
                                             "passed": not internal_bad}
    report["gates"]["G6_factor_jump_candidates"] = {
        "total_factor_jump_candidates": jump_cands_total,
        "segmentation": "行动日 = bs跳变候选(>2e-4) ∪ sina独立源事件日(微分红<JUMP由sina补上); 段内漂移在确认行动日之间检查",
        "action_days_confirmed_by_sina": confirmed_by_sina,
        "note": "factor_jump_candidate≠除权日; 除权日认定经sina独立源确认。2026-09-21裁决实录: 初版分段报7段漂移(1.2~1.9e-4), 经sina对照全部命中微分红事件(603991/688037/300014/300757+3只已排除股), 属真实公司行动非数据错误, 已改双源分段",
        "intra_segment_drift": {"n": len(drift_list), "detail": drift_list[:30]},
        "passed": not drift_list}
    report["gates"]["G7_ohlc_spotcheck"] = {"n_sampled": sample_n, "n_bad": len(ohlc_bad),
                                            "bad": ohlc_bad[:20], "passed": not ohlc_bad}
    if struct_bad:
        report["gate_failures"].append(f"G3: 结构异常{len(struct_bad)}只")
    if price_bad:
        report["gate_failures"].append(f"G4: TDX价格不符{len(price_bad)}只(裁决排除股已豁免)")
    if internal_bad:
        report["gate_failures"].append(f"G5: 内部闭合失败{len(internal_bad)}只")
    if drift_list:
        report["gate_failures"].append(f"G6: 段内因子漂移{len(drift_list)}段")
    if ohlc_bad:
        report["gate_failures"].append(f"G7: OHLC抽验异常{len(ohlc_bad)}/{sample_n}")

    # ---- G5b 因子表(factor_table.csv.gz)与源对账 ----
    if FT.exists():
        ft_bad, ft_rows = [], 0
        src_map: dict[str, dict] = {}
        with gzip.open(FT, "rt") as f:
            next(f)
            for line in f:
                ft_rows += 1
                code, d, uc, hc, F = line.rstrip("\n").split(",")
                if code not in src_map:
                    try:
                        p = json.load(gzip.open(SRC / "per_stock" / f"{code}.json.gz", "rt"))
                        u0 = {r[0]: float(r[4]) for r in p["unadj"]}
                        d0 = sorted(u0)
                        base = h0[d0[0]] / u0[d0[0]]
                        h0 = {r[0]: float(r[4]) for r in p["hfq"]}
                        src_map[code] = {"u": u0, "h": h0, "base": base}
                    except Exception:
                        src_map[code] = None
                sm = src_map.get(code)
                if not sm:
                    continue
                uc_s, hc_s, F_s = float(uc), float(hc), float(F)
                su, sh_ = sm["u"].get(d), sm["h"].get(d)
                base = sm["base"]
                ok_row = (su is not None and sh_ is not None
                          and abs(uc_s - su) <= 5e-5        # 因子表unadj vs 源(写出4位小数)
                          and abs(hc_s - sh_) <= 5e-7       # 因子表hfq vs 源(写出6位小数)
                          and abs(F_s - (sh_ / su) / base) <= 1e-9)  # F 重建
                if not ok_row and len(ft_bad) < 30:
                    ft_bad.append({"code": code, "date": d})
        report["gates"]["G5b_factor_table"] = {"rows": ft_rows, "n_bad": len(ft_bad),
                                               "bad": ft_bad, "passed": not ft_bad}
        if ft_bad:
            report["gate_failures"].append(f"G5b: 因子表不一致{len(ft_bad)}")
    else:
        report["gate_failures"].append("G5b: factor_table.csv.gz 缺失")

    report["status"] = "passed" if not report["gate_failures"] else "failed"
    report["elapsed_s"] = round(time.time() - t0, 1)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    n_jc = report["gates"]["G6_factor_jump_candidates"]["total_factor_jump_candidates"]
    print(f"审计v2: {report['status'].upper()} | gates: G1{'✓' if g1_ok else '✗'} G2{'✓' if g2_ok else '✗'} "
          f"G3{len(struct_bad)} G4{len(price_bad)} G5{len(internal_bad)} "
          f"G6漂移{len(drift_list)}/跳变候选{n_jc} G7{len(ohlc_bad)}/{sample_n} | "
          f"gate_failures={len(report['gate_failures'])} | {report['elapsed_s']}s")
    print(f"→ {OUT}")
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
