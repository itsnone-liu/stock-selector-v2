"""TDX-backed R4/OOS-B acquisition adapter."""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from stock_selector.data.tdx_live import TdxLiveClient

SOURCE_ID = "tdx_052d_v1"


def _qfq_map(daily_store: Path) -> dict[str, float]:
    if not daily_store.exists():
        return {}
    payload = json.load(gzip.open(daily_store, "rt"))
    return {str(row[0]).replace("-", ""): float(row[2]) for row in payload.get("qfq", [])}


def fetch_r4_days(code: str, after: str, through: str, daily_store: Path,
                  host: str | None = None, max_5m_bars: int = 12_000) -> dict[str, tuple]:
    """Return ``date -> (bars48, amount, raw_close, qfq_close, source_id)``.

    A requested day is emitted only when all contracts pass: complete 48-bar
    session, a matching TDX daily bar, turnover closure, and an independently
    materialized qfq close.  Missing qfq fails closed; raw TDX price is never
    silently substituted for adjusted price.
    """
    code6 = str(code).split(".")[-1].zfill(6)
    after_key, through_key = after.replace("-", ""), through.replace("-", "")
    qfq = _qfq_map(daily_store)
    with TdxLiveClient(host=host) as client:
        daily = client.fetch_range(code6, "daily", max_bars=800, since=after_key)
        bars5 = client.fetch_range(code6, "5m", max_bars=max_5m_bars, since=after_key)
    daily_by_day = {bar.time_key: bar for bar in daily
                    if after_key < bar.time_key <= through_key}
    by_day: dict[str, list] = {}
    for bar in bars5:
        day = bar.time_key[:8]
        if after_key < day <= through_key:
            by_day.setdefault(day, []).append([
                bar.time_key[-4:], bar.open, bar.high, bar.low, bar.close,
                float(bar.volume), bar.amount,
            ])
    result = {}
    for day, db in daily_by_day.items():
        intraday = sorted(by_day.get(day, []), key=lambda row: row[0])
        adjusted = qfq.get(day)
        if len(intraday) != 48 or adjusted is None:
            continue
        sum_amount = sum(row[6] for row in intraday)
        sum_volume = sum(row[5] for row in intraday)
        amount_ratio = sum_amount / db.amount if db.amount > 0 else 0
        volume_ratio = sum_volume / db.volume if db.volume > 0 else 0
        if not (0.95 <= amount_ratio <= 1.05 and 0.999 <= volume_ratio <= 1.001):
            continue
        iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        result[iso] = (intraday, db.amount, db.close, adjusted, SOURCE_ID)
    return result
