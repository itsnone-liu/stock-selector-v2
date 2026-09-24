#!/usr/bin/env python3
"""T4.3 Context-conditioned Path Layer：构建 + 分析 + 产物 + manifest + 双跑。"""
from __future__ import annotations

import hashlib
import math
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2            # noqa: E402
from t4.path import analysis as pa                          # noqa: E402
from t4.path import build_outcomes as bo                    # noqa: E402

BASELINE = "c605a39"
OUT = ROOT / "output/research/t4/context_path"
OUT.mkdir(parents=True, exist_ok=True)

PREREG_INTERACTIONS = [
    ("hi_load", "breadth_5d_asof_pct"),
    ("hi_load", "amount_yi_asof_pct"),
    ("hi_ref60", "breadth_5d_asof_pct"),
    ("hi_ref60", "new_high_20d_asof_pct"),
]


def frame_hash(df: pd.DataFrame, keys=("breakout_event_id",)) -> str:
    """稳健确定性 hash：按键排序后的 CSV 字节流（NaN/None 统一空串，
    float repr 确定）；hash_pandas_object 对混合 object 列不稳定，弃用。"""
    h = hashlib.sha256()
    d = df.sort_values(list(keys)).reset_index(drop=True)
    h.update(d.to_csv(index=False).encode("utf-8"))
    h.update(str(d.shape).encode())
    h.update(str(list(df.columns)).encode())
    return h.hexdigest()


def build_all():
    events = v2.load_events()
    t0 = pd.read_parquet(ROOT / "output/research/t4/t0_state/"
                         "t4_t0_state.parquet")
    ctx = bo.attach_quartiles(bo.asof_percentiles(t0))
    outcomes = bo.derive_outcomes()
    return events, t0, ctx, outcomes


