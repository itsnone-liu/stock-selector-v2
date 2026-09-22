#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""condition_h2stats.py — H2 统计核心(唯一实现; 合成测试与正式运行共用).

冻结(H2_PREREG v1.1, 二十一轮):
- 研究量: 全 b22 合并五日发生率差 θ = (Σev_g1/Σobs_g1) − (Σev_g2/Σobs_g2)
- 重抽时间轴 = 完整 b22 指数交易日序列; 每日每组 (ev, obs), 缺组= (0,0)
- 块 = 40 指数交易日环形块, 每次抽 ceil(n_axis/40) 个块起点, 拼回 n_axis 日
- NBOOT=2000, seed=20260922; 中心化 p=(1+Σ1(|θ*−θ̂|>=|θ̂|))/2001
- 95% CI = 未中心化 θ* 的 2.5/97.5 百分位
- 每次重抽断言两组分母(Σobs)均 > 0
"""
from __future__ import annotations

import numpy as np

SEED = 20260922
NBOOT = 2000
BLOCK = 40


def rate_diff(day_records: dict, g_hi: str, g_lo: str) -> float:
    """day_records: {day: {group: (ev, obs)}}; 返回 r_g_hi − r_g_lo."""
    ev1 = sum(v[g_hi][0] for v in day_records.values() if g_hi in v)
    ob1 = sum(v[g_hi][1] for v in day_records.values() if g_hi in v)
    ev2 = sum(v[g_lo][0] for v in day_records.values() if g_lo in v)
    ob2 = sum(v[g_lo][1] for v in day_records.values() if g_lo in v)
    assert ob1 > 0 and ob2 > 0, f"组分母为 0: {g_hi}={ob1}, {g_lo}={ob2}"
    return ev1 / ob1 - ev2 / ob2


def _resample_axis(axis_days: list, rng) -> list:
    n = len(axis_days)
    n_blocks = int(np.ceil(n / BLOCK))
    out = []
    for s in rng.integers(0, n, size=n_blocks):
        for j in range(BLOCK):
            out.append(axis_days[(s + j) % n])
    return out[:n]


def h2_test(day_records: dict, g_hi: str, g_lo: str,
            seed: int = SEED, nboot: int = NBOOT):
    """返回 {theta, ci_lo, ci_hi, p, n_axis_days, n_days_with_data}."""
    axis = sorted(day_records.keys())
    theta = rate_diff(day_records, g_hi, g_lo)
    rng = np.random.default_rng(seed)
    stars = np.empty(nboot)
    for b in range(nboot):
        picked = _resample_axis(axis, rng)
        rs = {}
        for k, d in enumerate(picked):
            rec = day_records[d]
            key = (d, k)
            rs[key] = rec          # 同日重复抽取→计数多次(分子分母同乘)
        # rate_diff 用 dict 值, 重复日通过列表展开
        ev1 = ob1 = ev2 = ob2 = 0
        for rec in rs.values():
            if g_hi in rec:
                ev1 += rec[g_hi][0]; ob1 += rec[g_hi][1]
            if g_lo in rec:
                ev2 += rec[g_lo][0]; ob2 += rec[g_lo][1]
        assert ob1 > 0 and ob2 > 0, f"重抽 b={b} 分母 0: {ob1}/{ob2}"
        stars[b] = ev1 / ob1 - ev2 / ob2
    t_b = stars - theta
    p = (1 + int(np.sum(np.abs(t_b) >= abs(theta)))) / (nboot + 1)
    return {"theta": float(theta),
            "ci_lo": float(np.percentile(stars, 2.5)),
            "ci_hi": float(np.percentile(stars, 97.5)),
            "p": float(p),
            "n_axis_days": len(axis),
            "n_days_with_data": sum(1 for v in day_records.values() if v)}


def holm2(res_a: dict, res_b: dict) -> dict:
    """Holm 家族=2: 返回调整后 p 与拒绝标记(α=0.05)."""
    ps = [("H2a", res_a["p"]), ("H2b", res_b["p"])]
    ps.sort(key=lambda x: x[1])
    m = 2
    adj = {}
    prev = 0.0
    for k, (name, p) in enumerate(ps):
        a = min(1.0, max(prev, (m - k) * p))
        adj[name] = {"raw_p": p, "holm_p": a, "reject_0.05": a < 0.05}
        prev = a
    return adj
