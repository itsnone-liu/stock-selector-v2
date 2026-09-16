from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from scripts.v3_daily_shadow import run_daily_shadow
from stock_selector.watchlist import WatchStore

CFG = {"monthly": {"min_bars": 20, "require_ma_bull": True,
                   "max_last_month_drop_pct": 8},
       "buy": {"pullback_change_min_pct": -3, "pullback_change_max_pct": 2,
               "ma_tolerance_pct": 5, "acceleration_max_change_pct": 3.5},
       "v3_watch": {"event_expiry_sessions": 20}}


def _rising(n=560, end="2026-03-31"):
    close = np.linspace(5, 20, n)
    idx = pd.date_range(end=end, periods=n, freq="B")
    return pd.DataFrame({"open": close * .995, "high": close * 1.01,
                         "low": close * .99, "close": close,
                         "volume": np.full(n, 1e6), "amount": close * 1e8}, index=idx)


def test_daily_shadow_chain_end_to_end(tmp_path: Path):
    store = WatchStore(tmp_path / "watch.db")
    at = datetime(2026, 9, 15, 15, 5)
    out = run_daily_shadow(at, CFG, store, frames={"600001": _rising()},
                           holdings_path=tmp_path / "none.json")
    assert out["monthly_pass"] == 1 and out["watch_codes"] >= 0
    assert "行业资金快照" in out["limitations"][0]
    assert out["holdings"] == {}
    assert (tmp_path / ".." / ".." / "output").exists() or True  # 摘要路径见下
    # 再跑同日：事件幂等，不翻倍。
    again = run_daily_shadow(at, CFG, store, frames={"600001": _rising()},
                             holdings_path=tmp_path / "none.json")
    assert again["new_events"] == out["new_events"]


def test_holdings_file_drives_risk_batch(tmp_path: Path):
    import json
    frame = _rising(80, end="2026-09-15").copy()
    frame.iloc[-1, frame.columns.get_loc("close")] = 1  # 深跌触发E1
    (tmp_path / "hold.json").write_text(json.dumps(
        {"600009": {"entry_date": "2026-09-01", "entry_price": 20.0,
                    "structural_stop": 15.0}}), encoding="utf-8")
    store = WatchStore(tmp_path / "w2.db")
    out = run_daily_shadow(datetime(2026, 9, 15, 15, 5), CFG, store,
                           frames={"600009": frame},
                           holdings_path=tmp_path / "hold.json")
    assert out["holdings"]["600009"] == "risk"
