#!/usr/bin/env python3
"""T4.1 Context 构建：市场/板块日表 + 行业映射 + 事件背景。

验收（开工令 §六）：事件集合差集为空；日期与映射抽样可追溯；
字段覆盖率与缺失原因；历史映射不可得时保留空值并明确限制。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2  # noqa: E402
from t4.context import build as tb              # noqa: E402

BASELINE = "28f7aed"


def frame_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(
        df.astype(str), index=True).values.tobytes())
    h.update(str(df.shape).encode())
    h.update(str(list(df.columns)).encode())
    return h.hexdigest()


def main():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    assert head == BASELINE, f"HEAD {head} != baseline {BASELINE}"
    cfg = yaml.safe_load((ROOT / "config/t4_context.yaml").read_text())
    OUT = ROOT / cfg["paths"]["out_dir"]
    OUT.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    # 行业快照（若未落盘则提示先拉取；不自动联网以保持可复现）
    snap = ROOT / cfg["paths"]["industry_snapshot"]
    assert snap.exists(), "industry snapshot missing: run scripts/fetch_csrc_industry.py"

    events = v2.load_events()
    print(f"[t4.1] events {len(events)} (V6 frozen universe)", flush=True)

    tb.set_stock_cache(ROOT / cfg["paths"]["per_stock_dir"])
    print(f"[t4.1] stock cache loaded {time.time() - t0:.0f}s",
          flush=True)

    smap = tb.build_sector_map(snap)
    mkt, sec = tb.build_daily_frames(
        ROOT / cfg["paths"]["per_stock_dir"], smap,
        min_members=cfg["aggregation"]["min_sector_members"])
    print(f"[t4.1] market_daily {len(mkt)} days, sector_daily {len(sec)} "
          f"rows ({sec.industry_gate.nunique()} gates) "
          f"{time.time() - t0:.0f}s", flush=True)

    ctx = tb.build_event_context(
        events, mkt, sec, smap,
        lookback=cfg["context"]["lookback_market"],
        pct_win=cfg["context"]["percentile_window"],
        breadth_days=cfg["context"]["breadth_avg_days"])
    print(f"[t4.1] event_context {len(ctx)} rows {time.time() - t0:.0f}s",
          flush=True)

    # 双跑（聚合+context 全量重算一次）
    smap2 = tb.build_sector_map(snap)
    mkt2, sec2 = tb.build_daily_frames(
        ROOT / cfg["paths"]["per_stock_dir"], smap2,
        min_members=cfg["aggregation"]["min_sector_members"])
    ctx2 = tb.build_event_context(
        events, mkt2, sec2, smap2,
        lookback=cfg["context"]["lookback_market"],
        pct_win=cfg["context"]["percentile_window"],
        breadth_days=cfg["context"]["breadth_avg_days"])
    det = {
        "market_daily": frame_hash(mkt) == frame_hash(mkt2),
        "sector_daily": frame_hash(sec) == frame_hash(sec2),
        "event_context": frame_hash(ctx) == frame_hash(ctx2),
    }
    (OUT / "t4_1_determinism.json").write_text(json.dumps(
        {"identical": all(det.values()), "frames": det}, indent=2))

    smap.to_parquet(OUT / "stock_sector_map.parquet", index=False)
    mkt.to_parquet(OUT / "market_daily.parquet", index=False)
    sec.to_parquet(OUT / "sector_daily.parquet", index=False)
    ctx.to_parquet(OUT / "t4_event_context.parquet", index=False)

    manifest = {
        "stage": "T4.1_context", "baseline_commit": BASELINE,
        "config_sha256": hashlib.sha256(
            (ROOT / "config/t4_context.yaml").read_bytes()).hexdigest(),
        "events": len(events), "context_rows": len(ctx),
        "market_days": len(mkt), "sector_rows": len(sec),
        "sector_gates": int(sec.industry_gate.nunique()),
        "map_rows": len(smap),
        "map_snapshot_date": "2026-09-21",
        "determinism": det,
        "elapsed_sec": round(time.time() - t0, 1),
    }
    (OUT / "manifest.json").write_text(json.dumps(
        manifest, indent=2, ensure_ascii=False))
    print(json.dumps(manifest, indent=2), flush=True)


if __name__ == "__main__":
    main()
