#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_identify_increment.py — 同样本信息增量实验 (2026-09-21 裁决).

设计: 同一批生命周期(到达 shrink/stabilization 且观察日具备合法预测资格),
  early=breakout 特征模型 vs current=时点特征模型:
  - 同标签/同事件集合/同测试折(按当前时点 obs_day 归桶)
  - 训练门禁同滚动验证(obs 桶<test 桶 且 la<test_start)
  - 逐折 AUC(平均秩); 事件级配对 ΔAUC=current−early
  - 合并完成折的事件重抽 bootstrap(股票块/日期块各 2000, percentile 95%)
边界: 开发期研究假设检验("回调阶段特征可能包含更多路径识别信息"),
  不构成信息增量确认, 不改交易规则/阈值/仓位。
"""
import csv
import gzip
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/posneg_v1"
SEED, BOOT = 20260919, 2000
MIN_TRAIN, MIN_TEST = 200, 50
DEV_NOTE = "开发期研究; 非实盘准入; 因子层 exception 保留"


def load(ds):
    return list(csv.DictReader(gzip.open(OUT / f"identify_{ds}.csv.gz", "rt")))


def eligibility_path(r):
    if r.get("path_family") == "right_censored":
        return False
    la, ob = r.get("label_available_day_path"), r["obs_day"]
    return bool(la and ob < la)


def cols(rows, prefixes):
    return sorted({c for r in rows[:50] for c in r if c.startswith(prefixes)})


def rawx(rows, xs):
    """缺失保留 np.nan(真实零值不得当缺失, 2026-09-21 P1 修复)."""
    return np.array([[float(r[c]) if r.get(c, "") not in ("", "None") else np.nan
                      for c in xs] for r in rows])


def fit_transform(Xtr, Xte, xs):
    """仅 np.isnan 判定缺失; 中位数/标准化仅训练折拟合.

    训练列全缺失 → 固定回填 0 并记录列名(返回 third)."""
    med = np.nanmedian(Xtr, axis=0)
    allmiss = np.isnan(med)
    med = np.where(allmiss, 0.0, med)
    def tf(M):
        M = M.copy()
        idx = np.isnan(M)
        M[idx] = np.take(med, idx.nonzero()[1])
        return M
    A = tf(Xtr)
    mu, sd = A.mean(0), A.std(0) + 1e-12
    dropped = [c for c, m in zip(xs, allmiss) if m]
    return (A - mu) / sd, (tf(Xte) - mu) / sd, dropped


def logreg(X, y, epochs=300, lr=0.1, l2=1e-3):
    n, d = X.shape
    w = np.zeros(d + 1)
    pc = max(y.mean(), 1e-6)
    sw = np.where(y == 1, (1 - pc) / pc, 1.0)
    Xb = np.hstack([X, np.ones((n, 1))])
    for _ in range(epochs):
        p = 1 / (1 + np.exp(-(Xb @ w)))
        w -= lr * (Xb.T @ ((p - y) * sw) / n + l2 * np.r_[w[:-1], 0])
    return w


def score(w, X):
    return np.hstack([X, np.ones((len(X), 1))]) @ w


def auc(y, s):
    """平均秩 AUC(tie 安全)."""
    order = np.argsort(s, kind="mergesort")
    s_sorted = s[order]
    ranks = np.empty(len(s))
    i = 0
    r = 1
    while i < len(s):
        j = i
        while j + 1 < len(s) and s_sorted[j + 1] == s_sorted[i]:
            j += 1
        avg = (r + r + (j - i)) / 2
        ranks[order[i:j + 1]] = avg
        r += (j - i + 1)
        i = j + 1
    n_pos = int((y == 1).sum())
    n_neg = int((y == 0).sum())
    if n_pos == 0 or n_neg == 0:
        return None
    return (ranks[y == 1].sum() - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def boot_delta_auc_by_fold(y, s_e, s_c, fold_id, wts, key, seed_off):
    """块重抽 bootstrap, 保留折身份(2026-09-21 P0 修复).

    每次重抽后: 按折分组分别算 ΔAUC(折内排序, 不跨折比较分数尺度),
    再按冻结权重(各折测试事件数占比)汇总; 无定义折权重归一到有值折.
    返回 (lo, hi, n_blocks, n_boot_skipped)."""
    blocks = defaultdict(list)
    for i in range(len(y)):
        blocks[key[i]].append(i)
    bk = list(blocks.values())
    rng = np.random.default_rng(SEED + seed_off)
    deltas = []
    skipped = 0
    for _ in range(BOOT):
        idx = np.concatenate([bk[rng.integers(len(bk))] for _ in range(len(bk))])
        per, ws = [], []
        for f in np.unique(fold_id[idx]):
            m = idx[fold_id[idx] == f]
            a_e, a_c = auc(y[m], s_e[m]), auc(y[m], s_c[m])
            if a_e is not None and a_c is not None:
                per.append(a_c - a_e)
                ws.append(wts[f])
        if per:                                     # 某折无正/负类→权重归一
            ws = np.array(ws)
            deltas.append(float(np.average(per, weights=ws)))
        else:
            skipped += 1
    deltas = np.sort(np.array(deltas))
    return (float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5)),
            len(bk), skipped)


def main():
    t0 = time.time()
    cur_ds = sys.argv[1] if len(sys.argv) > 1 else "shrink"
    target = sys.argv[2] if len(sys.argv) > 2 else "path_binary"
    la_col = "label_available_day_path"
    cur_rows = load(cur_ds)
    bo_rows = {r["lifecycle_id"]: r for r in load("breakout")}
    elig = [r for r in cur_rows if eligibility_path(r)
            and r["lifecycle_id"] in bo_rows]
    xs_cur = cols(cur_rows, ("sh_", "st_", "atr", "hlpos", "ma_bias", "rvol", "volratio"))
    xs_e = cols(load("breakout")[:50], ("bo_", "prep_days"))
    print(f"事件集: {len(elig)} (来自 {cur_ds}; 同样本 join breakout)", flush=True)
    y = np.array([1 if r["path_family"] == "never_reclaim" else 0 for r in elig])
    Xc_raw = rawx(elig, xs_cur)
    Xe_raw = rawx([bo_rows[r["lifecycle_id"]] for r in elig], xs_e)
    obk = np.array([(int(r["obs_day"][:4]) - 2015) * 2 + (0 if int(r["obs_day"][5:7]) <= 6 else 1)
                    for r in elig])
    las = [r[la_col] for r in elig]
    codes = [r["code"] for r in elig]
    days = [r["breakout_day"] for r in elig]
    folds = []
    all_idx = []
    for tb in sorted(set(obk))[:-1]:
        test_start = f"{2015 + tb // 2}-{'01' if tb % 2 == 0 else '07'}-01"
        tr = (obk < tb) & np.array([l < test_start for l in las])
        te = obk == tb
        rec = {"test_bucket": int(tb), "n_train": int(tr.sum()), "n_test": int(te.sum())}
        rec["completed"] = bool(tr.sum() >= MIN_TRAIN and te.sum() >= MIN_TEST)
        if rec["completed"]:
            Ec, Tc, drop_c = fit_transform(Xc_raw[tr], Xc_raw[te], xs_cur)
            Ee, Te, drop_e = fit_transform(Xe_raw[tr], Xe_raw[te], xs_e)
            s_c, s_e = score(logreg(Ec, y[tr]), Tc), score(logreg(Ee, y[tr]), Te)
            a_c, a_e = auc(y[te], s_c), auc(y[te], s_e)
            rec.update({"auc_current": round(a_c, 4), "auc_early": round(a_e, 4),
                        "delta_auc": round(a_c - a_e, 4)})
            if drop_c or drop_e:
                rec["all_missing_cols_filled0"] = {"current": drop_c, "early": drop_e}
            all_idx.append((np.where(te)[0], tb))
            rec["_scores"] = (s_e.copy(), s_c.copy())
        folds.append(rec)
    # 汇总: 冻结权重(各完成折测试事件数占比)加权 ΔAUC 均值
    # bootstrap 保留折身份: 重抽后逐折 ΔAUC→冻结权重汇总(不跨折比较分数)
    pooled = None
    if all_idx:
        idx = np.concatenate([a for a, _ in all_idx])
        fid = np.concatenate([np.full(len(a), int(tb)) for a, tb in all_idx])
        s_e = np.concatenate([folds[i]["_scores"][0] for i in range(len(folds)) if "_scores" in folds[i]])
        s_c = np.concatenate([folds[i]["_scores"][1] for i in range(len(folds)) if "_scores" in folds[i]])
        wts = {int(tb): float((obk == tb).sum()) for _, tb in all_idx}
        point = float(np.average([f["delta_auc"] for f in folds if f.get("completed")],
                                 weights=[wts[f["test_bucket"]] for f in folds if f.get("completed")]))
        yy, cc, dd = y[idx], [codes[i] for i in idx], [days[i] for i in idx]
        lo_s, hi_s, nb_s, sk_s = boot_delta_auc_by_fold(yy, s_e, s_c, fid, wts, cc, 1)
        lo_d, hi_d, nb_d, sk_d = boot_delta_auc_by_fold(yy, s_e, s_c, fid, wts, dd, 2)
        pooled = {"n_events_pooled": len(idx),
                  "weighted_delta_auc_point": round(point, 4),
                  "frozen_weights": {str(k): round(v / sum(wts.values()), 4) for k, v in wts.items()},
                  "delta_auc_stock_ci": [round(lo_s, 4), round(hi_s, 4)], "n_stock_blocks": nb_s,
                  "delta_auc_date_ci": [round(lo_d, 4), round(hi_d, 4)], "n_date_blocks": nb_d,
                  "bootstrap_skipped_draws": {"stock": sk_s, "date": sk_d},
                  "note": ("双侧 percentile 95%; 折内 ΔAUC 按冻结测试事件数权重汇总; "
                           "固定已训练模型后的测试样本重抽区间, 未含重新训练的不确定性")}
        for f in folds:
            f.pop("_scores", None)
    # P3: 预测提前量分布(la_path − obs_day, 自然日差; early=bo 视角, current=时点视角)
    from datetime import date as _d
    def _dd(a, b):
        return (_d(int(a[:4]), int(a[5:7]), int(a[8:10]))
                - _d(int(b[:4]), int(b[5:7]), int(b[8:10]))).days
    lead_cur = np.array([_dd(r[la_col], r["obs_day"]) for r in elig])
    lead_e = np.array([_dd(r[la_col], bo_rows[r["lifecycle_id"]]["obs_day"]) for r in elig])
    q = lambda v: {k: float(np.percentile(v, p)) for k, p in
                   (("min", 0), ("p25", 25), ("p50", 50), ("p75", 75), ("max", 100))}
    lead_dist = {"note": "label_available_day_path − obs_day 自然日差; 判断高 AUC 是否集中于临近结局观察日",
                 "current": q(lead_cur), "early_breakout": q(lead_e)}
    report = {"experiment": f"increment:{cur_ds}", "target": target,
              "early_features": xs_e, "current_features": xs_cur,
              "n_events": len(elig), "folds": folds, "pooled": pooled,
              "lead_days_distribution": lead_dist,
              "dev_note": DEV_NOTE,
              "hypothesis": "回调阶段特征可能包含更多路径识别信息(研究假设, 未确认)"}
    (OUT / f"identify_increment_{cur_ds}_{target}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(json.dumps({"folds": [{k: v for k, v in f.items() if k != "_scores"} for f in folds],
                      "pooled": pooled}, ensure_ascii=False))
    print(f"→ identify_increment_{cur_ds}_{target}.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