def main():
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    assert head == BASELINE, f"HEAD {head} != {BASELINE}"
    t_start = time.time()
    events, t0, ctx, outcomes = build_all()
    print(f"[t4.3] events {len(events)} ctx {ctx.shape} "
          f"outcomes {outcomes.shape} {time.time() - t_start:.0f}s",
          flush=True)

    # ---- V4 对账（Gate 4 素材，构建即验） ----
    recon = bo.reconcile_with_v4(outcomes)
    bad = {h: {c: v for c, v in d.items()
               if v["value_mismatch"] or v["null_pattern_mismatch"]}
           for h, d in recon.items()}
    bad = {h: d for h, d in bad.items() if d}
    (OUT / "t4_context_outcome_reconciliation.json").write_text(json.dumps(
        {"overlapping_horizons": {k: recon[k] for k in recon},
         "any_mismatch": bool(bad)}, indent=2))
    print(f"[t4.3] v4 reconciliation "
          f"{'CLEAN' if not bad else 'MISMATCH: ' + json.dumps(bad)[:300]}",
          flush=True)

    # ---- context state 表 ----
    cs = t0.merge(ctx, on="breakout_event_id", how="left")
    dens = bo.breakout_density(events)
    cs = cs.merge(dens, on="breakout_day", how="left")
    cs.to_parquet(OUT / "t4_context_state.parquet", index=False)

    # ---- outcomes 表（物理分离：不含任何 T0 特征） ----
    oc = outcomes.merge(
        events[["breakout_event_id", "code", "breakout_day"]],
        on="breakout_event_id", how="left")
    oc.to_parquet(OUT / "t4_context_path_outcomes.parquet", index=False)

    # ---- 分析 panel ----
    panel = cs.merge(oc, on=["breakout_event_id", "code", "breakout_day"])
    panel["hi_load"] = (panel["turnover_load_t0"] > 1).where(
        panel["turnover_load_t0"].notna())
    panel["hi_ref60"] = panel["t0_ref60_breakout"].astype(
        "float").where(panel["t0_ref60_breakout"].notna())

    # ---- Primary contrasts（3 轴 × 4H × 6M） ----
    rows = []
    for axis in ("breadth_5d_q", "amount_yi_q", "new_high_20d_q"):
        for h in bo.HORIZONS:
            ph = panel[panel["horizon"] == h]
            for m in pa.METRICS:
                rows.append(pa.market_contrast_row(ph, axis, h, m))
    mc = pd.DataFrame(rows)
    mc["p_holm"] = pa.holm(mc["p_two_sided_date_cluster"].to_numpy())
    mc.to_parquet(OUT / "t4_market_context_contrasts.parquet", index=False)
    mc[["context_axis", "horizon", "metric", "db_q4_minus_q1",
        "Q1_n_events", "Q4_n_events", "Q1_n_dates",
        "Q4_n_dates"]].to_parquet(
        OUT / "t4_date_balanced_contrasts.parquet", index=False)
    print(f"[t4.3] contrasts {mc.shape} {time.time() - t_start:.0f}s",
          flush=True)

    # ---- 预注册 interactions（4 组） ----
    irows = []
    for sc, mk in PREREG_INTERACTIONS:
        for h in bo.HORIZONS:
            ph = panel[panel["horizon"] == h]
            for m in pa.METRICS:
                irows.append(pa.interaction_row(ph, sc, mk, h, m))
    ic = pd.DataFrame(irows)
    ic["p_holm"] = pa.holm(ic["p_two_sided_date_cluster"].to_numpy())
    ic.to_parquet(OUT / "t4_context_interactions.parquet", index=False)
    print(f"[t4.3] interactions {ic.shape} {time.time() - t_start:.0f}s",
          flush=True)

    # ---- sector retrospective companion（NON-PIT） ----
    sc_ret = pd.read_parquet(
        ROOT / "output/research/t4/t0_state/"
        "t4_t0_sector_retrospective.parquet")
    spanel = sc_ret.merge(
        oc, on="breakout_event_id")
    srows = []
    for gate, g in spanel.groupby("industry_gate"):
        for h in (20, 40):
            gh = g[g["horizon"] == h]
            srows.append({
                "industry_gate": gate, "horizon": h, "n": int(len(gh)),
                "median_excess": float(
                    gh["fwd_mkt_excess_log"].median()),
                "median_mdd": float(
                    gh["future_max_drawdown"].median()),
                "p_new_high": float(
                    gh["new_high_within"].astype(bool).mean()),
                "pit_eligible": False,
                "label": "RETROSPECTIVE / NON-PIT "
                         "(csrc snapshot 2026-09-21)"})
    src = pd.DataFrame(srows)
    src.to_parquet(OUT / "t4_sector_retrospective_contrasts.parquet",
                   index=False)
    # 83 大类仅覆盖/样本规模诊断（不做出值）
    smap = pd.read_parquet(ROOT / "output/research/t4/context/"
                           "stock_sector_map.parquet")
    cls = smap[["code", "industry_class"]].copy()
    cls["code"] = cls["code"].str.split(".").str[1]
    evc = events[["code"]].merge(cls, on="code", how="left")
    cls_diag = evc["industry_class"].value_counts().rename_axis(
        "industry_class").reset_index(name="n_events")
    cls_diag.to_csv(OUT / "t4_83class_coverage_diagnostic.csv", index=False)

    # ---- attrition ----
    att = mc[["context_axis", "horizon", "metric", "n_base",
              "n_context_available", "n_outcome_available"]].copy()
    att.to_csv(OUT / "t4_context_attrition.csv", index=False)

    # ---- 年度稳定性（internal temporal robustness，非 OOS） ----
    panel["year"] = panel["breakout_day"].str[:4]
    yrows = []
    for axis in ("breadth_5d_q", "amount_yi_q", "new_high_20d_q"):
        for yr, gy in panel.groupby("year"):
            for h in (10, 20, 40):
                g = gy[gy["horizon"] == h]
                sub = g[g[axis].isin(["Q1", "Q4"]) &
                        g["fwd_mkt_excess_log"].notna()]
                if not len(sub):
                    continue
                q4 = sub[sub[axis] == "Q4"]["fwd_mkt_excess_log"].median()
                q1 = sub[sub[axis] == "Q1"]["fwd_mkt_excess_log"].median()
                yrows.append({"context_axis": axis, "year": yr,
                              "horizon": h, "q4_minus_q1": q4 - q1,
                              "n_q1": int((sub[axis] == "Q1").sum()),
                              "n_q4": int((sub[axis] == "Q4").sum()),
                              "n_obs_h": int(
                                  g["fwd_mkt_excess_log"].notna().sum())})
    pd.DataFrame(yrows).to_csv(
        OUT / "t4_yearly_stability.csv", index=False)

    # ---- breakout density diagnostic ----
    dd = cs[["breakout_day", "breadth_5d_asof_pct",
             "breakout_count_on_date"]].drop_duplicates("breakout_day")
    def _rank(x):
        x = np.asarray(x, dtype=float)
        r = np.empty(len(x))
        order = np.argsort(x, kind="stable")
        r[order] = np.arange(1, len(x) + 1)
        return r
    m_ = dd["breadth_5d_asof_pct"].notna()
    a_ = dd.loc[m_, "breadth_5d_asof_pct"].to_numpy(float)
    b_ = dd.loc[m_, "breakout_count_on_date"].to_numpy(float)
    ra, rb = _rank(a_), _rank(b_)
    rho = float(np.corrcoef(ra, rb)[0, 1])
    n_ = len(a_)
    t_ = rho * np.sqrt((n_ - 2) / max(1e-12, 1 - rho ** 2))
    pv = float(2 * (1 - 0.5 * (1 + math.erf(abs(t_) / math.sqrt(2)))))

    dep_audit = {
        "n_dates": int(len(dd)),
        "events_per_date_median": float(
            dd["breakout_count_on_date"].median()),
        "events_per_date_p95": float(
            dd["breakout_count_on_date"].quantile(.95)),
        "spearman_breadth_pct_vs_breakout_count": {"rho": float(rho),
                                                   "p": float(pv)},
        "cluster_design": {
            "primary": "breakout_day date cluster",
            "secondary": "stock cluster",
            "interval_policy": "max width of the two cluster bootstrap CIs",
            "n_boot": pa.N_BOOT, "rng_seed": 20260924},
        "dual_estimands": ["event-weighted", "date-balanced"],
        "note": "density is a market-cohort diagnostic, not a factor"}
    (OUT / "t4_context_dependency_audit.json").write_text(json.dumps(
        dep_audit, indent=2, ensure_ascii=False))

    # ---- 双跑（Gate 7）：构建层全量双跑 hash ----
    _, _, ctx2, oc2 = build_all()
    oc2 = oc2.merge(
        events[["breakout_event_id", "code", "breakout_day"]],
        on="breakout_event_id", how="left")
    oc2 = oc2[list(oc.columns)]
    det = {"asof_context": frame_hash(ctx) == frame_hash(ctx2),
           "path_outcomes": frame_hash(oc, ("breakout_event_id",
                                            "horizon")) == frame_hash(
               oc2, ("breakout_event_id", "horizon"))}
    (OUT / "t4_3_determinism.json").write_text(json.dumps(
        {"identical": all(det.values()), "frames": det}, indent=2))

    manifest = {
        "stage": "T4.3_context_path", "baseline_commit": BASELINE,
        "event_universe": 27422,
        "t0_state_source": "output/research/t4/t0_state @c605a39",
        "market_context_source": "output/research/t4/context @ca5e2a8",
        "sector_source": "t4_t0_sector_retrospective (NON-PIT)",
        "outcome_sources": {
            "primary_derivation": "t3_v3 event_path_daily/summary",
            "reconciliation": "t3_v4 dynamic_forward_outcomes @tau0 "
                              "H in {5,10,20} exact"},
        "horizons": list(bo.HORIZONS),
        "preregistered_interactions": [
            f"{s} x {m}" for s, m in PREREG_INTERACTIONS],
        "primary_family": "metric x horizon x context-axis "
                          "(Q4-Q1, Holm within family)",
        "asof_percentile": {"min_history_days": bo.MIN_HISTORY,
                            "history_rule": "market dates < T0",
                            "cuts": [0.25, 0.5, 0.75]},
        "estimands": ["event-weighted", "date-balanced"],
        "cluster": ["breakout_day", "stock"], "n_boot": pa.N_BOOT,
        "outcome_reconciliation_clean": not bad,
        "determinism": det,
        "elapsed_sec": round(time.time() - t_start, 1)}
    (OUT / "t4_context_manifest.json").write_text(json.dumps(
        manifest, indent=2, ensure_ascii=False))
    print(json.dumps({k: manifest[k] for k in (
        "outcome_reconciliation_clean", "determinism",
        "elapsed_sec")}, indent=2), flush=True)


if __name__ == "__main__":
    main()
