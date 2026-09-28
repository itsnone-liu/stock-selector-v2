"""审计目标提交唯一性绑定测试（Run audit_20260928055411432, T2, iteration 6）。

提交结构与证明义务：
- T0 = 代码提交（src/tests/SPEC 全部内容），测试运行的记录提交；
- TARGET = 本文件所在的证据提交：TARGET~1 == T0，且 TARGET 相对 T0 的增量
  仅允许 evidence 文件（docs/audit/* 与本绑定文件本身）。

由此本测试在被审计的目标提交上通过，当且仅当：
  1) 工作树干净（被测代码 == 提交内容）；
  2) 目标提交的父提交恰为固定的 T0（配合 3 唯一识别目标提交：T0 之上仅含
     证据增量的提交就是被审计目标）；
  3) 目标相对 T0 的 src/tests/SPEC 增量为空（除本文件），即代码与记录运行时
     完全一致——评审者 checkout T0 或 TARGET 运行套件结果相同；
  4) T2 语义套件收集数冻结为 66。

评审复核路径：git checkout <TARGET> && pytest tests/test_audit_target_binding.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

EXPECTED_CODE_COMMIT = "ccc3250bf3861e2d5fc1ebc5fba70c0cff542f3f"
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
    """T2 语义套件收集数量与提交时一致（模块级 test_ 函数，无参数化）。"""
    import sys as _sys

    for path in (str(REPO / "src"), str(REPO / "tests")):
        if path not in _sys.path:
            _sys.path.insert(0, path)
    import test_spec_semantics_t2 as t2

    names = [n for n in dir(t2) if n.startswith("test_")]
    assert len(names) == EXPECTED_T2_COLLECTION, f"T2 语义套件应收集 {EXPECTED_T2_COLLECTION} 条，实际 {len(names)}"
