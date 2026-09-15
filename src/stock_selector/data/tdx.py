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
        return code.startswith(("43", "83", "87", "88", "4", "8"))
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
