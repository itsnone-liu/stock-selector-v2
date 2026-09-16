"""P2 消融①：3.5% 涨幅上限的档位扫描（1/2/3/5/10/20%，另含3.5原版与无上限）。

上限语义（原版）：label = raw条件成立 且 r_today < cap。
r_today 可由面板字段精确重建：r_today_pct = r_yesterday_pct + return_acceleration_pct。
纯离线分析，不动生产。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

CAPS = [1.0, 2.0, 3.0, 3.5, 5.0, 10.0, 20.0, float("inf")]  # inf=无上限(=raw)
METRICS = ["fwd1", "fwd2", "fwd3", "fwd30", "peak3_return", "giveback_from_peak3"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="output/research/momentum_panel")
    ap.add_argument("--out", default="output/research/momentum_panel/analysis")
    args = ap.parse_args()
    d = Path(args.dir)

    sig_use = ["code", "date", "sv_raw", "td_raw", "sv_legacy", "td_legacy",
               "r_yesterday_pct", "return_acceleration_pct", "weekly_passed",
               "sv_continuation", "sv_rebound", "acc_continuation", "acc_rebound"]
    sig = pd.read_csv(d / "signal_panel.csv", dtype={"code": str}, usecols=lambda c: c in sig_use)
    out_use = ["code", "date"] + METRICS + ["next_week_return", "next_week_high"]
    oc = pd.read_csv(d / "outcome_panel.csv", dtype={"code": str}, low_memory=False,
                     usecols=lambda c: c in out_use)
    df = sig.merge(oc, on=["code", "date"], how="left")

    # 重建 r_today 并验证与已存 sv_legacy（3.5档）一致
    df["r_today_pct"] = df["r_yesterday_pct"] + df["return_acceleration_pct"]
    check = df["sv_raw"] & (df["r_today_pct"] < 3.5)
    agree = (check.fillna(False) == df["sv_legacy"].fillna(False)).mean()
    print(f"3.5档重建 vs 面板sv_legacy 一致率: {agree:.6f}")

    rows = []
    for label_raw, name in [("sv_raw", "shrinking_volume"), ("td_raw", "two_day")]:
        for cap in CAPS:
            capname = "no_cap" if np.isinf(cap) else f"{cap:g}%"
            m = df[label_raw].fillna(False) & (df["r_today_pct"] < cap)
            sub = df[m]
            row = {"label": name, "cap": capname, "n": int(len(sub))}
            for met in METRICS + ["next_week_return", "next_week_high"]:
                v = pd.to_numeric(sub[met], errors="coerce").dropna()
                row[f"{met}_med"] = round(float(v.median()), 5) if len(v) else None
                row[f"{met}_pos"] = round(float((v > 0).mean()), 4) if len(v) else None
            rows.append(row)
    res = pd.DataFrame(rows)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    res.to_csv(out / "p2_cap_sweep.csv", index=False)
    with open(out / "p2_cap_sweep_meta.json", "w") as f:
        json.dump({"caps": [c for c in CAPS], "check_agreement_3_5": agree,
                   "semantics": "label = raw AND r_today_pct < cap"}, f, indent=1)
    show = ["label", "cap", "n", "fwd1_med", "fwd1_pos", "fwd3_med",
            "fwd30_med", "peak3_return_med", "giveback_from_peak3_med", "next_week_return_med"]
    print(res[show].to_string(index=False))


if __name__ == "__main__":
    main()
