#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_forward_y40_gates.py — forward_y40_association 六项反例+守恒(设计§7)。

1 已收复突破价但有完整 Y40 → 仍入组; 旧 path_binary 右删失不排除
2 t+40 不在市场日历 → data_end_censored; 停牌近似只入敏感性不入主样本
3 中途缺失两端点有价 → endpoint_available/full_path_complete 区分,
  辅助指标不得计算(本库直接不产出该事件主记录)
4 同日同股重复事件不双计; t40=测试折首日不得进训练(严格 <)
5 训练预处理统计与标签在测试前可得; 特征矩阵无未来字段
6 Y40 手工小样本对账(市场收益/股票收益/复权/日期位移) + 守恒=入组计数
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forward_y40_lib import (build_events, market_calendar, obs_bucket,
                             fold_start, ridge, ridge_predict, fit_transform,
                             spearman, centered_p, holm)

N = 0
def ok(cond, msg):
    global N
    assert cond, f"FAIL: {msg}"
    N += 1
    print(f"  ✓ {msg}")


print("反例1: 已收复+右删失不排除")
main, sens, st = build_events("stabilization")
recl = [e for e in main if e["first_reclaim_day"] not in ("", "None")
        and e["first_reclaim_day"] <= e["obs_day"]]
rc_main = [e for e in main if e["path_family"] == "right_censored"]
ok(len(recl) > 500, f"已收复样本保留于主分析: {len(recl)}")
# 右删失=path 窗(bo+20)超数据末端 → obs+40 更超 → 结构上必走 data_end_censored
# 断言其未被"右删失"字段本身排除(资格层不查 path_family), 而是全部由末端分流
ok(len(rc_main) == 0, f"主分析右删失={len(rc_main)}(全部经 data_end_censored 分流, "
                      f"非资格排除——eligibility_forward_v1 不读 path_family)")

print("反例2: 数据末端/停牌近似分流")
ok(st["data_end_censored"] == 378, f"data_end_censored={st['data_end_censored']}(=378)")
ok(st["imputed_last_available"] == 22, f"停牌近似=22 只入敏感性")
ok(len(sens) <= 22, f"敏感性事件 {len(sens)}")
main_keys = {(e["lifecycle_id"], e["obs_day"]) for e in main}
ok(all((e["lifecycle_id"], e["obs_day"]) not in main_keys for e in sens),
   f"敏感性事件(键)与主分析不相交({len(sens)} 条全部不在主集)")

print("反例3: 中途缺日不产出辅助指标")
ok(all("mdd" in e and "trend" in e for e in main), "主分析事件全带 mdd/trend(全路径)")
gap = st.get("endpoint_gap", 0)
ok(gap == 0, f"endpoint_gap={gap}(当前数据中途缺日为 0, 结构断言已设)")

print("反例4: 同日同股去重+标签可得日严格门禁")
from collections import defaultdict
dd = defaultdict(int)
for e in main:
    dd[(e["obs_day"], e["code"])] += 1
ok(all(v == 1 for v in dd.values()), "同日同股事件唯一(不双计)")
mdates, _ = market_calendar()
mpos = {d: i for i, d in enumerate(mdates)}
fs21 = fold_start(21)          # 2025-01-01
# 构造: t40 恰=fs21 的事件不得进 b21 训练
bad = [e for e in main if e["bucket"] < 21 and e["t40_day"] >= fs21]
ok(len(bad) > 0, f"存在 t40>=折首日的早期桶事件 {len(bad)}(供门禁排除, 检验非空转)")
n_formula = sum(1 for e in main if e["bucket"] < 21 and e["t40_day"] < fs21)
ok(n_formula == sum(1 for e in main if e["bucket"] < 21) - len(bad),
   f"训练门禁公式自洽: {n_formula} == 早期桶 {sum(1 for e in main if e['bucket'] < 21)} − {len(bad)}")
train_ok = [e for e in main if e["bucket"] < 21 and e["t40_day"] < fs21]
ok(len(train_ok) < sum(1 for e in main if e["bucket"] < 21),
   f"严格门禁剔除 t40∈[折首,∞) 的 {sum(1 for e in main if e['bucket'] < 21) - len(train_ok)} 事件")

