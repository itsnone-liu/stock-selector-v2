"""T5.1 合成数据测试夹具：小规模人工日历与个股。"""
from __future__ import annotations

import numpy as np
import pandas as pd

MDATES = [f"2025-01-{d:02d}" for d in range(1, 21)]  # 20 个市场日


def fake_stock(code="000001", base=10.0, drift=0.01, gap_days=()):
    """生成 (dates, adj, raw, pch, amt, turn, vol)；gap_days=停牌。"""
    dates = [d for d in MDATES if d not in gap_days]
    n = len(dates)
    closes = [base * (1 + drift) ** i for i in range(n)]
    adj = list(closes)
    pch = [None] + [closes[i] / closes[i - 1] - 1
                    for i in range(1, n)]
    amt = [1e8] * n
    turn = [2.0] * n
    vol = [1e7] * n
    return code, dates, adj, list(closes), pch, amt, turn, vol


def fake_events(code="000001", t0="2025-01-06", end="2025-01-17"):
    return pd.DataFrame([{
        "breakout_event_id": f"{code}_{t0}", "code": code,
        "breakout_day": t0, "end_day": end,
        "E_class": "E2", "participation_policy": "P2_normal",
        "initial_risk_budget_class": "normal_budget",
        "M_cell": 1, "L_q": "L2", "R60": 0.0, "year": "2025",
        "pre20_turn_base": 2.0, "pre20_volume_base": 1e7,
        "pre20_amount_base": 1e8,
    }])


def fake_market():
    return pd.DataFrame({
        "date": MDATES,
        "pct_up": [0.5] * 20,
        "new_high_20d_count": [100 + i for i in range(20)],
        "mkt_amount_yi": [1e4] * 20,
    }).assign(breadth_5d=lambda d: d["pct_up"].rolling(
        5, min_periods=5).mean())
