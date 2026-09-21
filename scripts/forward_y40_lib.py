#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""forward_y40_lib.py — forward_y40_association 共享库(设计 ff8426e 冻结).

提供: 事件构建(eligibility_forward_v1+完整窗口+Y40 家族+标签可得日),
同日同股去重, Ridge(alpha=1, 截距不惩罚), Spearman, 40 日连续日期块
与股票块 bootstrap, 零假设中心双侧 bootstrap p 值。
冻结口径见 docs/reports/FORWARD_Y40_ASSOCIATION_DESIGN_V1.md。
"""
import csv
import gzip
import json
import struct
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research.identify_features import eligibility_forward_v1  # noqa: E402
from build_identify_features import load_stock                              # noqa: E402

H = 40
SEED = 20260919
BOOT = 2000
MIN_TRAIN, MIN_TEST = 200, 50
MIN_STK_PER_DAY = 10


def market_calendar():
    """上证日历+收盘(int32/100, §8 修正后口径)。"""
    b = Path("/root/tdx_data/vipdoc/sh/lday/sh999999.day").read_bytes()
    dates, close = [], []
    for i in range(len(b) // 32):
        d = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        dates.append(f"{d // 10000}-{d // 100 % 100:02d}-{d % 100:02d}")
        close.append(struct.unpack("<i", b[i * 32 + 16:i * 32 + 20])[0] / 100.0)
    return dates, np.array(close)


def obs_bucket(day):
    return (int(day[:4]) - 2015) * 2 + (0 if int(day[5:7]) <= 6 else 1)


def fold_start(bucket):
    y = 2015 + bucket // 2
    return f"{y}-{'01' if bucket % 2 == 0 else '07'}-01"


def build_events(ds, want_stats=False):
    """三时点行 → 主分析事件(完整 41 市场日) + 敏感性(imputed) + 守恒计数。

    返回 (events, sens, conservation); events 行 dict:
      code, obs_day, t40_day, label_avail_day(=t40_day), y40, mdd, trend,
      lifecycle_id, stage, bucket, 以及数据集原行(特征用)。
    """
    mdates, mclose = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    F = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        for row in csv.DictReader(f):
            F.setdefault(row["code"], {})[row["date"]] = float(row["F"])
    rows = list(csv.DictReader(gzip.open(
        ROOT / f"output/research/posneg_v1/identify_{ds}.csv.gz", "rt")))
    stat = {"n_rows": len(rows), "excl_not_active": 0, "obs_day_no_price": 0,
            "data_end_censored": 0, "window_all_missing": 0,
            "imputed_last_available": 0, "full_path": 0,
            "dup_same_day_same_stock": 0}
    cache = {}
    main_l, sens_l = [], []
    for r in rows:
        if not eligibility_forward_v1(r):
            stat["excl_not_active"] += 1
            continue
        code = r["code"]
        if code not in cache:
            j = json.load(gzip.open(ROOT / f"data/adjustment_baostock/per_stock/{code}.json.gz", "rt"))
            fc = F[code]
            padj = {row[0]: float(row[4]) * fc[row[0]]
                    for row in j["unadj"] if row[0] in fc}
            cache[code] = padj
        padj = cache[code]
        t = r["obs_day"]
        mi = mpos.get(t)
        if mi is None or mi + H >= len(mdates):
            stat["data_end_censored"] += 1
            continue
        p0 = padj.get(t)
        if p0 is None or p0 <= 0:
            stat["obs_day_no_price"] += 1
            continue
        t40 = mdates[mi + H]
        p40 = padj.get(t40)
        imputed = False
        if p40 is None:
            back = next((mdates[k] for k in range(mi + H, mi, -1) if mdates[k] in padj), None)
            if back is None:
                stat["window_all_missing"] += 1
                continue
            p40 = padj[back]
            imputed = True
        win = [padj.get(mdates[k]) for k in range(mi, mi + H + 1)]
        n_have = sum(1 for c in win if c is not None)
        if not np.isfinite(p0) or not np.isfinite(p40) or p0 <= 0 or p40 <= 0:
            stat["obs_day_no_price"] += 1
            continue
        ev = dict(r)
        ev.update({"code": code, "obs_day": t, "t40_day": t40,
                   "label_avail_day": t40,
                   "y40": float(np.log(p40 / p0) - np.log(mclose[mi + H] / mclose[mi])),
                   "stage": ds, "bucket": obs_bucket(t)})
        if imputed:
            stat["imputed_last_available"] += 1
            sens_l.append(ev)
            continue
        if n_have == H + 1:
            cc = [c for c in win if c is not None]
            run_max, mdd = cc[0], 0.0
            for c in cc:
                run_max = max(run_max, c)
                mdd = min(mdd, c / run_max - 1)
            seg = 0
            for si in range(8):
                a, b_ = mi + si * 5, mi + si * 5 + 5
                if np.log(padj[mdates[b_]] / padj[mdates[a]]) - \
                        np.log(mclose[b_] / mclose[a]) > 0:
                    seg += 1
            ev["mdd"], ev["trend"] = float(mdd), seg / 8
            stat["full_path"] += 1
            main_l.append(ev)
        else:
            # 端点可用但中途缺日: 主分析不用(§2.3), 仅计数
            stat.setdefault("endpoint_gap", 0)
            stat["endpoint_gap"] += 1
    # 同日同股去重(设计§5/§7): 保留 lifecycle_id 最大(最新生命周期)
    def dedup(lst, stat):
        seen, keep = {}, []
        for e in lst:
            k = (e["obs_day"], e["code"])
            if k in seen:
                stat["dup_same_day_same_stock"] += 1
                if e["lifecycle_id"] > seen[k]["lifecycle_id"]:
                    keep[keep.index(seen[k])] = e
                    seen[k] = e
            else:
                seen[k] = e
                keep.append(e)
        return keep
    main_l = dedup(main_l, stat)
    sens_l = dedup(sens_l, stat)
    n_out = (stat["excl_not_active"] + stat["data_end_censored"] +
             stat["obs_day_no_price"] + stat["window_all_missing"] +
             stat["imputed_last_available"] + stat.get("endpoint_gap", 0) +
             stat["full_path"])
    assert n_out == len(rows), f"守恒失败 {n_out} != {len(rows)}"
    stat["dup_same_day_same_stock"] = stat["dup_same_day_same_stock"] // 1
    stat["n_main_after_dedup"] = len(main_l)
    stat["n_sens_after_dedup"] = len(sens_l)
    return main_l, sens_l, stat


def ridge(X, y, alpha=1.0):
    """闭式 Ridge, 截距不惩罚; 返回预测函数所需参数。"""
    mu, sd = X.mean(0), X.std(0) + 1e-12
    Z = (X - mu) / sd
    yc = y - y.mean()
    A = Z.T @ Z + alpha * np.eye(Z.shape[1])
    w = np.linalg.solve(A, Z.T @ yc)
    return {"mu": mu, "sd": sd, "b0": float(y.mean()), "w": w}


def ridge_predict(m, X):
    return ((X - m["mu"]) / m["sd"]) @ m["w"] + m["b0"]


def fit_transform(Xtr, Xte):
    """训练折中位数填补(全缺列填 0 并记录)+标准化, 严格 transform 测试。"""
    med = np.nanmedian(Xtr, axis=0)
    allmiss = np.isnan(med)
    med = np.where(allmiss, 0.0, med)
    def tf(M):
        M = M.copy()
        i = np.isnan(M)
        M[i] = np.take(med, i.nonzero()[1])
        return M
    A = tf(Xtr)
    mu, sd = A.mean(0), A.std(0) + 1e-12
    return (A - mu) / sd, (tf(Xte) - mu) / sd, [int(k) for k in np.nonzero(allmiss)[0]]


def rank_avg(v):
    """向量化平均秩(tie 安全)。"""
    order = np.argsort(v, kind="mergesort")
    ss = v[order]
    grp = np.cumsum(np.r_[True, ss[1:] != ss[:-1]]) - 1
    cnt = np.bincount(grp)
    ends = np.cumsum(cnt).astype(float)
    avg = (ends + ends - cnt + 1) / 2
    r = np.empty(len(v))
    r[order] = avg[grp]
    return r


def spearman(a, b):
    if len(np.unique(a)) < 2 or len(np.unique(b)) < 2:
        return None
    ra, rb = rank_avg(a), rank_avg(b)
    ra -= ra.mean()
    rb -= rb.mean()
    denom = np.sqrt((ra ** 2).sum() * (rb ** 2).sum())
    return float((ra * rb).sum() / denom) if denom > 0 else None


def daily_ic(groups, dates, y, s):
    """逐 obs_day 横截面 Spearman; groups=事件→日期索引映射由调用方给。"""
    out = {}
    for d, idx in zip(dates, groups):
        if len(idx) >= MIN_STK_PER_DAY:
            ic = spearman(y[idx], s[idx])
            if ic is not None:
                out[d] = ic
    return out


def cont_40d_blocks(days):
    """有效日期按市场日历切连续 40 交易日块(不足 40 日的尾部残块并入末块标记)。"""
    mdates, _ = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    si = sorted(days, key=lambda d: mpos[d])
    blocks, cur = [], []
    for d in si:
        if cur and mpos[d] - mpos[cur[0]] >= H:
            blocks.append(cur)
            cur = []
        cur.append(d)
    if cur:
        blocks.append(cur)
    return blocks


def block_boot_delta(icA, icB, blocks, wts_fold):
    """40 日块重抽: 重组日期集 → 折内等权平均 → 折间冻结日期数加权。"""
    rng = np.random.default_rng(SEED)
    deltas = []
    for _ in range(BOOT):
        pick = [b for b in (blocks[rng.integers(len(blocks))] for _ in range(len(blocks)))]
        dd = [d for b in pick for d in b]
        per = []
        for f, wf in wts_fold:
            ds_f = [d for d in dd if d in f]
            if ds_f:
                per.append((np.mean([icB[d] - icA[d] for d in ds_f]), len(ds_f), wf))
        if per:
            num = sum(v * n * w for v, n, w in per)
            den = sum(n * w for _, n, w in per)
            deltas.append(num / den)
    return np.array(deltas)


def centered_p(boot_dist, obs=None):
    """零假设中心双侧 percentile bootstrap p(与 percentile CI 同口径)。

    H0: 真Δ=0 → p = 0 在 bootstrap 分布中的双侧尾部概率
    (2·min(P(boot≤0), P(boot≥0)), +1 修正)。CI 不含 0 ⇔ p<0.05
    (同一分布两种读法, 口径一致)。obs 仅保留签名兼容。
    """
    n_le = int((boot_dist <= 0).sum())
    n_ge = int((boot_dist >= 0).sum())
    p = 2 * min(n_le, n_ge) + 1
    return min(1.0, p / (len(boot_dist) + 1))


def holm(pvals):
    order = np.argsort(pvals)
    m = len(pvals)
    adj = np.empty(m)
    mx = 0.0
    for r, i in enumerate(order):
        mx = max(mx, (m - r) * pvals[i])
        adj[i] = min(1.0, mx)
    return adj
