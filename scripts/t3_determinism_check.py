#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""t3_determinism_check.py — 双跑确定性比对。

读取两次构建的 integrity_report.json（--first/--second），比对全部
product_sha256 是否逐字节一致；一致 → 确定性 Gate PASS。
"""
import argparse
import json
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/t3_v2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--first", default=str(OUT / "integrity_report.json"))
    ap.add_argument("--second", default=str(OUT / "_rerun_integrity_report.json"))
    args = ap.parse_args()
    a = json.loads(Path(args.first).read_text())["product_sha256"]
    b = json.loads(Path(args.second).read_text())["product_sha256"]
    diff = {k: {"first": a.get(k), "second": b.get(k)}
            for k in sorted(set(a) | set(b)) if a.get(k) != b.get(k)}
    res = {
        "gate": "DETERMINISM",
        "products_compared": len(set(a) | set(b)),
        "identical": not diff,
        "diff": diff,
        "verdict": "PASS" if not diff else "FAIL",
    }
    (OUT / "determinism_check.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1))
    print(json.dumps({k: res[k] for k in (
        "products_compared", "identical", "verdict")}))
    return 0 if not diff else 1


if __name__ == "__main__":
    raise SystemExit(main())
