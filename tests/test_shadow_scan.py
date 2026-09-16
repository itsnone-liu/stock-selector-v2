from datetime import datetime

import numpy as np
import pandas as pd

from stock_selector.shadow_scan import EVENT_VERSION, MONTHLY_STATE_VERSION, shadow_scan
from stock_selector.watchlist import WatchStore


def test_shadow_scan_builds_monthly_pool_and_multilabel_events(tmp_path):
    idx = pd.date_range("2024-01-02", periods=560, freq="B")
    close = np.linspace(5, 20, len(idx))
    frame = pd.DataFrame({"open": close * .995, "high": close * 1.01,
                          "low": close * .99, "close": close,
                          "volume": np.full(len(idx), 1_000_000.0),
                          "amount": close * 1_000_000}, index=idx)
    # 最后两日均阳，今天涨幅加速且缩量，允许多标签同时入账。
    frame.iloc[-2, frame.columns.get_loc("open")] = frame.iloc[-2]["close"] * .99
    frame.iloc[-1, frame.columns.get_loc("close")] = frame.iloc[-2]["close"] * 1.02
    frame.iloc[-1, frame.columns.get_loc("open")] = frame.iloc[-1]["close"] * .99
    frame.iloc[-1, frame.columns.get_loc("volume")] = 500_000
    cfg = {"monthly": {"min_bars": 20, "require_ma_bull": True,
                        "max_last_month_drop_pct": 8},
           "buy": {"pullback_change_min_pct": -3, "pullback_change_max_pct": 2,
                   "ma_tolerance_pct": 5, "acceleration_max_change_pct": 3.5}}
    store = WatchStore(tmp_path / "w.db")
    at = datetime.combine(idx[-1].date(), datetime.min.time().replace(hour=15, minute=5))
    out = shadow_scan({"600001": frame}, at, cfg, store)
    assert out["monthly_pool"] == ["600001"]
    assert out["events"] >= 2
    assert set(store.conn.execute("select distinct event_version from signal_event").fetchone()) == {EVENT_VERSION}
    assert store.monthly_pool(at.date().isoformat(), MONTHLY_STATE_VERSION) == {"600001"}
    row = store.conn.execute("select cost_ref,data_quality from behavior_feature").fetchone()
    assert '"vwap_20d"' in row[0]
    monthly = store.conn.execute("select metrics from monthly_state").fetchone()[0]
    assert '"current_month_incomplete": true' in monthly
    expiry = store.conn.execute("select expiry_at from signal_event limit 1").fetchone()[0]
    assert expiry > at.date().isoformat()
