#!/usr/bin/env python3
"""T3 V6 全量构建：四入场策略机会矩阵 + 双 clock 结果 + 配对统计。

用法：/root/venv/bin/python3 scripts/run_t3_v6.py [--smoke N]
确定性：全量双跑逐产物 hash 比对（execution_determinism.json）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2  # noqa: E402
from stock_selector.research import t3_v6 as v6  # noqa: E402

BASELINE = "c312371"


def frame_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(pd.util.hash_pandas_object(
        df.astype(str), index=True).values.tobytes())
    h.update(str(df.shape).encode())
    h.update(str(list(df.columns)).encode())
    return h.hexdigest()


def load_inputs(smoke: int | None):
    events = v2.load_events()
    if smoke:
        codes = sorted(events.code.unique())[:smoke]
        events = events[events.code.isin(codes)]
    events = v6.attach_reattack(events)
    factors = v2.load_factor_cache(ROOT / "output/research/t3_v2")
    mdates, mclose = v2.market_calendar_and_close()
    mpos = {d: i for i, d in enumerate(mdates)}
    return events, factors, mdates, mclose, mpos


def build_all_once(events, factors, mdates, mclose, mpos, ctx=None,
                   log=print):
    return v6.build_all(events, factors, mdates, mpos, mclose, ctx=ctx,
                        log=log)


def policy_outcomes_summary(mat) -> pd.DataFrame:
    """§9 policy-level 聚合：capital return / entry rate / exposure /
    cash / missed upside / avoided drawdown（per policy × window × h）。"""
    rows = []
    for w in v6.WINDOWS:
        for p in v6.POLICIES:
            m = mat[(mat["window"] == w) & (mat["policy"] == p)]
            ent = m[m["status"] == "entered"]
            noent = m[m["not_entered"].astype(bool)]
            for h in v6.EVENT_HORIZONS:
                col = f"ret_net_event_h{h}"
                comp = m[m[f"complete_event_h{h}"].astype(bool)]
                rows.append({
                    "policy": p, "window": w, "horizon": h,
                    "n": len(m), "n_complete": len(comp),
                    "entry_rate": len(ent) / len(m),
                    "mean_ret_net": comp[col].mean(),
                    "median_ret_net": comp[col].median(),
                    "p_ret_pos": (comp[col] > 0).mean(),
                    "mean_exposure_days_w40": m[
                        "exposure_days_w40"].mean(),
                    "mean_fraction_invested": m[
                        "fraction_invested"].mean(),
                    "median_missed_upside_in_window_pct": noent[
                        "missed_upside_in_window_pct"].mean()
                    if len(noent) else None,
                    "mean_post_window_min_pct": noent[
                        "post_window_min_pct"].mean()
                    if len(noent) else None,
                    "median_wait_days": ent["wait_days"].median()
                    if len(ent) else None,
                })
    return pd.DataFrame(rows)


def annual_contribution(mat) -> pd.DataFrame:
    """§20 internal temporal robustness：年度 cohort 贡献（策略均值 +
    6 对配对差年度均值）。"""
    rows = []
    pairs = [(a, b) for i, a in enumerate(v6.POLICIES)
             for b in v6.POLICIES[i + 1:]]
    for w in v6.WINDOWS:
        for h in v6.EVENT_HORIZONS:
            col = f"ret_net_event_h{h}"
            for y in sorted(mat["t0_year"].dropna().unique()):
                m = mat[(mat["window"] == w) & (mat["t0_year"] == y)]
                comp = m[m[f"complete_event_h{h}"].astype(bool)]
                r = {"window": w, "horizon": h, "year": y,
                     "n": len(m), "n_complete": len(comp)}
                for p in v6.POLICIES:
                    sub = comp[comp["policy"] == p]
                    r[f"mean_{p}"] = sub[col].mean()
                piv = m.pivot(index="breakout_event_id", columns="policy",
                              values=col).dropna()
                for a, b in pairs:
                    r[f"delta_{v6.POLICIES.index(a)}_"
                      f"{v6.POLICIES.index(b)}"] = (
                        piv[a] - piv[b]).mean() if len(piv) else None
                rows.append(r)
    return pd.DataFrame(rows)


def write_products(out: Path, prods: dict, manifest: dict):
    out.mkdir(parents=True, exist_ok=True)
    m = prods["matrix"]
    prods["opportunity_panel"].to_parquet(
        out / "execution_opportunity_panel.parquet", index=False)
    prods["entries"].to_parquet(
        out / "execution_entries.parquet", index=False)
    prods["tranches"].to_parquet(
        out / "execution_tranches.parquet", index=False)
    ent = m[m["status"] == "entered"]
    cols = (["breakout_event_id", "code", "policy", "window", "status",
             "first_fill_day", "first_fill_tau", "wait_days",
             "origin_state", "origin_structure", "origin_participation",
             "origin_turnover_load", "entry_state", "entry_turnover_load",
             "fraction_invested", "n_tranches_filled"]
            + [f"ret_net_entry_h{h}{s}" for h in (5, 10, 20)
               for s in ("", "_sc")]
            + [f"complete_entry_h{h}" for h in (5, 10, 20)]
            + [f"mfe_entry_h{h}" for h in (5, 10, 20)]
            + [f"mae_entry_h{h}" for h in (5, 10, 20)]
            + [f"mdd_entry_h{h}" for h in (5, 10, 20)]
            + [f"new_high_entry_h{h}" for h in (5, 10, 20)]
            + [f"mkt_excess_entry_h{h}" for h in (5, 10, 20)])
    ent[cols].to_parquet(out / "execution_entry_paths.parquet",
                         index=False)
    prods["policy_outcomes"].to_parquet(
        out / "execution_policy_outcomes.parquet", index=False)
    prods["contrasts"].to_parquet(
        out / "execution_state_contrasts.parquet", index=False)
    prods["fillability"].to_parquet(
        out / "execution_fillability_audit.parquet", index=False)
    prods["accounting"].to_parquet(
        out / "execution_no_entry_accounting.parquet", index=False)
    prods["attrition"].to_csv(out / "execution_attrition.csv", index=False)
    prods["annual"].to_parquet(
        out / "execution_annual_contribution.parquet", index=False)
    (out / "state_run_manifest.json").write_text(json.dumps(
        manifest, indent=2, ensure_ascii=False, default=str))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", type=int, default=None)
    args = ap.parse_args()
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    assert head == BASELINE, f"HEAD {head} != baseline {BASELINE}"
    t0 = time.time()
    OUT = ROOT / "output/research/t3_v6"
    OUT.mkdir(parents=True, exist_ok=True)
    events, factors, mdates, mclose, mpos = load_inputs(args.smoke)
    print(f"[v6] inputs: events {len(events)}, "
          f"calendar {mdates[0]}..{mdates[-1]}", flush=True)
    import time as _t
    _ct = _t.time()
    ctx = v6.build_context(events)
    print(f"[v6] context ready {_t.time() - _ct:.0f}s", flush=True)

    prods1 = build_all_once(events, factors, mdates, mclose, mpos, ctx)
    print(f"[v6] first build done {time.time() - t0:.0f}s "
          f"(matrix {len(prods1['matrix'])} rows)", flush=True)
    prods2 = build_all_once(events, factors, mdates, mclose, mpos, ctx,
                            log=lambda *a: None)
    det = {k: (frame_hash(prods1[k]), frame_hash(prods2[k]))
           for k in ("matrix", "entries", "fillability")}
    det = {k: {"hash1": a, "hash2": b, "identical": a == b}
           for k, (a, b) in det.items()}
    identical = all(v["identical"] for v in det.values())
    (OUT / "execution_determinism.json").write_text(json.dumps(
        {"identical": identical, "frames": det,
         "bootstrap_note": "contrasts run once (seeded, deterministic)"},
        indent=2))
    print(f"[v6] determinism identical={identical}", flush=True)

    m = prods1["matrix"]
    contrasts = v6.paired_contrasts(m)
    print(f"[v6] contrasts {len(contrasts)} rows, "
          f"holm_pass={int(contrasts['holm_pass'].sum())}", flush=True)
    prods = {
        "matrix": m,
        "opportunity_panel": m,
        "entries": prods1["entries"],
        "tranches": prods1["tranches"],
        "fillability": prods1["fillability"],
        "policy_outcomes": policy_outcomes_summary(m),
        "contrasts": contrasts,
        "accounting": v6.no_entry_accounting(m),
        "attrition": v6.attrition_table(m),
        "annual": annual_contribution(m),
    }
    manifest = {
        "rule_version": v6.RULE_VERSION,
        "baseline_commit": BASELINE,
        "state_dep": v6.STATE_DEP,
        "execution_model": "cn-a-share-eod-v1",
        "events": len(events),
        "matrix_rows": len(m),
        "smoke": args.smoke,
        "elapsed_sec": round(time.time() - t0, 1),
        "windows": list(v6.WINDOWS),
        "bootstrap": {"B": v6.BOOT_B, "seed": v6.BOOT_SEED,
                      "gates": v6.GATES},
    }
    write_products(OUT, prods, manifest)

    # 前瞻台账首笔（in-sample replay 基线，DATASET_END 快照）
    led_rows = []
    m18 = m[(m["window"] == 10)]
    for r in m18.itertuples(index=False):
        # 全体事件 breakout_day ≤ DATASET_END（事件宇宙冻结），
        # 均为 as-of 已发生的机会 → in-sample replay 基线记录
        led_rows.append({
            "asof_date": v2.DATASET_END,
            "breakout_event_id": r.breakout_event_id,
            "code": r.code, "policy": r.policy,
            "origin_state": r.origin_state,
            "trigger_status": r.status, "trigger_date":
                r.signal_day_trigger,
            "intended_fill_date": None, "actual_fill_date":
                r.first_fill_day,
            "fill_price": None,
            "policy_version": v6.RULE_VERSION,
            "state_version": v6.STATE_DEP,
            "input_manifest_hash": manifest["rule_version"],
            "note": "in_sample_replay",
        })
    led_path = OUT / "prospective_execution_ledger.parquet"
    if led_path.exists():
        led_path.unlink()      # 首笔基线随构建重建（in_sample_replay）
    v6.ledger_append(led_path, led_rows)
    chain = v6.verify_ledger_chain(OUT / "prospective_execution_ledger.parquet")
    print(f"[v6] ledger rows {chain['rows']} chain_ok="
          f"{chain['hash_chain_mismatches'] == 0}", flush=True)
    print(json.dumps({"rows": {"matrix": len(m),
                               "entries": len(prods1["entries"]),
                               "fillability": len(prods1["fillability"]),
                               "contrasts": len(contrasts)},
                      "elapsed_sec": round(time.time() - t0, 1)}),
          flush=True)


if __name__ == "__main__":
    main()
