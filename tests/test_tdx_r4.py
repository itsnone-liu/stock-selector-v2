import gzip
import json
from pathlib import Path

from stock_selector.data.tdx_live import TdxBar
from stock_selector.data.tdx_r4 import SOURCE_ID, fetch_r4_days


class FakeClient:
    def __init__(self, host=None): pass
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def fetch_range(self, code, period, max_bars, since):
        if period == "daily":
            return [TdxBar("20261016", 10, 11, 9, 10.5, 48_000, 4_800)]
        result = []
        for i in range(48):
            minutes = 9 * 60 + 35 + i * 5 if i < 24 else 13 * 60 + 5 + (i - 24) * 5
            key = f"20261016{minutes // 60:02d}{minutes % 60:02d}"
            result.append(TdxBar(key, 10, 10.1, 9.9, 10, 1_000, 100))
        return result


def _store(path: Path, include_qfq=True):
    payload = {"qfq": [["2026-10-16", "10", "10.4", "11", "9", "48"]] if include_qfq else []}
    with gzip.open(path, "wt") as handle:
        json.dump(payload, handle)


def test_r4_adapter_emits_complete_closed_day(tmp_path, monkeypatch):
    store = tmp_path / "000001.json.gz"
    _store(store)
    monkeypatch.setattr("stock_selector.data.tdx_r4.TdxLiveClient", FakeClient)
    got = fetch_r4_days("sz.000001", "2026-10-15", "2026-10-16", store)
    bars, amount, raw_close, qfq_close, source = got["2026-10-16"]
    assert len(bars) == 48
    assert amount == 48_000
    assert raw_close == 10.5
    assert qfq_close == 10.4
    assert source == SOURCE_ID


def test_r4_adapter_fails_closed_without_qfq(tmp_path, monkeypatch):
    store = tmp_path / "000001.json.gz"
    _store(store, include_qfq=False)
    monkeypatch.setattr("stock_selector.data.tdx_r4.TdxLiveClient", FakeClient)
    assert fetch_r4_days("000001", "2026-10-15", "2026-10-16", store) == {}
