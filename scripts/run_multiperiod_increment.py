#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_multiperiod_increment.py — 多周期背景增量主实验(设计 b42fe58, 有条件批准已生效).

四模型 A0/B0/A1/B1 × 三时点; 六项主比较:
  ΔIC_周价(s)=IC_A1−IC_A0; ΔIC_日量(s)=IC_B1−IC_A1; Holm(6)。
B0 复现两层门禁(五位小数一致 + 折级完整精度 1e-10)先于一切推断。
B2 预定义不运行。分组诊断=mc_pos 组内 ΔIC_日量(预定义探索性)。
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
from forward_y40_lib import (build_events, fold_start, obs_bucket, ridge,  # noqa: E402
                             ridge_predict, fit_transform, spearman, cont_40d_blocks,
                             block_boot_delta, centered_p, holm, MIN_TRAIN,
                             MIN_TEST, MIN_STK_PER_DAY, BOOT, SEED)
from run_forward_y40_association import FEATS, FOLDS  # noqa: E402
from multiperiod_lib import PRICE_FEATS, build_a1_features, assert_price_only_source  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
OLD = json.load(open(ROOT / "docs/reports/FORWARD_Y40_ASSOCIATION_V1.json"))


def stage_models(ds: str) -> dict[str, list[str]]:
    a0 = FEATS[ds]["A"]
    b0 = FEATS[ds]["B"]
    inc = [c for c in b0 if c not in a0]        # v1 日线量能增量列
    a1 = a0 + PRICE_FEATS
    b1 = a1 + inc
    return {"A0": a0, "B0": b0, "A1": a1, "B1": b1}


