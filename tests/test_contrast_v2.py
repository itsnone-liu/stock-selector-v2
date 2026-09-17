from __future__ import annotations

import numpy as np
import pandas as pd

from stock_selector.research.contrast import (
    block_bootstrap_median_diff,
    grouped_contrast,
    label_contrast_rows,
    nonoverlapping_events,
)


def test_nonoverlap_uses_trading_sessions():
    cal = pd.bdate_range("2025-01-01", periods=20)
    e = pd.DataFrame({"code": ["1"] * 4, "signal_type": ["sv"] * 4,
                      "first_trigger_date": [cal[0], cal[2], cal[5], cal[10]]})
    out = nonoverlapping_events(e, 5, cal)
    assert list(pd.to_datetime(out.first_trigger_date)) == [cal[0], cal[5], cal[10]]


def test_label_and_grouped_contrast():
    x = pd.DataFrame({
        "code": ["1", "2"], "first_trigger_date": ["2025-01-01", "2025-01-02"],
        "pattern": ["A", "A"], "fwd5": [.04, -.02], "fwd1": [.01, -.01],
        "mfe5_full": [.05, .01], "mae5_full": [-.01, -.02],
        "industry_excess5": [.03, -.03],
    })
    y = label_contrast_rows(x, horizons=(5,))
    assert list(y.result_5) == ["positive", "negative"]
    assert list(y.path_5) == ["immediate_continuation", "direct_failure"]
    g = grouped_contrast(y, ["pattern"], horizons=(5,))
    assert g.iloc[0].events == 2 and g.iloc[0].effective_n == 2


def test_block_bootstrap_reports_block_count_and_interval():
    rows = []
    for d in range(10):
        rows += [{"date": d, "treat": True, "v": .02 + d / 1000},
                 {"date": d, "treat": False, "v": -.01 + d / 1000}]
    r = block_bootstrap_median_diff(pd.DataFrame(rows), "v", "treat", block_col="date",
                                    iterations=100, seed=1)
    assert r["blocks"] == 10
    assert r["estimate"] > 0 and r["ci_low"] > 0
