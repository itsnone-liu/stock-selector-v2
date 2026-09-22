#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""verify_h1_anchor.py — H1 归档数值对照检查程序(十八轮提交; 归档声明之对照执行)."""
import json
from pathlib import Path
r = json.loads(Path("/root/project/workspace/stock-selector-v2/output/research/posneg_v1/MULTIPERIOD_CONDITION_H1_QB.json").read_text())
claimed = {"h1_theta": (-0.00711, r["h1"]["theta"]), "h1_ci": ((-0.01614, 0.00152), (r["h1"]["ci_lo"], r["h1"]["ci_hi"])),
           "h1_p": (0.1144, r["h1"]["p"]), "s1_ci": ((-0.01116, -0.00302), (r["s1"]["ci_lo"], r["s1"]["ci_hi"])),
           "s1_p": (0.0005, r["s1"]["p"]), "d1_f4": (-0.01558, r["d1"]["f4_day_mean"]), "d1_all6": (-0.02024, r["d1"]["all6_day_mean"]),
           "n_days_f4": (481, r["h1_sample_meta"]["n_days_f4"]), "n_pairs_f4": (21939, r["h1_sample_meta"]["n_pairs_f4"]),
           "n_stocks": (4727, r["s1"]["n_stocks"])}
for k, (c, a) in claimed.items():
    ok = all(x == y if isinstance(x, int) else abs(x - y) < 5e-5 for x, y in zip(c, a)) if isinstance(c, tuple) else (a == c if isinstance(c, int) else abs(a - c) < 5e-5)
    print(f"{k}: claimed={c} json={a} {'OK' if ok else 'MISMATCH'}")
    assert ok
print(f"ALL {len(claimed)} items consistent")