def run_stage(ds: str) -> dict:
    main, sens, censored = build_events(ds)
    a1tab = build_a1_features(main)
    for e in main:
        f = a1tab[(e["code"], e["obs_day"])]
        for k in PRICE_FEATS:
            e[k] = f[k]
    y = np.array([e["y40"] for e in main])
    models = stage_models(ds)
    days = np.array([e["obs_day"] for e in main])
    # 特征矩阵(一次性按全集列构造, 各模型取列)
    allcols = sorted({c for cols in models.values() for c in cols})
    colpos = {c: i for i, c in enumerate(allcols)}

    def fval(e, c):
        v = e.get(c, "")
        if v in ("", None, "None") or (isinstance(v, float) and np.isnan(v)):
            return np.nan
        return float(v)

    Xfull = np.array([[fval(e, c) for c in allcols] for e in main])
    preds_all = {tag: np.full(len(main), np.nan) for tag in models}
    fold_rows = []
    per_fold_ic = {tag: [] for tag in models}       # 每元素 (ic_dict_by_day)
    for tb in FOLDS:
        fs = fold_start(tb)
        tr = np.array([i for i, e in enumerate(main)
                       if obs_bucket(e["obs_day"]) < tb and e["label_avail_day"] < fs])
        te = np.array([i for i, e in enumerate(main) if obs_bucket(e["obs_day"]) == tb])
        if len(tr) < MIN_TRAIN or len(te) < MIN_TEST:
            fold_rows.append({"test_bucket": tb, "completed": False,
                              "n_train": int(len(tr)), "n_test": int(len(te))})
            for tag in models:
                per_fold_ic[tag].append({})
            continue
        te_pos = {int(i): k for k, i in enumerate(te)}
        by_date = defaultdict(list)
        for i in te:
            by_date[main[i]["obs_day"]].append(int(i))
        fr = {"test_bucket": tb, "completed": True,
              "n_train": int(len(tr)), "n_test": int(len(te))}
        for tag, cols in models.items():
            ci = [colpos[c] for c in cols]
            Ztr, Zte, _ = fit_transform(Xfull[np.ix_(tr, ci)], Xfull[np.ix_(te, ci)])
            m = ridge(Ztr, y[tr])
            p = ridge_predict(m, Zte)
            preds_all[tag][te] = p
            resid = y[te] - p
            fr[f"metrics_{tag}"] = {
                "mse": float(np.mean(resid ** 2)), "mae": float(np.mean(np.abs(resid)))}
            icd = {}
            for d, idxs in sorted(by_date.items()):
                if len(idxs) < MIN_STK_PER_DAY:
                    continue
                ii = np.array(idxs)
                kk = np.array([te_pos[i] for i in ii])
                v = spearman(y[ii], p[kk])
                if v is not None and np.isfinite(v):
                    icd[d] = v
            fr[f"mean_ic_{tag}"] = float(np.mean(list(icd.values()))) if icd else None
            fr[f"n_valid_days_{tag}"] = len(icd)
            per_fold_ic[tag].append(icd)
        fold_rows.append(fr)
    # ---- B0 复现两层门禁(先于推断) ----
    rep = {}
    viol = []
    for tag_old, tag_new in (("A", "A0"), ("B", "B0")):
        for f_old, f_new in zip(OLD["stages"][ds]["folds"], fold_rows):
            if not f_new.get("completed"):
                continue
            for key in (f"mean_ic_{tag_old}",):
                a, b = f_old[key], f_new[f"mean_ic_{tag_new}"]
                if a is not None and (b is None or abs(a - b) > 1e-10):
                    viol.append(f"{ds} b{f_old['test_bucket']} {key} {a} vs {b}")
            for mk in ("mse", "mae"):
                a = f_old[f"metrics_{tag_old}"][mk]
                b = f_new[f"metrics_{tag_new}"][mk]
                if abs(a - b) > 1e-10:
                    viol.append(f"{ds} b{f_old['test_bucket']} {tag_old}.{mk} {a} vs {b}")
            if f_old["n_train"] != f_new["n_train"] or f_old["n_test"] != f_new["n_test"]:
                viol.append(f"{ds} b{f_old['test_bucket']} n_train/n_test 不符")
    # 层1: B0−A0 五位小数
    def weighted_point(ic_x, ic_y):
        num = den = 0.0
        for dx, dy in zip(per_fold_ic[ic_x], per_fold_ic[ic_y]):
            ks = [d for d in dx if d in dy]
            if ks:
                num += np.mean([dy[d] - dx[d] for d in ks]) * len(ks)
                den += len(ks)
        return num / den if den else None
    pt_b0a0 = weighted_point("A0", "B0")
    old5 = round(OLD["stages"][ds]["primary"]["weighted_delta_ic_point"], 5)
    if pt_b0a0 is None or round(pt_b0a0, 5) != old5:
        viol.append(f"{ds} 层1: B0-A0 {pt_b0a0} 五位小数 != 旧 {old5}")
    rep["b0_reproduction"] = {"ok": not viol, "violations": viol[:20],
                              "b0_minus_a0_full": pt_b0a0, "old_rounded": old5}
    if viol:
        return {"b0_reproduction": rep["b0_reproduction"], "ABORTED": True,
                "n_main": len(main)}
    # ---- 六项主比较(本时点两项) ----
    def delta_boot(tag_x, tag_y):
        fold_icd = []
        num = den = 0.0
        for dx, dy in zip(per_fold_ic[tag_x], per_fold_ic[tag_y]):
            ks = [d for d in dx if d in dy]
            fold_icd.append(({d: dy[d] - dx[d] for d in ks},
                             cont_40d_blocks(sorted(ks)), len(ks)))
            if ks:
                num += np.mean([dy[d] - dx[d] for d in ks]) * len(ks)
                den += len(ks)
        point = num / den if den else None
        if point is None:
            return {"point": None}
        boot = block_boot_delta(fold_icd)
        return {"point": round(float(point), 5),
                "point_full": float(point),
                "ci95": [round(float(np.percentile(boot, 2.5)), 5),
                         round(float(np.percentile(boot, 97.5)), 5)],
                "p": centered_p(boot, float(point)),
                "n_valid_days": int(den)}
    rep["dIC_week_price_A1mA0"] = delta_boot("A0", "A1")
    rep["dIC_day_vol_B1mA1"] = delta_boot("A1", "B1")
    # ---- 分组诊断(mc_pos; 预定义探索性, 不属主检验) ----
    grp = {}
    for g in (True, False, None):
        sub = [i for i, e in enumerate(main) if e["mc_pos"] is g]
        days_g = sorted({main[i]["obs_day"] for i in sub})
        if len(sub) < 200 or len(days_g) < 40:
            grp[str(g)] = {"n": len(sub), "verdict": "不可检验(样本/有效日不足)"}
            continue
        idxset = set(sub)
        # 日级分组 IC: 按组内事件重算 spearman(B1/A1 各自 pred)
        fold_icd = []
        for tb in FOLDS:
            fs = fold_start(tb)
            te = [i for i, e in enumerate(main)
                  if obs_bucket(e["obs_day"]) == tb and e["mc_pos"] is g]
            if len(te) < MIN_TEST:
                fold_icd.append(({}, [], 0))
                continue
            by_date = defaultdict(list)
            for i in te:
                by_date[main[i]["obs_day"]].append(i)
            icd = {}
            for d, ii in sorted(by_date.items()):
                if len(ii) < MIN_STK_PER_DAY:
                    continue
                arr = np.array(ii)
                a = spearman(y[arr], preds_all["A1"][arr])
                b = spearman(y[arr], preds_all["B1"][arr])
                if a is not None and b is not None and np.isfinite(a) and np.isfinite(b):
                    icd[d] = b - a
            fold_icd.append((icd, cont_40d_blocks(sorted(icd)), len(icd)))
        pts = [np.mean(list(icd.values())) * n for icd, _, n in fold_icd if n]
        tot = sum(n for _, _, n in fold_icd)
        if tot == 0:
            grp[str(g)] = {"n": len(sub), "verdict": "不可检验(无有效日)"}
        else:
            grp[str(g)] = {"n": len(sub), "n_valid_days": tot,
                           "point": round(float(sum(pts) / tot), 5)}
    rep["group_diag_mc_pos"] = grp
    rep["n_main"] = len(main)
    rep["folds"] = fold_rows
    rep["model_features"] = {t: c for t, c in models.items()}
    # ---- 股票块频数敏感性(周价/日量两项; 无重训, 复用 preds_all) ----
    codes = np.array([e["code"] for e in main])
    by_stock = defaultdict(list)
    for i, c in enumerate(codes):
        by_stock[c].append(i)
    stocks = list(by_stock)
    sk = np.array(stocks)
    rng = np.random.default_rng(SEED + 7)
    sens = {}
    for name, tx, ty in (("week_price", "A0", "A1"), ("day_vol", "A1", "B1")):
        pts_ = []
        for _ in range(BOOT):
            cnt = defaultdict(int)
            for _ in range(len(stocks)):
                cnt[sk[rng.integers(len(sk))]] += 1
            dd = defaultdict(list)
            ddc = defaultdict(set)
            for s_, k in cnt.items():
                for i in by_stock[s_]:
                    if not np.isnan(preds_all[tx][i]) and not np.isnan(preds_all[ty][i]):
                        dd[days[i]].extend([i] * k)
                        ddc[days[i]].add(s_)
            vals = []
            for d, ix in dd.items():
                if len(ddc[d]) < MIN_STK_PER_DAY:
                    continue
                arr = np.array(ix)
                a = spearman(y[arr], preds_all[tx][arr])
                b = spearman(y[arr], preds_all[ty][arr])
                if a is not None and b is not None:
                    vals.append(b - a)
            if vals:
                pts_.append(float(np.mean(vals)))
        pts_ = np.array(pts_)
        sens[name] = {"ci95": [round(float(np.percentile(pts_, 2.5)), 5),
                               round(float(np.percentile(pts_, 97.5)), 5)],
                      "n_draws_valid": len(pts_)}
    rep["stock_block_sensitivity"] = sens
    return rep


