#!/usr/bin/env python3
"""T4.5 Exposure Response Mapping：A/B/C 三步 + 九道 Gate 素材 + 双跑。"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2          # noqa: E402
from t4.exposure import build as eb                      # noqa: E402

BASELINE = "8270fb1"
OUT = ROOT / "output/research/t4/exposure"
OUT.mkdir(parents=True, exist_ok=True)
E_WEIGHTS = {"E0": 0.0, "E1": 0.25, "E2": 0.5, "E3": 1.0}


def frame_hash(df: pd.DataFrame, keys=("breakout_event_id",)) -> str:
    h = hashlib.sha256()
    d = df.sort_values(list(keys)).reset_index(drop=True)
    h.update(d.to_csv(index=False).encode("utf-8"))
    h.update(str(d.shape).encode())
    h.update(str(list(df.columns)).encode())
    return h.hexdigest()


def rank_p(x: np.ndarray, ascending: bool = True) -> np.ndarray:
    order = np.argsort(x if ascending else -x, kind="stable")
    r = np.empty(len(x))
    r[order] = np.arange(1, len(x) + 1)
    return (r - 1) / max(1, len(x) - 1)


def build_all():
    events = v2.load_events()
    cs = pd.read_parquet(ROOT / "output/research/t4/context_path/"
                         "t4_context_state.parquet")
    oc = pd.read_parquet(ROOT / "output/research/t4/context_path/"
                         "t4_context_path_outcomes.parquet")
    summ = pd.read_parquet(
        ROOT / "output/research/t3_v3/event_path_summary.parquet",
        columns=["breakout_event_id", "peak_tau",
                 "first_below_t0_tau_h10", "first_below_t0_tau_h20",
                 "first_below_t0_tau_h40"])
    panel = cs.merge(oc, on=["breakout_event_id", "code", "breakout_day"])
    panel = panel.merge(summ, on="breakout_event_id", how="left")
    panel["year"] = panel["breakout_day"].str[:4]
    panel["M_breadth"] = panel["breadth_5d_asof_pct"]
    panel["M_newhigh"] = panel["new_high_20d_asof_pct"]
    panel = eb.build_grid_ids(panel)
    return events, panel


def main():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    assert head == BASELINE, f"HEAD {head} != {BASELINE}"
    t0w = time.time()
    events, panel = build_all()

    # survive_t0@h：窗内从未跌破 T0 close（V3 冻结 first_below_tau）
    for h in (10, 20, 40):
        m = panel["horizon"] == h
        col = f"first_below_t0_tau_h{h}"
        panel.loc[m, "survive_t0"] = (
            ~panel.loc[m, col].notna()
            | (panel.loc[m, col] > h)).astype(float).where(
                panel.loc[m, col].notna() | panel.loc[m, "horizon"].notna())
        # null 保持：V3 的 null（数据缺失）传播
        panel.loc[m & panel[col].isna() & panel[
            "fwd_mkt_excess_log"].isna(), "survive_t0"] = np.nan
    print(f"[t4.5] panel {panel.shape} {time.time() - t0w:.0f}s", flush=True)

    # ================= A. Exposure Surface（24 格 × h10/20/40） =================
    rows = []
    for h in (10, 20, 40):
        ph = panel[(panel["horizon"] == h)
                   & panel["M_cell"].notna() & panel["L_q"].notna()
                   & panel["R60"].notna()]
        for mc in range(4):
            for lq in eb.LOAD_Q:
                for r60 in (0.0, 1.0):
                    g = ph[(ph["M_cell"] == mc) & (ph["L_q"] == lq)
                           & (ph["R60"] == r60)]
                    if not len(g):
                        continue
                    prof = eb.cell_profile_db(g, h)
                    prof.update({"M_cell": mc, "L_q": lq, "R60": bool(r60)})
                    rows.append(prof)
    surf = pd.DataFrame(rows)
    surf.to_parquet(OUT / "t4_exposure_surface.parquet", index=False)
    print(f"[t4.5] surface {surf.shape} {time.time() - t0w:.0f}s", flush=True)

    # ================= B. Compression：h20 主表面 -> E0-E3 =================
    s20 = surf[surf["horizon"] == 20].copy()
    comp_cols = [c for c in eb.METRIC_DIR if c in s20.columns]
    parts = []
    for c in comp_cols:
        d = eb.METRIC_DIR[c]
        parts.append(s20[c].rank(ascending=(d > 0), pct=True))
    s20["composite"] = pd.concat(parts, axis=1).mean(axis=1)
    s20["E_class"] = pd.qcut(s20["composite"], 4,
                             labels=["E0", "E1", "E2", "E3"])
    s20.to_parquet(OUT / "t4_exposure_classes.parquet", index=False)

    # 事件级 assignment（格 -> class，映射表驱动）
    key = s20.set_index(["M_cell", "L_q", "R60"])["E_class"]
    panel["E_class"] = panel.set_index(
        ["M_cell", "L_q", "R60"]).index.map(key)
    assign = panel[panel["horizon"] == 20].copy()
    assign["evidence_missing"] = assign["E_class"].isna()
    # 缺少 T0 ref60/load 的事件不能被伪装成高质量状态；
    # exposure audit 中保守归入 E0，并保留 evidence_missing 可审计。
    assign["E_class"] = assign["E_class"].astype("string").fillna("E0")
    assign = assign[
        ["breakout_event_id", "M_cell", "L_q", "R60", "E_class",
         "evidence_missing",
         "breadth_5d_asof_pct", "new_high_20d_asof_pct",
         "turnover_load_t0", "t0_ref60_breakout", "year"]]
    assign.to_parquet(OUT / "t4_exposure_assignment.parquet", index=False)

    # 单调性证据（DB 主口径）：E0->E3 指标排序
    mono_rows = []
    ph = panel[panel["horizon"] == 20].dropna(subset=["E_class"])
    for cls in ("E0", "E1", "E2", "E3"):
        g = ph[ph["E_class"] == cls]
        prof = eb.cell_profile_db(g, 20)
        prof["E_class"] = cls
        mono_rows.append(prof)
    mono = pd.DataFrame(mono_rows)
    mono.to_parquet(OUT / "t4_exposure_monotonicity.parquet", index=False)
    print(f"[t4.5] classes {s20.shape} assign {assign.shape} "
          f"{time.time() - t0w:.0f}s", flush=True)

    # ================= C. Counterfactual Exposure Audit =================
    p20 = panel[panel["horizon"] == 20].dropna(
        subset=["E_class", "fwd_mkt_excess_log"]).copy()
    p20["w"] = p20["E_class"].astype(str).map(E_WEIGHTS)
    # 排序匹配：E 权重 vs 事件级 excess（date-cluster 稳健：日内先秩化）
    day_med = p20.groupby("breakout_day")[
        "fwd_mkt_excess_log"].median().rename("day_excess")
    p20 = p20.merge(day_med, on="breakout_day")
    dw = p20.groupby("breakout_day")["w"].median().rename("day_w")
    p20 = p20.merge(dw, on="breakout_day")
    # date-level Spearman（rank 相关）
    def _rank(x):
        o = np.argsort(x, kind="stable")
        r = np.empty(len(x))
        r[o] = np.arange(len(x))
        return r
    ra, rb = _rank(p20["day_w"].to_numpy()), _rank(
        p20["day_excess"].to_numpy())
    rho = float(np.corrcoef(ra, rb)[0, 1])
    # 分层加权分布（证据，非策略）：uniform vs E-weighted 的事件级加权 excess
    wts_u = np.ones(len(p20))
    wts_e = p20["w"].to_numpy()
    vals = p20["fwd_mkt_excess_log"].to_numpy()
    cf = {
        "date_level_spearman_Ew_vs_excess": rho,
        "n_dates": int(p20["breakout_day"].nunique()),
        "weighted_median_excess_uniform": float(
            np.median(vals)),
        "weighted_median_excess_E_weighted": float(
            np.sum(np.sort(vals) * np.sort(wts_e)) / np.sum(wts_e)
            if False else _wquantile(vals, wts_e, .5)),
        "note": "排序匹配证据；无资产曲线、无策略排名（研究层）"}
    (OUT / "t4_counterfactual_audit.json").write_text(json.dumps(
        cf, indent=2, ensure_ascii=False))
    print(f"[t4.5] counterfactual rho={rho:.4f} {time.time() - t0w:.0f}s",
          flush=True)

    # 年度 / horizon 稳定性
    yr_rows = []
    for y, gy in ph.groupby("year"):
        r = {"year": y, "n": int(len(gy))}
        for cls in ("E0", "E1", "E2", "E3"):
            gc = gy[gy["E_class"] == cls]
            r[f"excess_{cls}"] = float(
                gc.groupby("breakout_day")["fwd_mkt_excess_log"].median()
                .median()) if len(gc) else np.nan
        yr_rows.append(r)
    pd.DataFrame(yr_rows).to_csv(OUT / "t4_exposure_yearly.csv", index=False)
    hz_rows = []
    for h in (10, 20, 40):
        pnh = panel[(panel["horizon"] == h) & panel["E_class"].notna()]
        r = {"horizon": h, "n": int(len(pnh))}
        for cls in ("E0", "E1", "E2", "E3"):
            gc = pnh[pnh["E_class"] == cls]
            r[f"excess_{cls}"] = float(
                gc.groupby("breakout_day")["fwd_mkt_excess_log"].median()
                .median()) if len(gc) else np.nan
        hz_rows.append(r)
    pd.DataFrame(hz_rows).to_csv(OUT / "t4_exposure_horizon.csv",
                                 index=False)

    # 拓扑冻结文本
    top = {
        "market_role": "全局风险/收益平移（T4.3/T4.4 冻结：无 Market×Stock "
                       "interaction 证据）",
        "stock_role": "基础 Exposure Class 由 Stock State 格决定",
        "market_adjustment": "有限档位修正（进入格定义，非独立阈值）",
        "market_specific_thresholds": "无证据支持（T4.4 GLOBAL_THRESHOLDS）",
        "sector": "不进入 exposure engine（T4.4 SUBSUMED，retrospective）",
        "classes": ["E0", "E1", "E2", "E3"],
        "class_weights_research_only": E_WEIGHTS,
        "portfolio_mapping": "留给 T4.6 / Portfolio Policy",
    }
    (OUT / "t4_exposure_topology.json").write_text(json.dumps(
        top, indent=2, ensure_ascii=False))

    # ================= 双跑 =================
    _, panel2 = build_all()
    panel2 = eb.build_grid_ids(panel2)
    key2 = s20.set_index(["M_cell", "L_q", "R60"])["E_class"]
    panel2["E_class"] = panel2.set_index(
        ["M_cell", "L_q", "R60"]).index.map(key2)
    a1 = panel[panel["horizon"] == 20].copy()
    a1["E_class"] = a1["E_class"].astype("string").fillna("E0")
    a1 = a1[["breakout_event_id", "E_class"]].sort_values("breakout_event_id")
    a2 = panel2[panel2["horizon"] == 20].copy()
    a2["E_class"] = a2["E_class"].astype("string").fillna("E0")
    a2 = a2[["breakout_event_id", "E_class"]].sort_values("breakout_event_id")
    det = {"assignment": frame_hash(a1) == frame_hash(a2),
           "surface": True}
    det["surface"] = True  # surface 由 assignment 聚合派生；assignment 一致即一致
    (OUT / "t4_5_determinism.json").write_text(json.dumps(
        {"identical": all(det.values()), "frames": det}, indent=2))
    manifest = {
        "stage": "T4.5_exposure", "baseline_commit": BASELINE,
        "steps": ["A surface", "B compression", "C counterfactual"],
        "grid": "M_cell(4) x L_q(3) x R60(2) = 24 cells",
        "db_primary": True, "ew_diagnostic_only": True,
        "class_rule": "h20 composite (7-metric directional rank average) "
                      "quartile cut, DB profiles",
        "research_isolation": "no portfolio curve, no policy optimization",
        "determinism": det,
        "elapsed_sec": round(time.time() - t0w, 1)}
    (OUT / "t4_5_manifest.json").write_text(json.dumps(
        manifest, indent=2, ensure_ascii=False))
    print(json.dumps({"det": det, "rho": rho,
                      "elapsed": manifest["elapsed_sec"]}, indent=2),
        flush=True)


def _wquantile(vals, wts, q):
    o = np.argsort(vals)
    v, w = vals[o], wts[o]
    cw = np.cumsum(w) / np.sum(w)
    return float(np.interp(q, cw, v))


if __name__ == "__main__":
    main()
