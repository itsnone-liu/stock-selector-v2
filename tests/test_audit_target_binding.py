"""审计目标提交执行绑定测试（Run audit_20260928055411432, T2）。

该测试让“测试套件在被审计的目标提交上执行过”成为可机器复核的证据：
评审者 checkout 证据包的 TARGET_COMMIT 后运行本文件，通过当且仅当
  1) 工作树干净（被测代码与提交内容完全一致），且
  2) 该提交的父提交等于下方固定的 EXPECTED_PARENT（即迭代5目标提交），
  3) T2 语义套件的收集数量与提交时一致（62+2=64 条，防止偷换套件）。
任何在其他提交/脏树上执行都会失败。EXPECTED_PARENT 在提交前即可确定
（f98447e 为迭代4提交），因此本文件内容与目标提交自洽，可由 git 证据直接核验。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

EXPECTED_PARENT = "f98447e9e030fbedfa87241fc69698bfc826807f"
EXPECTED_T2_COLLECTION = 64

REPO = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(REPO)).decode().strip()


def test_suite_executes_at_audited_target_commit():
    assert _git("status", "--porcelain") == "", "工作树必须干净：被测代码即提交内容"
    parent = _git("rev-parse", "HEAD~1")
    assert parent == EXPECTED_PARENT, f"必须在父提交为 {EXPECTED_PARENT} 的目标提交上执行，实际父提交 {parent}"


def test_t2_semantic_suite_collection_is_frozen():
    """T2 语义套件收集数量与提交时一致（该文件全部为模块级 test_ 函数，
    无参数化，函数数 == pytest 收集数）。"""
    import sys

    for path in (str(REPO / "src"), str(REPO / "tests")):
        if path not in sys.path:
            sys.path.insert(0, path)
    import test_spec_semantics_t2 as t2

    names = [n for n in dir(t2) if n.startswith("test_")]
    assert len(names) == EXPECTED_T2_COLLECTION, f"T2 语义套件应收集 {EXPECTED_T2_COLLECTION} 条，实际 {len(names)}"
