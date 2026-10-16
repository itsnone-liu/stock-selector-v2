from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import requests

from stock_selector.data.tdx_live import TdxLiveClient
from stock_selector.models import Quote

LOG = logging.getLogger(__name__)


def _symbol(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("4", "8", "920")):
        return "bj" + code
    if code.startswith(("5", "6", "900")):
        return "sh" + code
    return "sz" + code


def _quote_timestamp(fields: list[str]) -> datetime | None:
    if len(fields) <= 30:
        return None
    raw = fields[30].strip()
    for pattern in ("%Y%m%d%H%M%S", "%Y%m%d%H%M"):
        try:
            return datetime.strptime(raw, pattern)
        except ValueError:
            continue
    return None


class TdxQuoteProvider:
    """Minute-resolution realtime quotes from TDX 7709.

    This matches the selector's actual contract (current price/open/previous
    close/cumulative volume and amount).  Unsupported BJ codes and missing
    minute sessions fail closed; no HTTP fallback is hidden inside the source.
    """

    source_id = "tdx_052d_1m_v1"

    def __init__(self, host: str | None = None, max_workers: int = 4):
        self.host = host
        self.max_workers = max_workers

    def _one(self, code: str, at: datetime) -> Quote:
        if code.startswith(("4", "8", "920")):
            raise ValueError("unsupported_bj_market")
        day = at.strftime("%Y%m%d")
        with TdxLiveClient(host=self.host) as client:
            minute = client.fetch(code, "1m", 0, 800)
            daily = client.fetch(code, "daily", 0, 10)
        today = [bar for bar in minute if bar.time_key.startswith(day) and
                 datetime.strptime(bar.time_key, "%Y%m%d%H%M") <= at]
        previous = [bar for bar in daily if bar.time_key < day]
        if not today or not previous:
            raise ValueError("missing_tdx_session")
        last = today[-1]
        return Quote(code=code, price=last.close, open=today[0].open,
                     previous_close=previous[-1].close,
                     volume=float(sum(bar.volume for bar in today)),
                     amount=float(sum(bar.amount for bar in today)),
                     timestamp=datetime.strptime(last.time_key, "%Y%m%d%H%M"))

    def fetch(self, codes: Iterable[str], at: datetime | None = None) -> tuple[dict[str, Quote], dict[str, str]]:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        at = at or datetime.now()
        normalized = [str(code).zfill(6) for code in codes]
        quotes, errors = {}, {}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {pool.submit(self._one, code, at): code for code in normalized}
            for future in as_completed(futures):
                code = futures[future]
                try:
                    quotes[code] = future.result()
                except Exception as exc:
                    errors[code] = f"tdx_failed:{type(exc).__name__}:{exc}"
        return quotes, errors


class TencentQuoteProvider:
    def __init__(self, timeout_seconds: int = 15, batch_size: int = 50, volume_multiplier: float = 100.0):
        self.timeout_seconds = timeout_seconds
        self.batch_size = batch_size
        # 腾讯A股成交量字段单位为“手”；系统内部统一使用“股”。
        self.volume_multiplier = volume_multiplier
        self.session = requests.Session()

    def fetch(self, codes: Iterable[str], at: datetime | None = None) -> tuple[dict[str, Quote], dict[str, str]]:
        normalized = [str(code).zfill(6) for code in codes]
        quotes: dict[str, Quote] = {}
        errors: dict[str, str] = {}
        for start in range(0, len(normalized), self.batch_size):
            batch = normalized[start : start + self.batch_size]
            symbols = [_symbol(code) for code in batch]
            try:
                response = self.session.get(
                    "http://qt.gtimg.cn/q=" + ",".join(symbols), timeout=self.timeout_seconds
                )
                response.raise_for_status()
                response.encoding = "gbk"
            except Exception as exc:
                message = f"request_failed:{type(exc).__name__}"
                LOG.warning("Tencent quote batch failed: %s", exc)
                errors.update({code: message for code in batch})
                continue
            seen: set[str] = set()
            for line in response.text.split(";"):
                if "=" not in line:
                    continue
                fields = line.split("=", 1)[1].strip().strip('"').split("~")
                if len(fields) < 7:
                    continue
                code = fields[2].strip().zfill(6)
                if code not in batch:
                    continue
                try:
                    price = float(fields[3])
                    previous_close = float(fields[4])
                    open_price = float(fields[5])
                    volume = float(fields[6]) * self.volume_multiplier
                except (ValueError, IndexError) as exc:
                    errors[code] = f"parse_failed:{type(exc).__name__}"
                    continue
                if price <= 0 or previous_close <= 0:
                    errors[code] = "invalid_zero_quote"
                    continue
                if open_price <= 0 or volume <= 0:
                    errors[code] = "halted_or_preopen_quote"
                    continue
                quotes[code] = Quote(
                    code=code,
                    price=price,
                    open=open_price,
                    previous_close=previous_close,
                    volume=volume,
                    timestamp=_quote_timestamp(fields),
                )
                seen.add(code)
            for code in batch:
                if code not in seen and code not in errors:
                    errors[code] = "missing_from_response"
        return quotes, errors
