#!/usr/bin/env python3
"""T4.4 Context Structure Discovery：构建 + 结构分析 + 决策矩阵 + 双跑。"""
from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2          # noqa: E402
from t4.discovery import analysis_discovery as ad        # noqa: E402
from t4.discovery import sector_primitives as sp         # noqa: E402

BASELINE = "28b1d48"
OUT = ROOT / "output/research/t4/discovery"
OUT.mkdir(parents=True, exist_ok=True)
SEC_PCT_COLS = ["sec_breadth_d5_loo", "sec_nh_density_loo",
                "sec_rel_breadth_d5", "sec_rel_strength20"]


def frame_hash(df: pd.DataFrame, keys=("breakout_event_id",)) -> str:
    h = hashlib.sha256()
    d = df.sort_values(list(keys)).reset_index(drop=True)
    h.update(d.to_csv(index=False).encode("utf-8"))
    h.update(str(d.shape).encode())
    h.update(str(list(df.columns)).encode())
    return h.hexdigest()


def cell_table(panel: pd.DataFrame, rows_col: str, cols_col: str,
               value_col: str, row_vals, col_vals) -> tuple:
    """格中位数表 + n 表。"""
    T, N = np.full((len(row_vals), len(col_vals), ), np.nan), np.zeros(
        (len(row_vals), len(col_vals)), int)
    for i, rv in enumerate(row_vals):
        for j, cv in enumerate(col_vals):
            g = panel[(panel[rows_col] == rv) & (panel[cols_col] == cv)
                      & panel[value_col].notna()]
            if len(g):
                T[i, j] = float(g[value_col].median())
                N[i, j] = len(g)
    return T, N


