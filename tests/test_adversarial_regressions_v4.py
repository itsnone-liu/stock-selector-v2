"""对抗性审计残留项的回归锁定：unknown池语义、membership边界、基准n护栏、
holding窗口完整门控、holding特征泄漏防护、旧入口契约闸门。"""
from __future__ import annotations

import json
import runpy
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from stock_selector.research.background_panel import holding_context_metrics
from stock_selector.research.benchmarks import forward_cross_section_benchmarks
from stock_selector.research.context_join import attach_historical_membership
from stock_selector.research.momentum_panel import build_panel_with_universe
from stock_selector.research.within_structure_analysis import within_structure_feature_contrast


def _uptrend(days: int = 300) -> pd.DataFrame:
    idx = pd.bdate_range("2024-06-03", periods=days)
    close = 10 * np.cumprod(np.full(days, 1.004))
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": 1e6, "amount": 1e7}, index=idx)


class _Store:
    def __init__(self, frames):
        self._frames = frames

    def daily(self, code):
        return self._frames.get(code)


CFG = {"monthly": {"min_bars": 20, "max_last_month_drop_pct": 8.0, "require_ma_bull": True}}


def test_missing_bar_unknown_preserves_pool_spell():
    f = _uptrend()
    hole = f.index[250]
    g = f.drop(index=hole)
    dates = [datetime.combine(d.date(), datetime.min.time()).replace(hour=15, minute=30)
             for d in f.index[240:260]]
    _, uni, _ = build_panel_with_universe(_Store({"600001": g}), ["600001"], dates, CFG, min_history=130)
    uni = uni[uni.code == "600001"].reset_index(drop=True)
    before = uni[uni.date == f.index[249].date().isoformat()].iloc[0]
    at = uni[uni.date == hole.date().isoformat()].iloc[0]
    after = uni[uni.date == f.index[251].date().isoformat()].iloc[0]
    if before.monthly_pool_state == "in" and after.monthly_pool_state == "in":
        assert at.data_status == "missing_bar" and at.monthly_pool_state == "unknown"
        # unknown不证明退出：保留spell上下文、池龄冻结，不新开段。
        assert at.monthly_pool_spell_id == before.monthly_pool_spell_id
        assert at.monthly_pool_spell_age == before.monthly_pool_spell_age
        assert after.monthly_pool_spell_id == before.monthly_pool_spell_id
        assert after.monthly_pool_spell_age == before.monthly_pool_spell_age + 1


def test_membership_invalid_effective_to_raises():
    panel = pd.DataFrame({"code": ["600001"], "date": ["2025-06-02"]})
    mem = pd.DataFrame({"code": ["600001"], "effective_from": ["2024-01-01"],
                        "effective_to": ["not-a-date"], "industry_code": ["C1"]})
    with pytest.raises(ValueError, match="invalid non-null dates"):
        attach_historical_membership(panel, mem)


def test_membership_status_separates_gap_from_unmapped():
    panel = pd.DataFrame({"code": ["600001", "600001", "600002"],
                          "date": ["2025-01-06", "2025-06-02", "2025-01-06"]})
    mem = pd.DataFrame({"code": ["600001", "600001"],
                        "effective_from": ["2024-01-01", "2025-03-03"],
                        "effective_to": ["2025-01-03", None],
                        "industry_code": ["C1", "C2"]})
    out = attach_historical_membership(panel, mem)
    assert out.loc[0, "membership_status"] == "effective_gap"
    assert pd.isna(out.loc[0, "industry_code"])
    assert out.loc[1, "membership_status"] == "matched" and out.loc[1, "industry_code"] == "C2"
    assert out.loc[2, "membership_status"] == "code_unmapped"


def test_forward_benchmarks_expose_sample_counts():
    idx = pd.bdate_range("2025-01-01", periods=8)
    frames = []
    for code in ("600001", "600002"):
        close = np.linspace(10, 11, 8) if code == "600001" else np.linspace(20, 19, 8)
        frames.append(pd.DataFrame({"code": code, "date": idx.astype(str), "close": close,
                                    "industry_code": ["C1"] * 8}))
    mkt, ind = forward_cross_section_benchmarks(pd.concat(frames), horizons=(1, 5))
    assert "market_fwd5_n" in mkt and "market_fwd1_n" in mkt
    assert "industry_fwd5_n" in ind
    # 尾部日期前视样本数递减且最后一日5日前瞻计数为0
    assert mkt.iloc[-1]["market_fwd5_n"] == 0
    assert pd.isna(mkt.iloc[-1]["market_fwd5"])
    assert mkt.iloc[0]["market_fwd5_n"] == 2


def test_holding_context_rejects_partial_windows():
    events = pd.DataFrame({"code": ["600001"], "date": ["2025-01-10"]})
    ctx = pd.DataFrame({"date": pd.bdate_range("2025-01-13", periods=2).astype(str),
                        "mret": [0.01, -0.02]})
    out = holding_context_metrics(events, ctx, value_col="mret", horizon=5)
    assert out.iloc[0]["holding_context_mret_h5_sum"] is None
    assert out.iloc[0]["holding_context_mret_h5_n"] == 2
    assert not bool(out.iloc[0]["holding_context_mret_h5_complete"])
    full = holding_context_metrics(events, ctx, value_col="mret", horizon=2)
    assert bool(full.iloc[0]["holding_context_mret_h2_complete"]) is True
    assert abs(full.iloc[0]["holding_context_mret_h2_sum"] - (-0.01)) < 1e-12


def test_feature_contrast_rejects_holding_columns():
    events = pd.DataFrame({"code": ["600001"], "date": ["2025-01-10"],
                           "fwd5": [0.01], "market_fwd5": [0.001], "industry_fwd5": [0.0011]})
    with pytest.raises(ValueError, match="cannot be used as pre-signal features"):
        within_structure_feature_contrast(events, horizon=5,
                                          feature_columns=["holding_context_mret_h5_sum"])


def test_positive_negative_entry_rejects_stale_panel(tmp_path, monkeypatch):
    d = tmp_path / "panel"; d.mkdir()
    (d / "manifest.json").write_text(json.dumps({"panel_version": "momentum_panel_v2_contract"}))
    monkeypatch.setattr(sys, "argv", ["analyze_positive_negative.py", "--dir", str(d)])
    with pytest.raises(SystemExit, match="stale panel contract"):
        runpy.run_path("scripts/analyze_positive_negative.py", run_name="__main__")
