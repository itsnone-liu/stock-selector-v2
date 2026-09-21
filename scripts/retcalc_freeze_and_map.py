#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""retcalc_freeze_and_map.py — retcalc_v1 输入冻结与日期映射预检 (2026-09-21, STAGE5 v7.1)。

任务书第一项: 固定 Stage4 v5 / 生命周期 / adjustment_v1 的 SHA256; 检查实际进出场
日期能否准确映射到因子表; **日期缺失不得静默使用邻近日期填充**(缺失→显式清单)。

产物 output/research/retcalc_v1/:
  INPUT_FREEZE.json   输入文件 SHA256 清单+行数+上游验收引用
  date_map_report.json  逐行映射结果(ok/missing明细, 按字段类型聚合)
"""
import glob
import gzip
import hashlib
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
V5_DIR = ROOT / "output/research/lifecycle_v1/entry_replay_v5_full"
FT = ROOT / "output/research/adjustment_v1/factor_table.csv.gz"
OUT = ROOT / "output/research/retcalc_v1"


def sha256_file(fp: Path) -> str:
    h = hashlib.sha256()
    with open(fp, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def to_prefixed(code6: str) -> str | None:
    """v5 纯6位 → 因子表前缀式(同 universe 规则: 6→sh, 0/3→sz; 其余→None)."""
    if len(code6) == 6 and code6[0] in "036":
        return ("sh." if code6[0] == "6" else "sz.") + code6
    return None


def main() -> int:
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)

    # ── 因子表日期索引(每股日期集合, 供映射) ──
    ft_dates: dict[str, set] = {}
    ft_codes = set()
    with gzip.open(FT, "rt") as f:
        next(f)
        for line in f:
            code, rest = line.split(",", 1)
            if code not in ft_codes:
                ft_codes.add(code)
                ft_dates[code] = set()
            d = rest[:10]
            ft_dates[code].add(d)
    print(f"因子表: {len(ft_codes)} 股", flush=True)

    # ── 输入冻结 ──
    parts = sorted(glob.glob(str(V5_DIR / "partitions/*/*.parquet")))
    v5_files = [{"file": str(Path(p).relative_to(ROOT)), "sha256": sha256_file(Path(p))}
                for p in parts]
    v5_accept = json.loads((ROOT / "docs/reports/ENTRY_REPLAY_STAGE4_V5_FULL_ACCEPTANCE.json").read_text())
    freeze = {
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "rule_version": "retcalc_v1-inputs",
        "entry_replay_v5": {
            "acceptance": "docs/reports/ENTRY_REPLAY_STAGE4_V5_FULL_ACCEPTANCE.json",
            "run_spec_hash": v5_accept["run_spec_hash"],   # 8ebdc40bacd5bcec
            "n_partitions": len(v5_files), "files_sha256": v5_files,
        },
        "adjustment_v1": {
            "factor_table_sha256": sha256_file(FT),
            "manifest": "output/research/adjustment_v1/MANIFEST.json",
            "audit": "docs/reports/ADJUSTMENT_V1_FETCH_AUDIT_V3.json (v3.1, audit_passed_with_exception)",
            "universe_frozen": "config/universe_frozen.json (count 5240)",
        },
        "lifecycle": {"hash_ref": "7f2c8dda08801d27 (spec §0 冻结, 不重跑)",
                      "acceptance": "docs/reports/LIFECYCLE_STAGE4_V1_FULL_ACCEPTANCE.json"},
    }
    (OUT / "INPUT_FREEZE.json").write_text(json.dumps(freeze, ensure_ascii=False, indent=1))

    # ── 日期映射检查(duckdb 逐行拉取关键字段) ──
    import duckdb
    con = duckdb.connect()
    q = f"""
    SELECT code, anchor_day, fill_date_close, fill_date_next,
           t1_fill_date, t2_fill_date, t3_fill_date,
           t1_next_date, t2_next_date, t3_next_date, strategy
    FROM read_parquet({parts!r})
    """
    miss_by_field = Counter()
    miss_rows = []          # 明细(截断保存)
    unmapped_codes = Counter()
    n_rows = 0
    fields = ["anchor_day", "fill_date_close", "fill_date_next", "t1_fill_date",
              "t2_fill_date", "t3_fill_date", "t1_next_date", "t2_next_date", "t3_next_date"]
    cur = con.execute(q)
    cols_pos = {d[0]: i for i, d in enumerate(cur.description)}
    while True:
        chunk = cur.fetchmany(20000)
        if not chunk:
            break
        for row in chunk:
            n_rows += 1
            code6 = row[cols_pos["code"]]
            pc = to_prefixed(str(code6))
            if pc is None or pc not in ft_dates:
                unmapped_codes[str(code6)] += 1
                continue
            dates = ft_dates[pc]
            for fname in fields:
                v = row[cols_pos[fname]]
                if v is None:
                    continue
                ds = str(v)[:10]
                if ds not in dates:
                    miss_by_field[fname] += 1
                    if len(miss_rows) < 200:
                        miss_rows.append({"code": pc, "field": fname, "date": ds,
                                          "strategy": row[cols_pos["strategy"]]})
        if n_rows % 50000 < 20000:
            print(f"[{n_rows}] missing={sum(miss_by_field.values())} unmapped={sum(unmapped_codes.values())} "
                  f"{time.time()-t0:.0f}s", flush=True)

    report = {"n_rows_checked": n_rows,
              "code_prefix_map_fail": dict(unmapped_codes),
              "missing_by_field": dict(miss_by_field),
              "n_missing_total": sum(miss_by_field.values()),
              "missing_detail_sample": miss_rows,
              "policy": "日期缺失不得邻近填充; 有缺失的行在 retcalc 中按字段语义处理(成交日缺失→该视角无效; anchor缺失→该行K3无效), 全部落显式清单"}
    (OUT / "date_map_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"映射检查: {n_rows} 行 | 代码映射失败 {sum(unmapped_codes.values())} 行 | "
          f"日期缺失 {sum(miss_by_field.values())} ({dict(miss_by_field)}) | {time.time()-t0:.0f}s")
    print(f"→ {OUT/'date_map_report.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