def main():
    t0 = time.time()
    assert_price_only_source()
    print("A1 零量能源审计通过", flush=True)
    report = {"experiment": "MULTIPERIOD_INCREMENT_V1",
              "design": "MULTIPERIOD_INCREMENT_DESIGN_V1 @ b42fe58",
              "seed": SEED, "boot": BOOT, "models_run": ["A0", "B0", "A1", "B1"],
              "b2_run": False, "stages": {}}
    for ds in ("breakout", "shrink", "stabilization"):
        t1 = time.time()
        r = run_stage(ds)
        report["stages"][ds] = r
        if r.get("ABORTED"):
            print(f"{ds}: B0 复现门禁失败, 中止", flush=True)
            break
        print(f"{ds}: 周价 {r['dIC_week_price_A1mA0'].get('point')} "
              f"| 日量 {r['dIC_day_vol_B1mA1'].get('point')} "
              f"| B0复现 ok={r['b0_reproduction']['ok']} | {time.time()-t1:.0f}s", flush=True)
    # Holm(6)
    comps = []
    for ds in ("breakout", "shrink", "stabilization"):
        st = report["stages"].get(ds, {})
        for key, label in (("dIC_week_price_A1mA0", "week_price"),
                           ("dIC_day_vol_B1mA1", "day_vol")):
            d = st.get(key, {})
            if d.get("p") is not None:
                comps.append((f"{ds}|{label}", d["p"]))
    if comps:
        names = [c[0] for c in comps]
        padj = holm([c[1] for c in comps])
        report["holm"] = {"comparisons": names,
                          "raw_p": {n: p for n, p in comps},
                          "holm_adj_p": {n: float(a) for n, a in zip(names, padj)},
                          "family_size": len(names)}
    report["elapsed_s"] = round(time.time() - t0, 1)
    (OUT / "MULTIPERIOD_INCREMENT_V1.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1))
    print(f"→ MULTIPERIOD_INCREMENT_V1.json | 总 {report['elapsed_s']}s", flush=True)


if __name__ == "__main__":
    main()
