#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""condition_h1stats.py — H1 统计核心(唯一实现; 合成测试与正式运行共用此函数).

冻结(DESIGN_V2 §5.5, 十五轮修正):
- θ̂_f=折内逐日 Δ_d 算术平均; θ̂=Σ w_f θ̂_f, w_f=折有效日数/Σ有效日
- bootstrap: 每折分别 40 指数交易日环形块重抽(不跨折), 2000 次,
  seed=20260922; 重抽日序列中重复日计多次
- 双侧 p(中心化): T_b=θ̂*_b−θ̂; p=(1+Σ1(|T_b|>=|θ̂|))/2001
- 95% CI: 未中心化 θ̂* 的 2.5/97.5 百分位
"""
from __future__ import annotations

import numpy as np

SEED = 20260922
NBOOT = 2000
BLOCK = 40


def theta_hat(day_deltas: dict, fold_of_day: dict, folds) -> float:
    """day_deltas: {day: Δ_d}; fold_of_day: {day: fold}; folds: 折列表."""
    w = {}
    th = {}
    for f in folds:
        ds = [d for d in day_deltas if fold_of_day[d] == f]
        if ds:
            w[f] = len(ds)
            th[f] = float(np.mean([day_deltas[d] for d in ds]))
    tot = sum(w.values())
    return sum(w[f] / tot * th[f] for f in w)


def _resample_fold_days(days_sorted: list, rng) -> list:
    """折内 40 日环形块重抽: 返回重抽后的日列表(长度=折内日数, 重复计次)."""
    n = len(days_sorted)
    n_blocks = int(np.ceil(n / BLOCK))
    out = []
    for s in rng.integers(0, n, size=n_blocks):
        for j in range(BLOCK):
            out.append(days_sorted[(s + j) % n])
    return out[:n]


def h1_test(day_deltas: dict, fold_of_day: dict, folds,
            seed: int = SEED, nboot: int = NBOOT):
    """返回 {theta, ci_lo, ci_hi, p, n_days, n_folds}."""
    rng = np.random.default_rng(seed)
    theta = theta_hat(day_deltas, fold_of_day, folds)
    stars = np.empty(nboot)
    for b in range(nboot):
        rs_deltas = []
        rs_fold = {}
        for f in folds:
            ds = sorted([d for d in day_deltas if fold_of_day[d] == f])
            if not ds:
                continue
            picked = _resample_fold_days(ds, rng)
            for i, d in enumerate(picked):
                key = (d, i)
                rs_deltas.append(key)
                rs_fold[key] = f
        val = theta_hat({k: day_deltas[k[0]] for k in rs_deltas}, rs_fold, folds)
        stars[b] = val
    t_b = stars - theta
    p = (1 + int(np.sum(np.abs(t_b) >= abs(theta)))) / (nboot + 1)
    return {"theta": float(theta),
            "ci_lo": float(np.percentile(stars, 2.5)),
            "ci_hi": float(np.percentile(stars, 97.5)),
            "p": float(p),
            "n_days": len(day_deltas),
            "n_folds": len({fold_of_day[d] for d in day_deltas})}
