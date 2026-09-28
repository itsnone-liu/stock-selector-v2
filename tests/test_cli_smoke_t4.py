"""T4 CLI 入口机器验证（独立于执行者自述）。

审计要求：主要 CLI 入口的 help/dry-run 验证必须可由审计桥接器在目标 commit
的全量 pytest 中独立复跑，不接受仅写入文档的自述。本文件以子进程真实调用
CLI 入口完成验证：

- 9 个子命令 ``--help`` 全部 exit 0（参数契约可解析，不依赖行情数据）；
- ``bottom-volume --realtime``（无 ``--select``）exit 2 且 stderr 指明用法
  （参数守卫在数据访问之前触发）；
- ``--select --realtime`` 与 ``--realtime --select`` 两种书写顺序都不触发
  参数守卫（都能通过解析进入数据阶段；真实数据缺失导致的失败不属于参数
  契约问题，不以伪数据伪造通过）。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CLI = [sys.executable, "-m", "stock_selector.cli"]

SUBCOMMANDS = [
    "universe", "trends", "after-close", "realtime",
    "board", "bottom-volume", "backtest", "decide", "replay",
]


def _env():
    env = dict(os.environ)
    src = str(REPO / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "") if env.get("PYTHONPATH") else src
    return env


def _run(args):
    return subprocess.run(CLI + args, capture_output=True, text=True, cwd=str(REPO), env=_env())


@pytest.mark.parametrize("cmd", SUBCOMMANDS)
def test_cli_help_exit_zero(cmd):
    r = _run([cmd, "--help"])
    assert r.returncode == 0, f"{cmd} --help exit {r.returncode}\n{r.stderr[-400:]}"
    assert "usage" in (r.stdout + r.stderr).lower()


def test_bottom_realtime_without_select_fails_with_usage():
    r = _run(["bottom-volume", "--realtime"])
    assert r.returncode == 2
    assert "--select" in r.stderr


@pytest.mark.parametrize("order", [["--select", "--realtime"], ["--realtime", "--select"]])
def test_bottom_realtime_both_orders_pass_argument_guard(order):
    r = _run(["bottom-volume"] + order)
    # 参数守卫不得触发（解析通过，进入数据阶段）。数据缺失是运行期错误，
    # 其退出码/报错与 argparse 的 exit 2 + usage 明显不同。
    guard_fired = r.returncode == 2 and "--select" in r.stderr
    assert not guard_fired, f"argument guard wrongly fired for {order}: {r.stderr[-300:]}"
