"""用户复审修复回归：日线触发三态OR、市场日历与采样分离、递进分析入口端到端。"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_selector.research.cohorts import attach_daily_trigger, daily_increment_cohort
from stock_selector.research.momentum_panel import build_panel_with_universe, PANEL_VERSION

REPO = Path(__file__).resolve().parents[1]


def test_partial_unknown_daily_trigger_stays_unknown():
    p = pd.DataFrame({"code": "600001", "date": "2025-01-06",
                      "monthly_provisional_state": True,
                      "weekly_eligibility_state": "eligible",
                      "sv_legacy": False, "td_legacy": None}, index=[0])
    x = attach_daily_trigger(p)
    assert x.iloc[0]["daily_trigger_state"] == "unknown"
    # 全部明确假 → not_triggered
    p2 = p.assign(td_legacy=False)
    assert attach_daily_trigger(p2).iloc[0]["daily_trigger_state"] == "not_triggered"
    # 任一真 → triggered（不受另一未知影响）
    p3 = p.assign(sv_legacy=True)
    assert attach_daily_trigger(p3).iloc[0]["daily_trigger_state"] == "triggered"
    # 对照A排除unknown
    c = daily_increment_cohort(p)
    assert len(c) == 0


class _Store:
    def __init__(self, frames):
        self._frames = frames

    def daily(self, code):
        return self._frames.get(code)


def _uptrend(days=300):
    idx = pd.bdate_range("2024-06-03", periods=days)
    close = 10 * np.cumprod(np.full(days, 1.004))
    return pd.DataFrame({"open": close * 0.999, "high": close * 1.01, "low": close * 0.99,
                         "close": close, "volume": 1e6, "amount": 1e7}, index=idx)


CFG = {"monthly": {"min_bars": 20, "max_last_month_drop_pct": 8.0, "require_ma_bull": True}}


def test_session_index_uses_market_calendar_not_sampling():
    f = _uptrend()
    cal = pd.DatetimeIndex(f.index)
    sampled = [datetime.combine(d.date(), datetime.min.time()).replace(hour=15, minute=30)
               for d in cal[::2]]
    _, uni, stats = build_panel_with_universe(_Store({"600001": f}), ["600001"],
                                              sampled, CFG, min_history=130,
                                              trading_calendar=cal)
    assert stats["calendar_source"] == "market"
    u = uni[uni.code == "600001"].reset_index(drop=True)
    # 采样日期的session_index必须是市场日历中的真实位置（1,3,5,...），不是采样序号(1,2,3,...)
    assert list(u["session_index"]) == [2 * i + 1 for i in range(len(u))]


def test_market_calendar_reads_index_file(tmp_path):
    from stock_selector.data.tdx import TdxStore
    import struct
    lday = tmp_path / "vipdoc" / "sh" / "lday"; lday.mkdir(parents=True)
    recs = b"".join(struct.pack("<IIIIIfII", int(d.strftime("%Y%m%d")), 1, 1, 1, 1, 1.0, 1, 1)
                    for d in pd.bdate_range("2025-01-01", periods=10))
    (lday / "sh000001.day").write_bytes(recs)
    cal = TdxStore(tmp_path).market_calendar()
    assert len(cal) == 10
    assert cal[0] == pd.Timestamp("2025-01-01")
