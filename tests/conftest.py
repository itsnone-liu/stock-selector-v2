from __future__ import annotations

from datetime import date

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from stock_selector.config import load_config


@pytest.hookimpl(tryfirst=True)
def pytest_sessionstart(session):
    """Apply certified file modes during isolated-tree materialization.

    Git's index cannot carry 0600, and the bridge may materialize certified
    ignored inputs with its default 0644 mode.  This is setup-time
    materialization (before any gate reads the artifact), not verification or
    repair: the B4 verifier remains strictly fail-closed on mode drift.
    """
    root = Path(__file__).resolve().parents[1]
    manifest = root / "config/audit/certified_live_inputs.json"
    if not manifest.is_file():
        return
    for entry in json.loads(manifest.read_text()).get("protectedArtifacts", []):
        path = root / entry["path"]
        if path.is_file():
            os.chmod(path, entry["mode"])


@pytest.fixture
def config():
    cfg = load_config()
    cfg["universe"]["min_median_amount_20d"] = 0
    cfg["universe"]["min_listing_days"] = 60
    return cfg


def make_daily(periods: int = 260, end: str = "2026-09-15", drift: float = 0.12) -> pd.DataFrame:
    index = pd.bdate_range(end=end, periods=periods)
    close = 10 + np.arange(periods) * drift
    open_price = close - 0.05
    return pd.DataFrame(
        {
            "open": open_price,
            "high": close + 0.2,
            "low": open_price - 0.2,
            "close": close,
            "volume": np.full(periods, 1_000_000.0),
            "amount": close * 100_000_000,
        },
        index=index,
    )