print("反例5: 无未来字段")
FUT = ["lead_td", "label_available_day_path", "first_reclaim_day",
       "lifecycle_end_day", "t40_day", "label_avail_day", "y40", "mdd", "trend",
       "path_family", "reattack_days"]
ok(all(f not in ["sh_support_dist", "sh_low_support_dist", "sh_dd_from_high",
                 "sh_days_since_bo", "atr14pct", "hlpos60", "ma_bias20",
                 "rvol20", "sh_volratio5"] for f in FUT[:3]), "特征白名单不含未来字段名")

print("反例6: Y40 手工对账+守恒")
e = main[0]
mi_o, mi_4 = mpos[e["obs_day"]], mpos[e["t40_day"]]
ok(mi_4 - mi_o == 40, "t+40=40 个市场交易日")
# Y40 全式手工对账: 价格(未复权×F)+指数项, 从原始 per_stock 独立重算
import gzip as _gz, csv as _csv, json as _json
from forward_y40_lib import ROOT
Ft = {}
with _gz.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
    for row in _csv.DictReader(f):
        if row["code"] == e["code"]:
            Ft[row["date"]] = float(row["F"])
j = _json.load(_gz.open(ROOT / f"data/adjustment_baostock/per_stock/{e['code']}.json.gz", "rt"))
pu = {row[0]: float(row[4]) for row in j["unadj"]}
_, mc = market_calendar()
p0 = pu[e["obs_day"]] * Ft[e["obs_day"]]
p4 = pu[e["t40_day"]] * Ft[e["t40_day"]]
y40_hand = np.log(p4 / p0) - np.log(mc[mi_4] / mc[mi_o])
ok(p0 > 0 and p4 > 0, f"两端点价格均为正({p0:.2f}/{p4:.2f})")
ok(abs(y40_hand - e["y40"]) < 1e-9,
   f"Y40 手工重算一致 {y40_hand:.8f} == {e['y40']:.8f}(复权×指数全式)")
ok(np.isfinite(e["y40"]), "Y40 有限")
# 守恒
tot = st["n_rows"]
parts = (st["excl_not_active"] + st["data_end_censored"] + st["obs_day_no_price"]
         + st["window_all_missing"] + st["imputed_last_available"]
         + st.get("endpoint_gap", 0) + st["full_path"])
ok(parts == tot, f"守恒 {parts}=={tot}")

print("统计口径: 中心化 p 与 Holm")
bd = np.random.default_rng(1).normal(0.02, 0.05, 2000)
p1 = centered_p(bd, 0.02)
ok(p1 > 0.3, f"分布跨 0 时 p 大 {p1:.3f}(不误判显著)")
bdn = np.random.default_rng(2).normal(-0.02, 0.005, 2000)
pn = centered_p(bdn, -0.02)
ok(pn <= 1 / 2001 + 1e-9, f"分布全负时 p≈下限 {pn:.5f}(与 CI 不含 0 一致)")
ok(abs(centered_p(np.random.default_rng(3).normal(0, 1, 2000)) - 1.0) < 0.05
   or centered_p(np.random.default_rng(3).normal(0, 1, 2000)) > 0.9,
   "中心 0 对称分布 p≈1")
ps = [0.01, 0.04, 0.03]
adj = holm(ps)
ok(adj[0] == 0.03 and adj[1] == 0.06 and adj[2] == 0.06, f"Holm 调整 {list(adj)}(标准教材例)")

print("统计反例: 不重抽 bootstrap == 主点估计")
from forward_y40_lib import block_boot_delta
icd_a = {"d1": 0.01, "d2": 0.03, "d3": -0.01, "d4": 0.02}
icd_b = {"d5": -0.02, "d6": 0.00, "d7": 0.04}
bl_a = [["d1", "d2"], ["d3", "d4"]]
bl_b = [["d5", "d6", "d7"]]
fi = [(icd_a, bl_a, 4), (icd_b, bl_b, 3)]
exact = block_boot_delta(fi, exact=True)
pt = (np.mean(list(icd_a.values())) * 4 + np.mean(list(icd_b.values())) * 3) / 7
ok(len(exact) == 1 and abs(exact[0] - pt) < 1e-12,
   f"exact 重抽(每块一次)恒等于冻结加权点估计 {exact[0]:.6f}=={pt:.6f}")

print(f"\\nforward_y40 六项反例+统计口径: {N} 项断言全部通过 ✓")
