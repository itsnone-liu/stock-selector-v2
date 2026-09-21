#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_identify_gates.py — 日期门禁反例测试四类 (2026-09-21 第三轮复审).

1 半年跨界: bo 在 H1 末, +20 日落 H2 → split_path 归 H2(按标签可得日)
2 生命周期终结晚于第 20 日: G1/G2 的 la_ge=end_day > la_path; G3=T3 首日
3 准备期回调早于突破日: t2_eff 取突破后事件; 无突破后事件→无 shrink 行
4 非恒定复权因子: raw 除权跳空由 F 补偿, 趋势特征反映复权收益
"""
import sys
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_identify_features import process_episode   # noqa: E402

N = 0


def ok(cond, msg):
    global N
    assert cond, msg
    N += 1


def mkdates(n, y=2025, m0=1):
    out, y_, m_ = [], y, m0
    for i in range(n):
        out.append(f"{y_:04d}-{m_:02d}-{1 + i % 28:02d}")
        if i % 28 == 27:
            m_ += 1
            if m_ > 12:
                y_, m_ = y_ + 1, 1
    return out


def mkcache(dates, F=None, split_adj=None):
    """合成行情: 温和上行; split_adj=(日, raw乘数, F乘数) 模拟除权.

    真实除权=水平移位: 自除权日起后续所有 raw 价格×raw_mul;
    F 自该日起×F_mul 补偿, 使 P_adj=raw×F 连续。"""
    F = F or {}
    u = {}
    p = 10.0
    shifted = False
    for d in dates:
        p *= 1.005
        raw = p * (split_adj[1] if (split_adj and shifted) else 1.0)
        F[d] = (split_adj[2] if (split_adj and shifted) else 1.0)
        if split_adj and d == split_adj[0]:
            shifted = True
        u[d] = (raw, raw * 1.01, raw * 0.99, raw, 1e6)
    return (dates, u, F, 0, {})


PL = {"cutoff_day": None, "path_family": "pullback_new_high", "path_subtype": None,
      "D": "0.05", "E": "0.0", "D_atr": "1.2", "group_eventual": "G2",
      "group_asof_20d": "G2", "structure_broken_asof_20d": "False"}

# ── 1 半年跨界: bo=2025-06-27(桶按 bo=2025H1), +20交易日 cutoff 落 2025-07 ──
dates = mkdates(60)
dates = [d for d in dates]
# 构造真实跨半年: 直接给 6/27 起 40 个连续日
dates = ["2025-06-%02d" % (3 + i) for i in range(28)] + ["2025-07-%02d" % (1 + i) for i in range(28)]
bo_d = dates[24]                                        # 2025-06-27
la_path = dates[24 + 20]                                # 2025-07-xx
pl = dict(PL, cutoff_day=la_path)
cache = mkcache(dates)
life_row = ("sz.000001", bo_d, None, dates[10], None, "2025-08-20", False, None)
r = process_episode("L1", pl, life_row, None, cache)
row1 = r["breakout"]
ok(row1["label_available_day_path"] == la_path, "la_path=bo+20交易日")
ok(row1["split_path"] == (2025 - 2015) * 2 + 1,      # 2025H2=12, 而非按 bo 的 11
   f"跨界: split_path 按标签可得日归 H2 ({row1['split_path']})")

# ── 2 la_ge 分目标: G2→end_day(>la_path); G3→T3 首日 ──
ok(row1["label_available_day_ge"] == "2025-08-20" and row1["label_available_day_ge"] > la_path,
   "G2 的 la_ge=end_day 且晚于第20日")
life_g3 = ("sz.000001", bo_d, None, dates[10], "2025-07-05", "2025-09-01", False, None)
r3 = process_episode("L2", dict(PL, group_eventual="G3", cutoff_day=la_path), life_g3, None, cache)
ok(r3["breakout"]["label_available_day_ge"] == "2025-07-05", "G3 的 la_ge=T3 首日")
life_unc = ("sz.000001", bo_d, None, dates[10], None, None, True, None)
ru = process_episode("L3", dict(PL, cutoff_day=la_path,
                                group_eventual="unknown_censored",
                                path_family="right_censored"), life_unc, None, cache)
ok(ru["breakout"]["label_uncertain"] is True and ru["breakout"]["label_available_day_ge"] is None,
   "删失/不确定→label_uncertain, la_ge=None")

# ── 3 准备期回调早于突破日 ──
pev = "000001_2025-06-20|000001_2025-06-26|000001_2025-07-03|000001_2025-07-10"
# bo=2025-06-27 → 有效 t2=2025-07-03
life_pb = ("sz.000001", bo_d, "2025-06-20", dates[10], None, "2025-08-20", False, pev)
rp = process_episode("L4", pl, life_pb, None, cache)
ok(rp["shrink"] is not None and rp["shrink"]["obs_day"] == "2025-07-03",
   f"t2_eff=突破后首个事件日(2025-07-03), got {rp['shrink'] and rp['shrink']['obs_day']}")
# 全部事件早于突破日 → 无 shrink 行
pev_pre = "000001_2025-06-20|000001_2025-06-26"
rn = process_episode("L5", pl, ("sz.000001", bo_d, "2025-06-20", dates[10],
                                None, "2025-08-20", False, pev_pre), None, cache)
ok(rn["shrink"] is None and rn["breakout"] is not None,
   "无突破后回调事件→不产 shrink 行(仅 breakout)")

# ── 4 非恒定复权因子: 除权日在观察窗内(bo 前), raw 跳空 -20%, F×1.25 补偿 ──
adj_day = dates[10]                                     # bo 之前的除权日
cache_adj = mkcache(dates, split_adj=(adj_day, 0.8, 1.25))
life_adj = ("sz.000001", bo_d, None, dates[5], None, "2025-08-20", False, None)
ra = process_episode("L6", pl, life_adj, None, cache_adj)
rb = process_episode("L6b", pl, life_adj, None, mkcache(dates))
ok(abs(ra["breakout"]["bo_cum20"] - rb["breakout"]["bo_cum20"]) < 1e-9,
   f"复权因子补偿后趋势特征不变(raw跳空被F抵消): {ra['breakout']['bo_cum20']} vs {rb['breakout']['bo_cum20']}")
# 反证: 不补偿(F恒1)时特征被除权扭曲
cache_raw = mkcache(dates, split_adj=(adj_day, 0.8, 1.0))
rr = process_episode("L6c", pl, life_adj, None, cache_raw)
ok(abs(rr["breakout"]["bo_cum20"] - rb["breakout"]["bo_cum20"]) > 1e-6,
   f"raw 跳空且无 F 补偿时特征被扭曲(对照): {rr['breakout']['bo_cum20']} vs {rb['breakout']['bo_cum20']}")

print(f"identify 日期门禁反例测试: {N} 项断言全部通过 ✓")
