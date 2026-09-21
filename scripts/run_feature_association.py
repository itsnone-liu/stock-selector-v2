#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_feature_association.py — 量价特征与路径差异关联研究 (2026-09-21 任务书).

核心问题: 尚未确定结局的时点, 哪些可观察的价格结构/量能特征与随后
不同发展路径存在稳定关联? (解释研究, 非模型迭代)

冻结:
- 目标 path_binary: never_reclaim=正类; 其余已确定路径=负类; 右删失不作确定标签
- 风险集检查(超出 obs<cutoff 门禁): 观察日前已发生足以确定结局的事件
  → 单列「结局已知」不进事前分析:
  (a) reattack_first(突破后首个再上攻日) <= obs_day → never_reclaim 已不可能
  (b) end_day <= obs_day → 生命周期已终结
- 效应量: Cliff's delta(平均秩, tie 安全; >0=正类取值更大)
  日期块(breakout_day)有放回 bootstrap 1000, percentile 95% (seed 20260919)
- 连续变量不找切点; 缺失≠零(nan 保留, 缺失率单独报告)
- 提前量=冻结交易日历(TDX∩baostock)内 cutoff−obs 的交易日差, 分层 1-5/6-10/11-20
- 时间稳定性: 逐半年 b19-b22(按 obs_day 归桶)效应方向/大小/n
产出: IDENTIFY_FEATURE_ASSOCIATION.json + IDENTIFY_FEATURE_ASSOCIATION.md
边界: 开发期研究; 不生成选股排名/交易信号/仓位规则; 因子层人工核对例外保留。
"""
import csv
import glob
import gzip
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import duckdb
import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research.identify_features import eligibility_riskset  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts"))
OUT = ROOT / "output/research/posneg_v1"
SRC = ROOT / "data/adjustment_baostock/per_stock"
SEED, BOOT = 20260919, 1000

# 共线性组(同一现象的多个观测视角; 结果解读按组而非孤立特征)
GROUPS = {
    "回调深度": ["sh_dd_from_high", "st_rebound_from_low"],
    "支撑与相对位置": ["sh_support_dist", "sh_low_support_dist", "st_close_vs_bo"],
    "价格位置": ["bo_hlpos60", "hlpos60", "bo_ma_bias20", "ma_bias20", "bo_dist_high60"],
    "动能": ["bo_ret1", "st_ret1", "st_prev_ret1", "bo_cum5", "bo_cum10", "bo_cum20"],
    "量能": ["bo_rvol20", "rvol20", "bo_volratio5", "volratio5", "sh_volratio5",
             "bo_volratio20", "st_volrecover"],
    "波动结构": ["bo_atr14pct", "atr14pct", "st_lower_shadow"],
    "时序": ["prep_days", "sh_days_since_bo"],
}
FEATURES = {
    "breakout": ["bo_atr14pct", "bo_cum10", "bo_cum20", "bo_cum5", "bo_dist_high60",
                 "bo_hlpos60", "bo_ma_bias20", "bo_ret1", "bo_rvol20", "bo_volratio20",
                 "bo_volratio5", "prep_days"],
    "shrink": ["atr14pct", "hlpos60", "ma_bias20", "rvol20", "sh_days_since_bo",
               "sh_dd_from_high", "sh_low_support_dist", "sh_support_dist",
               "sh_volratio5", "volratio5"],
    "stabilization": ["st_close_vs_bo", "st_lower_shadow", "st_prev_ret1",
                      "st_rebound_from_low", "st_ret1", "st_volrecover"],
}


def load(ds):
    return list(csv.DictReader(gzip.open(OUT / f"identify_{ds}.csv.gz", "rt")))


def life_meta():
    """占位: 失活判定已用数据集 lifecycle_end_day 列(2026-09-21 第八轮)."""
    return None


def cliff_delta(x1, x0):
    """Cliff's delta (x1 vs x0), 平均秩法 tie 安全; >0 = x1 更大."""
    n1, n0 = len(x1), len(x0)
    if n1 == 0 or n0 == 0:
        return None
    allv = np.concatenate([x1, x0])
    s = np.sort(allv)
    left = np.searchsorted(s, allv, "left")
    right = np.searchsorted(s, allv, "right")
    ranks = (left + right + 1) / 2.0
    r1 = ranks[:n1].sum()
    u1 = r1 - n1 * (n1 + 1) / 2
    return float(2 * u1 / (n1 * n0) - 1)


