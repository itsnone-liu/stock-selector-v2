#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_identify_leakproof.py — 防泄漏构造测试 (spec §4, 2026-09-21).

核心断言: 修改观察日之后的任何行情 bar, 三时点特征值完全不变。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from stock_selector.research.identify_features import (
    ObsFrame, feat_breakout, feat_shrink, feat_stabilization, split_semiannual)

N = 0


def ok(cond, msg):
    global N
    assert cond, msg
    N += 1


def mkframe(n=60, seed_price=10.0, drift=0.01):
    dates = [f"2025-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(n)]
    import random
    rng = random.Random(7)
    C, O, H, L, V, F = [], [], [], [], [], []
    p = seed_price
    for i in range(n):
        p *= 1 + drift + rng.uniform(-0.02, 0.02)
        o_ = p * rng.uniform(0.99, 1.01)
        C.append(p)
        O.append(o_)
        H.append(max(p, o_) * 1.005)
        L.append(min(p, o_) * 0.995)
        V.append(rng.uniform(5e5, 2e6))
        F.append(1.0)
    dC = dict(zip(dates, C))
    dO = dict(zip(dates, O))
    dH = dict(zip(dates, H))
    dL = dict(zip(dates, L))
    dV = dict(zip(dates, V))
    dF = dict(zip(dates, F))
    return dates, dO, dH, dL, dC, dV, dF


dates, dO, dH, dL, dC, dV, dF = mkframe()
OBS = 40


def feats_at(obs):
    fr = ObsFrame(dates, obs, dO, dH, dL, dC, dV, dF)
    f1 = feat_breakout(fr, prep_days=12, max_gain_from_anchor=0.08)
    bo_close = dC[dates[30]]
    post_hi = max(dC[d] for d in dates[30 + 1:obs + 1])
    f2 = feat_shrink(fr, bo_close, 30, post_hi)
    pl = min(dL[d] for d in dates[35:obs + 1])
    f3 = feat_stabilization(fr, bo_close, pl)
    return f1, f2, f3


base1, base2, base3 = feats_at(OBS)
# ── 防泄漏: 篡改观察日之后的行情 ──
for k in range(OBS + 1, 60):
    dC[dates[k]] *= 1.5
    dO[dates[k]] *= 2.0
    dH[dates[k]] *= 3.0
    dL[dates[k]] *= 0.5
    dV[dates[k]] *= 10.0
t1, t2, t3 = feats_at(OBS)
ok(base1 == t1, f"breakout 特征泄漏! diff={[k for k in base1 if base1[k]!=t1[k]]}")
ok(base2 == t2, f"shrink 特征泄漏! diff={[k for k in base2 if base2[k]!=t2[k]]}")
ok(base3 == t3, f"stabilization 特征泄漏! diff={[k for k in base3 if base3[k]!=t3[k]]}")

# ── 观察日前移 1 日特征应改变(敏感性, 证明截断真的在动) ──
p1, p2, p3 = feats_at(OBS - 1)
ok(any(base1[k] != p1[k] for k in base1), "观察日前移特征应变化(截断生效)")

# ── 时点2 禁止止跌确认信息: shrink 特征键不含 stabilization 专属键 ──
st_keys = set(t3) - set(t2)
ok(st_keys == {"st_ret1", "st_close_vs_bo", "st_rebound_from_low",
               "st_lower_shadow", "st_volrecover", "st_prev_ret1"},
   f"时点3 新增键恰为确认信号: {st_keys}")
ok(not any(k.startswith("st_") for k in t2), "时点2 无 st_* 确认信号字段")
ok(not any(k.startswith(("path_", "K2_", "K3_", "K4_", "group_")) for k in t1),
   "时点1 无结果标签字段")

# ── 切分器 ──
ok(split_semiannual("2015-01-01") == 0 and split_semiannual("2015-07-01") == 1,
   "2015H1/H2")
ok(split_semiannual("2024-12-31") == 19 and split_semiannual("2025-01-01") == 20,
   "2024H2=19, 2025H1=20")

print(f"identify 防泄漏单测: {N} 项断言全部通过 ✓")
