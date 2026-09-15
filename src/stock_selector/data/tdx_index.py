"""TDX .day 指数文件直读（绕过个股市场前缀推断：sh000001=上证指数）。

记录32字节：u32日期(yyyymmdd), u32开/高/低/收(×100), f32成交额,
u32成交量, u32保留。
"""

from __future__ import annotations

import struct
from pathlib import Path

import pandas as pd

RECORD = struct.Struct("<IIIIIfII")


def index_daily(tdx_dir: str | Path, market: str = "sh", code: str = "000001") -> pd.DataFrame | None:
    path = Path(tdx_dir) / "vipdoc" / market / "lday" / f"{market}{code}.day"
    if not path.exists():
        return None
    blob = path.read_bytes()
    rows = []
    for offset in range(0, len(blob) - 31, 32):
        date, o, h, low, c, amount, vol, _reserved = RECORD.unpack_from(blob, offset)
        y, rest = date // 10000, date % 10000
        m, d = rest // 100, rest % 100
        try:
            ts = pd.Timestamp(year=y, month=m, day=d)
        except ValueError:
            continue
        rows.append((ts, o / 100.0, h / 100.0, low / 100.0, c / 100.0, float(vol), amount))
    if not rows:
        return None
    return pd.DataFrame(
        rows,
        columns=["datetime", "open", "high", "low", "close", "volume", "amount"],
    ).set_index("datetime")
