"""run_progressive_analysis入口端到端冒烟：三对照→组间bootstrap→策略/形态事件
→同结构正负→持有期背景全部产出；伪造TdxStore，不触真实数据。"""
from __future__ import annotations

import json
import sys
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
    days = pd.bdate_range("2025-01-06", periods=60).strftime("%Y-%m-%d")
    sig_rows, out_rows, uni_rows = [], [], []
    for i, d in enumerate(days, start=1):
        for code in ("600001", "600002", "600003"):
            # A对照需足样本：600001 sv隔日真(触发30/未触发30)，其余明确未触发
            if code == "600001":
                sv, td = bool(i % 2 == 0), False
            else:
                sv, td = False, False
            sig_rows.append({"code": code, "date": d, "session_index": i,
                             "monthly_pool_spell_age": i, "monthly_provisional_state": True,
                             "weekly_eligibility_state": "eligible",
                             "sv_legacy": sv, "td_legacy": td})
            r = {"code": code, "date": d}
            for h in (1, 2, 3, 5, 10, 15, 20):
                r[f"fwd{h}"] = 0.001 * ((i % 5) - 2) + (0.002 if code == "600001" else 0.0)
            out_rows.append(r)
            uni_rows.append({"code": code, "date": d, "session_index": i,
                             "data_status": "available", "monthly_pool_state": "in",
                             "monthly_pool_spell_id": 1, "monthly_pool_spell_age": i,
                             "monthly_state_reason": "provisional_passed"})
    sig = pd.DataFrame(sig_rows); sig.to_csv(p / "signal_panel.csv", index=False)
    pd.DataFrame(out_rows).to_csv(p / "outcome_panel.csv", index=False)
    trig = [d for i, d in enumerate(days, 1) if i % 5 == 0]
    pd.DataFrame({"code": "600001", "signal_type": "sv_legacy",
                  "first_trigger_date": trig}).to_csv(p / "episode_panel.csv", index=False)
    pd.DataFrame(uni_rows).to_csv(p / "universe_state_panel.csv", index=False)
    pd.DataFrame({"episode_id": ["600001_strategy_sv_1", "600001_strategy_td_1"],
                  "code": ["600001", "600001"],
                  "signal_type": ["sv_legacy", "td_legacy"],
                  "first_trigger_date": [trig[0], trig[0]],
                  "last_trigger_date": [trig[-1], trig[-1]],
                  "consecutive_confirmations": [3, 3],
                  "monthly_pool_spell_id": [1, 1],
                  "first_pattern_trigger_date": [trig[0], trig[0]],
                  "pattern_to_strategy_lag_sessions": [0, 0],
                  "end_date": [None, None], "end_reason": ["right_censored", "right_censored"],
                  "boundary_uncertain": [False, False], "right_censored": [True, True]}
                  ).to_csv(p / "strategy_episode_panel.csv", index=False)
    (p / "manifest.json").write_text(json.dumps({"panel_version": PANEL_VERSION}))
    return p


def test_progressive_main_smoke(tmp_path, monkeypatch):
    panel = _mk_panel(tmp_path)
    mem = tmp_path / "mem.csv"
    pd.DataFrame({"code": ["600001", "600002", "600003"],
                  "effective_from": ["2024-01-01"] * 3, "effective_to": [None] * 3,
                  "industry_code": ["C1", "C2", "C1"]}).to_csv(mem, index=False)
    idx = pd.bdate_range("2024-12-01", periods=90)
    frames = {}
    for code, base in (("600001", 10.0), ("600002", 20.0), ("600003", 30.0)):
        close = base * np.cumprod(1 + np.full(90, 0.002))
        frames[code] = pd.DataFrame({"open": close * 0.999, "high": close * 1.01,
                                     "low": close * 0.99, "close": close,
                                     "volume": 1e6, "amount": 1e7}, index=idx)
    import importlib.util
    from stock_selector.research.context_join import attach_historical_membership
    m = pd.read_csv(mem, dtype={"code": str})
    idx = pd.bdate_range("2024-12-01", periods=90).strftime("%Y-%m-%d")
    rows, closes = [], []
    for code, base in (("600001", 10.0), ("600002", 20.0), ("600003", 30.0)):
        close = base * np.cumprod(1 + np.full(90, 0.002))
        rows.append(pd.DataFrame({"code": code, "date": idx,
                                  "return": pd.Series(close).pct_change()}))
        closes.append(pd.DataFrame({"code": code, "date": idx, "close": close}))
    fake = (attach_historical_membership(pd.concat(rows), m),
            attach_historical_membership(pd.concat(closes), m))
    spec = importlib.util.spec_from_file_location(
        "run_progressive_analysis", REPO / "scripts" / "run_progressive_analysis.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "build_market_frames", lambda *a, **k: fake)
    _FakeStore._frames = frames
    out = tmp_path / "pout"
    monkeypatch.setattr(sys, "argv", [
        "run_progressive_analysis.py", "--panel-dir", str(panel), "--membership", str(mem),
        "--tdx-dir", str(tmp_path), "--out", str(out),
        "--protocol", str(REPO / "config/research/momentum_efficiency/protocol_v1.yaml")])
    mod.main()

    for f in ("progressive_summary.csv", "bootstrap_contrasts.json",
              "strategy_episode_report.csv", "pattern_episode_report.csv",
              "within_structure_contrast.csv", "holding_context.csv",
              "PROGRESSIVE_MANIFEST.json"):
        assert (out / f).exists(), f
    summ = pd.read_csv(out / "progressive_summary.csv")
    assert set(summ["comparison"]) == {
        "daily_increment_within_monthly_weekly", "weekly_state_within_daily_shape",
        "weekly_direct_within_monthly"}
    srep = pd.read_csv(out / "strategy_episode_report.csv")
    assert srep.iloc[0]["episodes"] == 2  # 同日sv/td双事件均计入
    # bootstrap必须真实执行且键契约正确（B1/B2回归）
    import math
    boot = json.loads((out / "bootstrap_contrasts.json").read_text())
    a_boot = boot["daily_increment_within_monthly_weekly"]
    assert a_boot, "bootstrap组间对比为空：入口对bootstrap路径失明"
    entry = next(iter(a_boot.values()))
    assert entry["estimate"] is not None and "ci_excludes_zero" in entry
    assert entry["n_a"] >= 30 and entry["n_b"] >= 30
    man = json.loads((out / "PROGRESSIVE_MANIFEST.json").read_text())
    assert man["strategy_episodes"] == 2 and man["pattern_episodes"] == len(
        pd.read_csv(panel / "episode_panel.csv"))
