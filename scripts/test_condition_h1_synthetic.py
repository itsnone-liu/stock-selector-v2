#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_condition_h1_synthetic.py — 三项合成反例测试(十五轮; 验证 H1 本体函数).

必须直接调用 condition_h1stats.h1_test(与正式运行同一实现);
测试程序不得另写公式。全部通过 exit 0, 任一失败 exit 1。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from condition_h1stats import h1_test, SEED  # noqa: E402

FOLDS = (19, 20, 21, 22)


def make_synthetic(mu, sd, days_per_fold=120, pairs_per_day=10, seed=777):
    rng = np.random.default_rng(seed)
    day_deltas, fold_of_day = {}, {}
    for f in FOLDS:
        for i in range(days_per_fold):
            day = f"b{f}d{i:03d}"
            day_deltas[day] = float(np.mean(rng.normal(mu, sd, pairs_per_day)))
            fold_of_day[day] = f
    return day_deltas, fold_of_day


def main():
    ok = True
    # ① 合成零差: p > 0.10
    dd, fd = make_synthetic(mu=0.0, sd=1.0)
    r0 = h1_test(dd, fd, FOLDS, seed=SEED)
    print(f"① 零差: theta={r0['theta']:+.4f} CI=[{r0['ci_lo']:.4f},{r0['ci_hi']:.4f}] p={r0['p']:.3f}")
    if not (r0["p"] > 0.10 and r0["ci_lo"] < 0 < r0["ci_hi"]):
        print("   FAIL: 零差数据 p 应>0.10 且 CI 覆盖 0"); ok = False
    else:
        print("   PASS")
    # ② 已知差 0.5: CI 覆盖真值且 p < 0.01
    dd, fd = make_synthetic(mu=0.5, sd=1.0)
    r1 = h1_test(dd, fd, FOLDS, seed=SEED)
    print(f"② 已知差0.5: theta={r1['theta']:+.4f} CI=[{r1['ci_lo']:.4f},{r1['ci_hi']:.4f}] p={r1['p']:.4f}")
    if not (r1["ci_lo"] <= 0.5 <= r1["ci_hi"] and r1["p"] < 0.01):
        print("   FAIL: 已知差数据 CI 应覆盖 0.5 且 p<0.01"); ok = False
    else:
        print("   PASS")
    # ③ 退化: 单折全选重抽(每折 1 日, 块=全集)不崩溃
    dd = {f"b{f}d0": 0.3 for f in FOLDS}
    fd = {f"b{f}d0": f for f in FOLDS}
    r2 = h1_test(dd, fd, FOLDS, seed=SEED)
    print(f"③ 退化(每折1日): theta={r2['theta']:+.4f} p={r2['p']:.3f} n_days={r2['n_days']}")
    if not (np.isfinite(r2["theta"]) and np.isfinite(r2["p"])):
        print("   FAIL: 退化输入产生非有限值"); ok = False
    else:
        print("   PASS")
    print("ALL PASS" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
