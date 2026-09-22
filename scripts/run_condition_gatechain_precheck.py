#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_condition_gatechain_precheck.py — 完整门槛链预检(2026-09-22 十三轮授权; 无 Y40 数值).

门槛链(DESIGN_V2 §5.2 冻结顺序), 沿用冻结匹配规则重建匹配对(确定性同参数):
1 配对资格(事件>=1 且对照>=10) — 已有
2 同日匹配(档位精确+0.2SD caliper, 全局贪心) — 复算, 不调参
3 Y40 窗口资格: d+40 在指数日历(逐折核查)
4 价格完整性: 配对双方 d+40 各自有价格行(不读价格值/Y40 值)
输出: 四折(b19-b22)覆盖表 + 逐日可用匹配对数分布 + 分母分立
(>=1 对日=可算配对差 / >=2 对日=可算 SMD) + 检验家族建议名单(固定提交)。
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
    mdates, _ = market_calendar()
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
            feat_cache[key] = (mo.get("price_vs_monthly_ma6"), mo.get("ma_spread_3_6"),
                               mo.get("trend_len_completed"), we.get("wk_close_vs_ma4"),
                               we.get("wk_up_streak"))
        return feat_cache[key]

    per_day = []
    n_ev_all = n_matched_all = n_win_ok = n_price_ok = 0
    for d in paired_days:
        evs = sorted(event_by_day[d])
        ctrls = sorted(risk_by_day[d] - set(evs))
        ct_ma4 = [feats(c, d)[3] for c in ctrls]
        ct_ma4 = [x for x in ct_ma4 if x is not None and x == x]
        sd = float(np.std(ct_ma4, ddof=1)) if len(ct_ma4) >= 2 else 0.0
        pairs = []
        if sd > 0:
            cand = []
            for e in evs:
                fe = feats(e, d)
                if fe[3] is None or fe[4] is None:
                    continue
                st_e = 2 if fe[4] >= 2 else int(fe[4])
                for c in ctrls:
                    fc = feats(c, d)
                    if fc[3] is None or fc[4] is None:
                        continue
                    st_c = 2 if fc[4] >= 2 else int(fc[4])
                    if st_e != st_c:
                        continue
                    dist = abs(fe[3] - fc[3]) / sd
                    if dist <= CALIPER:
                        cand.append((dist, e, c))
            cand.sort()
            ue, uc = set(), set()
            for dist, e, c in cand:
                if e not in ue and c not in uc:
                    ue.add(e); uc.add(c)
                    pairs.append((e, c))
        # 门槛3: Y40 窗口资格(不读价格值)
        win_ok = mpos[d] + 40 < len(mdates)
        # 门槛4(首尾口径, S2 敏感性): 双方 d+40 各自有价格行
        d40 = mdates[mpos[d] + 40] if win_ok else None
        pairs_full = []
        if d40:
            for e, c in pairs:
                if d40 in series_by_code.get(e, {}) and d40 in series_by_code.get(c, {}):
                    pairs_full.append((e, c))
        # 门槛5(H1 主样本, 原冻结 Y40 主口径): 双方 d..d+40 全部 41 个
        # 指数交易日均有价格行(完整价格路径; 不读价格值)
        pairs_path41 = []
        if win_ok:
            path_days = mdates[mpos[d]:mpos[d] + 41]
            for e, c in pairs:
                se = series_by_code.get(e, {})
                sc = series_by_code.get(c, {})
                if all(dd in se for dd in path_days) and all(dd in sc for dd in path_days):
                    pairs_path41.append((e, c))
        n_ev_all += len(evs)
        n_matched_all += len(pairs)
        n_win_ok += len(pairs) if win_ok else 0
        n_price_ok += len(pairs_full)
        per_day.append({"day": d, "bucket": obs_bucket(d), "n_ev": len(evs),
                        "n_pairs_matched": len(pairs),
                        "n_pairs_win_ok": len(pairs) if win_ok else 0,
                        "n_pairs_full": len(pairs_full),
                        "n_pairs_path41": len(pairs_path41)})
        if len(per_day) % 150 == 0:
            print(f"{len(per_day)}/{len(paired_days)} | {time.time()-t0:.0f}s", flush=True)

    def summ(rows, label):
        return {"scope": label, "n_days": len(rows),
                "days_ge1_pair": sum(1 for r in rows if r["n_pairs_path41"] >= 1),
                "days_ge2_pair": sum(1 for r in rows if r["n_pairs_path41"] >= 2),
                "pairs_matched": sum(r["n_pairs_matched"] for r in rows),
                "pairs_win_ok": sum(r["n_pairs_win_ok"] for r in rows),
                "pairs_full_endpoint": sum(r["n_pairs_full"] for r in rows),
                "pairs_full_path41": sum(r["n_pairs_path41"] for r in rows),
                "days_ge1_endpoint": sum(1 for r in rows if r["n_pairs_full"] >= 1),
                "pairs_per_day_p50": float(np.median([r["n_pairs_path41"] for r in rows])) if rows else None}

    rep = {"audit": "MULTIPERIOD_CONDITION_GATECHAIN_PRECHECK", "date": "2026-09-22",
           "y40_read": False,
           "gates": "1 配对资格 → 2 冻结匹配 → 3 d+40 在指数日历 → 4 首尾完整(S2) → 5 全路径 41 日完整(H1 主口径, 原冻结)",
           "overall": summ(per_day, "ALL"),
           "by_fold": {b: summ([r for r in per_day if r["bucket"] == b], f"b{b}") for b in FOLDS},
           "other_buckets": {b: summ([r for r in per_day if r["bucket"] == b], f"b{b}")
                             for b in sorted({r["bucket"] for r in per_day}) if b not in FOLDS},
           "per_day_rows": per_day,
           "family_proposal": {
               "note": "固定检验家族名单(提交复审; 门槛链结果之上, 不依平衡表挑选)",
               "family": [
                   {"id": "H1", "role": "主检验",
                    "test": "量-2 匹配样本同日配对 Y40 差 Δ_d 序列折合并 ≠ 0 (日期块主推断 2000 抽)",
                    "enter_holm": True},
                   {"id": "S1", "role": "股票聚集敏感性(非主推断)",
                    "test": "H1 点估计/区间按股票块重抽复算, 分歧如实并报", "enter_holm": False},
                   {"id": "S2", "role": "窗口敏感性",
                    "test": "窗口完整性口径(仅 d+40 首尾 vs 全窗逐日)下 H1 稳定性", "enter_holm": False},
                   {"id": "D1", "role": "描述(量-1)",
                    "test": "未调整组间差(事件 vs 同日对照), 仅描述不推断", "enter_holm": False}],
               "holm_family_size": 1,
               "note2": "量-1 与敏感性不进 Holm; Q-A(Δ=5/Δ=1) 家族另行冻结"}}
    (OUT / "MULTIPERIOD_CONDITION_GATECHAIN_PRECHECK.json").write_text(json.dumps(rep, ensure_ascii=False))
    o = rep["overall"]
    n_path41 = sum(r["n_pairs_path41"] for r in per_day)
    print(f"门槛链: 匹配 {n_matched_all} → 窗口 {n_win_ok} → 首尾 {n_price_ok} → 全路径41 {n_path41} | "
          f"日(>=1对/>=2对) {o['days_ge1_pair']}/{o['days_ge2_pair']} | {time.time()-t0:.0f}s", flush=True)
    print("→ MULTIPERIOD_CONDITION_GATECHAIN_PRECHECK.json")


if __name__ == "__main__":
    main()
