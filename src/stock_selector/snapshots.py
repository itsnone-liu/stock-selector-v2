from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from stock_selector.models import Quote
from stock_selector.output import write_csv


COLUMNS = ["date", "minute", "code", "volume_shares", "quote_timestamp", "captured_at"]


class VolumeSnapshotStore:
    """持久化盘中累计量，以便下一交易日做同刻比较。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read(self) -> pd.DataFrame:
        if not self.path.exists():
            return pd.DataFrame(columns=COLUMNS)
        frame = pd.read_csv(self.path, dtype={"code": str})
        if frame.empty:
            return pd.DataFrame(columns=COLUMNS)
        frame["code"] = frame["code"].astype(str).str.zfill(6)
        return frame

    def references(self, codes: list[str], at: datetime, tolerance_minutes: int = 5) -> dict[str, float]:
        frame = self.read()
        if frame.empty:
            return {}
        frame["date"] = pd.to_datetime(frame["date"]).dt.date
        frame["minute"] = frame["minute"].astype(int)
        current_minute = at.hour * 60 + at.minute
        older = frame[frame["date"] < at.date()].copy()
        if older.empty:
            return {}
        latest_date = older["date"].max()
        older = older[(older["date"] == latest_date) & ((older["minute"] - current_minute).abs() <= tolerance_minutes)]
        if older.empty:
            return {}
        older["distance"] = (older["minute"] - current_minute).abs()
        older = older.sort_values(["code", "distance", "minute"]).drop_duplicates("code")
        wanted = {str(code).zfill(6) for code in codes}
        return {
            str(row.code).zfill(6): float(row.volume_shares)
            for row in older.itertuples()
            if str(row.code).zfill(6) in wanted and float(row.volume_shares) > 0
        }

    def save(self, quotes: dict[str, Quote], captured_at: datetime) -> Path:
        existing = self.read()
        rows = []
        for code, quote in quotes.items():
            if quote.volume is None or quote.volume <= 0:
                continue
            stamp = quote.timestamp or captured_at
            rows.append(
                {
                    "date": stamp.date().isoformat(),
                    "minute": stamp.hour * 60 + stamp.minute,
                    "code": code,
                    "volume_shares": quote.volume,
                    "quote_timestamp": stamp.isoformat(),
                    "captured_at": captured_at.isoformat(),
                }
            )
        combined = pd.concat([existing, pd.DataFrame(rows, columns=COLUMNS)], ignore_index=True)
        if not combined.empty:
            combined = combined.drop_duplicates(["date", "minute", "code"], keep="last").sort_values(["date", "minute", "code"])
        return write_csv(combined, self.path)
