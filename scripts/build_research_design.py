#!/usr/bin/env python3
"""从冻结信号面板构造P3/P4设计表；只产出对照与特征设计，不关联或汇总收益。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from stock_selector.research.comparisons import build_progressive_comparisons


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--panel-dir", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--horizons", default="1,2,3,5,10,15,20")
    a = p.parse_args()
    horizons = tuple(int(x) for x in a.horizons.split(",") if x)
    panel_dir, out = Path(a.panel_dir), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    sig = pd.read_csv(panel_dir / "signal_panel.csv", dtype={"code": str}, low_memory=False)
    designs = build_progressive_comparisons(sig, horizons=horizons)
    manifest = {"source": str(panel_dir), "horizons": list(horizons), "tables": {}}
    for name, frame in designs.items():
        frame.to_csv(out / f"{name}.csv", index=False)
        manifest["tables"][name] = {"rows": len(frame),
                                    "cohorts": frame["cohort"].value_counts(dropna=False).to_dict()}
    (out / "DESIGN_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
