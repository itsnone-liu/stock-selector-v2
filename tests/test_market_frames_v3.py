from __future__ import annotations

import pandas as pd

import scripts.run_e_stage_analysis as e


class _Store:
    def __init__(self, frames): self.frames = frames
    def list_codes(self): return list(self.frames)
    def daily(self, code): return self.frames[code].copy()


def _frame():
    idx = pd.date_range("2025-01-02", periods=7, freq="B")
    return pd.DataFrame({"open": range(10, 17), "high": range(11, 18),
                         "low": range(9, 16), "close": range(10, 17),
                         "volume": [100] * 7}, index=idx)


def test_market_frames_use_daily_membership_preclose_and_tail(monkeypatch):
    monkeypatch.setattr(e, "TdxStore", lambda _: _Store({"600001": _frame()}))
    mem = pd.DataFrame({
        "code": ["600001", "600001"],
        "effective_from": ["2020-01-01", "2025-01-07"],
        "effective_to": ["2025-01-06", None],
        "industry_code": ["A", "B"],
    })
    returns, prices = e.build_market_frames("unused", 0, mem, "2025-01-03", "2025-01-07",
                                             end_buffer_sessions=2)
    # 截窗首日收益使用窗口外前收盘；尾部补两交易日。
    first = returns[returns.date == "2025-01-03"].iloc[0]
    assert round(first["return"], 8) == round(11 / 10 - 1, 8)
    assert prices.date.max() == "2025-01-09"
    # 行业在有效期切换日逐日变化，收益和价格表都携带行业。
    assert prices.set_index("date").loc["2025-01-06", "industry_code"] == "A"
    assert prices.set_index("date").loc["2025-01-07", "industry_code"] == "B"
    assert returns.set_index("date").loc["2025-01-07", "industry_code"] == "B"
