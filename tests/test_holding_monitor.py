from datetime import datetime

import pandas as pd

from stock_selector.decision.exits import ExitAnchor
from stock_selector.holding_monitor import monitor_holdings


def test_holding_monitor_runs_even_outside_all_pools():
    idx = pd.to_datetime(["2026-09-15", "2026-09-16"])
    frame = pd.DataFrame({"close": [10.0, 8.0]}, index=idx)
    anchor = ExitAnchor("2026-09-15", 10, 9, time_stop_days=5,
                        trail_pct=.08, max_hold_days=20)
    out = monitor_holdings({"600009": anchor}, {"600009": frame},
                           datetime(2026, 9, 16, 15, 5), {})
    assert out["held_count"] == 1
    assert out["holdings"]["600009"]["status"] == "risk"
    assert any(s["rule"] == "E1_structural_stop"
               for s in out["holdings"]["600009"]["signals"])


def test_missing_held_data_is_unknown_not_silent_drop():
    out = monitor_holdings({"600009": ExitAnchor("2026-09-15", 10, 9)}, {},
                           datetime(2026, 9, 16, 15, 5), {})
    assert out["holdings"]["600009"]["status"] == "unknown"
