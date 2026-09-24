#!/usr/bin/env python3
"""T3 V5 realtime state snapshot — historical replay and daily operation.

Usage:
    python3 scripts/t3_v5_snapshot.py --asof YYYY-MM-DD [--ledger]

Reads the frozen state_vector_daily product (PIT states only) plus the
frozen event list; writes realtime_state_snapshot.parquet. With --ledger,
appends the snapshot to the hash-chained prospective_state_ledger.parquet
(append-only; asof must strictly increase).

The snapshot contains NO forward outcome fields (No-Future gate).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2  # noqa: E402
from stock_selector.research import t3_v5 as v5  # noqa: E402

OUT = ROOT / "output/research/t3_v5"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", required=True)
    ap.add_argument("--ledger", action="store_true")
    args = ap.parse_args()

    svd = pd.read_parquet(OUT / "state_vector_daily.parquet")
    events = v2.load_events()
    mdates, _ = v2.market_calendar_and_close()
    mpos = {d: i for i, d in enumerate(mdates)}
    manifest = json.loads((OUT / "state_run_manifest.json").read_text())
    snap = v5.build_snapshot(args.asof, svd, events, mdates, mpos,
                             input_manifest_hash=manifest["manifest_hash"])
    if not len(snap):
        print(f"[v5-snapshot] no active anchored events at {args.asof}")
        return
    snap.to_parquet(OUT / "realtime_state_snapshot.parquet", index=False,
                    compression="snappy")
    print(f"[v5-snapshot] asof={args.asof} rows={len(snap)} "
          f"rule={v5.COMPACT_RULE_VERSION} "
          f"schema={v5.STATE_SCHEMA_VERSION}")
    print(snap["compact_state"].value_counts().to_string())
    if args.ledger:
        led = v5.ledger_append(OUT / "prospective_state_ledger.parquet",
                               snap, args.asof,
                               note="prospective" if args.asof > v2.DATASET_END
                               else "in-sample replay")
        print(f"[v5-snapshot] ledger now {len(led)} rows; chain "
              f"{v5.verify_ledger_chain(OUT / 'prospective_state_ledger.parquet')}")


if __name__ == "__main__":
    main()
