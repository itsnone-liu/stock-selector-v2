#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_forward_y40_association.py — 连续 Y40 下的量能独立信息主实验
(设计 FORWARD_Y40_ASSOCIATION_DESIGN_V1, ff8426e 冻结; 执行授权 2026-09-21)。

主检验: ΔIC = IC_B − IC_A(同日横截面 Spearman, A=价格/波动/时序,
B=A+量能列), Ridge alpha=1.0 不调参, 折 b19-b22, 训练标签可得日
(=t+40 市场日)严格早于折首日。
推断: 40 连续交易日块 bootstrap(主) + 股票块(敏感性); 零假设中心
双侧 p(平移法); 三阶段 Holm。辅助: 逐折 MSE/MAE/R²_oos。
边界: 开发期; 非因果; 非收益证明; 不调 alpha 不换特征不挑时点。
"""
import json
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from forward_y40_lib import (build_events, obs_bucket, fold_start, ridge,
                             ridge_predict, fit_transform, spearman,
                             cont_40d_blocks, block_boot_delta, centered_p, holm,
                             H, SEED, BOOT, MIN_TRAIN, MIN_TEST)

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/posneg_v1"

FEATS = {
    "breakout": {
        "A": ["bo_ret1", "bo_cum5", "bo_cum10", "bo_cum20", "bo_ma_bias20",
              "bo_hlpos60", "bo_dist_high60", "bo_atr14pct", "bo_rvol20", "prep_days"],
        "B": ["bo_ret1", "bo_cum5", "bo_cum10", "bo_cum20", "bo_ma_bias20",
              "bo_hlpos60", "bo_dist_high60", "bo_atr14pct", "bo_rvol20", "prep_days",
              "bo_volratio5", "bo_volratio20"]},
    "shrink": {
        "A": ["sh_support_dist", "sh_low_support_dist", "sh_dd_from_high",
              "sh_days_since_bo", "atr14pct", "hlpos60", "ma_bias20", "rvol20"],
        "B": ["sh_support_dist", "sh_low_support_dist", "sh_dd_from_high",
              "sh_days_since_bo", "atr14pct", "hlpos60", "ma_bias20", "rvol20",
              "sh_volratio5"]},
    "stabilization": {
        "A": ["st_close_vs_bo", "st_ret1", "st_prev_ret1", "st_rebound_from_low",
              "st_lower_shadow", "atr14pct", "hlpos60", "ma_bias20", "rvol20"],
        "B": ["st_close_vs_bo", "st_ret1", "st_prev_ret1", "st_rebound_from_low",
              "st_lower_shadow", "atr14pct", "hlpos60", "ma_bias20", "rvol20",
              "st_volrecover"]},
}
FOLDS = (19, 20, 21, 22)


def run_stage(ds):
    main, sens, st = build_events(ds)
    y_all = np.array([e["y40"] for e in main])
    codes = [e["code"] for e in main]
    days = [e["obs_day"] for e in main]
    res = {"conservation": st, "folds": [], "sensitivity_note":
           f"停牌近似 {len(sens)} 事件仅敏感性(不混入主分析; 报告于 JSON 尾部)"}
    per_fold_delta = []      # (dict date->ΔIC_d, 折权重=有效日期数)
    sens_scores = []
    for tb in FOLDS:
        ts = fold_start(tb)
        tr_idx = [i for i, e in enumerate(main)
                  if e["bucket"] < tb and e["label_avail_day"] < ts]
        te_idx = [i for i, e in enumerate(main) if e["bucket"] == tb]
        fold_rec = {"test_bucket": tb, "n_train": len(tr_idx), "n_test": len(te_idx)}
        if len(tr_idx) < MIN_TRAIN or len(te_idx) < MIN_TEST:
            fold_rec.update({"completed": False,
                             "skip_reason": f"n_train={len(tr_idx)}<200 或 n_test={len(te_idx)}<50"})
            res["folds"].append(fold_rec)
            continue
        fold_rec["completed"] = True
        models, preds = {}, {}
        for tag in ("A", "B"):
            fl = FEATS[ds][tag]
            X = np.array([[float(e[c]) if e.get(c, "") not in ("", "None") else np.nan
                           for c in fl] for e in main])
            Ztr, Zte, allmiss = fit_transform(X[tr_idx], X[te_idx])
            ytr = y_all[tr_idx]
            m = ridge(Ztr, ytr)
            s_te = ridge_predict(m, Zte)
            models[tag], preds[tag] = m, s_te
            fold_rec[f"metrics_{tag}"] = {
                "mse": float(np.mean((s_te - y_all[te_idx]) ** 2)),
                "mae": float(np.mean(np.abs(s_te - y_all[te_idx]))),
                "r2_oos": float(1 - np.mean((s_te - y_all[te_idx]) ** 2)
                                / np.mean((ytr.mean() - y_all[te_idx]) ** 2))}
            if allmiss:
                fold_rec.setdefault("all_missing_cols", {})[tag] = allmiss
        # 同日横截面 IC
        by_date = defaultdict(list)
        for k, i in enumerate(te_idx):
            by_date[days[i]].append(i)
        icA, icB, icd = {}, {}, {}
        te_pos = {i: k for k, i in enumerate(te_idx)}
        for d, idxs in by_date.items():
            if len(idxs) < 10:
                continue
            kk = np.array([te_pos[i] for i in idxs])
            a = spearman(y_all[np.array(idxs)], preds["A"][kk])
            b = spearman(y_all[np.array(idxs)], preds["B"][kk])
            if a is not None and b is not None:
                icA[d], icB[d], icd[d] = a, b, b - a
        fold_rec.update({"n_valid_days": len(icd),
                         "mean_ic_A": float(np.mean(list(icA.values()))) if icA else None,
                         "mean_ic_B": float(np.mean(list(icB.values()))) if icB else None,
                         "mean_delta_ic": float(np.mean(list(icd.values()))) if icd else None})
        res["folds"].append(fold_rec)
        if icd:
            per_fold_delta.append((icA, icB, icd))
        sens_scores.append((te_idx, preds))
    # 总体: 折有效日期数冻结加权
    tot_w = sum(len(fd[2]) for fd in per_fold_delta)
    if tot_w == 0:
        res["primary"] = {"status": "无法评估(无有效交易日)"}
        return res, None
    point = sum(np.mean(list(fd[2].values())) * len(fd[2])
                for fd in per_fold_delta) / tot_w
    # 40 日块 bootstrap(主, 复审修正: 折内独立重抽+原始 w_f 加权)
    fold_icd = [(fd[2], cont_40d_blocks(sorted(fd[2])), len(fd[2]))
                for fd in per_fold_delta]
    n_blocks_total = sum(len(b) for _, b, _ in fold_icd)
    boot = block_boot_delta(fold_icd)
    ci = [float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))]
    p = centered_p(boot, point)
    res["primary"] = {
        "weighted_delta_ic_point": round(float(point), 5),
        "n_time_blocks": n_blocks_total, "n_valid_days": tot_w,
        "time_block_ci95": [round(x, 5) for x in ci],
        "time_block_p_centered": round(float(p), 5),
        "ci_excludes_zero": bool(ci[0] > 0 or ci[1] < 0)}
    return res, (boot, point)


def stock_block_sens(ds, res):
    """股票块重抽敏感性: 重抽股票→重复抽中去重(强度低估方向)→重算日 IC。"""
    main, _, _ = build_events(ds)
    y = np.array([e["y40"] for e in main])
    # 需要重训? 设计§6.2: 不含重训不确定性 → 用主实验冻结预测? 此处独立简单重跑折内预测代价高;
    # 按设计: 重算每日横截面 IC 用同一冻结模型分数 —— 实现上保存折内全测试事件分数
    # 为控制复杂度: 重用主实验分数需重构; 采用等价实现: 在本函数内重训同折同特征(确定性相同)
    by_stock = defaultdict(list)
    for i, e in enumerate(main):
        by_stock[e["code"]].append(i)
    stocks = list(by_stock)
    rng = np.random.default_rng(SEED + 7)
    pts = []
    counts_dist = []
    FOLDS = (19, 20, 21, 22)
    preds_all = {"A": np.full(len(main), np.nan), "B": np.full(len(main), np.nan)}
    for tb in FOLDS:
        ts = fold_start(tb)
        tr = [i for i, e in enumerate(main) if e["bucket"] < tb and e["label_avail_day"] < ts]
        te = [i for i, e in enumerate(main) if e["bucket"] == tb]
        if len(tr) < 200 or len(te) < 50:
            continue
        for tag in ("A", "B"):
            X = np.array([[float(e[c]) if e.get(c, "") not in ("", "None") else np.nan
                           for c in FEATS[ds][tag]] for e in main])
            Ztr, Zte, _ = fit_transform(X[tr], X[te])
            m = ridge(Ztr, y[tr])
            preds_all[tag][te] = ridge_predict(m, Zte)
    days = [e["obs_day"] for e in main]
    base_days = sorted({days[i] for i in range(len(main)) if not np.isnan(preds_all["A"][i])})
    sk = np.array(stocks)
    # 频数权重版(2026-09-21 复审修正): 保留每股票抽中次数 k,
    # 该股记录在当日秩相关中计 k 次(复制展开=加权秩相关标准展开);
    # 同日门槛按**不同证券数**(去重后)判断 ≥10
    for _ in range(BOOT):
        cnt = defaultdict(int)
        for _ in range(len(stocks)):
            cnt[sk[rng.integers(len(sk))]] += 1
        dd = defaultdict(list)
        dd_codes = defaultdict(set)
        for s_, k in cnt.items():
            for i in by_stock[s_]:
                if not np.isnan(preds_all["A"][i]):
                    dd[days[i]].extend([i] * k)
                    dd_codes[days[i]].add(s_)
        deltas = []
        for d, ix in dd.items():
            if len(dd_codes[d]) < 10:
                continue
            ix = np.array(ix)
            a = spearman(y[ix], preds_all["A"][ix])
            b = spearman(y[ix], preds_all["B"][ix])
            if a is not None and b is not None:
                deltas.append(b - a)
        if deltas:
            pts.append(float(np.mean(deltas)))
        counts_dist.append(sum(1 for v in cnt.values() if v > 1))
    pts = np.array(pts)
    return {"n_stock_blocks": len(stocks), "n_draws_valid": len(pts),
            "stock_ci95": [round(float(np.percentile(pts, 2.5)), 5),
                           round(float(np.percentile(pts, 97.5)), 5)],
            "mean_dup_stock_per_draw": round(float(np.mean(counts_dist)), 1),
            "note": ("频数权重版: 抽中 k 次的股票记录计 k 次(加权秩相关展开); "
                     "同日门槛按不同证券数; 不含重训不确定性。"
                     "v1 去重版区间已撤回(superseded, 见 v1 提交)")}


def sensitivity_imputed(ds):
    """停牌近似事件敏感性(设计§2.3): 并入测试折重算 ΔIC, 报告与主分析差。"""
    main, sens, _ = build_events(ds)
    all_e = main + sens
    y = np.array([e["y40"] for e in all_e])
    res = {"n_sens": len(sens)}
    per_fold = []
    for tb in FOLDS:
        ts = fold_start(tb)
        tr = [i for i, e in enumerate(all_e)
              if e["bucket"] < tb and e["label_avail_day"] < ts and i < len(main)]
        te = [i for i, e in enumerate(all_e) if e["bucket"] == tb]
        te_main = [i for i in te if i < len(main)]
        if len(tr) < MIN_TRAIN or len(te_main) < MIN_TEST:
            continue
        preds = {}
        for tag in ("A", "B"):
            X = np.array([[float(e[c]) if e.get(c, "") not in ("", "None") else np.nan
                           for c in FEATS[ds][tag]] for e in all_e])
            Ztr, Zte, _ = fit_transform(X[tr], X[te])
            m = ridge(Ztr, y[tr])
            preds[tag] = ridge_predict(m, Zte)
        te_pos = {i: k for k, i in enumerate(te)}
        by_date = defaultdict(list)
        for i in te:
            by_date[all_e[i]["obs_day"]].append(i)
        icd = {}
        for d, idxs in by_date.items():
            if len(idxs) < 10:
                continue
            kk = np.array([te_pos[i] for i in idxs])
            a = spearman(y[np.array(idxs)], preds["A"][kk])
            b = spearman(y[np.array(idxs)], preds["B"][kk])
            if a is not None and b is not None:
                icd[d] = b - a
        if icd:
            per_fold.append((icd, len(icd)))
    if per_fold:
        tot = sum(n for _, n in per_fold)
        res["delta_ic_with_imputed"] = round(float(sum(
            np.mean(list(icd.values())) * n for icd, n in per_fold) / tot), 5)
    return res


def main():
    t0 = time.time()
    head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True,
                          text=True, cwd=ROOT).stdout.strip()
    report = {"design": "FORWARD_Y40_ASSOCIATION_DESIGN_V1.md(ff8426e)",
              "code_head": head, "seed": SEED, "boot": BOOT,
              "model": "Ridge alpha=1.0(闭式, 截距不惩罚), 不调参",
              "primary_question": "ΔIC=IC_B−IC_A 同日横截面 Spearman",
              "stages": {}, "holm": {}, "guard": [
                  "开发期; 非因果; 非收益证明; 现有 5240 股票库(存活偏差)",
                  "IC 只检验选股排序(同日基准收益为常数), 不证明跑赢基准或正收益",
                  "bootstrap 推断为近似; 时间块数量有限可能不稳定",
                  "CI 跨 0 ≠ 证实没有信息"]}
    pvals = {}
    for ds in ("breakout", "shrink", "stabilization"):
        res, extra = run_stage(ds)
        if extra:
            boot, point = extra
            pvals[ds] = res["primary"]["time_block_p_centered"]
        print(f"{ds}: " + json.dumps(res.get("primary", {}), ensure_ascii=False)[:200],
              flush=True)
        report["stages"][ds] = res
    # Holm(三比较)
    if pvals:
        ks = list(pvals)
        adj = holm([pvals[k] for k in ks])
        report["holm"] = {"raw_p": {k: pvals[k] for k in ks},
                          "holm_adj_p": {k: round(float(a), 5) for k, a in zip(ks, adj)},
                          "method": "40 日时间块 bootstrap 零假设中心双侧 p(平移,+1 修正); Holm 三比较"}
    for ds in ("breakout", "shrink", "stabilization"):
        t1 = time.time()
        report["stages"][ds]["stock_block_sensitivity"] = stock_block_sens(ds, report)
        report["stages"][ds]["imputed_sensitivity"] = sensitivity_imputed(ds)
        print(f"{ds} 股票块+停牌敏感性完成 | {time.time()-t1:.0f}s", flush=True)
    (OUT / "FORWARD_Y40_ASSOCIATION_V1.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(f"→ FORWARD_Y40_ASSOCIATION_V1.json | 总 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
