#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_identify_rolling.py — 五折逐半年滚动验证 (spec §4, 2026-09-21 第三轮修订).

本轮修复(2026-09-21 第四轮复审):
1 预处理防泄漏: 填补中位数/标准化(mu,sd)逐折仅用训练集拟合, 测试集仅 transform
2 测试集归属: 按 obs_day 的半年桶(不再用 split_path/split_ge=标签可得日桶)
3 目标资格独立:
   - path_binary: 排除 path_family==right_censored; 不排 group 不确定;
     要求 obs_day < label_available_day_path(第20日收盘后结局已知非预测)
   - group_g3: 正类=G3(T3 已发生, 右删失亦可, spec 允许); 负类=完整终结
     G1/G2; 排除 unknown_censored(未终结无T3); 要求 obs_day <
     label_available_day_ge(T3 已发生=已知事实识别, 不进预测表现)
4 折完成标记: completed 仅当 n_train>=200 且 n_test>=50; 未达门槛如实
   标记不算完成, 五折全列
冻结: 特征/标签/切分/模型(逻辑回归+类权重, seed 20260919), 不看测试折调参。
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
MIN_TRAIN, MIN_TEST = 200, 50


def load(ds):
    return list(csv.DictReader(gzip.open(OUT / f"identify_{ds}.csv.gz", "rt")))


def eligibility(rows, target):
    """目标独立资格筛选 → (elig_mask, y 或 None)."""
    elig, y = [], []
    for r in rows:
        e, yy = False, None
        if target == "path_binary":
            if r.get("path_family") != "right_censored":
                la, ob = r.get("label_available_day_path"), r["obs_day"]
                if la and ob < la:                    # 严格 <: 结局确定前
                    e, yy = True, 1 if r["path_family"] == "never_reclaim" else 0
        elif target == "group_g3":
            ge = r.get("group_eventual")
            la, ob = r.get("label_available_day_ge"), r["obs_day"]
            if ge == "G3" and la and ob < la:         # T3 前(否则=事实识别)
                e, yy = True, 1
            elif ge in ("G1", "G2") and la and ob < la:
                e, yy = True, 0                       # 完整终结负类
            # unknown_censored(未终结无T3)排除
        elig.append(e)
        y.append(yy)
    return elig, y


def to_raw_x(rows, elig, xs):
    X = []
    for r, e in zip(rows, elig):
        if not e:
            continue
        X.append([float(r[c]) if r.get(c, "") not in ("", "None") else np.nan
                  for c in xs])
    return np.array(X, dtype=float)


def obs_bucket(day):
    y, m = int(day[:4]), int(day[5:7])
    return (y - 2015) * 2 + (0 if m <= 6 else 1)


def fold_fit_transform(Xtr, Xte):
    """填补+标准化仅用训练集拟合."""
    med = np.nanmedian(Xtr, axis=0)
    def tf(M):
        idx = np.isnan(M)
        M = M.copy()
        M[idx] = np.take(med, idx.nonzero()[1])
        return M
    A = tf(Xtr)
    mu, sd = A.mean(0), A.std(0) + 1e-12
    return (A - mu) / sd, (tf(Xte) - mu) / sd


def fit_logreg(X, y, epochs=300, lr=0.1, l2=1e-3, seed=20260919):
    rng = np.random.default_rng(seed)
    n, d = X.shape
    w = np.zeros(d + 1)
    pc = max(y.mean(), 1e-6)
    sw = np.where(y == 1, (1 - pc) / max(pc, 1e-6), 1.0)
    Xb = np.hstack([X, np.ones((n, 1))])
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-(Xb @ w)))
        g = Xb.T @ ((p - y) * sw) / n + l2 * np.r_[w[:-1], 0]
        w -= lr * g
    return w


def main():
    t0 = time.time()
    assert len(sys.argv) > 1, "usage: run_identify_rolling.py {breakout|shrink|stabilization} [path_binary|group_g3]"
    ds, target = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "path_binary")
    rows = load(ds)
    xs = sorted({c for r in rows[:50] for c in r if c.startswith(FEATURE_PREFIX)})
    elig, y = eligibility(rows, target)
    X = to_raw_x(rows, elig, xs)
    y = np.array([yy for yy, e in zip(y, elig) if e], dtype=float)
    obs = [r["obs_day"] for r, e in zip(rows, elig) if e]
    la = [(r.get("label_available_day_path") if target == "path_binary"
           else r.get("label_available_day_ge"))
          for r, e in zip(rows, elig) if e]
    obk = [obs_bucket(d) for d in obs]
    buckets = sorted(set(obk))
    folds, n_completed = [], 0
    for tb in buckets[:-1]:
        test_start = f"{2015 + tb // 2}-{'01' if tb % 2 == 0 else '07'}-01"
        tr = np.array([(k < tb) and (l < test_start) for k, l in zip(obk, la)])
        te = np.array([k == tb for k in obk])
        rec = {"test_bucket": tb, "test_start": test_start,
               "n_train": int(tr.sum()), "n_test": int(te.sum()),
               "train_pos_rate": float(y[tr].mean()) if tr.sum() else None,
               "test_pos_rate": float(y[te].mean()) if te.sum() else None}
        rec["completed"] = bool(tr.sum() >= MIN_TRAIN and te.sum() >= MIN_TEST)
        if rec["completed"]:
            n_completed += 1
            Xtr, Xte = fold_fit_transform(X[tr], X[te])
            w = fit_logreg(Xtr, y[tr])
            pred = (np.hstack([Xte, np.ones((len(Xte), 1))]) @ w) >= 0
            tp = int(((pred == 1) & (y[te] == 1)).sum())
            rec.update({"pos_recall": tp / max(int((y[te] == 1).sum()), 1),
                        "precision": tp / max(int(pred.sum()), 1),
                        "predicted_pos_rate": float(pred.mean())})
        else:
            rec["skip_reason"] = f"train<{MIN_TRAIN} 或 test<{MIN_TEST}"
        folds.append(rec)
    report = {"dataset": ds, "target": target, "features": xs,
              "n_rows_loaded": len(rows),
              "n_eligible": int(X.shape[0]),
              "class_balance": dict(Counter(y.tolist())),
              "folds": folds, "n_folds_completed": n_completed,
              "gate": ("train: obs 桶<test 桶 且 la<test_start; "
                       "test: obs_day 半年桶; 资格按目标独立; "
                       "obs_day<la(严格, 结局确定前); 逐折训练集拟合填补/标准化"),
              "dev_note": DEV_NOTE, "seed": 20260919}
    (OUT / f"identify_rolling_{ds}_{target}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps(folds, ensure_ascii=False))
    print(f"→ identify_rolling_{ds}_{target}.json | 完成 {n_completed}/{len(folds)} 折 | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
