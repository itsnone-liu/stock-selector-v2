from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

import requests

from stock_selector.models import Quote

LOG = logging.getLogger(__name__)


def _symbol(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("4", "8")):
        return "bj" + code
    if code.startswith(("5", "6", "9")):
        return "sh" + code
    return "sz" + code


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
                quotes[code] = Quote(
                    code=code,
                    price=price,
                    open=open_price if open_price > 0 else price,
                    previous_close=previous_close,
                    volume=volume if volume >= 0 else None,
                    timestamp=at or datetime.now(),
                )
                seen.add(code)
            for code in batch:
                if code not in seen and code not in errors:
                    errors[code] = "missing_from_response"
        return quotes, errors
