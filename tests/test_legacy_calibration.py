"""legacy_reconstructed_v1 取证校准语义的测试（依据 docs/research/LEGACY_FORENSICS.md）。"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from stock_selector.decision.weekly_momentum import (
    ACTIVE_UP,
    CURRENT_WEEK,
    NO_MOMENTUM,
    PREVIOUS_COMPLETED_WEEK,
    PULLBACK_WEAKENING,
    legacy_weekday,
)
from tests.test_decision_core import make_daily, week_frame

CFG = {"surge": {}}


def _two_red_rows(frame: pd.DataFrame, asof: datetime, day2_vol: float) -> pd.DataFrame:
    """衔接帧价格水平的双阴两行（d1 阴、d2 阴，量可调）。"""
    base = float(frame["close"].iloc[-1])
    d1 = pd.Timestamp(asof.date()) - pd.Timedelta(days=1)
    return pd.DataFrame(
        {"open": [base * 1.002, base * 0.985], "high": [base * 1.006, base * 0.99],
         "low": [base * 0.975, base * 0.955], "close": [base * 0.98, base * 0.96],
         "volume": [4_000_000.0, day2_vol],
         "amount": [4_000_000.0 * base, day2_vol * base]},
        index=[d1, pd.Timestamp(asof.date())],
    )



def _monday_after(frame: pd.DataFrame) -> datetime:
    last = pd.Timestamp(frame.index[-1])
    monday = last + pd.Timedelta(days=3)
    return datetime(monday.year, monday.month, monday.day, 10, 30)


def _tuesday_after(frame: pd.DataFrame) -> datetime:
    last = pd.Timestamp(frame.index[-1])
    tue = last + pd.Timedelta(days=4)
    return datetime(tue.year, tue.month, tue.day, 10, 30)


def test_monday_ignores_current_week_entirely():
    """取证必修点①：周一纯看最近两个完整周，本周临时K不参与。

    构造：上周+前周=双阳加速（ACTIVE_UP），但周一当天暴跌爆量——
    v1 必须仍然返回 ACTIVE_UP（旧代码周一根本不看本周）。
    """
    frame = week_frame(prev_week_pct=5.0, prev_week_vol=6_000_000, weeks=8)
    asof = _monday_after(frame)
    # 周一当日大跌阴线（若参与评估会触发 veto/pullback）
    crash = make_daily([10.0, 9.0, 8.1], volumes=[9_000_000] * 3,
                       end=asof.strftime("%Y-%m-%d"))
    crash = crash.iloc[:-2]  # 只留 asof 当日一根
    crash.index = [pd.Timestamp(asof.date())]
    frame = pd.concat([frame, crash])
    result = legacy_weekday(frame, asof, CFG)
    assert result.state == ACTIVE_UP
    assert result.evidence_origin == PREVIOUS_COMPLETED_WEEK
    assert result.mode == "legacy_reconstructed_v1"


def test_tuesday_requires_monday_gate():
    """取证§1：周二必须先过周一逻辑（完整周形态门槛）。"""
    # 上周平盘（非双阳、非阴转阳）→ 周一门槛不过 → 周二即便本周走强也不看
    frame = week_frame(prev_week_pct=-1.5, prev_week_vol=5_000_000, weeks=8)
    asof = _tuesday_after(frame)
    d1 = pd.Timestamp(asof.date()) - pd.Timedelta(days=1)
    pop = pd.DataFrame(
        {"open": [10.0, 10.5], "high": [10.6, 11.2], "low": [9.9, 10.4],
         "close": [10.5, 11.1], "volume": [8_000_000.0, 9_000_000.0],
         "amount": [84e6, 99.9e6]},
        index=[d1, pd.Timestamp(asof.date())],
    )
    frame = pd.concat([frame, pop])
    result = legacy_weekday(frame, asof, CFG)
    assert result.state != ACTIVE_UP
    assert result.evidence_origin == PREVIOUS_COMPLETED_WEEK
    assert any("门槛" in n for n in result.notes)


def test_tuesday_double_red_no_shrink_rejected():
    """取证§1：过门槛后双阴未缩量 → 剔除（NO_MOMENTUM）。"""
    frame = week_frame(prev_week_pct=5.0, prev_week_vol=6_000_000, weeks=8)
    asof = _tuesday_after(frame)
    two_red = _two_red_rows(frame, asof, day2_vol=5_000_000.0)
    frame = pd.concat([frame, two_red])
    result = legacy_weekday(frame, asof, CFG)
    assert result.state == NO_MOMENTUM
    assert any("剔除" in n for n in result.notes)


def test_tuesday_double_red_shrinking_weakening():
    """取证§1：双阴且周二缩量 → PULLBACK_WEAKENING。"""
    frame = week_frame(prev_week_pct=5.0, prev_week_vol=6_000_000, weeks=8)
    asof = _tuesday_after(frame)
    two_red = _two_red_rows(frame, asof, day2_vol=3_000_000.0)
    frame = pd.concat([frame, two_red])
    result = legacy_weekday(frame, asof, CFG)
    assert result.state == PULLBACK_WEAKENING


def test_form_a_exempt_volume_gate_only_in_legacy():
    """取证必修点③：形态A（前周阴→当周阳转）豁免量比门槛，仅 legacy 口径。

    构造：倒数第二周阴线（-3%），最后一周阳转（+4%）但缩量至0.6×（<0.8门槛）。
    legacy 应 ACTIVE_UP（形态A无量比要求）；revised 不豁免 → 非 ACTIVE_UP。
    """
    frame = week_frame(prev_week_pct=2.0, prev_week_vol=5_000_000, weeks=7,
                       )  # 末周五=2026-09-18
    # 日期必须连续：阴线周 09-21..09-25，阳转周 09-28..10-02
    bear = make_daily([10.0, 9.85, 9.7, 9.55, 9.4], volumes=[1_000_000] * 5,
                      end="2026-09-25")
    bull = make_daily([9.4, 9.6, 9.8, 10.0, 10.2], volumes=[600_000] * 5,
                      end="2026-10-02")
    frame = pd.concat([frame, bear, bull])
    asof = datetime(2026, 10, 2, 15, 10)
    res_legacy = legacy_weekday(frame, asof, CFG)
    assert res_legacy.state == ACTIVE_UP, res_legacy.metrics
    assert res_legacy.metrics.get("form_a_volume_exempt_applied") is True
    from stock_selector.decision.weekly_momentum import revised_weekday
    res_revised = revised_weekday(frame, asof, CFG)
    assert res_revised.state != ACTIVE_UP  # 不豁免：缩量0.6<0.8 被挡


def test_wed_thu_projection_uses_completion_divisor():
    """取证必修点②：投影=已实现涨幅÷完成度（≠固定×5）。"""
    frame = week_frame(prev_week_pct=4.0, prev_week_vol=5_000_000, weeks=8)
    # 进入新的一周：周一/周二/周三（asof=周三盘中，本周第3个交易日）
    last = pd.Timestamp(frame.index[-1])
    wed = last + pd.Timedelta(days=5)
    extra = make_daily([10.2, 10.4, 10.6], volumes=[1_000_000] * 3,
                       end=wed.strftime("%Y-%m-%d"))
    frame = pd.concat([frame, extra])
    asof = datetime(wed.year, wed.month, wed.day, 10, 30)
    result = legacy_weekday(frame, asof, CFG)
    proj = result.metrics.get("legacy_projected_week_pct")
    realized = result.metrics.get("realized_week_return_pct")
    assert proj is not None and realized is not None
    # 周三10:30：完成度=(2+60/240)/5≈0.55；固定×5 会得到 realized*5
    assert proj == pytest.approx(realized / 0.55, abs=realized * 0.5)
    assert proj != pytest.approx(realized * 5.0, rel=0.05)
