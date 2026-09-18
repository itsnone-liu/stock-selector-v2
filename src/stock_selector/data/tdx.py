from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd
from mootdx.reader import Reader

LOG = logging.getLogger(__name__)


def market_for_code(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("4", "8")):
        return "bj"
    return "sh" if code.startswith(("5", "6", "9")) else "sz"


def valid_security_code(market: str, code: str, include_b_share: bool = False) -> bool:
    code = str(code).zfill(6)
    if not code.isdigit():
        return False
    if market == "sh":
        prefixes = ("600", "601", "603", "605", "688", "689")
        return code.startswith(prefixes) or (include_b_share and code.startswith("900"))
    if market == "sz":
        prefixes = ("000", "001", "002", "003", "004", "300", "301")
        return code.startswith(prefixes) and not code.startswith("39")
    if market == "bj":
        return code.startswith(("43", "83", "87", "88", "920", "4", "8"))
    return False


class TdxStore:
    def __init__(self, tdx_dir: str | Path):
        self.tdx_dir = Path(tdx_dir)
        self.reader = Reader.factory(tdxdir=str(self.tdx_dir))

    def list_codes(self, include_b_share: bool = False) -> list[str]:
        codes: set[str] = set()
        for market in ("sh", "sz", "bj"):
            folder = self.tdx_dir / "vipdoc" / market / "lday"
            if not folder.exists():
                LOG.warning("TDX market directory missing: %s", folder)
                continue
            for path in folder.glob("*.day"):
                stem = path.stem
                code = stem[2:] if stem[:2] in {"sh", "sz", "bj"} else stem
                if valid_security_code(market, code, include_b_share):
                    codes.add(code.zfill(6))
        return sorted(codes)

    def daily(self, code: str) -> pd.DataFrame | None:
        code = str(code).zfill(6)
        try:
            frame = self.reader.daily(symbol=code)
        except Exception as exc:
            LOG.exception("Failed reading TDX daily data for %s: %s", code, exc)
            return None
        if frame is None or frame.empty:
            return None
        frame = frame.copy()
        frame.index = pd.to_datetime(frame.index)
        frame = frame[~frame.index.duplicated(keep="last")].sort_index()
        required = ["open", "high", "low", "close", "volume"]
        if any(column not in frame.columns for column in required):
            LOG.error("TDX daily data missing columns for %s: %s", code, frame.columns.tolist())
            return None
        return frame

    def market_calendar(self, index_file: str = "sh000001") -> pd.DatetimeIndex | None:
        """完整市场交易日历：直接解析指数.day文件（与个股缺bar无关）。

        返回升序 DatetimeIndex；文件缺失或为空返回 None。
        """
        path = None
        for market in ("sh", "sz", "bj"):
            candidate = self.tdx_dir / "vipdoc" / market / "lday" / f"{index_file}.day"
            if candidate.exists():
                path = candidate
                break
        if path is None:
            LOG.warning("TDX index file missing: %s.day", index_file)
            return None
        dates: list[str] = []
        data = path.read_bytes()
        for i in range(0, len(data) - 31, 32):
            chunk = data[i:i + 32]
            n = int.from_bytes(chunk[0:4], "little")  # yyyymmdd
            y, m, d = n // 10000, n // 100 % 100, n % 100
            if not (1990 <= y <= 2100 and 1 <= m <= 12 and 1 <= d <= 31):
                continue
            dates.append(f"{y:04d}-{m:02d}-{d:02d}")
        if not dates:
            return None
        return pd.DatetimeIndex(pd.to_datetime(sorted(set(dates))))


def load_name_map(path: str | Path | None) -> dict[str, str]:
    if not path:
        return {}
    name_path = Path(path)
    if not name_path.exists():
        return {}
    try:
        raw = json.loads(name_path.read_text(encoding="utf-8"))
    except Exception as exc:
        LOG.warning("Cannot read stock names from %s: %s", name_path, exc)
        return {}
    if isinstance(raw, dict):
        return {str(k).zfill(6): str(v) for k, v in raw.items() if v is not None}
    return {}
