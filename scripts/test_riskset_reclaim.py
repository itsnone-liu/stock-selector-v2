#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_riskset_reclaim.py — 风险集反例测试三例 (2026-09-21 P0 修正).

风险集判据 = 突破后首次 P_adj_close >= P_bo_adj(与 classify_path 同口径):
1 收复但无 T3: 第2日收盘 10.01>=10 → never 已不可能(known_negative),
   即便 reattack_days 为空
2 观察日当天首次收复: 当日收盘已收复 → 该观察日已非事前, 必须剔除
3 生命周期结束但 20 日内未收复: end_day<=obs 不构成 20 日结局已知
   (classify_path 依 20 日窗, 不以 end_day 为终点) → 单列 inactive 而非 known
"""
import sys
from pathlib import Path

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from build_identify_features import process_episode   # noqa: E402

N = 0


def ok(c, m):
    global N
    assert c, m
    N += 1


def mk(dates, base=10.0, path={}):
    """bo 当日收盘=base(anchor); path: {日: 收盘}; 其余日低于 anchor。"""
    u = {}
    for i, d in enumerate(dates):
        c = base if d == dates[0] else path.get(d, base * 0.96)
        u[d] = (c, c * 1.01, c * 0.99, c, 1e6)
    return (dates, u, {d: 1.0 for d in dates}, 0, {})


dates = [f"2025-06-{d:02d}" for d in range(3, 28)] + [f"2025-07-{d:02d}" for d in range(1, 29)]
bo_d = dates[0]
PL = {"cutoff_day": dates[20], "path_family": "x", "path_subtype": None, "D": "0", "E": "0",
      "D_atr": "1", "group_eventual": "G2", "group_asof_20d": "G2",
      "structure_broken_asof_20d": "False"}
life_base = ("sz.000001", bo_d, None, None, None, "2025-08-20", False, None)

# 基准: 全程低于 anchor → first_reclaim=None(never 事前风险集)
c0 = mk(dates)
r0 = process_episode("L0", dict(PL), life_base, None, c0)
ok(r0["breakout"]["first_reclaim_day"] is None, "未收复→None")

# 反例1: 收复但无 T3 —— 第2日收盘 10.01, reattack 空
c1 = mk(dates, path={dates[1]: 10.01})
r1 = process_episode("L1", dict(PL), life_base, None, c1)
fr = r1["breakout"]["first_reclaim_day"]
ok(fr == dates[1], f"首次收复日=第2日(reattack 空), got {fr}")

# 反例2: 观察日当天首次收复 —— shrink 观察日=dates[5], 当日收盘首次达 anchor
pev = "000001_" + dates[5]
c2 = mk(dates, path={dates[5]: 10.05})
r2 = process_episode("L2", dict(PL), ("sz.000001", bo_d, None, None, None,
                                      "2025-08-20", False, pev), None, c2)
ok(r2["shrink"]["obs_day"] == dates[5], "shrink 观察日=回调事件日")
ok(r2["breakout"]["first_reclaim_day"] == dates[5],
   "观察日当天首次收复: first_reclaim==obs_day → 判据 <= 剔除")

# 反例3: 生命周期结束但 20 日内未收复 —— end_day 在窗内, 收复未发生
c3 = mk(dates)
life_end = ("sz.000001", bo_d, None, None, None, dates[10], False, None)
r3 = process_episode("L3", dict(PL), life_end, None, c3)
ok(r3["breakout"]["first_reclaim_day"] is None,
   "end<=obs 但窗内未收复 → 非 reclaim_known; 归 lifecycle_inactive(单列)")

print(f"风险集收复反例测试: {N} 项断言全部通过 ✓")

# ── 统一资格函数断言(第八轮: 最终筛选, 非仅 first_reclaim 生成) ──
import gzip as _gz, csv as _csv
_rows = list(_csv.DictReader(_gz.open(
    ROOT / "output/research/posneg_v1/identify_shrink.csv.gz", "rt")))
from stock_selector.research.identify_features import eligibility_riskset as _elig
import sys as _s; _s.path.insert(0, str(ROOT / "src"))
_risk = [r for r in _rows if _elig(r)]
_n_ind = sum(1 for r in _rows if r["path_family"] != "right_censored"
             and r["obs_day"] < r["label_available_day_path"]
             and not (r["first_reclaim_day"] and r["first_reclaim_day"] not in ("", "None")
                      and r["first_reclaim_day"] <= r["obs_day"])
             and not (r["lifecycle_end_day"] and r["lifecycle_end_day"] not in ("", "None")
                      and r["lifecycle_end_day"] <= r["obs_day"]))
ok(len(_risk) == _n_ind, f"资格函数与独立实现一致({len(_risk)}=={_n_ind})")
ok(len(_risk) > 0, "shrink 活跃风险集非空")
print(f"统一资格函数断言 +2 | shrink 活跃风险集 {len(_risk)}")
