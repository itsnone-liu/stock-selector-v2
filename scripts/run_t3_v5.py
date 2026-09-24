#!/usr/bin/env python3
"""T3 V5 full build: turnover normalization audit + confound contrasts,
4-axis state vector (daily grid), compact states, transitions, internal
validation, baseline realtime snapshot + first ledger entry, manifest,
and an in-process full double-build determinism check.

Baseline: 64a2a22 (T3 V4 frozen). No forward outcomes enter any state.
"""
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
from stock_selector.research import t3_v2 as v2  # noqa: E402
from stock_selector.research import t3_v3 as v3  # noqa: E402
from stock_selector.research import t3_v4 as v4  # noqa: E402
from stock_selector.research import t3_v5 as v5  # noqa: E402

OUT = ROOT / "output/research/t3_v5"
BASELINE = "64a2a22"


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def frame_hash(df):
    return hashlib.sha256(pd.util.hash_pandas_object(
        df, index=True).values.tobytes()).hexdigest()


def load_inputs():
    daily = pd.read_parquet(
        ROOT / "output/research/t3_v3/event_path_daily.parquet",
        columns=v5._PANEL_COLS)
    riskset = pd.read_parquet(
        ROOT / "output/research/t3_v4/dynamic_riskset.parquet")
    fwd = pd.read_parquet(
        ROOT / "output/research/t3_v4/dynamic_forward_outcomes.parquet")
    factors = v2.load_factor_cache(ROOT / "output/research/t3_v2")
    events = v2.load_events()
    mdates, mclose = v2.market_calendar_and_close()
    return daily, riskset, fwd, factors, events, mdates, mclose


def build_all(inputs, log=print):
    daily, riskset, fwd, factors, events, mdates, mclose = inputs
    t0 = time.time()
    load_long = v5.build_turnover_load(events, mdates, factors, log=log)
    log(f"[v5] turnover raw pass done {time.time() - t0:.0f}s")
    with_load = v5.attach_load_columns(daily, load_long)
    # raw accumulation vs frozen panel cumulative: must agree exactly
    a = with_load["cum_turnover_since_t0"].astype(float)
    b = with_load["cum_turnover_raw"].astype(float)
    mism = int(((a.notna() | b.notna())
                & ~np.isclose(a, b, rtol=1e-9, atol=1e-9,
                              equal_nan=True)).sum())
    if mism:
        raise RuntimeError(f"raw cum_turnover vs panel mismatch: {mism}")
    ident_bad = int((~with_load["load_identity_ok"].astype(bool)).sum())
    if ident_bad:
        raise RuntimeError(f"load identity violations: {ident_bad}")
    log(f"[v5] cross-checks clean (cum 0 mismatch, identity 0 violations)")
    ref_bins = v5.freeze_reference_bins(with_load)
    svd = v5.assign_states(with_load, ref_bins)
    ck = svd[svd["tau"].isin(v5.CHECKPOINTS)].reset_index(drop=True)
    tr = v5.build_transitions(svd)
    val = v5.internal_validation(svd, fwd)
    conf = v5.confound_contrasts(
        with_load[with_load["tau"].isin(v5.CONF_ALL_TAUS)], riskset, fwd)
    verdict = v5.confound_verdict(conf)
    log(f"[v5] confound verdict: {verdict}")
    audit = with_load[[
        "breakout_event_id", "code", "breakout_day", "tau",
        "observation_date", "cum_turnover_since_t0",
        "mean_turnover_since_t0", "pre20_turn_base", "turn_n_to_tau",
        "expected_turnover_since_t0", "turnover_load_to_tau",
        "mean_turnover_load_to_tau", "load_identity_ok"]]
    return {"svd": svd, "ck": ck, "tr": tr, "val": val, "conf": conf,
            "verdict": verdict, "ref_bins": ref_bins, "audit": audit}


