"""T5.1 测试一：PIT 纪律与相对日/终止语义（合成数据）。"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from t5_fixture import MDATES, fake_events, fake_market, fake_stock  # noqa
from t5 import primitives_build as B                             # noqa


@pytest.fixture
def built():
    ev = fake_events()
    mkt = fake_market()
    stocks = [fake_stock()]
    state = B.build_dynamic_state(ev, mkt, stocks, MDATES)
    return state


def test_delta_day_continuous(built):
    g = built.sort_values("delta_day")
    assert list(g["delta_day"]) == list(range(len(g)))
    # state_date 与日历一致
    mpos = {d: i for i, d in enumerate(MDATES)}
    t0p = mpos["2025-01-06"]
    for r in g.itertuples(index=False):
        assert r.state_date == MDATES[t0p + r.delta_day]


def test_lifecycle_end_termination(built):
    # end=2025-01-17 → m0=5, e=16 → cap_life=11 <= 40 → LIFECYCLE_END
    last = built[built["termination_reason"].notna()].iloc[0]
    assert last["termination_reason"] == "LIFECYCLE_END"
    assert last["delta_day"] == 11


def test_no_future_peek(built):
    # 合成数据单调上涨：peak 应等于当日 cum（无未来回填），dd=0
    g = built.dropna(subset=["cum_ret_from_t0_log"])
    assert (g["post_t0_peak_ret_log"] >= g["cum_ret_from_t0_log"] - 1e-12
            ).all()
    assert (g["drawdown_from_peak_log"].abs() < 1e-12).all()
    # max_dd 单调不减
    assert (g["max_dd_to_date_log"].diff().fillna(0) >= -1e-12).all()


def test_row_present_suspension():
    ev = fake_events(end="2025-01-20")
    mkt = fake_market()
    stocks = [fake_stock(gap_days=("2025-01-08",))]
    state = B.build_dynamic_state(ev, mkt, stocks, MDATES)
    mpos = {d: i for i, d in enumerate(MDATES)}
    t0p = mpos["2025-01-06"]
    sus = state[state["delta_day"] == t0p - t0p + 2].iloc[0]
    assert sus["row_present"] is False or sus["row_present"] == False
    assert pd.isna(sus["cum_ret_from_t0_log"])


def test_pit_market_context_no_ffill(built):
    # 市场背景首日 breadth_5d 为 NaN（rolling5 需 5 日），不得向后借
    d0 = built[built["state_date"] == MDATES[0]]
    assert d0["mkt_breadth_5d"].isna().all()
