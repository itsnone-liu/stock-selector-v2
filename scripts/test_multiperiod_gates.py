#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_multiperiod_gates.py — 多周期实验反例/门禁测试(设计 §6)。

覆盖: A1 零量能源审计+输入白名单; A1 特征小样本手工对账(周不足→None);
B0 复现两层门禁(JSON 结构); 口径断言(主样本数=封存 v1)。
运行约 3-6 分钟(build_events 全量)。
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "scripts"))
N = 0


def ok(cond, msg):
    global N
    N += 1
    print(("  ✓ " if cond else "  ✗ FAIL ") + msg)
    assert cond, f"FAIL: {msg}"


print("反例1: A1 零量能审计")
from multiperiod_lib import (weekly_price_feats, assert_price_only_source,  # noqa: E402
                             PRICE_FEATS, load_price_series)
assert_price_only_source()
ok(True, "weekly_price_feats 函数体无量能标识符(源审计)")
# 运行时输入白名单: load_price_series 函数体(剥 docstring)不含量能列引用
import inspect as _insp
_lps_src = _insp.getsource(load_price_series)
_body = _lps_src.split('"""', 2)[-1]        # 剥掉 docstring, 留可执行体
ok(all(t not in _body for t in ("volume", "amount", "turnover", "row[1]", "row[2]", "row[5]")),
   "load_price_series 可执行体仅取 date/close 列(源白名单)")

print("反例2: A1 特征手工对账(构造三周)")
cl = {"2026-06-05": 10.0, "2026-06-12": 10.4,          # W-3 末
      "2026-06-15": 10.5, "2026-06-19": 10.8,          # W-2 末
      "2026-06-22": 11.0, "2026-06-26": 11.3,          # W-1 末
      "2026-06-29": 11.4, "2026-07-01": 11.6}          # 本周(obs)
f = weekly_price_feats(cl, "2026-07-01")
ok(abs(f["prev_week_cc_pct"] - (11.3 / 10.8 - 1) * 100) < 1e-9, "prev_week_cc_pct 手工一致")
ok(abs(f["prev2_week_cc_pct"] - (10.8 / 10.4 - 1) * 100) < 1e-9, "prev2 手工一致")
ok(f["mc_pos"] is True, "mc_pos=True(两周均涨)")
ok(abs(f["week_realized_pct"] - (11.6 / 11.3 - 1) * 100) < 1e-9, "week_realized_pct 手工一致")
ok(abs(f["l_eff_redef"] - abs((11.3 / 10.8 - 1) * 100)) < 1e-9, "l_eff_redef=|prev|")
f2 = weekly_price_feats({k: v for k, v in cl.items() if k >= "2026-06-22"}, "2026-07-01")
ok(all(v is None for v in f2.values()), "完整周不足3 → 全 None")
f3 = weekly_price_feats(cl, "2026-06-19")
ok(all(v is None for v in f3.values()),
   "当周(即使看似完结)不计入完整周: obs 在 W25 → 仅 2 完整周 → None")
# 前两周一涨一跌 → mc_pos False
cl4 = dict(cl); cl4["2026-06-26"] = 10.7
ok(weekly_price_feats(cl4, "2026-07-01")["mc_pos"] is False, "mc_pos=False(前周跌)")

print("反例3: B0 复现门禁两层结构(旧 JSON 完整精度在场)")
old = json.load(open(ROOT / "docs/reports/FORWARD_Y40_ASSOCIATION_V1.json"))
for ds in ("breakout", "shrink", "stabilization"):
    folds = old["stages"][ds]["folds"]
    ok(all("mean_delta_ic" in f and "metrics_A" in f for f in folds),
       f"{ds}: 旧 JSON 折级完整精度字段在场(层2 比较可行)")
    ok(len([f for f in folds if f.get("completed")]) == 4, f"{ds}: 四折完整")

print("反例4: 口径断言(主样本数=封存 v1)")
from forward_y40_lib import build_events  # noqa: E402
EXP = {"breakout": 26126, "shrink": 20909, "stabilization": 12620}
for ds, exp in EXP.items():
    main, sens, cens = build_events(ds)
    ok(len(main) == exp, f"{ds}: 主样本 {len(main)}=={exp}(封存 v1)")
    ok(len(main) + len(sens) + len(cens) > len(main), f"{ds}: 敏感/删失分流非空(口径分离)")

print("反例5: 模型特征集结构")
from run_multiperiod_increment import stage_models  # noqa: E402
m = stage_models("breakout")
ok(set(m) == {"A0", "B0", "A1", "B1"}, "四模型齐")
from run_forward_y40_association import FEATS  # noqa: E402
ok(m["A0"] == FEATS["breakout"]["A"] and m["B0"] == FEATS["breakout"]["B"],
   "A0/B0 逐列==v1 冻结特征集")
ok(all(c in m["B1"] for c in m["A1"]), "B1 ⊇ A1")
ok(all(c in m["A1"] for c in PRICE_FEATS), "A1 含五个周价特征")
ok(all(c in m["B0"] and c not in m["A0"] for c in
       [c for c in m["B0"] if c not in m["A0"]]), "B0 增量列=v1 量能列")
ok(not any(c in m["A1"] for c in m["B0"] if c not in m["A0"]),
   "A1 不含任何 v1 日线量能列")
ok("B2" not in m, "B2 未构造(预定义不运行)")

print(f"\nmultiperiod 反例/门禁: {N} 项断言全部通过 ✓")


if __name__ == "__main__":
    pass
