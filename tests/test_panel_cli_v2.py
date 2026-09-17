from __future__ import annotations

import importlib.util
import sys


def test_panel_cli_default_horizons_declared(capsys):
    spec = importlib.util.spec_from_file_location("build_momentum_panel", "scripts/build_momentum_panel.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old = sys.argv
    try:
        sys.argv = ["build_momentum_panel.py", "--help"]
        try:
            mod.main()
        except SystemExit as exc:
            assert exc.code == 0
    finally:
        sys.argv = old
    help_text = capsys.readouterr().out
    assert "--horizons" in help_text
    assert "1,2,3,5,10,15,20" in help_text
    # 实际端到端列输出由外部CLI冒烟验收；此测试锁住入口和默认窗口。
