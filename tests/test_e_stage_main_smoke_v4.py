"""E阶段正式入口端到端冒烟：真实main()跑通stale闸门→设计表→逐日行业→
分组汇总→not_run bootstrap存根。伪造TdxStore，不触真实数据、不构成回测。"""
from __future__ import annotations

import json
import runpy
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_selector.research.momentum_panel import PANEL_VERSION

REPO = Path(__file__).resolve().parents[1]


class _FakeStore:
    _frames: dict = {}

    def __init__(self, tdx_dir=None):
        pass

    def list_codes(self):
        return sorted(self._frames)

    def daily(self, code):
        return self._frames.get(code)


def _mk_panel(tmp: Path) -> Path:
    p = tmp / "panel"; p.mkdir()
    days = pd.bdate_range("2025-01-06", periods=40).strftime("%Y-%m-%d")
    rows = []
    for i, d in enumerate(days, start=1):
        rows.append({"code": "600001", "date": d, "session_index": i,
                     "monthly_pool_spell_age": i, "monthly_provisional_state": True,
                     "weekly_eligibility_state": "eligible" if i % 2 else "observation",
                     "sv_legacy": bool(i % 3 == 0), "td_legacy": False})
    sig = pd.DataFrame(rows)
    sig.to_csv(p / "signal_panel.csv", index=False)
    out = sig[["code", "date"]].copy()
    for h in (1, 5, 20):
        out[f"fwd{h}"] = np.linspace(-0.01, 0.02, len(out))
    out.to_csv(p / "outcome_panel.csv", index=False)
    trig = days[2::6]
    ep = pd.DataFrame({"code": "600001", "signal_type": "sv_legacy", "first_trigger_date": trig})
    ep.to_csv(p / "episode_panel.csv", index=False)
    (p / "manifest.json").write_text(json.dumps({"panel_version": PANEL_VERSION}))
    return p


def test_e_stage_main_smoke_end_to_end(tmp_path, monkeypatch):
    panel = _mk_panel(tmp_path)
    mem = tmp_path / "mem.csv"
    pd.DataFrame({"code": ["600001", "600002"],
                  "effective_from": ["2024-01-01", "2024-01-01"],
                  "effective_to": [None, None],
                  "industry_code": ["C1", "C2"]}).to_csv(mem, index=False)

    idx = pd.bdate_range("2024-12-01", periods=90)
    frames = {}
    for code, base in (("600001", 10.0), ("600002", 20.0)):
        close = base * np.cumprod(1 + np.full(90, 0.002))
        frames[code] = pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                                     "low": close * 0.99, "close": close,
                                     "volume": 1e6, "amount": 1e7}, index=idx)

    import importlib.util
    spec = importlib.util.spec_from_file_location("run_e_stage_analysis",
                                                  REPO / "scripts" / "run_e_stage_analysis.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "TdxStore", _FakeStore)
    _FakeStore._frames = frames

    out = tmp_path / "e_out"
    monkeypatch.setattr(sys, "argv", [
        "run_e_stage_analysis.py", "--panel-dir", str(panel), "--membership", str(mem),
        "--tdx-dir", str(tmp_path), "--out", str(out),
        "--protocol", str(REPO / "config/research/momentum_efficiency/protocol_v1.yaml")])
    mod.main()

    designs = sorted(f.name for f in (out / "designs").glob("*.csv"))
    assert any(d.startswith("daily_increment_within_monthly_weekly") for d in designs)
    assert any(d.startswith("weekly_state_within_daily_shape") for d in designs)
    assert any(d.startswith("weekly_direct_within_monthly") for d in designs)

    ev = pd.read_csv(out / "e_stage_events.csv", dtype={"code": str})
    assert ev["industry_code"].notna().all()
    assert set(ev["industry_context"]) <= {"industry_broad_up", "industry_broad_down",
                                           "industry_normal", "unknown"}
    boot = json.loads((out / "e_stage_bootstrap.json").read_text())
    assert boot["status"] == "not_run"
    man = json.loads((out / "E_STAGE_MANIFEST.json").read_text())
    assert man["bench_codes"] == 2
    assert "不可跨分项相加" in man["median_note"]
    assert (out / "e_stage_summary.csv").exists()


def test_e_stage_main_rejects_stale_panel(tmp_path, monkeypatch):
    panel = _mk_panel(tmp_path)
    (panel / "manifest.json").write_text(json.dumps({"panel_version": "old"}))
    monkeypatch.setattr(sys, "argv", [
        "run_e_stage_analysis.py", "--panel-dir", str(panel),
        "--membership", str(tmp_path / "m.csv"), "--out", str(tmp_path / "o")])
    with pytest.raises(SystemExit, match="stale panel contract"):
        runpy.run_path(str(REPO / "scripts" / "run_e_stage_analysis.py"), run_name="__main__")
