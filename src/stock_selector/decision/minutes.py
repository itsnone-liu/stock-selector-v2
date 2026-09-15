"""分钟数据层（蓝图 §6.1）。

盘中可得规则的回测必须有分钟级历史。当前本地 TDX 分钟缓存为空且
行情服务器不可达，因此：
- TdxMinuteReader：lc1/lc5 文件解析器（部署侧数据到位后即用）；
- SyntheticMinuteProvider：从日线合成分钟K（**仅引擎测试用，非经验数据**，
  均匀价格路径+均匀量分布，明确标注 synthetic）。
"""

from __future__ import annotations

import struct
from datetime import date, datetime
from pathlib import Path

import pandas as pd

MINUTES_PER_SESSION = 240


def _decode_date(word: int) -> tuple[int, int, int]:
    """TDX分钟文件的日期编码：word = (year-2004)*2048 + month*100 + day。"""
    year = word // 2048 + 2004
    month = (word % 2048) // 100
    day = (word % 2048) % 100
    return year, month, day


class TdxMinuteReader:
    """读取 TDX .lc1(1分钟)/.lc5(5分钟) 文件。

    记录32字节：u16日期, u16时间(HHMM), f32 open/high/low/close,
    f32 amount, u32 vol(手), u32 保留。
    """

    RECORD = struct.Struct("<HHfffffII")

    def __init__(self, tdx_dir: str):
        self.tdx_dir = Path(tdx_dir)

    def _path(self, code: str, freq: str) -> Path | None:
        market = "sh" if code.startswith(("6", "9", "5")) else ("bj" if code.startswith(("4", "8", "9")) else "sz")
        sub = {"1": "minline", "5": "fzline"}[freq]
        path = self.tdx_dir / "vipdoc" / market / sub / f"{market}{code}.lc{freq}"
        return path if path.exists() else None

    def frame(self, code: str, freq: str = "1") -> pd.DataFrame | None:
        path = self._path(code, freq)
        if path is None:
            return None
        rows = []
        blob = path.read_bytes()
        for i in range(0, len(blob) - 31, 32):
            d, t, o, h, low, c, amount, vol, _reserved = self.RECORD.unpack_from(blob, i)
            year, month, day = _decode_date(d)
            hh, mm = t // 100, t % 100
            try:
                ts = pd.Timestamp(datetime(year, month, day, hh, mm))
            except ValueError:
                continue
            rows.append((ts, o, h, low, c, float(vol), amount))
        if not rows:
            return None
        return pd.DataFrame(rows, columns=["datetime", "open", "high", "low", "close", "volume", "amount"]).set_index("datetime")


class SyntheticMinuteProvider:
    """从日线合成分钟K（引擎防穿越测试专用，非经验数据）。

    合成规则（确定性）：价格 open→close 线性路径，high/low 对称包络；
    成交量均匀分布在240分钟。所有输出标记 synthetic=True 的责任在调用方。
    """

    def __init__(self, daily_loader):
        self._daily_loader = daily_loader
        self._cache: dict[str, pd.DataFrame] = {}

    def minute_frame(self, code: str, day: date) -> pd.DataFrame | None:
        daily = self._daily(code)
        if daily is None or daily.empty:
            return None
        ts = pd.Timestamp(day)
        if ts not in daily.index:
            return None
        bar = daily.loc[ts]
        o, c = float(bar["open"]), float(bar["close"])
        h, low = float(bar["high"]), float(bar["low"])
        total_volume = float(bar["volume"])
        per = total_volume / MINUTES_PER_SESSION
        index = []
        for minute in range(MINUTES_PER_SESSION):
            if minute < 120:  # 上午 9:30-11:29
                total = 9 * 60 + 30 + minute
            else:  # 下午 13:00-14:59
                total = 13 * 60 + (minute - 120)
            hh, mm = divmod(total, 60)
            index.append(pd.Timestamp(datetime(day.year, day.month, day.day, hh, mm)))
        frac = [(i + 1) / MINUTES_PER_SESSION for i in range(MINUTES_PER_SESSION)]
        closes = [o + (c - o) * f for f in frac]
        opens = [o + (c - o) * (f - 1 / MINUTES_PER_SESSION) for f in frac]
        highs = [min(h, max(op, cl) * 1.001) for op, cl in zip(opens, closes)]
        lows = [max(low, min(op, cl) * 0.999) for op, cl in zip(opens, closes)]
        return pd.DataFrame(
            {"open": opens, "high": highs, "low": lows, "close": closes,
             "volume": [per] * MINUTES_PER_SESSION, "amount": [per * cl for cl in closes]},
            index=pd.DatetimeIndex(index),
        )

    def _daily(self, code: str) -> pd.DataFrame | None:
        if code not in self._cache:
            self._cache[code] = self._daily_loader(code)
        return self._cache[code]
