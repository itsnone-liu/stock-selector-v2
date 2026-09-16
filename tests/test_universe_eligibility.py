"""P0选样防前视：资格判定不得使用as_of之后的流动性/上市数据。"""
import pandas as pd

from scripts.backtest_decision import stream_qualified_codes


class StubStore:
    def __init__(self, frames):
        self.frames = frames

    def daily(self, code):
        return self.frames.get(code)


def _frame(start, days, amount):
    idx = pd.date_range(start, periods=days, freq="B")
    return pd.DataFrame({"close": [10.0] * days, "amount": [amount] * days}, index=idx)


def test_early_illiquid_stock_qualifies_only_when_tail_filter_is_date_aware():
    # 2025年前半年无流动性、之后放量：旧末端过滤会把它选入2025窗口（前视）。
    idx_a = pd.date_range("2024-01-01", periods=120, freq="B")   # 冷淡期
    idx_b = pd.date_range("2025-06-02", periods=180, freq="B")   # 放量期
    cold = pd.DataFrame({"close": 10.0, "amount": 1e4}, index=idx_a)
    hot = pd.DataFrame({"close": 10.0, "amount": 1e8}, index=idx_b)
    frame = pd.concat([cold, hot])
    store = StubStore({"600001": frame})

    # as_of=窗口起点(2025-01-02)：当时末端120日仍是冷淡期 → 排除。
    got = list(stream_qualified_codes(store, ["600001"], 2e7, as_of="2025-01-02"))
    assert got == []

    # 旧行为（数据末端过滤）保留给对照复现，仍会选入：
    legacy = list(stream_qualified_codes(store, ["600001"], 2e7))
    assert legacy == ["600001"]


def test_insufficient_history_at_as_of_is_excluded_even_if_later_long():
    idx = pd.date_range("2024-11-01", periods=300, freq="B")
    frame = pd.DataFrame({"close": 10.0, "amount": 1e8}, index=idx)
    store = StubStore({"600002": frame})
    assert list(stream_qualified_codes(store, ["600002"], 2e7, as_of="2024-12-01")) == []
