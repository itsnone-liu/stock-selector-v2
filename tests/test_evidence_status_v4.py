"""35f审计测试盲区补齐：evidence_status四态可达性、短周完结判定、
veto覆写后的gate一致性、component_means均值恒等。"""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd

from stock_selector.signals import weekly_features as wf
from stock_selector.signals.snapshot import build_snapshot
from stock_selector.signals.weekly_features import evaluate_weekly
from stock_selector.research.within_structure_analysis import component_means


def _frame(weeks: int = 13, start: str = "2025-07-14", base: float = 10.0) -> pd.DataFrame:
    idx = pd.bdate_range(start, periods=weeks * 5)
    n = len(idx)
    close = base * np.cumprod(1 + 0.004 + np.zeros(n))
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": 1e6, "amount": 1e7}, index=idx)


def test_evidence_status_complete_on_friday():
    f = _frame()
    fri = [d for d in f.index if d.weekday() == 4][-2]
    as_of = datetime.combine(fri.date(), datetime.min.time()).replace(hour=15, minute=30)
    ev = evaluate_weekly(build_snapshot("600001", as_of, f))
    assert ev.evidence_status == "complete"


def test_evidence_status_complete_on_short_week_final_session():
    f = _frame()
    # 2025-10-09所在交易周仅有该周四一个交易日（国庆后）
    cal = pd.DatetimeIndex([pd.Timestamp("2025-10-09")])
    as_of = datetime(2025, 10, 9, 15, 30)
    snap = build_snapshot("600001", as_of, f, trading_calendar=cal)
    assert snap.planned_sessions_this_week == 1
    ev = evaluate_weekly(snap)
    assert ev.components["short_week"] is True
    assert ev.evidence_status == "complete"


def test_evidence_status_partial_midweek_and_insufficient_short_history():
    f = _frame()
    wed = [d for d in f.index if d.weekday() == 2][-2]
    as_of = datetime.combine(wed.date(), datetime.min.time()).replace(hour=15, minute=30)
    ev = evaluate_weekly(build_snapshot("600001", as_of, f))
    assert ev.evidence_status == "partial"

    tiny = _frame(weeks=1, start="2025-08-04")
    tue = datetime(2025, 8, 5, 15, 30)
    ev2 = evaluate_weekly(build_snapshot("600001", tue, tiny))
    assert ev2.weekday_path == "tuesday_gate_unknown"
    assert ev2.evidence_status == "insufficient"


def test_legacy_gate_status_consistent_with_veto_override(monkeypatch):
    f = _frame()
    mon = [d for d in f.index if d.weekday() == 0][-1]
    as_of = datetime.combine(mon.date(), datetime.min.time()).replace(hour=15, minute=30)
    monkeypatch.setattr(wf, "bearish_heavy_veto", lambda frame: (True, {"fake": True}))
    ev = evaluate_weekly(build_snapshot("600001", as_of, f))
    if "veto_overridden_branch_pass" in ev.notes:
        # veto把passed压成False后，gate标签必须与最终passed一致
        assert ev.passed is False
        assert ev.legacy_gate_status == "failed"


def test_component_means_identity_adds_up():
    rng = np.random.default_rng(11)
    n = 60
    events = pd.DataFrame({
        "code": "600001",
        "fwd5": rng.normal(0.01, 0.02, n),
        "market_fwd5": rng.normal(0.0, 0.005, n),
        "industry_fwd5": rng.normal(0.002, 0.008, n),
        "cohort": rng.choice(["triggered", "not_triggered"], n),
    })
    out = component_means(events, 5, group_columns=["cohort"])
    for _, row in out.iterrows():
        total = (row[("component_market_5", "mean")]
                 + row[("component_industry_vs_market_5", "mean")]
                 + row[("component_stock_vs_industry_5", "mean")])
        assert abs(total - row[("fwd5", "mean")]) < 1e-9
