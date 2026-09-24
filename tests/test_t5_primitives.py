"""T5.1 测试三：价格/参与/效率 primitives 数值正确性（手工构造答案）。"""
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
from t5 import primitives as P                          # noqa


def test_price_primitives_known_values():
    # 构造 4 日已知路径：10, 11, 10.45, 12
    vals = [(0, 10.0), (1, 11.0), (2, 10.45), (3, 12.0)]
    out = P.price_primitives(vals)
    assert math.isclose(out["cum_ret_from_t0_log"],
                        math.log(12.0 / 10.0), rel_tol=1e-12)
    assert math.isclose(out["post_t0_peak_ret_log"],
                        math.log(12.0 / 10.0), rel_tol=1e-12)
    assert math.isclose(out["ret_1d_log"],
                        math.log(12.0 / 10.45), rel_tol=1e-12)
    assert math.isclose(out["ret_3d_log"],
                        math.log(12.0 / 10.0), rel_tol=1e-12)
    # 峰谷差最大处：11 → 10.45
    assert math.isclose(out["max_dd_to_date_log"],
                        math.log(11.0 / 10.45), rel_tol=1e-12)
    assert math.isclose(out["drawdown_from_peak_log"], 0.0, abs_tol=1e-12)
    assert out["days_since_peak"] == 0
    assert out["pullback_length_days"] == 0


def test_new_high_flag_requires_20_history():
    assert P.new_high_flag([1.0] * 20, 1.5) is True
    assert P.new_high_flag([1.0] * 20, 0.9) is False
    assert P.new_high_flag([1.0] * 19, 5.0) is None


def test_efficiency_small_denominator_guard():
    assert P.efficiency_signed(0.05, 0.001) is None      # 分母 < eps
    assert math.isclose(P.efficiency_signed(0.05, 0.5), 0.1,
                        rel_tol=1e-12)


def test_load_and_contraction():
    assert P.load_vs_base(4.0, 2.0) == 2.0
    assert P.load_vs_base(4.0, None) is None
    assert P.load_vs_base(4.0, 0.0) is None
    ct, ex = P.contraction_expansion(1.0, 2.0)
    assert ct is True and ex is False


def test_state_participation_semantics():
    """turn 恒 2、base 恒 2 → load 恒 1；change 恒 0。"""
    state = B.build_dynamic_state(fake_events(end="2025-01-20"),
                                  fake_market(), [fake_stock()], MDATES)
    v = state["turnover_load_vs_prebreak"].dropna()
    assert (v == 1.0).all()
    c = state["turnover_load_change_1d"].dropna()
    assert (c == 0.0).all()


def test_updown_counts():
    u, d = P.updown_days([0.01, -0.02, 0.03, 0.04], 3)
    assert u == 2 and d == 1
    assert P.updown_days([0.01], 3) == (None, None)
