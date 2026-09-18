import json
import runpy
import sys

import pandas as pd
import pytest

from stock_selector.research.momentum_panel import PANEL_VERSION


def _panel(tmp_path, version):
    p = tmp_path / "panel"; p.mkdir()
    pd.DataFrame({"code": ["1", "1"], "date": ["2025-01-01", "2025-01-02"],
                  "session_index": [1, 2], "monthly_pool_spell_age": [1, 2],
                  "monthly_provisional_state": [True, True],
                  "weekly_eligibility_state": ["eligible", "eligible"],
                  "sv_legacy": [True, False], "td_legacy": [False, False]}).to_csv(p / "signal_panel.csv", index=False)
    (p / "manifest.json").write_text(json.dumps({"panel_version": version}))
    return p


def test_design_cli_rejects_stale_contract(tmp_path, monkeypatch):
    p = _panel(tmp_path, "old")
    monkeypatch.setattr(sys, "argv", ["build_research_design.py", "--panel-dir", str(p),
                                      "--out", str(tmp_path / "out")])
    with pytest.raises(SystemExit, match="stale panel contract"):
        runpy.run_path("scripts/build_research_design.py", run_name="__main__")


def test_design_cli_materializes_three_comparisons(tmp_path, monkeypatch):
    p = _panel(tmp_path, PANEL_VERSION); out = tmp_path / "out"
    monkeypatch.setattr(sys, "argv", ["build_research_design.py", "--panel-dir", str(p),
                                      "--out", str(out), "--horizons", "1"])
    runpy.run_path("scripts/build_research_design.py", run_name="__main__")
    m = json.loads((out / "DESIGN_MANIFEST.json").read_text())
    assert any(k.startswith("daily_increment_within_monthly_weekly") for k in m["tables"])
    assert any(k.startswith("weekly_state_within_daily_shape") for k in m["tables"])
    assert any(k.startswith("weekly_direct_within_monthly") for k in m["tables"])
