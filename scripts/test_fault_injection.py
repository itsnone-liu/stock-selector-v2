#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_fault_injection.py — audit_adjustment_v3 故障注入测试 (2026-09-21 第二轮审查要求)。

5 类注入 × 各自独立沙盒, 断言对应门禁 **不能错误通过**:
  A 篡改因子表 F 值        → G5b row_mismatch
  B 删除因子表一行         → G5b validated_rows < expected_rows
  C 删除一只 TDX .day     → G4 missing_local_files
  D 删除一只 sina factors → G6 sina_load_failures
  E 篡改冻结清单(改一个code, 不动codes_sha256) → G0 codes_sha256 不符

沙盒: /tmp/audit_fault_lab/ 复制 8 只真实股(含分红/送转事件), frozen 只记 codes_sha256
(其余基准 not_recorded 跳过), excl 为空。基线(无注入)必须 PASSED 供对照。
"""
import gzip
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

PY = sys.executable
ROOT = Path("/root/project/workspace/stock-selector-v2")
LAB = Path("/tmp/audit_fault_lab")
SRC = ROOT / "data/adjustment_baostock"
SN = ROOT / "data/adjustment_sina/factors"
TDX = Path("/root/tdx_data/vipdoc")
V3 = ROOT / "scripts/audit_adjustment_v3.py"

# 8 只真实股: 含除权事件/停牌差异
CODES = ["sh.600000", "sh.600006", "sh.603991", "sh.688037",
         "sz.000006", "sz.300014", "sz.300757", "sz.302132"]


def build_sandbox(tag: str, tamper=None) -> Path:
    d = LAB / tag
    if d.exists():
        shutil.rmtree(d)
    (d / "data/per_stock").mkdir(parents=True)
    (d / "sina").mkdir()
    (d / "tdx/sh/lday").mkdir(parents=True)
    (d / "tdx/sz/lday").mkdir(parents=True)
    # manifest: 只留 8 只(保留原每股 sha256 → G2 可验)
    m = json.loads((SRC / "fetch_manifest.json").read_text())
    m["stocks"] = {c: m["stocks"][c] for c in CODES}
    (d / "data/fetch_manifest.json").write_text(json.dumps(m, indent=1))
    for c in CODES:
        shutil.copy(SRC / "per_stock" / f"{c}.json.gz", d / "data/per_stock" / f"{c}.json.gz")
        shutil.copy(SN / f"{c}.json.gz", d / "sina" / f"{c}.json.gz")
        mkt, num = c.split(".")
        shutil.copy(TDX / mkt / "lday" / f"{mkt}{num}.day", d / "tdx" / mkt / "lday" / f"{mkt}{num}.day")
    # frozen: 8 只 codes + codes_sha256 (其余基准 not_recorded)
    payload = "\n".join(CODES) + "\n"
    frozen = {"count": len(CODES), "codes": list(CODES),
              "codes_sha256": hashlib.sha256(payload.encode()).hexdigest()}
    if tamper == "E":   # 改一个 code 不动哈希
        frozen["codes"][0] = "sh.699999"
    (d / "frozen.json").write_text(json.dumps(frozen, indent=1))
    # 因子表: 从 8 只源构建(与 build_adjustment_v1 同法: F=hfq/unadj 首日归一)
    lines = ["code,date,unadj_close,hfq_close,F"]
    for c in CODES:
        p = json.load(gzip.open(d / "data/per_stock" / f"{c}.json.gz", "rt"))
        u = {r[0]: float(r[4]) for r in p["unadj"]}
        h = {r[0]: float(r[4]) for r in p["hfq"]}
        days = sorted(u)
        base = h[days[0]] / u[days[0]]
        for d_ in days:
            if u[d_] <= 0:
                continue
            lines.append(f"{c},{d_},{u[d_]:.4f},{h[d_]:.6f},{(h[d_]/u[d_])/base:.10f}")
    if tamper == "A":   # 篡改: 第100行 F×10
        parts = lines[100].split(",")
        parts[4] = f"{float(parts[4]) * 10:.10f}"
        lines[100] = ",".join(parts)
    if tamper == "B":   # 删一行
        del lines[200]
    with gzip.open(d / "ft.csv.gz", "wt") as f:
        f.write("\n".join(lines) + "\n")
    # excl 空
    (d / "excl.json").write_text(json.dumps({"excluded": []}))
    if tamper == "C":   # 删一只 TDX
        (d / "tdx/sh/lday/sh600000.day").unlink()
    if tamper == "D":   # 删一只 sina
        (d / "sina/sh.600000.json.gz").unlink()
    return d


def run_audit(d: Path, no_g0: bool = True) -> tuple[int, dict]:
    cmd = [PY, str(V3),
           "--data-dir", str(d / "data"), "--sina-dir", str(d / "sina"),
           "--tdx-dir", str(d / "tdx"), "--frozen", str(d / "frozen.json"),
           "--excl", str(d / "excl.json"), "--ft", str(d / "ft.csv.gz"),
           "--out", str(d / "report.json")]
    if no_g0:
        cmd.append("--no-g0")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    rep = json.loads((d / "report.json").read_text())
    return r.returncode, rep


def main() -> int:
    print("── 基线(无注入, 应 PASSED):")
    d = build_sandbox("baseline")
    rc, rep = run_audit(d, no_g0=True)
    print(f"  exit={rc} status={rep['status']} gate_failures={rep['gate_failures']}")
    assert rc == 0 and rep["status"] == "passed", "基线必须通过"

    cases = [
        ("A", "篡改因子表F", "G5b", True),
        ("B", "删因子表一行", "G5b", True),
        ("C", "删TDX文件", "G4", True),
        ("D", "删sina文件", "G6", True),
        ("E", "改冻结清单", "G0", False),   # E 必须带 G0
    ]
    all_ok = True
    for tag, desc, gate, no_g0 in cases:
        d = build_sandbox(f"fault_{tag}", tamper=tag)
        rc, rep = run_audit(d, no_g0=no_g0)
        hit = any(gf.startswith(gate) for gf in rep["gate_failures"])
        ok = (rc == 1 and rep["status"] == "failed" and hit)
        all_ok &= ok
        print(f"── 注入{tag} {desc}: exit={rc} status={rep['status']} "
              f"命中{gate}={'✓' if hit else '✗'} {'PASS' if ok else '**未拦截**'}")
        if not hit:
            print(f"   gate_failures={rep['gate_failures']}")
    print(f"\n故障注入测试: {'全部拦截 ✓' if all_ok else '存在未拦截 ✗'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
