#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_capital_behavior_proxy.py — 资金态度代理指标独立信息验证 (v1, 2026-09-21 放行).

任务书三问:
1 成交量有没有独立信息?  A(价格基准)/B(A+量能)/C(B+结构) 嵌套,
  同活跃风险集/同折/同模型: 配对 ΔAUC(B−A)为核心, C−B 次之
2 信息在哪些状态出现?     缩量条件效应: 位置×动量状态(事前固定边界)分层,
  层内连续量能特征 Cliff's δ(不二分缩放量挑组)
3 是否跨期稳定?           逐折+股票块/日期块 bootstrap percentile 95%

冻结(事前固定, 不按结果挑选):
- 信息集合(每时点): 见 SETS; 交互项=预定义乘积(放量方向一致性/位置×量)
- sh_volratio5 与 volratio5 全等, 只保留前者; rvol20=收益波动率归结构集
- 分层边界: 位置 near=|距突破位|<=3%; 动量(shrink 无当日收益不分会):
  stab 反弹幅度 st_rebound_from_low>=3% 为有效止跌
- lead_td=冻结交易日历内 cutoff−obs 交易日差, 归 A(时间信息)
- 模型/预处理/资格: 与 identify 滚动验证完全一致(eligibility_riskset,
  训练折拟合填补标准化, 逻辑回归 seed 20260919)
边界: 开发期; 非因果; 非收益证明; 不调阈值不选模型; 因子层例外保留。
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
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "output/research/posneg_v1"
SEED, BOOT = 20260919, 2000
MIN_TRAIN, MIN_TEST = 200, 50
from stock_selector.research.identify_features import eligibility_riskset  # noqa: E402
from build_identify_features import load_stock                            # noqa: E402

SETS = {
    "breakout": {
        "A": ["bo_ret1", "bo_cum5", "bo_cum10", "bo_cum20", "lead_td"],
        "B": ["bo_ret1", "bo_cum5", "bo_cum10", "bo_cum20", "lead_td",
              "bo_volratio5", "bo_volratio20"],
        "C": ["bo_ret1", "bo_cum5", "bo_cum10", "bo_cum20", "lead_td",
              "bo_volratio5", "bo_volratio20", "bo_atr14pct", "bo_hlpos60",
              "bo_ma_bias20", "bo_dist_high60",
              "ret1_x_vol5", "atr_x_vol20"],
    },
    "shrink": {
        "A": ["sh_support_dist", "sh_low_support_dist", "sh_dd_from_high",
              "sh_days_since_bo", "lead_td"],
        "B": ["sh_support_dist", "sh_low_support_dist", "sh_dd_from_high",
              "sh_days_since_bo", "lead_td", "sh_volratio5"],
        "C": ["sh_support_dist", "sh_low_support_dist", "sh_dd_from_high",
              "sh_days_since_bo", "lead_td", "sh_volratio5", "atr14pct",
              "hlpos60", "ma_bias20", "rvol20", "dist_x_vol"],
    },
    "stabilization": {
        "A": ["st_close_vs_bo", "st_prev_ret1", "st_ret1", "lead_td"],
        "B": ["st_close_vs_bo", "st_prev_ret1", "st_ret1", "lead_td",
              "st_volrecover"],
        "C": ["st_close_vs_bo", "st_prev_ret1", "st_ret1", "lead_td",
              "st_volrecover", "st_lower_shadow", "st_rebound_from_low",
              "ret1_x_volrec"],
    },
}
VOL_FEAT = {"breakout": ["bo_volratio5", "bo_volratio20"],
            "shrink": ["sh_volratio5"],
            "stabilization": ["st_volrecover"]}
NEAR, REBOUND = 0.03, 0.03          # 分层边界(事前固定)


def load(ds):
    return list(csv.DictReader(gzip.open(OUT / f"identify_{ds}.csv.gz", "rt")))


_CAL, _POS = {}, {}          # 模块级: 三时点共享行情日历缓存


def aug_rows(rows):
    """加 lead_td 与交互项(观察日已知量)."""
    F = {}
    with gzip.open(ROOT / "output/research/adjustment_v1/factor_table.csv.gz", "rt") as f:
        for row in csv.DictReader(f):
            F.setdefault(row["code"], {})[row["date"]] = float(row["F"])
    cal, pos = _CAL, _POS
    out = []
    for r in rows:
        code = r["code"]
        if code not in cal:
            ds_ = load_stock(code, F)[0]
            cal[code] = ds_
            pos[code] = {d: i for i, d in enumerate(ds_)}
        p = pos[code]
        r = dict(r)
        r["lead_td"] = p[r["label_available_day_path"]] - p[r["obs_day"]]
        def _f(k):
            v = r.get(k, "")
            return float(v) if v not in ("", "None") else np.nan
        r["ret1_x_vol5"] = _f("bo_ret1") * _f("bo_volratio5")
        r["atr_x_vol20"] = _f("bo_atr14pct") * _f("bo_volratio20")
        r["dist_x_vol"] = _f("sh_support_dist") * _f("sh_volratio5")
        r["ret1_x_volrec"] = _f("st_ret1") * _f("st_volrecover")
        out.append(r)
    return out


