#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_identify_rolling.py — 五折逐半年滚动验证程序 (spec §4, 2026-09-21).

建模门禁(2026-09-21 第三轮复审冻结, 先门禁后模型):
  训练集: obs_day < TEST_START 且 la_day(训练目标) < TEST_START
  测试集: obs_day 落测试半年; 指标仅在标签成熟(la_day<=评估基准)后计算
  排除: label_uncertain; 预测 20 日结局要求 pred_legal_path(观察日<=la_path)
  折序: 桶 18..22 各作一次测试期, train=全部更早桶(且门禁过滤)
基线模型: 纯 numpy 逻辑回归(L-BFGS 不可用→梯度下降), 类别不平衡用类权重;
  先冻结特征/标签/切分, 不看测试折调参(裁决: 开发研究, 非实盘准入)。
运行: 需先 rebuild identify 数据集(含 split_path/split_ge 元数据列)。
"""
import csv
import gzip
import json
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/posneg_v1"
DEV_NOTE = "开发样本研究; adjustment_v1 exception 未闭合; 非实盘准入规则"
FEATURE_PREFIX = ("bo_", "sh_", "st_", "prep_days", "atr", "hlpos", "ma_bias",
                  "rvol", "volratio")
TARGETS = {"path_binary": ("path_family", {"never_reclaim": 1}, "split_path",
                           "label_available_day_path"),
           "group_g3": ("group_eventual", {"G3": 1}, "split_ge",
                        "label_available_day_ge")}


def load(ds: str):
    return list(csv.DictReader(gzip.open(OUT / f"identify_{ds}.csv.gz", "rt")))


def xcols(row):
    return sorted(k for k in row if k.startswith(FEATURE_PREFIX))


def to_xy(rows, target):
    col, pos_map, _, _ = TARGETS[target]
    xs = xcols(rows[0])
    X, y, keep = [], [], []
    for i, r in enumerate(rows):
        if r.get("label_uncertain") in ("True", "true", "1"):
            continue
        y0 = pos_map.get(r.get(col), 0)
        if col == "group_eventual" and r.get("group_eventual") == "unknown_censored":
            continue
        if target == "path_binary" and r.get("pred_legal_path") not in ("True", "true", "1"):
            continue
        vec = []
        for c in xs:
            v = r.get(c, "")
            vec.append(float(v) if v not in ("", "None") else np.nan)
        X.append(vec)
        y.append(y0)
        keep.append(i)
    X = np.array(X, dtype=float)
    med = np.nanmedian(X, axis=0)
    idx = np.isnan(X)
    X[idx] = np.take(med, idx.nonzero()[1])
    mu, sd = X.mean(0), X.std(0) + 1e-12
    return (X - mu) / sd, np.array(y), keep, xs, (mu, sd, med)


def fit_logreg(X, y, epochs=300, lr=0.1, l2=1e-3, seed=20260919):
    rng = np.random.default_rng(seed)
    n, d = X.shape
    w = np.zeros(d + 1)
    pc = max(y.mean(), 1e-6)
    sw = np.where(y == 1, (1 - pc) / max(pc, 1e-6), 1.0)      # 类权重
    Xb = np.hstack([X, np.ones((n, 1))])
    for _ in range(epochs):
        z = Xb @ w
        p = 1 / (1 + np.exp(-z))
        g = Xb.T @ ((p - y) * sw) / n + l2 * np.r_[w[:-1], 0]
        w -= lr * g
    return w


def predict(w, X):
    return (np.hstack([X, np.ones((len(X), 1))]) @ w) >= 0


def main():
    t0 = time.time()
    assert len(sys.argv) > 1, "usage: run_identify_rolling.py {breakout|shrink|stabilization} [target]"
    ds, target = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "path_binary")
    _, _, split_col, la_col = TARGETS[target]
    rows = load(ds)
    X, y, keep, xs, norm = to_xy(rows, target)
    splits = [int(rows[i][split_col]) for i in keep]
    las = [rows[i][la_col] for i in keep]
    obs = [rows[i]["obs_day"] for i in keep]
    buckets = sorted(set(splits))
    folds = []
    for tb in buckets[:-1]:                                   # 每桶一次测试期
        test_start = f"{2015 + tb // 2}-{'01' if tb % 2 == 0 else '07'}-01"
        tr = np.array([(s < tb) and (la < test_start) and (ob < test_start)
                       for s, la, ob in zip(splits, las, obs)])
        te = np.array([s == tb for s in splits])
        rec = {"test_bucket": tb, "test_start": test_start,
               "n_train": int(tr.sum()), "n_test": int(te.sum()),
               "train_pos_rate": float(y[tr].mean()) if tr.sum() else None,
               "test_pos_rate": float(y[te].mean()) if te.sum() else None}
        if tr.sum() >= 200 and te.sum() >= 50:
            w = fit_logreg(X[tr], y[tr])
            pred = predict(w, X[te])
            tp = int(((pred == 1) & (y[te] == 1)).sum())
            rec.update({"auc_proxy_pos_recall": tp / max(int((y[te] == 1).sum()), 1),
                        "precision": tp / max(int(pred.sum()), 1),
                        "predicted_pos_rate": float(pred.mean())})
        else:
            rec["skip"] = "train<200 或 test<50"
        folds.append(rec)
    report = {"dataset": ds, "target": target, "features": xs,
              "n_rows_loaded": len(rows), "n_rows_model": len(y),
              "class_balance": dict(Counter(y.tolist())),
              "folds": folds, "dev_note": DEV_NOTE, "seed": 20260919,
              "gate": "train: obs&la < test_start; test: obs 桶内; "
                      "label_uncertain 排除; path 目标需 pred_legal_path"}
    (OUT / f"identify_rolling_{ds}_{target}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(folds, ensure_ascii=False))
    print(f"→ identify_rolling_{ds}_{target}.json | {time.time()-t0:.0f}s | {DEV_NOTE}")


if __name__ == "__main__":
    main()
