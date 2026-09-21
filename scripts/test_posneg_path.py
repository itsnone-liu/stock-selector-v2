#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_posneg_path.py — §8.3 门禁: 六情形构造测试逐一断言唯一归类 + 标签算法.

运行: PYTHONPATH=src python scripts/test_posneg_path.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stock_selector.research.posneg_path import (
    classify_path, group_asof, group_labels)

N = 0


def ok(cond, msg):
    global N
    assert cond, msg
    N += 1


PB = 10.0


def mk(levels):
    """levels: 20 个价格(相对P_bo), 直接构造窗口。"""
    return [PB * x for x in levels]


# 1 单边上涨(D=0, NH<TR? 单边上涨 TR=首日最低, NH 存在>=TR) → pullback_new_high(3b含D=0)
w = mk([1.01 + 0.01 * i for i in range(20)])
r = classify_path(PB, w, True)
ok(r["family"] == "pullback_new_high" and r["D"] == 0.0, f"单边上涨→pullback_new_high(D=0): {r}")

# 2 横盘恒等(全=P_bo) → reclaim_no_new_high(spec: 该类覆盖横盘恒等)
w = mk([1.0] * 20)
r = classify_path(PB, w, True)
ok(r["family"] == "reclaim_no_new_high", f"横盘恒等→reclaim_no_new_high: {r}")
ok(r["D"] == 0.0, "横盘恒等 D=0")

# 3 先涨后跌(NH 早于 TR) 且最低点后曾收复(RC 存在) → high_then_pullback_reclaimed
w = mk([1.05, 1.03] + [0.96] * 15 + [1.0, 1.01, 1.0])
r = classify_path(PB, w, True)
ok(r["family"] == "high_then_pullback_reclaimed", f"先涨后跌再收复→high_then_pullback_reclaimed: {r}")
ok(r["NH"] < r["TR"] and r["RC"] is not None, f"NH<TR 且 RC 存在: {r['NH']}<{r['TR']} rc={r['RC']}")

# 4 先跌后涨(TR 早, NH 晚) → pullback_new_high
w = mk([0.95, 0.94, 0.93] + [1.0, 1.02, 1.05] + [1.03] * 14)
r = classify_path(PB, w, True)
ok(r["family"] == "pullback_new_high" and r["NH"] >= r["TR"], f"先跌后涨: {r}")

# 5 同日并列(NH==TR: 最低日即新高日不可能; 构造 NH 日序==TR 日序=并列极值日) →
#   argmin 首个最小与首个 strict_new_high 同日 → NH>=TR → 3b
w = mk([0.99] + [1.08] + [1.02] * 18)          # 全程高位横盘, TR=1(0.99), NH=2 → pullback_new_high
r = classify_path(PB, w, True)
ok(r["family"] == "pullback_new_high", f"并列极值归3b: {r}")
# NH==TR 真同日: 波动窗口使 argmin 与首个新高同日
w = mk([1.00, 0.90, 1.12, 0.95] + [1.0] * 16)  # TR=2, NH=3 ≥ TR
r2 = classify_path(PB, w, True)
ok(r2["family"] == "pullback_new_high" and r2["TR"] == 2 and r2["NH"] == 3, f"同日并列断言: {r2}")

# 6 期末恰收复(窗内最低在中途, 最后日 reclaim 但无 NH) → reclaim_no_new_high
w = mk([0.97, 0.95, 0.94] + [0.96] * 16 + [1.0])
r = classify_path(PB, w, True)
ok(r["family"] == "reclaim_no_new_high" and r["RC"] == 20, f"期末恰收复: {r}")

# 7 never_reclaim + subtype 边界
w = mk([0.8500001] * 20)                         # E≈0.1499999 边界内侧 → unconfirmed(<=0.15)
r = classify_path(PB, w, True)
ok(r["family"] == "never_reclaim" and r["subtype"] == "breakout_unconfirmed", f"E边界内侧: {r}")
w = mk([0.849] * 20)
r = classify_path(PB, w, True)
ok(r["subtype"] == "breakout_failure", "E>0.15→breakout_failure")

# 8 reclaim_then_fade: 曾 reclaim 但全部发生在 TR 之前, TR 后无收复
w = mk([1.02] + [0.90] * 19)                     # 首日 reclaim, 次日起低于 P_bo
r = classify_path(PB, w, True)
ok(r["family"] == "reclaim_then_fade", f"先站上后回落未归: {r}")

# 9 窗口不完整 → right_censored
r = classify_path(PB, mk([1.0] * 19), False)
ok(r["family"] == "right_censored", "窗口不完整→right_censored")

# 10 group_labels 算法
ok(group_labels(None, None, True) == "unknown_censored", "censored只有T1→unknown")
ok(group_labels("2025-01-10", None, True) == "unknown_censored", "censored T2无T3→unknown")
ok(group_labels("2025-01-10", "2025-02-01", True) == "G3", "censored T3已现→G3")
ok(group_labels(None, None, False) == "G1", "complete无T2→G1")
ok(group_labels("2025-01-10", None, False) == "G2", "complete T2无T3→G2")
ok(group_labels("2025-01-10", "2025-02-01", False) == "G3", "complete T3→G3")

# 11 group_asof
ok(group_asof(None, None, None) == "unknown_censored", "窗口不完整→unknown")
ok(group_asof("2025-01-10", None, "2025-01-20") == "G2", "T2<=cutoff→G2")
ok(group_asof("2025-01-10", None, "2025-01-09") == "G1", "T2>cutoff→G1")

print(f"posneg path 单测: {N} 项断言全部通过 ✓")
