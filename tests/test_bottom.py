from datetime import datetime

import numpy as np
import pandas as pd

from stock_selector.bottom_pool import BottomPoolStore
from stock_selector.models import Decision
from stock_selector.strategies.bottom import bottom_volume_signal


def make_bottom_daily(days: int = 300, base_price: float = 20.0) -> pd.DataFrame:
    """构造：深回撤+低位平台+安静量，最后一日三倍量大涨。"""
    index = pd.bdate_range(end="2026-09-15", periods=days)
    rng = np.random.default_rng(7)
    # 前250日在高位震荡后跌到低位，近60日低位横盘
    high_phase = base_price * (1.0 + 0.02 * np.sin(np.arange(250) / 25.0))
    decline = np.linspace(base_price, base_price * 0.62, 40)
    platform = base_price * 0.62 + 0.05 * np.sin(np.arange(days - 290) / 5.0) + rng.normal(0, 0.03, days - 290)
    close = np.concatenate([high_phase, decline, platform])
    close[-1] = close[-2] * 1.068  # 大涨6.8%，收阳
    open_ = close - 0.02
    open_[-1] = close[-1] - close[-1] * 0.02
    low = np.minimum(open_, close) - 0.05
    low[-1] = open_[-1] + (close[-1] - open_[-1]) * 0.2  # 收盘位于振幅上部
    high = np.maximum(open_, close) + 0.05
    volume = np.full(days, 1_000_000.0)
    volume[-6:] = 950_000.0
    volume[-1] = 3_200_000.0  # 前5日均量的3倍以上
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": close * volume},
        index=index,
    )


def test_bottom_volume_signal_fires(config):
    result = bottom_volume_signal(make_bottom_daily(), config)
    assert result.decision is Decision.PASS
    assert result.metrics["volume_multiple"] >= 3.0
    assert result.metrics["day_change_pct"] >= 6.0


def test_bottom_volume_rejects_already_rallied(config):
    daily = make_bottom_daily()
    closes = daily["close"].copy()
    closes.iloc[-21:-1] = closes.iloc[-21:-1] * np.linspace(1.0, 1.18, 20)
    daily["close"] = closes
    daily.iloc[-1, daily.columns.get_loc("close")] = closes.iloc[-2] * 1.07
    daily.iloc[-1, daily.columns.get_loc("open")] = daily.iloc[-1]["close"] * 0.98
    result = bottom_volume_signal(daily, config)
    # 前20日已累计上涨：或已超15%上限，或价格已脱离低位平台/回撤变浅
    assert result.decision is Decision.REJECT
    assert result.reason in {"prelaunch_out_of_range", "above_low_platform", "drawdown_too_shallow"}


def test_bottom_volume_rejects_low_volume(config):
    daily = make_bottom_daily()
    daily.iloc[-1, daily.columns.get_loc("volume")] = 1_800_000.0
    result = bottom_volume_signal(daily, config)
    assert result.decision is Decision.REJECT
    assert result.reason == "volume_multiple_too_low"


def test_pool_state_machine(tmp_path):
    store = BottomPoolStore(tmp_path / "events.csv")
    store.append(
        [
            {
                "代码": "000001",
                "名称": "测试",
                "事件日": "2026-09-10",
                "事件日最低": 9.5,
                "状态": "active",
            }
        ]
    )
    daily = pd.DataFrame(
        {"close": [10.0, 9.4, 9.2], "volume": [1e6, 1e6, 1e6]},
        index=pd.bdate_range(end="2026-09-15", periods=3),
    )
    counts = store.refresh(lambda code: daily, datetime(2026, 9, 15, 15, 0), 60)
    assert counts["invalidated"] == 1
    assert store.active().empty

    store2 = BottomPoolStore(tmp_path / "events2.csv")
    rising = pd.DataFrame(
        {"close": [10.0 + i * 0.1 for i in range(70)], "volume": [1e6] * 70},
        index=pd.bdate_range(end="2026-09-15", periods=70),
    )
    store2.append(
        [
            {
                "代码": "000002",
                "事件日": str(pd.Timestamp(rising.index[3]).date()),
                "事件日最低": float(rising["low"].iloc[3]) if "low" in rising.columns else 10.3,
                "状态": "active",
            }
        ]
    )
    counts2 = store2.refresh(lambda code: rising, datetime(2026, 9, 15, 15, 0), 60)
    assert counts2["expired"] == 1

    store3 = BottomPoolStore(tmp_path / "events3.csv")
    store3.append([{"代码": "000003", "事件日": "2026-09-10", "事件日最低": 9.5, "状态": "active"}])
    store3.mark_converted(["000003"], datetime(2026, 9, 15, 15, 0).date())
    frame = store3.load()
    assert frame.iloc[0]["状态"] == "converted"
    assert frame.iloc[0]["转化日"] == "2026-09-15"
