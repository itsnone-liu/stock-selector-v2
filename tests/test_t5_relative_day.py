"""T5.1 测试二：相对日/终止/行数守恒（合成 + 属性测试）。"""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from t5_fixture import MDATES, fake_events, fake_market, fake_stock  # noqa
from t5 import primitives_build as B                             # noqa
from t5.constants import MAX_HORIZON                             # noqa


def test_span_max_horizon():
    # 60 日长日历 + lifecycle 很远 → 受 40 上限
    cal = [f"2025-03-{d:02d}" for d in range(1, 32)] + \
          [f"2025-04-{d:02d}" for d in range(1, 31)]
    mpos = {d: i for i, d in enumerate(cal)}
    last, reason = B.event_span(mpos, mpos["2025-03-01"], "2099-01-01",
                                len(cal))
    assert last == MAX_HORIZON and reason == "MAX_HORIZON"


def test_span_data_end():
    mpos = {d: i for i, d in enumerate(MDATES)}
    # 日历先尽
    last, reason = B.event_span(mpos, mpos["2025-01-15"], "2099-01-01",
                                len(MDATES))
    assert reason == "DATA_END"
    assert last == len(MDATES) - 1 - mpos["2025-01-15"]


def test_rowcount_identity():
    ev = fake_events(end="2025-01-12")
    state = B.build_dynamic_state(ev, fake_market(), [fake_stock()],
                                  MDATES)
    mpos = {d: i for i, d in enumerate(MDATES)}
    m0, e = mpos["2025-01-06"], mpos["2025-01-12"]
    assert len(state) == min(MAX_HORIZON, e - m0,
                             len(MDATES) - 1 - m0) + 1


def test_event_isolation():
    """同股两个事件索引不得混用：各自从自己的 T0 起算。"""
    e1 = fake_events(t0="2025-01-06", end="2025-01-20")
    e2 = fake_events(t0="2025-01-10", end="2025-01-20")
    e2["breakout_event_id"] = "000001_2025-01-10"
    ev = pd.concat([e1, e2])
    state = B.build_dynamic_state(ev, fake_market(), [fake_stock()],
                                  MDATES)
    for eid, g in state.groupby("event_id"):
        t0 = eid.split("_")[1]
        assert (g["breakout_day"] == t0).all()
        assert g[g["delta_day"] == 0]["state_date"].iloc[0] == t0
        assert (g["cum_ret_from_t0_log"].dropna().iloc[0] == 0.0
                if g["cum_ret_from_t0_log"].notna().any() else True)