def main():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    assert head == BASELINE, f"HEAD {head} != {BASELINE}"
    t0w = time.time()
    events = v2.load_events()
    cs = pd.read_parquet(ROOT / "output/research/t4/context_path/"
                         "t4_context_state.parquet")
    oc = pd.read_parquet(ROOT / "output/research/t4/context_path/"
                         "t4_context_path_outcomes.parquet")
    panel0 = cs.merge(oc, on=["breakout_event_id", "code", "breakout_day"])
    panel0["year"] = panel0["breakout_day"].str[:4]

    # ---- sector primitives（LOO）----
    sec = sp.build_sector_primitives(events)
    sec = sp.attach_asof_pct(sec, SEC_PCT_COLS)
    print(f"[t4.4] sector primitives {sec.shape} "
          f"coverage={sec['sec_rel_strength20'].notna().mean():.4f} "
          f"{time.time() - t0w:.0f}s", flush=True)
    sec["pit_primary_eligible"] = False
    sec["is_point_in_time"] = False
    sec["retrospective_context_only"] = True
    sec["membership_snapshot_date"] = "2026-09-21"
    sec["loo_rule"] = "sector aggregates exclude focal stock " \
                      "(decomposable stats only)"
    sec.to_parquet(OUT / "t4_sector_context.parquet", index=False)

    panel = panel0.merge(
        sec.drop(columns=["breakout_day"]), on=["breakout_event_id"],
        how="left")
    panel["hi_load"] = (panel["turnover_load_t0"] > 1).where(
        panel["turnover_load_t0"].notna())
    panel["hi_ref60"] = panel["t0_ref60_breakout"].astype("float").where(
        panel["t0_ref60_breakout"].notna())
    # market 分位（T4.3 冻结）与 sector 分位（本阶段）
    for c, q in (("breadth_5d_asof_pct", "M_breadth"),
                 ("new_high_20d_asof_pct", "M_newhigh")):
        panel[q] = panel[c]
    panel["S_relstrength"] = panel["sec_rel_strength20_asof_pct"]
    panel["S_relbreadth"] = panel["sec_rel_breadth_d5_asof_pct"]

    # ================= 1. Market 二维结构 =================
    rows2d = []
    for h in (10, 20, 40):
        ph = panel[(panel["horizon"] == h)
                   & panel["fwd_mkt_excess_log"].notna()]
        for metric, col in (("median_excess", "fwd_mkt_excess_log"),
                            ("median_mdd", "future_max_drawdown"),
                            ("p_new_high", "new_high_within"),
                            ("p_lose_ref20", "lose_ref20_within")):
            sub = ph.copy()
            if metric in ("p_new_high", "p_lose_ref20"):
                sub[col] = sub[col].astype(float)
            T, N = cell_table(sub, "new_high_20d_q", "breadth_5d_q",
                              col if metric not in (
                                  "median_mdd",) else col,
                              ["Q1", "Q2", "Q3", "Q4"],
                              ["Q1", "Q2", "Q3", "Q4"]) if metric != \
                "median_mdd" else cell_table(
                sub.dropna(subset=[col]), "new_high_20d_q", "breadth_5d_q",
                col, ["Q1", "Q2", "Q3", "Q4"], ["Q1", "Q2", "Q3", "Q4"])
            grand, reff, ceff, resid, ratio = ad.median_polish(T)
            # 条件化：within new-high Q 的 breadth Q4−Q1（EW/DB/boot）
            cond = {}
            for nq in ("Q2", "Q3"):
                r = ad.conditional_contrast(
                    sub, "new_high_20d_q", (nq,), "breadth_5d_q", col)
                cond[f"breadth_effect_within_newhigh_{nq}"] = r
            cond_rev = {}
            for bq in ("Q2", "Q3"):
                r = ad.conditional_contrast(
                    sub, "breadth_5d_q", (bq,), "new_high_20d_q", col)
                cond_rev[f"newhigh_effect_within_breadth_{bq}"] = r
            rows2d.append({
                "horizon": h, "metric": metric,
                "table": json.dumps(np.where(np.isfinite(T),
                                             np.round(T, 4), None)
                                    .tolist()),
                "n_table": json.dumps(N.tolist()),
                "polish_interaction_ratio": ratio,
                **{f"{k}_{kk}": vv for k, r in cond.items()
                   for kk, vv in r.items()},
                **{f"rev_{k}_{kk}": vv for k, r in cond_rev.items()
                   for kk, vv in r.items()}})
    m2d = pd.DataFrame(rows2d)
    m2d.to_parquet(OUT / "t4_market_2d_structure.parquet", index=False)
    print(f"[t4.4] market 2d {m2d.shape} {time.time() - t0w:.0f}s",
          flush=True)

    # 分年 surface 稳定性（median_excess h20 的 polish ratio per year）
    yr_rows = []
    for y, gy in panel[(panel["horizon"] == 20)
                       & panel["fwd_mkt_excess_log"].notna()
                       ].groupby("year"):
        T, N = cell_table(gy, "new_high_20d_q", "breadth_5d_q",
                          "fwd_mkt_excess_log",
                          ["Q1", "Q2", "Q3", "Q4"], ["Q1", "Q2", "Q3", "Q4"])
        _, _, _, resid, ratio = ad.median_polish(T)
        yr_rows.append({"year": y, "polish_interaction_ratio": ratio,
                        "n_cells_filled": int((N > 0).sum())})
    pd.DataFrame(yr_rows).to_csv(OUT / "t4_market2d_yearly.csv", index=False)

    # ================= 2. M -> S =================
    ms_rows = []
    ph = panel[(panel["horizon"] == 20) & panel["fwd_mkt_excess_log"]
               .notna() & panel["S_relstrength"].notna()]
    for s_col, s_name in (("S_relstrength", "sector_rel_strength"),
                          ("S_relbreadth", "sector_rel_breadth")):
        sub = ph[ph[s_col].notna()].copy()
        sub["S_q"] = pd.qcut(sub[s_col], 4, labels=["Q1", "Q2", "Q3", "Q4"], duplicates="drop")
        for mq in ("Q1", "Q2", "Q3", "Q4"):
            g = sub[sub["M_breadth"].notna()].copy()
            g["M_q_tmp"] = pd.qcut(g["M_breadth"], 4,
                                   labels=["Q1", "Q2", "Q3", "Q4"])
            gg = g[g["M_q_tmp"] == mq]
            if not len(gg):
                continue
            vals = gg["fwd_mkt_excess_log"].astype(float).to_numpy()
            grp = (gg["S_q"] == "Q4").astype(int).to_numpy()
            r = ad.q4_minus_q1_ew_db(vals, grp,
                                     gg["breakout_day"].to_numpy(),
                                     gg["code"].to_numpy())
            ms_rows.append({"sector_dim": s_name, "within_market_breadth_q":
                            mq, **r, "n": int(len(gg))})
    ms = pd.DataFrame(ms_rows)
    ms.to_parquet(OUT / "t4_market_sector_structure.parquet", index=False)
    print(f"[t4.4] M->S {ms.shape} {time.time() - t0w:.0f}s", flush=True)

    # ================= 3. M × S 可加性 + 三层 =================
    ph3 = panel[(panel["horizon"] == 20) & panel["fwd_mkt_excess_log"]
                .notna() & panel["S_relstrength"].notna()].copy()
    T, N = cell_table(ph3.assign(
        M4=pd.qcut(ph3["M_breadth"], 4, labels=["Q1", "Q2", "Q3", "Q4"]),
        S4=pd.qcut(ph3["S_relstrength"], 4,
                   labels=["Q1", "Q2", "Q3", "Q4"])),
        "M4", "S4", "fwd_mkt_excess_log",
        ["Q1", "Q2", "Q3", "Q4"], ["Q1", "Q2", "Q3", "Q4"])
    grand, reff, ceff, resid, ratio_ms = ad.median_polish(T)
    # 2×2 DiD（M/S 中位二分）
    ph3["M_hi"] = ph3["M_breadth"] >= .5
    ph3["S_hi"] = ph3["S_relstrength"] >= .5
    vals = ph3["fwd_mkt_excess_log"].astype(float).to_numpy()
    cell = (ph3["M_hi"].astype(int) * 2 + ph3["S_hi"].astype(int)).to_numpy()
    dates = ph3["breakout_day"].to_numpy()
    stocks = ph3["code"].to_numpy()
    duniq, dinv = np.unique(dates, return_inverse=True)
    idx = np.arange(len(vals))
    dmap = {k: idx[dinv == k] for k in range(len(duniq))}

    def _did(rows):
        c = [float(np.median(vals[rows][cell[rows] == k]))
             for k in range(4)]
        if not all(np.isfinite(x) for x in c):
            return np.nan
        return (c[3] - c[1]) - (c[2] - c[0])

    did_pt = _did(np.arange(len(vals)))
    stats = []
    for b in range(ad.N_BOOT):
        pick = ad.RNG.choice(np.fromiter(dmap.keys(), dtype=int),
                          size=len(dmap), replace=True)
        stats.append(_did(np.concatenate([dmap[k] for k in pick])))
    v = np.array([x for x in stats if np.isfinite(x)])
    p_ms = float(min(1.0, 2 * min((v <= 0).mean(), (v >= 0).mean())))
    # 三层：within (M_hi, S_hi) 格的 load hi−lo 与 ref60 hi−lo
    tl_rows = []
    for m in (False, True):
        for s in (False, True):
            g = ph3[(ph3["M_hi"] == m) & (ph3["S_hi"] == s)]
            for sd, sname in (("hi_load", "load"),
                              ("hi_ref60", "ref60")):
                gg = g[g[sd].notna()]
                if not len(gg):
                    continue
                vv = gg["fwd_mkt_excess_log"].astype(float).to_numpy()
                gs = gg[sd].astype(bool).astype(int).to_numpy()
                lo_ = vv[gs == 0]
                hi_ = vv[gs == 1]
                tl_rows.append({
                    "mkt_hi": m, "sector_hi": s, "stock_dim": sname,
                    "hi_minus_lo": float(np.median(hi_) - np.median(lo_))
                    if len(hi_) and len(lo_) else np.nan,
                    "n": int(len(gg))})
    tl = pd.DataFrame(tl_rows)
    par = {}
    for sname, gg in tl.groupby("stock_dim"):
        d = gg["hi_minus_lo"].dropna()
        par[sname] = {"spread_max_min": float(d.max() - d.min()),
                      "median": float(d.median()),
                      "sign_consistent": bool((d < 0).all() or (d > 0).all())}
    three = {"ms_polish_interaction_ratio": ratio_ms,
             "ms_did_ew": did_pt, "ms_did_p_date_cluster": p_ms,
             "stock_parallelism": par}
    (OUT / "t4_three_layer_structure.json").write_text(json.dumps(
        three, indent=2, ensure_ascii=False, default=str))
    tl.to_parquet(OUT / "t4_three_layer_cells.parquet", index=False)

    # ================= 4. 决策矩阵 =================
    def _sig(x):
        return bool(np.isfinite(x) and x > 0 and x < .05)

    med2d = m2d[m2d["metric"] == "median_excess"]
    h20 = med2d[med2d["horizon"] == 20].iloc[0]
    cond_b = [h20.get(f"breadth_effect_within_newhigh_{q}_ew")
              for q in ("Q2", "Q3")]
    cond_n = [h20.get(f"rev_newhigh_effect_within_breadth_{q}_ew")
              for q in ("Q2", "Q3")]
    dm = []
    dm.append({"structure": "Market Context dimensionality",
               "hypothesis": "breadth & new-high both retain conditional "
                             "increment -> keep 2-D",
               "evidence": f"breadth|newhigh EW {[round(x,4) if np.isfinite(x) else None for x in cond_b]}; "
                           f"newhigh|breadth EW {[round(x,4) if np.isfinite(x) else None for x in cond_n]}; "
                           f"polish ratio h20={h20['polish_interaction_ratio']:.3f}",
               "decision": "KEEP_2D" if all(
                   np.isfinite(x) and abs(x) > .002 for x in cond_b
                   if x is not None) and all(
                   np.isfinite(x) and abs(x) > .002 for x in cond_n
                   if x is not None) else "COLLAPSE_CANDIDATE"})
    mss = ms[ms["sector_dim"] == "sector_rel_strength"]
    db_med = mss["db"].median()
    dm.append({"structure": "Sector Context independence",
               "hypothesis": "sector relative strength retains effect "
                             "within market breadth quartiles",
               "evidence": f"S Q4-Q1 within M-Q1..Q4 (DB): "
                           f"{[round(x,4) for x in mss['db']]}",
               "decision": "INDEPENDENT_SECTOR_LAYER" if np.isfinite(db_med) \
                   and db_med > .002 else "SECTOR_SUBSUMED_BY_MARKET"})
    dm.append({"structure": "Market x Sector additivity",
               "hypothesis": "interaction weak & stable -> additive",
               "evidence": f"polish ratio={ratio_ms:.3f}, DiD EW="
                           f"{did_pt:.4f}, p={p_ms:.3f}",
               "decision": "ADDITIVE" if (ratio_ms < .3 and not _sig(
                   p_ms)) else "INTERACTION_CANDIDATE"})
    dm.append({"structure": "Stock state global thresholds",
               "hypothesis": "load/ref60 effects parallel across "
                             "(M,S) cells -> global thresholds",
               "evidence": json.dumps(par, default=str)[:300],
               "decision": "GLOBAL_THRESHOLDS" if all(
                   v["sign_consistent"] for v in par.values()) else
               "REGIME_DEPENDENT_THRESHOLDS"})
    dm.append({"structure": "amount axis status",
               "hypothesis": "trend-contaminated (T4.3) -> diagnostic only",
               "evidence": "expanding percentile saturated 2025+",
               "decision": "DIAGNOSTIC_ONLY"})
    pd.DataFrame(dm).to_csv(OUT / "t4_structure_decision_matrix.csv",
                            index=False)

    # ================= 双跑（Gate） =================
    sec2 = sp.attach_asof_pct(
        sp.build_sector_primitives(events), SEC_PCT_COLS)
    for _c, _v in (("pit_primary_eligible", False),
                   ("is_point_in_time", False),
                   ("retrospective_context_only", True),
                   ("membership_snapshot_date", "2026-09-21"),
                   ("loo_rule", sec["loo_rule"].iloc[0])):
        sec2[_c] = _v
    det = {"sector_primitives": frame_hash(sec) == frame_hash(sec2)}
    (OUT / "t4_4_determinism.json").write_text(json.dumps(
        {"identical": all(det.values()), "frames": det}, indent=2))
    manifest = {
        "stage": "T4.4_discovery", "baseline_commit": BASELINE,
        "lineage": {"events": "28b1d48 frozen", "market_pct":
                    "T4.3 as-of expanding percentile",
                    "sector_membership": "csrc snapshot 2026-09-21 "
                                         "(NON-PIT, retrospective only)"},
        "loo": "sector aggregates exclude focal stock, decomposable stats",
        "sector_pct_pool": "pooled cross-gate daily values, dedup per "
                           "(day, gate)",
        "boot": {"n": ad.N_BOOT, "seed": 20260925},
        "determinism": det,
        "elapsed_sec": round(time.time() - t0w, 1)}
    (OUT / "t4_4_manifest.json").write_text(json.dumps(
        manifest, indent=2, ensure_ascii=False))
    print(json.dumps({"decision_matrix": dm[0]["decision"], "sector":
                      dm[1]["decision"], "additive": dm[2]["decision"],
                      "stock": dm[3]["decision"], "determinism": det},
                     indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
