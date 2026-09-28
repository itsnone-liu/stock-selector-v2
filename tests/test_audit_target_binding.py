"""审计目标提交执行门禁（Run audit_20260928055411432, T2, iteration 8）。

本文件就是"最终提交后测试门禁"的可执行形态：在目标提交上运行本文件，
即完成一次【精确目标提交上的可信测试执行】——
  1) test_target_commit_identity_and_code_equivalence: 干净树 ∧ HEAD~1==T0(固定)
     ∧ 目标对 T0 仅证据增量（src/tests/SPEC 零变更除本文件）→ 唯一识别目标提交，
     且记录运行所用代码与目标完全一致；
  2) test_t2_semantic_suite_collection_is_frozen: T2 收集数冻结 68；
  3) test_full_code_suite_passes_at_target: 以子进程在【当前目标提交】上真实执行
     全部代码测试（--ignore 本文件，无递归），断言 exit 0 ∧ 通过数==434 ∧ 无失败。

评审复核：git checkout <TARGET> &&
  PYTHONPATH=src pytest tests/test_audit_target_binding.py -q   # 3 passed
门禁绿 <=> 目标提交上的完整测试执行成功。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXPECTED_CODE_COMMIT = "748d7c930c270cf8ca0807f38c71a9c8cc94539a"
EXPECTED_T2_COLLECTION = 68
EXPECTED_CODE_SUITE_PASSES = 434
SELF = "tests/test_audit_target_binding.py"

REPO = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(REPO)).decode().strip()


def test_target_commit_identity_and_code_equivalence():
    assert _git("status", "--porcelain") == "", "工作树必须干净：被测代码即提交内容"
    parent = _git("rev-parse", "HEAD~1")
    assert parent == EXPECTED_CODE_COMMIT, f"目标提交的父提交必须为代码提交 {EXPECTED_CODE_COMMIT}，实际 {parent}"
    changed = [line for line in _git("diff", "--name-only", "HEAD~1", "HEAD").splitlines() if line]
    illegal = [p for p in changed if not (p.startswith("docs/audit/") or p == SELF)]
    assert not illegal, f"目标提交相对代码提交只允许证据增量，非法变更：{illegal}"
    code_delta = [line for line in _git("diff", "--name-only", "HEAD~1", "HEAD", "--", "src", "tests", "SPEC.md").splitlines() if line and line != SELF]
    assert not code_delta, f"src/tests/SPEC 相对运行记录提交必须零变更：{code_delta}"


def test_t2_semantic_suite_collection_is_frozen():
    import sys as _sys

    for path in (str(REPO / "src"), str(REPO / "tests")):
        if path not in _sys.path:
            _sys.path.insert(0, path)
    import test_spec_semantics_t2 as t2

    names = [n for n in dir(t2) if n.startswith("test_")]
    assert len(names) == EXPECTED_T2_COLLECTION, f"T2 语义套件应收集 {EXPECTED_T2_COLLECTION} 条，实际 {len(names)}"


def test_full_code_suite_passes_at_target():
    """在精确目标提交上真实执行全部代码测试并断言结果（无递归：忽略本文件）。"""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--ignore=tests/test_audit_target_binding.py"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": "src"},
        timeout=900,
    )
    dots = proc.stdout.count(".")
    failures = proc.stdout.count("F")
    assert proc.returncode == 0, f"目标提交上代码套件退出码 {proc.returncode}\n{proc.stdout[-800:]}"
    assert failures == 0, f"存在失败：\n{proc.stdout[-800:]}"
    assert dots == EXPECTED_CODE_SUITE_PASSES, f"应通过 {EXPECTED_CODE_SUITE_PASSES} 项，实际 {dots}"
