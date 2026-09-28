"""审计目标提交唯一性绑定测试（Run audit_20260928055411432, T2, iteration 7）。

结构：T0=代码提交（全部 src/tests/SPEC 变更），套件在 T0 干净树全量执行并落盘；
TARGET=本文件所在提交=T0+仅证据增量。本测试在 TARGET 上通过当且仅当：
  1) 工作树干净（被测代码 == 提交内容）；
  2) HEAD~1 == T0（固定哈希；T0 从未被 amend，可 checkout 复跑）；
  3) TARGET 相对 T0 的增量仅证据文件（docs/audit/* 与本文件），
     src/tests/SPEC 零变更 → 记录的运行与 TARGET 代码完全一致；
  4) T2 语义套件收集数冻结 66。
评审复核：git checkout <TARGET> && pytest tests/test_audit_target_binding.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXPECTED_CODE_COMMIT = "f17ccd7514eeee40ea51500f13b69787a7db6ebc"
EXPECTED_T2_COLLECTION = 66
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
