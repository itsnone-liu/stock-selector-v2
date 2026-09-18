#!/usr/bin/env python3
"""冻结面板的正负结果分析入口；不构造或修改信号。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

from stock_selector.research.contrast import HORIZONS, grouped_contrast, label_contrast_rows, nonoverlapping_events
from stock_selector.research.momentum_panel import PANEL_VERSION


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", required=True)
    p.add_argument("--protocol", default="config/research/momentum_efficiency/protocol_v1.yaml")
    p.add_argument("--calendar", help="可选交易日CSV，第一列为日期；提供时输出20日非重叠稳健样本")
    a = p.parse_args()
    d = Path(a.dir)
    manifest_path = d / "manifest.json"
    if not manifest_path.exists():
        raise SystemExit("panel manifest missing")
    if json.loads(manifest_path.read_text()).get("panel_version") != PANEL_VERSION:
        raise SystemExit(f"stale panel contract: expected {PANEL_VERSION}")
    cfg = yaml.safe_load(Path(a.protocol).read_text())
    c = cfg["result_classification"]
    sig = pd.read_csv(d / "signal_panel.csv", dtype={"code": str}, low_memory=False)
    out = pd.read_csv(d / "outcome_panel.csv", dtype={"code": str}, low_memory=False)
    ep = pd.read_csv(d / "episode_panel.csv", dtype={"code": str})

    # episode只取首触发日，再接信号日证据与结果。
    first = ep.rename(columns={"first_trigger_date": "date"})
    x = first.merge(sig, on=["code", "date"], how="left", validate="many_to_one")
    x = x.merge(out, on=["code", "date"], how="left", suffixes=("", "_out"), validate="many_to_one")
    x["half"] = pd.to_datetime(x["date"]).dt.to_period("2Q").astype(str)
    x = label_contrast_rows(x, horizons=HORIZONS,
                            delta=float(c["excess_return_neutral_band"]),
                            meaningful_mfe=float(c["meaningful_mfe"]),
                            deep_mae=float(c["deep_mae"]))
    x.to_csv(d / "positive_negative_events.csv", index=False)

    groups = [g for g in ["signal_type", "weekly_base_pattern", "weekly_weekday_path",
                          "weekly_eligibility_state", "industry_code", "market_context", "half"]
              if g in x.columns]
    tables = []
    for g in groups:
        t = grouped_contrast(x, [g], horizons=HORIZONS); t.insert(0, "dimension", g); tables.append(t)
    summary = pd.concat(tables, ignore_index=True) if tables else pd.DataFrame()
    summary.to_csv(d / "positive_negative_summary.csv", index=False)

    nonoverlap_n = None
    if a.calendar:
        cal = pd.to_datetime(pd.read_csv(a.calendar).iloc[:, 0])
        stable = nonoverlapping_events(ep, 20, pd.DatetimeIndex(cal))
        stable.to_csv(d / "episode_panel_nonoverlap20.csv", index=False)
        nonoverlap_n = len(stable)
    print(json.dumps({"events": len(x), "summary_rows": len(summary),
                      "nonoverlap20": nonoverlap_n, "groups": groups}, ensure_ascii=False))


if __name__ == "__main__":
    main()
