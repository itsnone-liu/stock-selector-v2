#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""identify_features.py — 三时点事前识别特征 (spec §4, 2026-09-21).

防泄漏原则(engine 强制):
    一切特征只允许 dates[:obs_pos+1] 内的行情; 观察日之后的任何 bar
    修改不得改变特征值(防泄漏测试逐一断言)。
三时点特征分层:
    breakout_day      截至突破日(含当日)盘面: 趋势/量能/波动/位置/形态上下文
    first_shrink_day  + 当日缩量/支撑距离/回调深度天数(禁止止跌确认信息)
    stabilization_day + 确认信号(当日收盘反弹/收复比例/下影/量能恢复)
标签(path_family/D/E/group_asof_20d/K*)仅作结果列, 永不进特征。
"""
from __future__ import annotations


class ObsFrame:
    """单股行情 + 观察日截断视图(o=观察日 pos; 只暴露 [:o+1])."""

    def __init__(self, dates, o, op, h, l, c, v, F):
        self.dates = dates[: o + 1]
        self.o = o
        # 复权修正(2026-09-21 复审): 特征一律用 P_adj=raw×F,
        # 否则跨除权日的趋势/位置特征被除权跳空扭曲
        self.O = [op[d] * F[d] for d in self.dates]
        self.H = [h[d] * F[d] for d in self.dates]
        self.L = [l[d] * F[d] for d in self.dates]
        self.C = [c[d] * F[d] for d in self.dates]
        self.V = [v[d] for d in self.dates]      # 量不复权

    def __len__(self):
        return len(self.dates)

    def ret(self, i):
        return self.C[i] / self.C[i - 1] - 1 if i > 0 else None

    def cumret(self, n):
        i = len(self) - 1
        j = i - n
        return self.C[i] / self.C[j] - 1 if j >= 0 else None

    def mean_vol(self, n):
        i = len(self) - 1
        j = i - n + 1
        return sum(self.V[j:i + 1]) / n if j >= 0 else None

    def atr_pct(self, n=14):
        i = len(self) - 1
        if i < n:
            return None
        trs = []
        for j in range(i - n + 1, i + 1):
            pc = self.C[j - 1]
            trs.append(max(self.H[j], pc) - min(self.L[j], pc))
        atr = sum(trs) / n
        return atr / self.C[i] if self.C[i] > 0 else None

    def high_low_pos(self, n=60):
        """观察日收盘在过去 n 日高低区间的位置(0=最低,1=最高)."""
        i = len(self) - 1
        j = i - n + 1
        if j < 0:
            return None
        hi, lo = max(self.C[j:i + 1]), min(self.C[j:i + 1])
        return (self.C[i] - lo) / (hi - lo) if hi > lo else None

    def dist_to_high(self, n=60):
        i = len(self) - 1
        j = i - n + 1
        if j < 0:
            return None
        return self.C[i] / max(self.C[j:i + 1]) - 1

    def ma_bias(self, n=20):
        i = len(self) - 1
        j = i - n + 1
        if j < 0:
            return None
        return self.C[i] / (sum(self.C[j:i + 1]) / n) - 1

    def realized_vol(self, n=20):
        i = len(self) - 1
        j = i - n + 1
        if j < 0 or i <= j:
            return None
        rs = [self.C[k] / self.C[k - 1] - 1 for k in range(j + 1, i + 1)]
        m = sum(rs) / len(rs)
        return (sum((x - m) ** 2 for x in rs) / len(rs)) ** 0.5


def feat_breakout(fr: ObsFrame, prep_days: float | None) -> dict:
    """时点1: 截至突破日(含当日)特征.

    2026-09-21 复审删除 max_gain_from_anchor(生命周期终结才可知=未来
    最高价, 已证实泄漏); prep_days=突破日-准备期起点(正数, 方向修正)."""
    i = len(fr) - 1
    return {
        "bo_ret1": fr.ret(i),
        "bo_cum5": fr.cumret(5), "bo_cum10": fr.cumret(10),
        "bo_cum20": fr.cumret(20),
        "bo_volratio5": fr.V[i] / fr.mean_vol(5) if fr.mean_vol(5) else None,
        "bo_volratio20": fr.V[i] / fr.mean_vol(20) if fr.mean_vol(20) else None,
        "bo_atr14pct": fr.atr_pct(14),
        "bo_hlpos60": fr.high_low_pos(60),
        "bo_dist_high60": fr.dist_to_high(60),
        "bo_ma_bias20": fr.ma_bias(20),
        "bo_rvol20": fr.realized_vol(20),
        "prep_days": prep_days,
    }


def feat_shrink(fr: ObsFrame, p_bo_close: float, bo_pos_abs: int,
                post_bo_high: float | None) -> dict:
    """时点2: 缩量回调日. p_bo_close=突破日收盘(观察日之前, 允许),
    bo_pos_abs/post_bo_high 均截至观察日(含). 禁止任何止跌确认后信息."""
    i = len(fr) - 1
    mv5 = fr.mean_vol(5)
    f = {
        "sh_volratio5": fr.V[i] / mv5 if mv5 else None,
        "sh_support_dist": fr.C[i] / p_bo_close - 1 if p_bo_close else None,
        "sh_low_support_dist": fr.L[i] / p_bo_close - 1 if p_bo_close else None,
        "sh_days_since_bo": float(i - bo_pos_abs),
        "sh_dd_from_high": (fr.C[i] / post_bo_high - 1
                            if post_bo_high else None),
    }
    f.update(feat_breakout_attrs(fr))
    return f


def feat_breakout_attrs(fr: ObsFrame):
    """shrink/stabilization 时点仍携带的基准盘面(全部观察日截断)."""
    i = len(fr) - 1
    return {
        "atr14pct": fr.atr_pct(14), "hlpos60": fr.high_low_pos(60),
        "ma_bias20": fr.ma_bias(20), "rvol20": fr.realized_vol(20),
        "volratio5": fr.V[i] / fr.mean_vol(5) if fr.mean_vol(5) else None,
    }


def feat_stabilization(fr: ObsFrame, p_bo_close: float,
                       pullback_low: float | None) -> dict:
    """时点3: 止跌确认日. 只允许当日确认信号 + 此前信息."""
    i = len(fr) - 1
    prev_c = fr.C[i - 1] if i > 0 else None
    rng = fr.H[i] - fr.L[i]
    f = {
        "st_ret1": fr.ret(i),
        "st_close_vs_bo": fr.C[i] / p_bo_close - 1 if p_bo_close else None,
        "st_rebound_from_low": (fr.C[i] / pullback_low - 1
                                if pullback_low else None),
        "st_lower_shadow": ((min(fr.O[i], fr.C[i]) - fr.L[i]) / rng
                            if rng and rng > 0 else None),
        "st_volrecover": fr.V[i] / fr.mean_vol(5) if fr.mean_vol(5) else None,
        "st_prev_ret1": fr.ret(i - 1) if i > 1 else None,
    }
    f.update(feat_breakout_attrs(fr))
    return f


def split_semiannual(breakout_day: str, start_year: int = 2015) -> int:
    """逐半年桶编号: 0=2015H1, 1=2015H2, ... (冻结切分器)."""
    y, m = int(breakout_day[:4]), int(breakout_day[5:7])
    return (y - start_year) * 2 + (0 if m <= 6 else 1)


def eligibility_riskset(r):
    """path_binary 活跃风险集统一资格(2026-09-21 第八轮冻结, 三脚本共用).

    排除(互斥优先序):
    1 first_reclaim_day <= obs_day(含当日) → reclaim_known_negative
    2 path_family == right_censored → 右删失不作确定标签
    3 lifecycle_end_day <= obs_day → lifecycle_inactive(活跃性排除,
      classify_path 依 20 日窗, end 不构成标签已知)
    须 obs_day < label_available_day_path(严格, 结局确定前).
    行参数: identify 数据集 dict(first_reclaim_day/lifecycle_end_day 需在).
    """
    fr = r.get("first_reclaim_day")
    if fr and fr <= r["obs_day"]:
        return False
    if r.get("path_family") == "right_censored":
        return False
    ed = r.get("lifecycle_end_day")
    if ed and ed <= r["obs_day"]:
        return False
    la = r.get("label_available_day_path")
    return bool(la and r["obs_day"] < la)
