#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_condition_h2_synthetic.py — H2 统计核心合成测试(二十一轮; 验证本体).

直接调用 condition_h2stats.h2_test/holm2 与 run_condition_qa_coverage.classify
(与正式运行同一实现; 测试不另写公式)。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from condition_h2stats import h2_test, holm2, SEED  # noqa: E402
from run_condition_qa_coverage import classify  # noqa: E402


def make_synthetic(rate1, rate2, n_days=117, obs_lo=80, obs_hi=120, seed=777):
    rng = np.random.default_rng(seed)
    recs = {}
    for i in range(n_days):
        d = f"2026d{i:03d}"
        o1 = int(rng.integers(obs_lo, obs_hi))
        o2 = int(rng.integers(obs_lo, obs_hi))
        recs[d] = {"hi": (int(rng.binomial(o1, rate1)), o1),
                   "lo": (int(rng.binomial(o2, rate2)), o2)}
    return recs


def main():
    ok = True
    # ① 零差: p>0.10 且 CI 覆盖 0
    r0 = h2_test(make_synthetic(0.20, 0.20), "hi", "lo", seed=SEED)
    print(f"① 零差: theta={r0['theta']:+.4f} CI=[{r0['ci_lo']:.4f},{r0['ci_hi']:.4f}] p={r0['p']:.3f}")
    if not (r0["p"] > 0.10 and r0["ci_lo"] < 0 < r0["ci_hi"]):
        print("   FAIL"); ok = False
    else:
        print("   PASS")
    # ② 已知差 +0.10: CI 覆盖 0.1 且 p<0.01
    r1 = h2_test(make_synthetic(0.30, 0.20), "hi", "lo", seed=SEED)
    print(f"② 已知差0.1: theta={r1['theta']:+.4f} CI=[{r1['ci_lo']:.4f},{r1['ci_hi']:.4f}] p={r1['p']:.4f}")
    if not (r1["ci_lo"] <= 0.10 <= r1["ci_hi"] and r1["p"] < 0.01):
        print("   FAIL"); ok = False
    else:
        print("   PASS")
    # ③ 单块退化(轴 40 日)不崩溃
    r2 = h2_test(make_synthetic(0.25, 0.20, n_days=40), "hi", "lo", seed=SEED)
    print(f"③ 40日轴: theta={r2['theta']:+.4f} p={r2['p']:.3f} n={r2['n_axis_days']}")
    if not all(np.isfinite(r2[k]) for k in ("theta", "ci_lo", "ci_hi", "p")):
        print("   FAIL"); ok = False
    else:
        print("   PASS")
    # ④ classify 二十一轮反例: 行政终止(102)早于窗内突破(104)→行政删失
    r3 = classify(i=100, bo_i=104, end_i=102, mkt=False, n_md=1000)
    print(f"④ 行政早于突破: {r3}")
    if r3 != "censor_admin":
        print("   FAIL"); ok = False
    else:
        print("   PASS")
    # ⑤ 行政与事件同日→行政优先(保守, 冻结优先级 竞争>行政>事件)
    r4 = classify(i=100, bo_i=103, end_i=103, mkt=False, n_md=1000)
    print(f"⑤ 行政事件同日: {r4}")
    if r4 != "censor_admin":
        print("   FAIL"); ok = False
    else:
        print("   PASS")
    # ⑥ holm2 冒烟: 小 p 在前, 单调
    adj = holm2({"p": 0.02}, {"p": 0.04})
    print(f"⑥ holm2: {adj}")
    if not (adj["H2a"]["holm_p"] <= adj["H2b"]["holm_p"] and adj["H2a"]["holm_p"] == 0.04):
        print("   FAIL"); ok = False
    else:
        print("   PASS")
    print("ALL PASS" if ok else "FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