def boot_ci(v, y, keys, seed_off):
    """日期块 bootstrap CI.

    修复(2026-09-21 自查): 块必须建在样本全集(正+负)上, 重抽样本后
    再按 y 拆分——原实现块仅建于正类索引导致负类错位抽取,
    点估计落在 CI 外暴露该缺陷。"""
    blocks = defaultdict(list)
    for i in range(len(v)):
        blocks[keys[i]].append(i)
    bk = list(blocks.values())
    rng = np.random.default_rng(SEED + seed_off)
    deltas = []
    for _ in range(BOOT):
        sel = np.concatenate([bk[rng.integers(len(bk))] for _ in range(len(bk))])
        yy = y[sel]
        d = cliff_delta(v[sel][yy == 1], v[sel][yy == 0])
        if d is not None:
            deltas.append(d)
    deltas = np.sort(np.array(deltas))
    return [float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))]


def feat_stat(vals, y, keys=None, seed_off=0):
    """单特征×一组样本 → 分布+效应量(+可选 CI)."""
    v = np.array(vals, dtype=float)
    m = ~np.isnan(v)
    n1, n0 = int(((y == 1) & m).sum()), int(((y == 0) & m).sum())
    rec = {"n_total": int(m.sum()), "n_pos": n1, "n_neg": n0,
           "miss_rate": float((~m).mean()),
           "miss_rate_pos": float((~m)[y == 1].mean()) if (y == 1).any() else None,
           "miss_rate_neg": float((~m)[y == 0].mean()) if (y == 0).any() else None}
    if n1 >= 30 and n0 >= 30:
        x1, x0 = v[(y == 1) & m], v[(y == 0) & m]
        for tag, xx in (("pos", x1), ("neg", x0)):
            rec[f"med_{tag}"] = float(np.median(xx))
            rec[f"p25_{tag}"] = float(np.percentile(xx, 25))
            rec[f"p75_{tag}"] = float(np.percentile(xx, 75))
        d = cliff_delta(x1, x0)
        rec["cliffs_delta"] = round(d, 4)
        rec["direction"] = ("正类更大" if d > 0 else "正类更小") if d is not None else None
        if keys is not None:
            vm, ym = v[m], y[m]
            kk = [keys[i] for i in range(len(v)) if m[i]]
            rec["cliffs_delta_dateblock_ci"] = [round(x, 4) for x in
                                                boot_ci(vm, ym, kk, seed_off)]
            lo, hi = rec["cliffs_delta_dateblock_ci"]
            rec["ci_excludes_zero"] = bool(lo > 0 or hi < 0)
    return rec


