"""tdx_index .day 直读测试（合成二进制文件）。"""

from __future__ import annotations

import struct

from stock_selector.data.tdx_index import RECORD, index_daily


def _write_day(tmp_path, rows):
    folder = tmp_path / "vipdoc" / "sh" / "lday"
    folder.mkdir(parents=True)
    (folder / "sh000001.day").write_bytes(b"".join(RECORD.pack(*r) for r in rows))
    return tmp_path


def test_index_daily_roundtrip(tmp_path):
    rows = [
        (20260914, 385000, 390000, 384000, 389000, 1.5e11, 400000000, 0),
        (20260915, 389000, 392000, 388000, 386400, 1.6e11, 440000000, 0),
    ]
    frame = index_daily(_write_day(tmp_path, rows), "sh", "000001")
    assert len(frame) == 2
    assert frame["open"].iloc[0] == 3850.0
    assert frame["close"].iloc[-1] == 3864.0
    assert frame["high"].iloc[0] == 3900.0


def test_index_daily_missing_file(tmp_path):
    assert index_daily(tmp_path, "sh", "000001") is None


def test_index_daily_skips_bad_date(tmp_path):
    rows = [
        (20991301, 385000, 390000, 384000, 389000, 1.0e11, 1, 0),  # 非法月份
        (20260915, 389000, 392000, 388000, 386400, 1.6e11, 440000000, 0),
    ]
    frame = index_daily(_write_day(tmp_path, rows), "sh", "000001")
    assert len(frame) == 1
