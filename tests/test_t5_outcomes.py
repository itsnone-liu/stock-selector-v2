"""T5.1 测试四：outcome 表独立性与 censor 语义。"""
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

from t5_fixture import MDATES, fake_events, fake_market, fake_stock  # noqa
from t5 import primitives_build as B                    # noqa
from t5 import outcomes as OC                           # noqa


@pytest.fixture
def pair():
    ev = fake_events(end="2025-01-20")
    stocks = [fake_stock(drift=0.05)]     # 每日 +5%：答案可手算
    state = B.build_dynamic_state(ev, fake_market(), stocks, MDATES)
    oc = OC.build_dynamic_outcomes(
        state[["event_id", "code", "breakout_day", "delta_day",
               "state_date", "row_present"]], stocks, MDATES)
    return state, oc, stocks


def test_keys_identical(pair):
    state, oc, _ = pair
    k1 = set(zip(state["event_id"], state["delta_day"]))
    k2 = set(zip(oc["event_id"], oc["delta_day"]))
    assert k1 == k2


def test_outcome_values(pair):
    _, oc, stocks = pair
    code, dates, adj, _raw, _pch, _amt, _turn, _vol = stocks[0]
    mpos = {d: i for i, d in enumerate(MDATES)}
    # 取 delta=0 行：fwd_ret_1d = log(adj[t+1]/adj[t0])
    r0 = oc[oc["delta_day"] == 0].iloc[0]
    i0 = mpos["2025-01-06"]
    assert math.isclose(r0["fwd_ret_1d_log"],
                        math.log(adj[i0 + 1] / adj[i0]), rel_tol=1e-12)
    assert r0["complete_1d"] is True or r0["complete_1d"] == True
    assert r0["fwd_new_high_5d"] == True   # 单调上涨必超峰值
    # 合成数据 T0 前历史不足 20 日 → ref20 缺 → None/NaN（正确缺失语义）
    assert pd.isna(r0["fwd_lose_ref20_5d"])


def test_censor_at_data_end(pair):
    """窗口不完整 → complete=False，绝不当零。"""
    _, oc, _ = pair
    last = oc[oc["delta_day"] == oc["delta_day"].max()].iloc[0]
    # end=01-20 即数据末：delta=10 之后无未来 → 全部 incomplete
    for h in (1, 3, 5, 10):
        assert last[f"complete_{h}d"] in (False, None) or \
            last[f"n_obs_{h}d"] < h
    assert pd.isna(last["fwd_ret_1d_log"])


def test_outcome_not_in_state(pair):
    state, oc, _ = pair
    leak = set(oc.columns) & set(state.columns) - {"event_id", "delta_day"}
    assert not leak


def test_suspended_row_outcome_empty():
    ev = fake_events(end="2025-01-20")
    stocks = [fake_stock(gap_days=("2025-01-08",))]
    state = B.build_dynamic_state(ev, fake_market(), stocks, MDATES)
    oc = OC.build_dynamic_outcomes(
        state[["event_id", "code", "breakout_day", "delta_day",
               "state_date", "row_present"]], stocks, MDATES)
    sus = oc[oc["delta_day"] == 2].iloc[0]
    assert pd.isna(sus["fwd_ret_1d_log"])
    assert bool(sus["complete_1d"]) is False
