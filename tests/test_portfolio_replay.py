"""组合级回放器核心不变量的测试（注入桩 service，数据合成）。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from portfolio_replay import run_portfolio_replay  # noqa: E402
from tests.test_decision_core import make_daily  # noqa: E402

CFG = {"decision": {"portfolio": {"single_max_pct": 20, "industry_max_pct": 40,
                                  "daily_add_max_pct": 30},
                    "exits": {"time_stop_days": 5, "trail_pct": 8.0, "max_hold_days": 20}}}


def _index(days: int, end: str, start_level: float = 4000.0) -> pd.DataFrame:
    idx = pd.bdate_range(end=end, periods=days)
    closes = start_level * np.cumprod(1 + np.linspace(0.0005, 0.0008, days))
    return pd.DataFrame({"open": closes * 0.999, "high": closes * 1.005,
                         "low": closes * 0.994, "close": closes,
                         "volume": [1e8] * days, "amount": [4e11] * days}, index=idx)


def _frames(codes: list[str], days: int, end: str) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(7)
    out = {}
    for c in codes:
        n = days
        closes = 10.0 * np.cumprod(1 + rng.normal(0.001, 0.015, n))
        out[c] = make_daily(list(closes), list(rng.uniform(8e5, 1.2e6, n)), end=end)
    return out


class StubService:
    """day1 对所有代码给 buy；持仓满 N 天后给 E2 卖出信号。"""

    def __init__(self, hold_days: int = 6):
        self.first_buy_dates: dict[str, str] = {}
        self.hold_days = hold_days

    def evaluate(self, code, asof, quote=None, context_payload=None,
                 portfolio=None, anchor=None):
        today = str(asof.date())
        if code in portfolio.positions:
            entry = datetime.fromisoformat(portfolio.positions[code].lots[0].buy_date.isoformat())
            held = (asof - entry).days
            if held >= self.hold_days:
                return {"action": "sell", "confidence": "high",
                        "exit_signals": [{"rule": "E2_time_stop", "action": "sell"}],
                        "invalidation": {}, "rationale": []}
            return {"action": "hold", "confidence": "medium", "exit_signals": [],
                    "invalidation": {}, "rationale": []}
        if code not in self.first_buy_dates:
            self.first_buy_dates[code] = today
            return {"action": "buy", "confidence": "high", "exit_signals": [],
                    "invalidation": {"structural_stop": 9.0}, "rationale": ["stub"]}
        return {"action": "watch", "confidence": "low", "exit_signals": [],
                "invalidation": {}, "rationale": []}


def test_portfolio_replay_invariants():
    days, end = 30, "2026-03-31"
    codes = ["600001", "600002", "600003", "600004"]
    frames = _frames(codes, days, end)
    index = _index(90, end)  # ≥60根才有 regime
    result = run_portfolio_replay(frames, index, CFG, start="2026-03-01", end=end,
                                  capital=1_000_000.0, top_per_day=2,
                                  service=StubService())
    daily = result["daily"]
    trades = result["trades"]
    # 不变量
    assert len(daily) > 0
    assert set(daily["regime"]) == {"bull"}, daily["regime"].unique()  # 上升指数=bull
    assert len(trades) > 0, "bull 档应有成交"
    assert (daily["cash"] >= -1.0).all(), "现金不允许为负"
    assert daily["equity"].iloc[-1] > 0
    # 敞口上限（bull=100%）
    assert (daily["invested"] / daily["equity"] <= 1.0 + 1e-6).all()
    # 单日新增上限 30%（两条买单各 ≤20%）
    buys = trades[trades["side"] == "buy"]
    assert (buys["value"] <= daily["equity"].max() * 0.2 + 1).all()
    added = buys.groupby("date")["value"].sum()
    eq_by_date = daily.set_index("date")["equity"]
    for d, v in added.items():
        assert v / eq_by_date[d] <= 0.3 + 1e-6, f"{d} 单日新增超限"
    # 卖出存在（桩到期）且先买后卖
    sells = trades[trades["side"] == "sell"]
    assert len(sells) > 0, "桩到期应产生卖出"
    # 首个信号日无成交（T+1开盘模型）
    assert trades["date"].iloc[0] > daily["date"].iloc[0]
    codes_traded = set(buys["code"]) | set(sells["code"])
    assert codes_traded <= set(codes)


def test_input_order_does_not_change_selection_or_result():
    days, end = 30, "2026-03-31"
    codes = ["600004", "600002", "600003", "600001"]
    frames = _frames(codes, days, end)
    index = _index(90, end)
    a = run_portfolio_replay(frames, index, CFG, "2026-03-01", end,
                             top_per_day=2, service=StubService())
    reversed_frames = dict(reversed(list(frames.items())))
    b = run_portfolio_replay(reversed_frames, index, CFG, "2026-03-01", end,
                             top_per_day=2, service=StubService())
    cols = ["date", "code", "side", "qty", "reason"]
    pd.testing.assert_frame_equal(a["trades"][cols].reset_index(drop=True),
                                  b["trades"][cols].reset_index(drop=True))
    assert a["summary"]["final_equity"] == b["summary"]["final_equity"]
    assert a["summary"]["input_snapshot_hash"] == b["summary"]["input_snapshot_hash"]


def test_future_data_mutation_does_not_change_past_decisions():
    days, end = 30, "2026-03-31"
    codes = ["600001", "600002"]
    frames = _frames(codes, days, end)
    index = _index(90, end)
    cutoff = "2026-03-20"
    a = run_portfolio_replay(frames, index, CFG, "2026-03-01", cutoff,
                             top_per_day=2, service=StubService())
    corrupted = {c: f.copy() for c, f in frames.items()}
    for f in corrupted.values():
        mask = f.index > pd.Timestamp(cutoff)
        f.loc[mask, ["open", "high", "low", "close"]] *= 100
    corrupted_index = index.copy()
    corrupted_index.loc[corrupted_index.index > pd.Timestamp(cutoff),
                        ["open", "high", "low", "close"]] *= 100
    b = run_portfolio_replay(corrupted, corrupted_index, CFG, "2026-03-01", cutoff,
                             top_per_day=2, service=StubService())
    cols = ["date", "code", "side", "qty", "price"]
    pd.testing.assert_frame_equal(a["trades"][cols].reset_index(drop=True),
                                  b["trades"][cols].reset_index(drop=True))
    pd.testing.assert_frame_equal(a["daily"], b["daily"])


def test_portfolio_replay_weak_regime_blocks_buys():
    days, end = 20, "2026-03-31"
    codes = ["600009"]
    frames = _frames(codes, days, end)
    # 全程下跌指数（≥60根）→ weak 档 → 目标敞口 0，买入全被 regime cap 拒绝
    n = 90
    idx_closes = 5000.0 * np.cumprod(1 - np.abs(np.linspace(0.004, 0.006, n)))
    index = pd.DataFrame({"open": idx_closes * 1.001, "high": idx_closes * 1.002,
                          "low": idx_closes * 0.998, "close": idx_closes,
                          "volume": [1e8] * n, "amount": [4e11] * n},
                         index=pd.bdate_range(end=end, periods=n))
    result = run_portfolio_replay(frames, index, CFG, start="2026-03-02", end=end,
                                  capital=1_000_000.0, service=StubService())
    assert set(result["daily"]["regime"]) == {"weak"}  # 确认档位真实为 weak（非None）
    assert len(result["trades"]) == 0, "weak 档不应有任何买入"
    assert (result["daily"]["invested"] == 0.0).all()
