from datetime import datetime

from stock_selector.models import Quote
from stock_selector.snapshots import VolumeSnapshotStore


def test_snapshot_store_matches_previous_date_same_minute(tmp_path):
    store = VolumeSnapshotStore(tmp_path / "volumes.csv")
    yesterday = datetime(2026, 9, 14, 11, 30)
    today = datetime(2026, 9, 15, 11, 32)
    store.save({"000001": Quote("000001", 10, 10, 9.9, 1_000_000, timestamp=yesterday)}, yesterday)
    assert store.references(["000001"], today)["000001"] == 1_000_000


def test_snapshot_store_rejects_nonmatching_time(tmp_path):
    store = VolumeSnapshotStore(tmp_path / "volumes.csv")
    yesterday = datetime(2026, 9, 14, 10, 0)
    store.save({"000001": Quote("000001", 10, 10, 9.9, 1_000_000, timestamp=yesterday)}, yesterday)
    assert store.references(["000001"], datetime(2026, 9, 15, 11, 30)) == {}
