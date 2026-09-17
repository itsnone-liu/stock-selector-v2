from __future__ import annotations

from datetime import datetime

import pandas as pd

from stock_selector.signals.weekly_features import early_week_comparison_evidence


def _rows(dates, opens, closes, vols):
    return pd.DataFrame({"open": opens, "close": closes,
                         "high": [max(o, c) + .1 for o, c in zip(opens, closes)],
                         "low": [min(o, c) - .1 for o, c in zip(opens, closes)],
                         "volume": vols, "amount": [v * 10 for v in vols]},
                        index=pd.to_datetime(dates))


def test_monday_same_progress_and_short_week_proration():
    d = _rows(["2025-09-29", "2025-09-30", "2025-10-09"],
              [10, 10.1, 10], [10.1, 10.2, 10.2], [100, 120, 150])
    e = early_week_comparison_evidence(d, datetime(2025, 10, 9, 15, 30), planned_sessions=2)
    assert e["sessions"] == 1 and e["planned_sessions"] == 2
    assert e["evidence_strength"] == .5
    assert e["planned_prorated_return_pct"] == 4.0  # +2%单日按2日短周折算
    assert e["same_progress_volume_ratio"] == 1.5


def test_tuesday_recovery_ratio_is_parallel_evidence():
    d = _rows(["2025-08-04", "2025-08-05", "2025-08-11", "2025-08-12"],
              [10, 10.1, 10, 9.7], [10.1, 10.2, 9.8, 9.9], [100, 100, 120, 110])
    e = early_week_comparison_evidence(d, datetime(2025, 8, 12, 15, 30), planned_sessions=5)
    assert e["sessions"] == 2
    assert e["tuesday_recovery_ratio"] == 1.0  # 周一跌0.2，周二实体涨0.2
    assert e["tuesday_closes_above_monday_close"] is True


def test_cc_same_progress_uses_closes_not_opens():
    # 上周(08-04~05)收盘10.2；上上周不存在→cc_prev_same=None。
    # 补上上周：两周前周一/周二。
    d = _rows(["2025-07-28", "2025-07-29", "2025-08-04", "2025-08-05",
               "2025-08-11", "2025-08-12"],
              [10, 10.05, 10, 10.1, 10, 9.7],
              [10.05, 10.1, 10.1, 10.2, 9.8, 9.9],
              [100, 100, 100, 100, 120, 110])
    e = early_week_comparison_evidence(d, datetime(2025, 8, 12, 15, 30), planned_sessions=5)
    # 本周至今收盘9.9 vs 上周收盘10.2 → cc_current≈-2.9412
    assert e["cc_current_return_pct"] == round(9.9 / 10.2 * 100 - 100, 4)
    # 上周同进度(前2日)收盘10.2 vs 上上周收盘10.1 → +0.9901
    assert e["cc_prev_same_progress_return_pct"] == round(10.2 / 10.1 * 100 - 100, 4)
    assert e["cc_same_progress_return_delta_pct"] == round(
        (9.9 / 10.2 - 10.2 / 10.1) * 100, 4)


def test_spring_festival_empty_calendar_week_falls_back_to_trading_week():
    # 2026春节：02-14~02-23休市，02-24(周二)恢复。
    # 日历"上周"02-16~22零交易——必须回退到交易周02-09~13及再上周02-02~06。
    dates = ["2026-01-30", "2026-02-02", "2026-02-03", "2026-02-04", "2026-02-05", "2026-02-06",
             "2026-02-09", "2026-02-10", "2026-02-11", "2026-02-12", "2026-02-13",
             "2026-02-24", "2026-02-25"]
    closes = [10.0, 10.1, 10.2, 10.1, 10.2, 10.3,
              10.2, 10.2, 10.3, 10.4, 10.5,
              10.4, 10.6]
    opens = [c - 0.05 for c in closes]
    vols = [100.0] * len(dates)
    d = _rows(dates, opens, closes, vols)
    # 周二02-24：本周至今=02-24单日；上一交易周=02-09~13(n=1→02-09)
    e = early_week_comparison_evidence(d, datetime(2026, 2, 24, 15, 30), planned_sessions=5)
    assert e["sessions"] == 1
    assert "note" not in e
    assert e["cc_current_return_pct"] == round(10.4 / 10.5 * 100 - 100, 4)
    assert e["cc_prev_same_progress_return_pct"] == round(10.2 / 10.3 * 100 - 100, 4)
    assert e["same_progress_volume_ratio"] == 1.0
