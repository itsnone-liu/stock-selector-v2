#!/usr/bin/env python3
"""从已落盘的e_stage_events.csv补算bootstrap与manifest（不重跑全管线）。"""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, "src")
from stock_selector.research.contrast import block_bootstrap_median_diff

out = Path(sys.argv[1])
events = pd.read_csv(out / "e_stage_events.csv", dtype={"code": str, "industry_code": str},
                     usecols=lambda c: c in {"code", "date", "weekly_eligibility_state",
                                             "industry_code",
                                             "industry_excess1", "industry_excess5",
                                             "industry_excess20", "market_excess1",
                                             "market_excess5", "market_excess20"})
events["_is_eligible"] = events["weekly_eligibility_state"] == "eligible"
boot = {}
for block in ("code", "date"):
    for prefix in ("industry_excess", "market_excess"):
        for h in (1, 5, 20):
            col = f"{prefix}{h}"
            boot[f"{prefix}{h}_by_{block}"] = block_bootstrap_median_diff(
                events.dropna(subset=[col]), col, "_is_eligible",
                block_col=block, iterations=300)
(out / "e_stage_bootstrap.json").write_text(json.dumps(boot, ensure_ascii=False, indent=2))

sig = pd.read_csv("output/research/momentum_panel_v2/signal_panel.csv",
                  usecols=["weekly_eligibility_state"], low_memory=False)
manifest = {
    "panel_dir": "output/research/momentum_panel_v2",
    "events": len(events),
    "bench_codes": 5588,
    "membership_coverage": float(events["industry_code"].notna().mean()),
    "eligibility_counts": sig["weekly_eligibility_state"].value_counts(dropna=False).to_dict(),
    "note": "bootstrap补算自e_stage_events.csv；eligibility计数来自全量signal_panel",
}
(out / "E_STAGE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
print(json.dumps({k: boot[k] for k in list(boot)[:6]}, ensure_ascii=False, indent=1))
print(json.dumps(manifest, ensure_ascii=False))