def xy(rows, feats):
    X = np.array([[float(r[c]) if r.get(c, "") not in ("", "None") else np.nan
                   for c in feats] for r in rows])
    y = np.array([1 if r["path_family"] == "never_reclaim" else 0 for r in rows])
    return X, y


def fit_transform(Xtr, Xte):
    med = np.nanmedian(Xtr, axis=0)
    med = np.where(np.isnan(med), 0.0, med)
    def tf(M):
        M = M.copy()
        i = np.isnan(M)
        M[i] = np.take(med, i.nonzero()[1])
        return M
    A = tf(Xtr)
    mu, sd = A.mean(0), A.std(0) + 1e-12
    return (A - mu) / sd, (tf(Xte) - mu) / sd


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


def auc(y, s):
    """平均秩 AUC, 纯 numpy 向量化 tie 处理(bootstrap 热路径)."""
    n1, n0 = int((y == 1).sum()), int((y == 0).sum())
    if n1 == 0 or n0 == 0:
        return None
    order = np.argsort(s, kind="mergesort")
    ss = s[order]
    new_grp = np.r_[True, ss[1:] != ss[:-1]]
    grp = np.cumsum(new_grp) - 1
    counts = np.bincount(grp)
    ends = np.cumsum(counts).astype(float)
    starts = ends - counts + 1
    avg = (starts + ends) / 2
    ranks_sorted = avg[grp]
    ranks = np.empty(len(s))
    ranks[order] = ranks_sorted
    return float((ranks[y == 1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


def nest_bootstrap(scores, y, fid, wts, key, seed_off, pair):
    """折内配对 ΔAUC(集合 pair 如 ('B','A')): 块重抽→逐折→冻结权重汇总."""
    blocks = defaultdict(list)
    for i in range(len(y)):
        blocks[key[i]].append(i)
    bk = list(blocks.values())
    rng = np.random.default_rng(SEED + seed_off)
    deltas = []
    for _ in range(BOOT):
        idx = np.concatenate([bk[rng.integers(len(bk))] for _ in range(len(bk))])
        per, ws = [], []
        for f in np.unique(fid[idx]):
            m = idx[fid[idx] == f]
            a1 = auc(y[m], scores[pair[0]][m])
            a0 = auc(y[m], scores[pair[1]][m])
            if a1 is not None and a0 is not None:
                per.append(a1 - a0)
                ws.append(wts[f])
        if per:
            deltas.append(float(np.average(per, weights=np.array(ws))))
    d = np.sort(np.array(deltas))
    return [float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))]


def cliff(x1, x0):
    n1, n0 = len(x1), len(x0)
    if n1 < 30 or n0 < 30:
        return None
    allv = np.concatenate([x1, x0])
    s = np.sort(allv)
    l = np.searchsorted(s, allv, "left")
    r = np.searchsorted(s, allv, "right")
    rk = (l + r + 1) / 2
    u1 = rk[:n1].sum() - n1 * (n1 + 1) / 2
    return float(2 * u1 / (n1 * n0) - 1)


def main():
    t0 = time.time()
    report = {"experiment": "capital_behavior_proxy_v1", "frozen": {
        "sets": SETS, "dedup": "sh_volratio5==volratio5 全等, 留前者; rvol20=收益波动率→C",
        "strata": {"near_band": NEAR, "rebound_min": REBOUND,
                   "shrink_无当日收益不分动量态": True},
        "model": "逻辑回归+类权重, 训练折拟合填补标准化, seed 20260919",
        "riskset": "eligibility_riskset 统一活跃风险集"},
        "results": {}, "stratified": {},
        "guard": "开发期; 非因果; 非收益证明; 不调阈值不选模型"}
    for ds in ("breakout", "shrink", "stabilization"):
        rows = [r for r in aug_rows(load(ds)) if eligibility_riskset(r)]
        y = np.array([1 if r["path_family"] == "never_reclaim" else 0 for r in rows])
        obk = np.array([(int(r["obs_day"][:4]) - 2015) * 2
                        + (0 if int(r["obs_day"][5:7]) <= 6 else 1) for r in rows])
        las = [r["label_available_day_path"] for r in rows]
        codes = [r["code"] for r in rows]
        days = [r["breakout_day"] for r in rows]
        scores, fold_data = {}, []
        for tag in ("A", "B", "C"):
            X, _ = xy(rows, SETS[ds][tag])
            sc = np.full(len(rows), np.nan)
            folds = []
            for tb in sorted(set(obk))[:-1]:
                ts = f"{2015 + tb // 2}-{'01' if tb % 2 == 0 else '07'}-01"
                tr = np.array([(k < tb) and (l < ts) for k, l in zip(obk, las)])
                te = obk == tb
                if tr.sum() >= MIN_TRAIN and te.sum() >= MIN_TEST:
                    Xtr, Xte = fit_transform(X[tr], X[te])
                    w = logreg(Xtr, y[tr])
                    sc[te] = np.hstack([Xte, np.ones((int(te.sum()), 1))]) @ w
                    folds.append({"bucket": int(tb), "n_test": int(te.sum()),
                                  "auc": round(auc(y[te], sc[te]), 4)})
            fold_data.append(folds)
            scores[tag] = sc
            report["results"].setdefault(ds, {})[f"auc_folds_{tag}"] = folds
        mask = ~np.isnan(scores["A"]) & ~np.isnan(scores["B"]) & ~np.isnan(scores["C"])
        fid = obk[mask].astype(int)
        wts = {int(b): float((obk[mask] == b).sum()) for b in np.unique(fid)}
        res = {"n_eval": int(mask.sum())}
        for pi, (p, so) in enumerate({("B", "A"): "volume_increment",
                                      ("C", "B"): "structure_increment",
                                      ("C", "A"): "total_increment"}.items()):
            per = []
            for b in np.unique(fid):
                m = mask.copy()
                m2 = np.where(mask)[0][fid == b]
                a1, a0 = auc(y[m2], scores[p[0]][m2]), auc(y[m2], scores[p[1]][m2])
                if a1 is not None and a0 is not None:
                    per.append({"bucket": int(b), "delta": round(a1 - a0, 4)})
            sc_pair = {p[0]: scores[p[0]][mask], p[1]: scores[p[1]][mask]}
            ci_s = nest_bootstrap(sc_pair, y[mask], fid, wts,
                                  [codes[i] for i in np.where(mask)[0]], pi * 2 + 1, p)
            ci_d = nest_bootstrap(sc_pair, y[mask], fid, wts,
                                  [days[i] for i in np.where(mask)[0]], pi * 2 + 2, p)
            pt = float(np.average([d["delta"] for d in per],
                                  weights=[wts[d["bucket"]] for d in per]))
            res[so] = {"per_fold": per, "weighted_point": round(pt, 4),
                       "stock_ci": [round(x, 4) for x in ci_s],
                       "date_ci": [round(x, 4) for x in ci_d],
                       "ci_excludes_zero": bool(ci_s[0] > 0 or ci_s[1] < 0)}
        report["results"][ds]["increments"] = res
        # 第二项: 缩量条件效应(层内连续量能 δ + 逐半年方向)
        # breakout 观察日=突破日, 距突破位恒 0, 无位置/动量态可言 → 不分层
        strat = {}
        for r_i, r in enumerate(rows if ds != "breakout" else []):
            if ds == "stabilization":
                v = float(r["st_close_vs_bo"])
                pos_ = "near" if abs(v) <= NEAR else ("below" if v < -NEAR else "above")
                reb = float(r["st_rebound_from_low"]) if r["st_rebound_from_low"] not in ("", "None") else np.nan
                mom = "rebound" if (not np.isnan(reb) and reb >= REBOUND) else "weak"
                key = f"{pos_}|{mom}"
                volf = "st_volrecover"
            else:
                v = float(r["sh_support_dist"])
                pos_ = "near" if abs(v) <= NEAR else ("below" if v < -NEAR else "above")
                key = pos_
                volf = "sh_volratio5"
            strat.setdefault(key, []).append(r_i)
        srep = {}
        for key, idxs in strat.items():
            yy = y[idxs]
            rec = {"n": len(idxs), "pos_rate": round(float(yy.mean()), 4)}
            vf = [float(rows[i][volf]) if rows[i][volf] not in ("", "None") else np.nan
                  for i in idxs]
            vf = np.array(vf)
            mm = ~np.isnan(vf)
            rec["vol_missing"] = round(float((~mm).mean()), 4)
            if mm.sum() > 60 and 30 <= int(((yy == 1) & mm).sum()) and 30 <= int(((yy == 0) & mm).sum()):
                d_all = cliff(vf[mm & (yy == 1)], vf[mm & (yy == 0)])
                rec["vol_cliffs_delta"] = round(d_all, 4) if d_all is not None else None
                by_h = {}
                for tb in (19, 20, 21, 22):
                    hb = np.array([obk[i] == tb for i in idxs])
                    sub = vf[hb]
                    ys = yy[hb]
                    m2 = ~np.isnan(sub)
                    d_h = cliff(sub[m2 & (ys == 1)], sub[m2 & (ys == 0)])
                    if d_h is not None:
                        by_h[str(tb)] = round(d_h, 4)
                rec["vol_delta_by_halfyear"] = by_h
            srep[key] = rec
        if ds != "breakout":
            report["stratified"][ds] = {"vol_feature": volf, "states": srep}
        else:
            report["stratified"][ds] = {"note": "突破日无位置/动量态, 不适用条件分层"}
        print(f"{ds}: n={len(rows)} B-A={res['volume_increment']['weighted_point']}"
              f" CI{res['volume_increment']['stock_ci']} | {time.time()-t0:.0f}s", flush=True)
    (OUT / "CAPITAL_BEHAVIOR_PROXY.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(f"→ CAPITAL_BEHAVIOR_PROXY.json | {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
