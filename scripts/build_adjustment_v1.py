#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_adjustment_v1.py — 复权因子层 adjustment_v1 构建 (2026-09-21)。

依 STAGE5_POSNEG_ADJUSTED_SPEC §5:
  F_t = hfq_close / unadj_close (baostock 主源), 每股首日归一 F=1(相对因子;
  因子比消费 F_exit/F_entry 对基准不敏感);
  无公司行动→延续前值(逐行情日有行, 无行动日 F 自然恒定);
  停牌沿用前值(行情日展开, 非行情日不在表中);
  排除清单: config/adjustment_v1_exclusions.json (2026-09-21 用户裁决: 600603
  数据源错误剔除 + material错位/因子漂移边缘股不进, 共24只)。

产物 output/research/adjustment_v1/:
  factor_table.csv.gz   长表: code,date,unadj_close,hfq_close,F
  MANIFEST.json         universe_sha/源哈希/排除/审计引用/规则版本
  quality_report.json   每股行数/F范围/首末日期 + fail-fast 清单
"""
import gzip
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
SRC = ROOT / "data/adjustment_baostock"
SN = ROOT / "data/adjustment_sina/factors"
EXCL = ROOT / "config/adjustment_v1_exclusions.json"
OUT = ROOT / "output/research/adjustment_v1"
RULE_VERSION = "adjustment_v1"
TOL_F = 1e-9


def sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    t0 = time.time()
    manifest = json.loads((SRC / "fetch_manifest.json").read_text())
    ok_codes = sorted(c for c, v in manifest["stocks"].items() if v.get("status") == "ok")
    excl = set(json.loads(EXCL.read_text())["excluded"])
    codes = [c for c in ok_codes if c not in excl]
    print(f"构建 adjustment_v1: 源ok {len(ok_codes)} - 排除 {len(ok_codes) - len(codes)} = {len(codes)} 只", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    fails = []
    stats = {"n": 0, "rows": 0, "f_min": 1e9, "f_max": 0.0,
             "first_date": Counter(), "last_date": Counter()}
    # sina 交叉验证对照(末段 F vs sina 末因子)
    xv = []
    fact_path = OUT / "factor_table.csv.gz"
    with gzip.open(fact_path, "wt", encoding="utf-8") as fo:
        fo.write("code,date,unadj_close,hfq_close,F\n")
        for i, code in enumerate(codes):
            try:
                p = json.load(gzip.open(SRC / "per_stock" / f"{code}.json.gz", "rt"))
                u = {r[0]: float(r[4]) for r in p["unadj"]}
                h = {r[0]: float(r[4]) for r in p["hfq"]}
                days = sorted(set(u) & set(h))
                if not days or not u[days[0]]:
                    raise ValueError("empty/unusable")
                base = h[days[0]] / u[days[0]]
                if base <= 0:
                    raise ValueError("bad base")
                rows = []
                for d in days:
                    if u[d] <= 0:
                        continue
                    f_raw = h[d] / u[d]
                    f = f_raw / base   # 首日归一
                    rows.append((code, d, u[d], h[d], f))
                    stats["f_min"] = min(stats["f_min"], f)
                    stats["f_max"] = max(stats["f_max"], f)
                for code_, d, uc, hc, f in rows:
                    fo.write(f"{code_},{d},{uc:.4f},{hc:.6f},{f:.10f}\n")
                stats["n"] += 1
                stats["rows"] += len(rows)
                stats["first_date"][rows[0][1][:7]] += 1
                stats["last_date"][rows[-1][1][:7]] += 1
                # 交叉验证: 末段 F_raw vs sina 末因子(窗口内)
                try:
                    s = json.load(gzip.open(SN / f"{code}.json.gz", "rt"))
                    wl, wh = days[0], days[-1]
                    evs = sorted((e["date"], float(e["factor"])) for e in s["events"]
                                 if wl <= e["date"] <= wh)
                    if evs:
                        f_end = h[days[-1]] / u[days[-1]]
                        xv.append({"code": code, "bs_f_end": round(f_end, 6),
                                   "sina_f_end": round(evs[-1][1], 6),
                                   "ratio": round(f_end / evs[-1][1], 6)})
                except Exception:
                    pass
            except Exception as e:
                fails.append({"code": code, "err": str(e)[:60]})
            if (i + 1) % 500 == 0:
                print(f"[{i+1}/{len(codes)}] rows={stats['rows']} fails={len(fails)} "
                      f"elapsed={time.time()-t0:.0f}s", flush=True)

    manifest_out = {
        "rule_version": RULE_VERSION,
        "built_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "universe_sha256": manifest.get("universe_sha256"),
        "n_source_ok": len(ok_codes), "n_excluded": len(ok_codes) - len(codes),
        "n_built": stats["n"], "n_rows": stats["rows"],
        "exclusions": sorted(excl),
        "exclusion_rule": json.loads(EXCL.read_text())["rule"],
        "source": {
            "primary": "data/adjustment_baostock (hfq/unadj close列 r[4])",
            "fetch_manifest_sha256": sha256_file(SRC / "fetch_manifest.json"),
            "factor_table_sha256": sha256_file(fact_path),
        },
        "audit_refs": [
            "docs/reports/ADJUSTMENT_V1_FETCH_AUDIT.json (A1-A6, 单源)",
            "docs/reports/ADJUSTMENT_V1_CROSS_AUDIT.json (C1-C3, 跨源)",
        ],
        "semantics": "F=hfq/unadj 首日归一; 无行动延续前值; 停牌沿用(行情日展开); P_adj=P_raw×F",
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest_out, ensure_ascii=False, indent=1))
    qr = {"n": stats["n"], "rows": stats["rows"],
          "f_range": [round(stats["f_min"], 4), round(stats["f_max"], 4)],
          "first_date_hist": dict(stats["first_date"]), "last_date_hist": dict(stats["last_date"]),
          "fails": fails, "cross_check_sina": {"n": len(xv), "sample": xv[:5]}}
    (OUT / "quality_report.json").write_text(json.dumps(qr, ensure_ascii=False, indent=1))
    print(f"完成: {stats['n']}只 {stats['rows']}行 F∈[{stats['f_min']:.3f},{stats['f_max']:.3f}] "
          f"fails={len(fails)} 交叉验证{xv and len(xv)}只 → {OUT} ({time.time()-t0:.0f}s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
