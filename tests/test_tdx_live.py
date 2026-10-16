import struct

import pytest

from stock_selector.data.tdx_live import TdxBar, market_of, parse_bars


def _enc_price(value: int) -> bytes:
    negative = value < 0
    number = abs(value)
    first = number & 0x3F
    number >>= 6
    out = bytearray([first | (0x40 if negative else 0) | (0x80 if number else 0)])
    while number:
        byte = number & 0x7F
        number >>= 7
        out.append(byte | (0x80 if number else 0))
    return bytes(out)


def _body(category: int, key: int | tuple[int, int], volume: float, amount: float) -> bytes:
    out = bytearray(struct.pack("<H", 1))
    out += struct.pack("<I", key) if category == 9 else struct.pack("<HH", *key)
    for value in (10150, -160, 50, -170):
        out += _enc_price(value)
    out += struct.pack("<ff", volume, amount)
    return bytes(out)


def test_minute_float32_turnover_contract():
    packed_day = ((2026 - 2004) << 11) + 10 * 100 + 15
    bar = parse_bars(_body(0, (packed_day, 9 * 60 + 35), 1_380_000, 13_851_237), 0)[0]
    assert bar == TdxBar("202610150935", 10.15, 10.2, 9.98, 9.99, 13_851_237.0, 1_380_000)


def test_daily_volume_lots_are_normalized_to_shares():
    bar = parse_bars(_body(9, 20261015, 127_870, 127_842_216), 9)[0]
    assert bar.amount == pytest.approx(127_842_216)
    assert bar.volume == 12_787_000


def test_market_mapping():
    assert market_of("600000") == 1
    assert market_of("510300") == 1
    assert market_of("000001") == 0
    assert market_of("300750") == 0