def main():
    t0 = time.time()
    # 冻结交易日历(per code, 复用 build 的 load_stock 需 F 因子表)
    from build_identify_features import load_stock
    F = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        for row in csv.DictReader(f):
            F.setdefault(row["code"], {})[row["date"]] = float(row["F"])
    cal_cache = {}

    def lead_td(code, obs, la):
        if code not in cal_cache:
            cal_cache[code] = set(load_stock(code, F)[0])
        cal = cal_cache[code]
        # 交易日差: 逐日推进计数(obs, la] 的交易日数
        import datetime as dt
        d0 = dt.date(*map(int, obs.split("-")))
        d1 = dt.date(*map(int, la.split("-")))
        n, d = 0, d0
        while d < d1:
            d += dt.timedelta(days=1)
            if d.isoformat() in cal:
                n += 1
        return n

    report = {"risk_set_check": {}, "datasets": {}, "method": {
        "target": "path_binary: never_reclaim=正类; 右删失排除",
        "risk_set": ("剔除 (a)reclaim_known_negative: first_reclaim_day<=obs_day(含当日,"
                     "P_adj_close>=P_bo_adj 与 classify_path 同口径)→never 已不可能; "
                     "(b)lifecycle_inactive: end_day<=obs_day 且未因收复剔除→不再属于活跃"
                     "生命周期(classify_path 依 20 日窗, end 不构成标签已知), 研究性单列"),
        "lead_unit": "冻结交易日历(TDX∩baostock)内 cutoff−obs 交易日差",
        "lead_bins": "1-5 / 6-10 / 11-20",
        "effect": "Cliff's delta(平均秩); 日期块 bootstrap 1000 percentile 95% seed 20260919",
        "collinearity_note": "结果按共线性组解读(回调深度/支撑位置/价格位置/动能/量能/波动/时序), 不孤立解释",
        "caveat": "开发期关联研究; 效应≠因果; 不构成交易规则/收益证明",
    }}
    for ds in ("breakout", "shrink", "stabilization"):
        rows = load(ds)
        risk, reclaim_neg, inactive = [], [], []
        n_pre = 0                                    # 独立资格计数(守恒对照)
        for r in rows:
            if r["path_family"] == "right_censored":
                continue
            if not (r["obs_day"] < r["label_available_day_path"]):
                continue
            n_pre += 1
            fr = r.get("first_reclaim_day")
            ed = r.get("lifecycle_end_day")
            if fr and fr <= r["obs_day"]:
                reclaim_neg.append(r)              # 已知负类(含观察日当日收复)
            elif ed and ed <= r["obs_day"]:
                inactive.append(r)                 # 活跃性排除(非标签已知)
            else:
                risk.append(r)
                # 与统一资格函数交叉核对(单一事实源)
                assert eligibility_riskset(r), f"风险集函数不一致: {r['lifecycle_id']}"
        n_all = len(risk) + len(reclaim_neg) + len(inactive)
        assert n_all == n_pre, f"守恒失败 {n_all} != 独立资格计数 {n_pre}"
        report["risk_set_check"][ds] = {
            "n_total_eligible": n_all, "n_risk_set": len(risk),
            "n_reclaim_known_negative": len(reclaim_neg),
            "n_lifecycle_inactive": len(inactive),
            "conservation": f"{n_all} == {len(risk)}+{len(reclaim_neg)}+{len(inactive)}"}
        y = np.array([1 if r["path_family"] == "never_reclaim" else 0 for r in risk])
        obk = np.array([(int(r["obs_day"][:4]) - 2015) * 2
                        + (0 if int(r["obs_day"][5:7]) <= 6 else 1) for r in risk])
        dkeys = [r["breakout_day"] for r in risk]
        leads = np.array([lead_td(r["code"], r["obs_day"],
                                  r["label_available_day_path"]) for r in risk])
        bins = {"1-5": (leads >= 1) & (leads <= 5),
                "6-10": (leads >= 6) & (leads <= 10),
                "11-20": (leads >= 11) & (leads <= 20)}
        cover = {"lead_min": int(leads.min()), "lead_p50": float(np.median(leads)),
                 "lead_max": int(leads.max()),
                 **{k: float(v.mean()) for k, v in bins.items()}}
        ds_rep = {"n_risk": len(risk),
                  "pos_rate": float(y.mean()), "lead_coverage": cover, "features": {}}
        for fi, feat in enumerate(FEATURES[ds]):
            vals = [r.get(feat, "") for r in risk]
            nums = [float(v) if v not in ("", "None") else np.nan for v in vals]
            m = np.array([not np.isnan(x) for x in nums])
            fr = {"overall": feat_stat(nums, y, dkeys, fi),
                  "by_halfyear": {}, "by_lead": {}}
            for tb in (19, 20, 21, 22):
                sel = obk == tb
                if sel.sum() >= 100:
                    sub = [np.nan] * len(nums)
                    for i in np.where(sel)[0]:
                        sub[i] = nums[i]
                    st = feat_stat(sub, y)
                    fr["by_halfyear"][str(tb)] = {k: st[k] for k in
                                                  ("n_total", "cliffs_delta", "direction")
                                                  if k in st}
            for bn, sel in bins.items():
                if sel.sum() >= 100:
                    sub = [np.nan] * len(nums)
                    for i in np.where(sel)[0]:
                        sub[i] = nums[i]
                    st = feat_stat(sub, y)
                    fr["by_lead"][bn] = {k: st[k] for k in
                                         ("n_total", "cliffs_delta", "direction") if k in st}
            ds_rep["features"][feat] = fr
            print(f"  {ds}/{feat}: δ={fr['overall'].get('cliffs_delta')}", flush=True)
        report["datasets"][ds] = ds_rep
        print(f"{ds}: 风险集 {len(risk)} | 收复已知负 {len(reclaim_neg)} | "
              f"失活单列 {len(inactive)} | {time.time()-t0:.0f}s", flush=True)
    (OUT / "IDENTIFY_FEATURE_ASSOCIATION.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(f"→ IDENTIFY_FEATURE_ASSOCIATION.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