def write_products(res, inputs, manifest_hash):
    _, _, _, _, events, mdates, _ = inputs
    OUT.mkdir(parents=True, exist_ok=True)
    mpos = {d: i for i, d in enumerate(mdates)}
    res["audit"].to_parquet(OUT / "turnover_normalization_audit.parquet",
                            index=False, compression="snappy")
    svd = res["svd"]
    svd.to_parquet(OUT / "state_vector_daily.parquet", index=False,
                   compression="snappy")
    res["ck"].to_parquet(OUT / "state_checkpoints.parquet", index=False,
                         compression="snappy")
    tr = res["tr"]
    trans = pd.concat([
        tr["daily_transitions"].rename(
            columns={"tau": "tau_from"}).assign(
            tau_to=lambda x: x["tau_from"] + 1),
        tr["checkpoint_transitions"]], ignore_index=True)
    trans.to_parquet(OUT / "state_transitions.parquet", index=False,
                     compression="snappy")
    runs = tr["runs"]
    run_stats = runs.merge(tr["first_entry"].groupby("state").agg(
        n_first_entries=("breakout_event_id", "size"),
        median_first_entry_tau=("first_entry_tau", "median")),
        on="state", how="left")
    run_stats = run_stats.merge(
        tr["revisits"].groupby("state").agg(
            n_events_with_state=("breakout_event_id", "size"),
            mean_revisits=("revisit_count", "mean"),
            p90_revisits=("revisit_count", lambda x: float(
                np.percentile(x, 90)))),
        on="state", how="left")
    run_stats.to_parquet(OUT / "state_run_stats.parquet", index=False,
                         compression="snappy")
    res["val"].to_parquet(OUT / "state_internal_validation.parquet",
                          index=False, compression="snappy")
    res["conf"].to_parquet(OUT / "turnover_confound_contrasts.parquet",
                           index=False, compression="snappy")
    (OUT / "compact_state_definition.json").write_text(json.dumps(
        v5.definition_json(res["ref_bins"], res["verdict"]),
        ensure_ascii=False, indent=2))
    # baseline realtime snapshot + first ledger entry (in-sample baseline,
    # NOT prospective evidence)
    snap = v5.build_snapshot(v2.DATASET_END, svd, events, mdates, mpos,
                             input_manifest_hash=manifest_hash)
    snap.to_parquet(OUT / "realtime_state_snapshot.parquet", index=False,
                    compression="snappy")
    led = v5.ledger_append(OUT / "prospective_state_ledger.parquet", snap,
                           v2.DATASET_END,
                           note="in-sample baseline; prospective rows "
                                "append strictly after 2026-09-18")
    return snap, led


def main():
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    if not head.startswith(BASELINE):
        raise RuntimeError(f"HEAD {head} != baseline {BASELINE}")
    t0 = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    inputs = load_inputs()
    daily = inputs[0]
    print(f"[v5] inputs: panel {len(daily)} rows, events "
          f"{len(inputs[4])}, calendar {daily['observation_date'].min()}"
          f"..{daily['observation_date'].max()}", flush=True)
    res1 = build_all(inputs)
    print(f"[v5] first build done {time.time() - t0:.0f}s", flush=True)
    hashes1 = {k: frame_hash(res1[k]) for k in
               ("svd", "ck", "val", "conf", "audit")}
    tr1 = res1["tr"]
    h_tr = frame_hash(pd.concat([
        tr1["daily_transitions"], tr1["checkpoint_transitions"],
        tr1["runs"], tr1["first_entry"], tr1["revisits"]],
        ignore_index=True).sort_index(axis=1))
    res2 = build_all(inputs, log=lambda *_: None)
    hashes2 = {k: frame_hash(res2[k]) for k in
               ("svd", "ck", "val", "conf", "audit")}
    tr2 = res2["tr"]
    h_tr2 = frame_hash(pd.concat([
        tr2["daily_transitions"], tr2["checkpoint_transitions"],
        tr2["runs"], tr2["first_entry"], tr2["revisits"]],
        ignore_index=True).sort_index(axis=1))
    identical = all(hashes1[k] == hashes2[k] for k in hashes1) \
        and h_tr == h_tr2 and res1["verdict"] == res2["verdict"]
    det = {"products_compared": 7, "identical": bool(identical),
           "frame_hashes": hashes1, "verdict": res1["verdict"]}
    (OUT / "state_determinism.json").write_text(json.dumps(det, indent=2))
    if not identical:
        raise RuntimeError("determinism check FAILED")
    manifest = {
        "schema_version": v5.STATE_SCHEMA_VERSION,
        "rule_version": v5.COMPACT_RULE_VERSION,
        "baseline_commit": BASELINE,
        "built_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
        "inputs": {
            "t3_v3_daily": sha(ROOT / "output/research/t3_v3/"
                               "event_path_daily.parquet"),
            "t3_v4_riskset": sha(ROOT / "output/research/t3_v4/"
                                 "dynamic_riskset.parquet"),
            "t3_v4_forward": sha(ROOT / "output/research/t3_v4/"
                                 "dynamic_forward_outcomes.parquet")},
        "confound_verdict": res1["verdict"],
        "row_counts": {
            "state_vector_daily": len(res1["svd"]),
            "audit": len(res1["audit"]),
            "confound_contrasts": len(res1["conf"]),
            "internal_validation": len(res1["val"])},
    }
    manifest_hash = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    manifest["manifest_hash"] = manifest_hash
    snap, led = write_products(res1, inputs, manifest_hash)
    manifest["products"] = {
        p.name: {"sha256": sha(p), "rows": (
            len(snap) if p.name == "realtime_state_snapshot.parquet"
            else len(pd.read_parquet(p)) if p.suffix == ".parquet"
            and p.name != "prospective_state_ledger.parquet" else (
                len(led) if p.name == "prospective_state_ledger.parquet"
                else None))}
        for p in sorted(OUT.glob("*.parquet"))}
    (OUT / "state_run_manifest.json").write_text(json.dumps(
        manifest, ensure_ascii=False, indent=2))
    print(f"[v5] snapshot rows {len(snap)}, ledger rows {len(led)}", flush=True)
    print(json.dumps({"rows": manifest["row_counts"],
                      "verdict": res1["verdict"],
                      "elapsed_sec": round(time.time() - t0, 1)}), flush=True)


if __name__ == "__main__":
    main()
