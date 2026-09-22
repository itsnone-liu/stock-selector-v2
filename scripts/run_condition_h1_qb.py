#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_h1_qb.py — Q-B H1 主检验(2026-09-22 十五轮授权; 测试已全过后执行一次).

授权: 三项合成反例测试 ALL PASS(验证 condition_h1stats.h1_test 本体)后,
按冻结版本执行一次 Q-B H1 主检验+既定敏感性。Y40 数值在本脚本读取(首次)。

冻结链: 匹配规则(档位精确+0.2SD 全局贪心)→门槛 5(全路径 41 日)→
Δ_d=当日配对差 y40_e−y40_c 均值→θ̂ 按有效日数加权→日期块折内重抽
(2000, seed=20260922)→中心化 p / percentile CI(§5.5)。

S1 股票块敏感性(§5.1): 配对按事件股分组, 事件股 40 股环形块重抽
(2000, seed=20260922), 重算 Δ_d→θ̂*; 与主推断分歧如实并报。
D1 描述(量-1): 未调整组间差(事件组 vs 同日全部合格对照)仅描述。
"""
from __future__ import annotations

import glob
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "scripts"))
import duckdb  # noqa: E402
from multiperiod_lib import load_price_series  # noqa: E402
from forward_y40_lib import market_calendar, obs_bucket  # noqa: E402
from run_condition_stage0_audit import monthly_states, weekly_states  # noqa: E402
from run_condition_riskset_v2 import independent_code_map  # noqa: E402
from condition_h1stats import h1_test, SEED, NBOOT  # noqa: E402

OUT = ROOT / "output/research/posneg_v1"
PANEL = ROOT / "output/research/momentum_panel_v3"
CALIPER = 0.2
FOLDS = (19, 20, 21, 22)


def main():
    t0 = time.time()
    cmap = independent_code_map()
    con = duckdb.connect()
    files = glob.glob(str(ROOT / "output/research/lifecycle_v1/lifecycle_stage4_v1_full/**/*.parquet"), recursive=True)
    df = con.execute(f"""
        select code, lifecycle_id, anchor_day, breakout_day, end_day
        from read_parquet({files!r})""").fetchall()
    lc = {lid: (code, anchor, bo, end) for code, lid, anchor, bo, end in df}
    pool_in = defaultdict(dict)
    want = {v[0].split(".")[-1] if "." in v[0] else v[0] for v in lc.values()}
    import csv
    with open(PANEL / "universe_state_panel.csv") as f:
        for r in csv.DictReader(f):
            if r["code"] in want:
                pool_in[r["code"]][r["date"]] = (r["monthly_pool_state"] == "in")
    mdates, iclose = market_calendar()
    mpos = {d: i for i, d in enumerate(mdates)}
    risk_by_day = defaultdict(set)
    series_by_code = {}
    for lid, (code, anchor, bo, end) in lc.items():
        c6 = code.split(".")[-1] if "." in code else code
        full = cmap.get(c6)
        if full is None or anchor not in mpos:
            continue
        a_i = mpos[anchor]
        s_i = mpos[bo] + 1 if (bo and bo in mpos) else min(mpos.get(end, len(mdates)), a_i + 120, len(mdates) - 1)
        try:
            closes = load_price_series(full)
        except FileNotFoundError:
            continue
        series_by_code[c6] = closes
        dayset = set(closes.keys())
        pin = pool_in.get(c6, {})
        for d in mdates[a_i:s_i]:
            if d in dayset and pin.get(d):
                risk_by_day[d].add(c6)
    event_by_day = defaultdict(set)
    for lid, (code, anchor, bo, end) in lc.items():
        c6 = code.split(".")[-1] if "." in code else code
        if bo and cmap.get(c6) and bo in mpos and c6 in risk_by_day.get(bo, set()):
            event_by_day[bo].add(c6)
    print(f"风险集重建 | {time.time()-t0:.0f}s", flush=True)

    paired_days = [d for d, evs in sorted(event_by_day.items())
                   if len(evs) >= 1 and len(risk_by_day[d] - evs) >= 10]
    feat_cache = {}

    def feats(c6, d):
        key = (c6, d)
        if key not in feat_cache:
            closes = series_by_code[c6]
            mo = monthly_states(closes, d)
            we = weekly_states(closes, d)
            feat_cache[key] = (we.get("wk_close_vs_ma4"), we.get("wk_up_streak"))
        return feat_cache[key]

    def y40_of(c6, d, i_d):
        """Y40=ln(P[d+40]/P[d])−ln(I[d+40]/I[d]); 已过门槛 5 保证端点存在."""
        s = series_by_code[c6]
        return (np.log(s[mdates[i_d + 40]] / s[d])
                - np.log(iclose[i_d + 40] / iclose[i_d]))

    day_deltas, fold_of_day, pairs_all, d1_day_deltas = {}, {}, [], {}
    for d in paired_days:
        i_d = mpos[d]
        if not (i_d + 40 < len(mdates)):
            continue
        evs = sorted(event_by_day[d])
        ctrls = sorted(risk_by_day[d] - set(evs))
        ct_ma4 = [feats(c, d)[0] for c in ctrls]
        ct_ma4 = [x for x in ct_ma4 if x is not None and x == x]
        sd = float(np.std(ct_ma4, ddof=1)) if len(ct_ma4) >= 2 else 0.0
        if sd <= 0:
            continue
        cand = []
        for e in evs:
            fe = feats(e, d)
            if fe[0] is None or fe[1] is None:
                continue
            st_e = 2 if fe[1] >= 2 else int(fe[1])
            for c in ctrls:
                fc = feats(c, d)
                if fc[0] is None or fc[1] is None:
                    continue
                st_c = 2 if fc[1] >= 2 else int(fc[1])
                if st_e != st_c:
                    continue
                if abs(fe[0] - fc[0]) / sd <= CALIPER:
                    cand.append((abs(fe[0] - fc[0]) / sd, e, c))
        cand.sort()
        ue, uc = set(), set()
        pairs = []
        for dist, e, c in cand:
            if e not in ue and c not in uc:
                ue.add(e); uc.add(c)
                se, sc = series_by_code.get(e, {}), series_by_code.get(c, {})
                path = mdates[i_d:i_d + 41]
                if all(x in se for x in path) and all(x in sc for x in path):
                    pairs.append((e, c))
        if not pairs:
            continue
        diffs = [float(y40_of(e, d, i_d) - y40_of(c, d, i_d)) for e, c in pairs]
        day_deltas[d] = float(np.mean(diffs))
        fold_of_day[d] = obs_bucket(d)
        for (e, c), df_ in zip(pairs, diffs):
            pairs_all.append({"day": d, "ev": e, "ct": c, "diff": df_})
        # D1: 未调整组间差(事件组 vs 同日全部合格对照, 不匹配, 仅描述)
        ev_y = [float(y40_of(e, d, i_d)) for e in evs
                if mdates[i_d + 40] in series_by_code.get(e, {})]
        ct_y = [float(y40_of(c, d, i_d)) for c in ctrls
                if mdates[i_d + 40] in series_by_code.get(c, {})]
        if ev_y and ct_y:
            d1_day_deltas[d] = float(np.mean(ev_y) - np.mean(ct_y))
        if len(day_deltas) % 150 == 0:
            print(f"{len(day_deltas)} 日 | {time.time()-t0:.0f}s", flush=True)

    # H1 主检验(折内日期块重抽, h1_test 本体)
    h1 = h1_test(day_deltas, fold_of_day, FOLDS, seed=SEED, nboot=NBOOT)
    # S1 股票块敏感性: 配对按事件股分组, 40 股环形块重抽
    rng = np.random.default_rng(SEED)
    by_ev = defaultdict(list)
    for p in pairs_all:
        by_ev[p["ev"]].append(p)
    evs_sorted = sorted(by_ev)
    n = len(evs_sorted)
    stars = []
    for b in range(NBOOT):
        starts = rng.integers(0, n, size=int(np.ceil(n / 40)))
        picked = []
        for s in starts:
            for j in range(40):
                picked.extend(by_ev[evs_sorted[(s + j) % n]])
        rd = defaultdict(list)
        for p in picked:
            rd[p["day"]].append(p["diff"])
        rs_deltas = {d: float(np.mean(v)) for d, v in rd.items()}
        stars.append(h1_test_static(rs_deltas, fold_of_day))
    stars = np.array(stars)
    t_b = stars - h1["theta"]
    p_s1 = (1 + int(np.sum(np.abs(t_b) >= abs(h1["theta"])))) / (NBOOT + 1)
    s1 = {"theta": h1["theta"],
          "ci_lo": float(np.percentile(stars, 2.5)),
          "ci_hi": float(np.percentile(stars, 97.5)),
          "p": float(p_s1), "note": "股票块重抽(事件股 40 股环形块); 分歧如实并报"}
    # D1
    d1_folds = {}
    for f in FOLDS:
        ds = [v for d, v in d1_day_deltas.items() if obs_bucket(d) == f]
        d1_folds[f] = float(np.mean(ds)) if ds else None
    d1 = {"day_mean_overall": float(np.mean(list(d1_day_deltas.values()))) if d1_day_deltas else None,
          "by_fold": d1_folds, "role": "量-1 未调整组间差, 仅描述不推断"}

    rep = {"audit": "MULTIPERIOD_CONDITION_H1_QB", "date": "2026-09-22",
           "authorized_by": "十五轮(合成测试 ALL PASS 后执行一次)",
           "h1": h1, "s1": s1, "d1": d1,
           "n_pairs": len(pairs_all), "n_days": len(day_deltas),
           "n_days_by_fold": {f: sum(1 for d in day_deltas if fold_of_day[d] == f) for f in FOLDS},
           "formula": "§5.5 十五轮: 中心化 p=(1+Σ1(|θ̂*−θ̂|>=|θ̂|))/2001; CI=未中心化 percentile",
           "per_day_delta_examples": {d: day_deltas[d] for d in list(sorted(day_deltas))[:5]}}
    (OUT / "MULTIPERIOD_CONDITION_H1_QB.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1))
    print(f"H1: theta={h1['theta']:+.5f} CI=[{h1['ci_lo']:.5f},{h1['ci_hi']:.5f}] p={h1['p']:.4f} | "
          f"日 {h1['n_days']} 对 {len(pairs_all)} | {time.time()-t0:.0f}s", flush=True)
    print(f"S1: CI=[{s1['ci_lo']:.5f},{s1['ci_hi']:.5f}] p={s1['p']:.4f}")
    print(f"D1 描述: 全期日均 {d1['day_mean_overall']:+.5f} | 折 {[f'{v:+.4f}' if v else 'NA' for v in d1_folds.values()]}")
    print("→ MULTIPERIOD_CONDITION_H1_QB.json")


def h1_test_static(day_deltas, fold_of_day):
    """θ̂ 静态计算(供 S1 重抽内部用, 与 h1_test 同加权)."""
    w, th = {}, {}
    for f in FOLDS:
        ds = [d for d in day_deltas if fold_of_day.get(d) == f]
        if ds:
            w[f] = len(ds)
            th[f] = float(np.mean([day_deltas[d] for d in ds]))
    tot = sum(w.values())
    return sum(w[f] / tot * th[f] for f in w)


if __name__ == "__main__":
    main()
