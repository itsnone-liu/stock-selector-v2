#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_coverage_precheck.py — 任务一 14 项检验逐折覆盖预检(2026-09-22 授权).

授权: 无结果变量参与(不读取 Y40 值做任何统计; 仅事件/股票/日期计数)。
目的(七轮复审前置条件): 阶段0 全样本覆盖 ≠ 训练折四分位下的逐折门槛;
先预检 14 项(C1-C12 格子 + C13/C14 同日截面秩相关)逐折可检验性,
多数不可检验则直接报告识别能力不足, 不运行完整统计流程。

口径:
- 折: v1 FOLDS b19-b22; 测试折=obs_bucket==f 事件; 训练折四分位=obs_bucket<f
  (简化口径: 正式实现按 v1 label_avail_day<fold_start STRICT 完整划分重算,
  并在主运行时断言与本预检差异——若主实现覆盖更低, 以主实现为准重判)
- C1-C12 配对日: 同日条件组≥10 只不同股票 且 同日其余合格≥10 只不同股票,
  才计 1 个配对日; 每折配对日≥10 且 折测试组事件≥50 → 可检验
- C13/C14 截面日: 每日≥10 只不同股票 且 该特征当日秩有变化(非全并列);
  每折有效截面日≥10 → 可检验(无组事件门槛)
- 格子: price_vs_monthly_ma6 四分位(训练折边界, 逐折)× wk_up_streak 档(0/1/2+)
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "scripts"))
from forward_y40_lib import build_events, obs_bucket  # noqa: E402
from run_forward_y40_association import FOLDS  # noqa: E402
from run_condition_stage0_audit import monthly_states, weekly_states  # noqa: E402
import multiperiod_lib as _mpl  # noqa: E402
from multiperiod_lib import load_price_series  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"


def main():
    t0 = time.time()
    rows = build_events("breakout")[0]
    # 特征重算(纯价格; 不触 Y40)
    by_code = defaultdict(set)
    for e in rows:
        by_code[e["code"]].add(e["obs_day"])
    feats = {}
    for code, days in by_code.items():
        try:
            closes = load_price_series(code)
        except FileNotFoundError:
            closes = {}
        for d in days:
            mo = monthly_states(closes, d)
            we = weekly_states(closes, d)
            feats[(code, d)] = (mo.get("price_vs_monthly_ma6"),
                                we.get("wk_up_streak"))
    print(f"特征重算完成 {len(rows)} | {time.time()-t0:.0f}s", flush=True)
    assert _mpl._FACTOR_SKIP_COUNT == 0, "复权因子缺失(应=0)"  # 经模块对象读当前值, 非 import 时快照

    ev = []
    for e in rows:
        pm, us = feats[(e["code"], e["obs_day"])]
        ev.append({"code": e["code"], "day": e["obs_day"],
                   "fold": obs_bucket(e["obs_day"]), "pm": pm, "us": us})

    res = {"precheck": "MULTIPERIOD_CONDITION_COVERAGE_PRECHECK",
           "date": "2026-09-22", "y40_read": False,
           "fold_def": "test=obs_bucket==f; 训练四分位=obs_bucket<f(简化口径, 见 docstring)",
           "rules": {"C1_12": "配对日=同日双侧≥10 不同股票; 折≥10 配对日且 组事件≥50",
                     "C13_14": "截面日=每日≥10 股且特征秩有变化; 折≥10 截面日"},
           "items": {}}
    n_ok = 0
    for f in FOLDS:
        test = [e for e in ev if e["fold"] == f and e["pm"] is not None]
        train_pm = [e["pm"] for e in ev if e["fold"] < f and e["pm"] is not None]
        q = np.percentile(train_pm, [25, 50, 75])
        for e in test:
            e["q"] = ("q1" if e["pm"] <= q[0] else "q2" if e["pm"] <= q[1]
                      else "q3" if e["pm"] <= q[2] else "q4")
        # C1-C12
        for qi in ("q1", "q2", "q3", "q4"):
            for st in ("0", "1", "2+"):
                grp = [e for e in test if e["q"] == qi and
                       (st == "2+" if e["us"] is not None and e["us"] >= 2
                        else e["us"] is not None and str(int(e["us"])) == st)]
                # 同日双侧计数
                day_g = defaultdict(set)
                day_o = defaultdict(set)
                gset = {(e["code"], e["day"]) for e in grp}
                for e in test:
                    if (e["code"], e["day"]) in gset:
                        day_g[e["day"]].add(e["code"])
                    else:
                        day_o[e["day"]].add(e["code"])
                paired = sum(1 for d in day_g
                             if len(day_g[d]) >= 10 and len(day_o.get(d, ())) >= 10)
                ok = paired >= 10 and len(grp) >= 50
                res["items"][f"C_{f}_{qi}|{st}"] = {
                    "n_group": len(grp), "paired_days_min10both": paired,
                    "testable": bool(ok)}
                if ok:
                    n_ok += 1
        # C13/C14
        for cname, key in (("pm", "pm"), ("us", "us")):
            byday = defaultdict(list)
            for e in test:
                if e[key] is not None:
                    byday[e["day"]].append((e[key], e["code"]))
            ndays = 0
            for d, lst in byday.items():
                codes = {c for _, c in lst}
                vals = [v for v, _ in lst]
                if len(codes) >= 10 and len(set(np.round(vals, 9))) > 1:
                    ndays += 1
            ok = ndays >= 10
            res["items"][f"C_{f}_{cname}"] = {"valid_crosssection_days": ndays,
                                              "testable": bool(ok)}
            if ok:
                n_ok += 1
        print(f"fold {f}: 完成 | {time.time()-t0:.0f}s", flush=True)
    # 14 项级别汇总: 一项可检验=至少一折可检验? 否——冻结方案为折合并推断,
    # 任一折覆盖失败即不可检验(p=1)。逐项判定: 全部四折 testable 才 testable。
    item_names = sorted({k.rsplit("_", 1)[0] for k in res["items"]} | set())
    # 重新聚合(上面 key 形如 C_b19_q1|0 / C_b19_pm)
    agg = {}
    for k, v in res["items"].items():
        fold, name = k[2:].split("_", 1)
        agg.setdefault(f"C_{name}", {})[fold] = v["testable"]
    final = {}
    for name, folds in agg.items():
        final[name] = {"folds_testable": folds,
                       "testable": all(folds.values())}
    res["final_14"] = final
    n_final = sum(1 for v in final.values() if v["testable"])
    res["n_testable_final"] = n_final
    res["verdict"] = ("识别能力不足(可检验项 %d/14)——不运行完整统计流程" % n_final
                      if n_final < 8 else
                      "可检验项 %d/14——按冻结方案进入主检验(待批准)" % n_final)
    (OUT / "MULTIPERIOD_CONDITION_COVERAGE_PRECHECK.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1))
    print(f"可检验(全四折): {n_final}/14 | {res['verdict']}", flush=True)
    print(f"→ MULTIPERIOD_CONDITION_COVERAGE_PRECHECK.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
