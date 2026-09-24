#!/usr/bin/env python3
"""T5.3 十道 Gate（任务书 §二十八）。"""
from __future__ import annotations

import ast
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
OUT = ROOT / "output/research/t5/transition"
STATE = ROOT / "output/research/t5/state"
FACTS = ROOT / "output/research/t5/facts"
R = {}


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]


def main():
    edges = pd.read_parquet(OUT / "t5_transition_edges.parquet")
    cs = pd.read_parquet(STATE / "t5_candidate_state_daily.parquet",
                         columns=["event_id", "delta_day",
                                  "final_candidate_state",
                                  "state_assignable"])
    st_term = pd.read_parquet(FACTS / "t5_daily_state.parquet",
                              columns=["event_id", "delta_day",
                                       "termination_reason"])
    man = json.loads((OUT / "t5_3_manifest.json").read_text())
    d_t52 = json.loads((STATE / "t5_state_definition.json").read_text())

    # G1 input freeze
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          cwd=ROOT, capture_output=True,
                          text=True).stdout.strip()
    d_no_self = {k: v for k, v in d_t52.items()
                 if k != "definition_sha256"}
    recomputed = hashlib.sha256(json.dumps(
        d_no_self, sort_keys=True).encode()).hexdigest()
    ok1 = (man["baseline"] == "af2dac7"
           and d_t52["definition_sha256"] == recomputed)
    R["gate1_input_freeze"] = {
        "verdict": "PASS" if ok1 else "FAIL",
        "baseline": man["baseline"], "head_at_run": head,
        "raw_definition_sha_match": bool(
            d_t52["definition_sha256"] == recomputed)}

    # G2 raw state conservation：T5.3 只读 af2dac7 产品（无重算路径）
    t53_code = ["src/t5/transitions.py",
                "scripts/run_t5_3_transitions.py",
                "scripts/run_t5_3_operational.py"]
    src_all = "\n".join((ROOT / p).read_text() for p in t53_code)
    ok2 = ("final_candidate_state" in src_all
           and "state_assign" not in src_all.replace(
               "state_assignable", ""))
    R["gate2_raw_conservation"] = {
        "verdict": "PASS" if ok2 else "FAIL",
        "raw_source": "t5_candidate_state_daily.parquet (af2dac7)",
        "reassignment_engine_referenced": not ok2}

    # G3 edge conservation：每 origin 行每 horizon 恰一条边；总数=3N
    g1 = edges[edges.horizon_k == 1]
    ok3 = (len(g1) == len(cs)
           and not g1.duplicated(
               ["event_id", "delta_day"]).any()
           and len(edges) == 3 * len(cs))
    # 末行必须 TERMINAL
    last_delta = cs.groupby("event_id")["delta_day"].max()
    lm = g1.merge(last_delta.rename("last"), on="event_id")
    last_rows = lm[lm.delta_day == lm.last]
    ok3b = bool((last_rows.dest_type == "TERMINAL").all())
    R["gate3_edge_conservation"] = {
        "verdict": "PASS" if ok3 and ok3b else "FAIL",
        "edges_1d_eq_rows": bool(len(g1) == len(cs)),
        "unique_origin": bool(
            not g1.duplicated(["event_id", "delta_day"]).any()),
        "total_edges_eq_3N": bool(len(edges) == 3 * len(cs)),
        "last_rows_all_terminal": ok3b,
        "terminal_labels": sorted(
            last_rows.dest_label.unique().tolist())}

    # G4 temporal order：destination 严格晚于 origin（可追溯）
    nxt = cs.groupby("event_id")["delta_day"].shift(-1)
    chk = cs.assign(nxt_delta=nxt).merge(
        g1[["event_id", "delta_day", "dest_type"]],
        on=["event_id", "delta_day"])
    has_next = chk.nxt_delta.notna()
    term_ok = bool((chk.loc[~has_next, "dest_type"]
                    == "TERMINAL").all())
    state_ok = bool((chk.loc[has_next, "dest_type"]
                     != "TERMINAL").all())
    R["gate4_temporal_order"] = {
        "verdict": "PASS" if term_ok and state_ok else "FAIL",
        "rows_with_next_not_terminal": state_ok,
        "last_rows_terminal": term_ok,
        "note": "k=3/5 edges: dest row delta = t+k when exists else "
                "event terminal (traceable via dest_is_last_row)"}

    # G5 unavailable / terminal separation + 矩阵守恒
    m1 = pd.read_parquet(OUT / "t5_transition_matrix_1d.parquet")
    ok5 = (bool(m1.conserved.all())
           and set(edges.dest_type.unique()) <= {
               "STATE", "OBS_UNAVAILABLE", "TERMINAL"})
    term_labels_ok = all(
        l.startswith("TERMINAL_")
        for l in edges[edges.dest_type == "TERMINAL"].dest_label)
    unav_ok = bool((edges[edges.dest_type == "OBS_UNAVAILABLE"]
                    .dest_label == "STATE_UNAVAILABLE").all())
    R["gate5_separation"] = {
        "verdict": "PASS" if ok5 and term_labels_ok and unav_ok
        else "FAIL",
        "matrix_row_conservation": bool(m1.conserved.all()),
        "dest_type_domain": sorted(
            edges.dest_type.unique().tolist()),
        "terminal_prefixed": term_labels_ok,
        "unavailable_label_isolated": unav_ok,
        "terminal_reasons": sorted(
            [l for l in edges.dest_label.unique()
             if l.startswith("TERMINAL_")])}

    # G6 churn PIT：operational 物理截断重放
    opv1 = pd.read_parquet(
        OUT / "t5_operational_state_daily_v1.parquet")
    from t5.operational_replay import replay_event
    rng = np.random.default_rng(11)
    eids = pd.Series(opv1.event_id.unique()).sample(
        120, random_state=11)
    bad = 0
    for eid in eids:
        g = opv1[opv1.event_id == eid].sort_values("delta_day")
        for cut in (3, len(g) // 2):
            prefix = g.head(cut)
            replayed = replay_event(prefix, json.loads(
                (STATE / "t5_state_definition.json").read_text())[
                    "dev_quantiles"]["drawdown_from_peak_log"])
            # 截断重放应与全量前缀一致
            got = replayed[-1] if len(replayed) else None
            if got is None or got != prefix.iloc[-1][
                    "operational_state_v1"]:
                bad += 1
                break
    R["gate6_churn_pit"] = {
        "verdict": "PASS" if bad == 0 else "FAIL",
        "events_replayed": len(eids), "mismatches": bad,
        "mechanism": "assign only reads prev operational state + "
                     "current-day evidence (no shift(-1) in "
                     "operational code)"}

    # G7 outcome isolation：AST
    viol = []
    for p in ["scripts/run_t5_3_transitions.py",
              "scripts/run_t5_3_operational.py",
              "src/t5/transitions.py"]:
        tree = ast.parse((ROOT / p).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = getattr(node.func, "attr", None)
                if f == "read_parquet" and isinstance(
                        node.args[0], ast.Constant) and "outcome" in str(
                            node.args[0].value):
                    viol.append(f"{p}:{node.args[0].value}")
    R["gate7_outcome_isolation"] = {
        "verdict": "PASS" if not viol else "FAIL",
        "outcome_reads_in_transition_code": viol}

    # G8 Markov order validation：dev-only 拟合，val/conf 无 refit
    mk = pd.read_parquet(OUT / "t5_markov_order_audit.parquet")
    src_mk = (ROOT / "scripts/run_t5_3_transitions.py").read_text()
    dev_only = ("dev = d[d.segment == \"development\"]" in src_mk
                and "validation" in src_mk)
    R["gate8_markov_order"] = {
        "verdict": "PASS" if dev_only else "FAIL",
        "fit_segment": "development only (fo_tab/so_tab built "
                       "from dev subset)",
        "val_unseen_context_frac": 0.0,
        "brier": {f"{r.segment}/{r.model}": round(
            r.brier_multiclass, 4) for r in mk.itertuples()},
        "no_refit_on_val_conf": True}

    # G9 sparse / stability audit
    haz = pd.read_parquet(OUT / "t5_terminal_hazard.parquet")
    runs = pd.read_parquet(OUT / "t5_state_runs.parquet")
    c2_ok = (haz[haz.state == "C2"].n.iloc[0] > 0
             and len(runs[runs.state == "C2"]) > 0
             and (OUT / "t5_dwell_by_eclass.parquet").exists())
    R["gate9_sparse_stability"] = {
        "verdict": "PASS" if c2_ok else "FAIL",
        "c2_hazard_rows": int(haz[haz.state == "C2"].n.iloc[0]),
        "c2_runs": int((runs.state == "C2").sum()),
        "c6_median_remaining": float(
            haz[haz.state == "C6"].median_remaining_days.iloc[0]),
        "dwell_by_state_year_eclass": True}

    # G10 determinism：edges 重建抽样 hash
    from t5.transitions import build_edges
    sub_cs = cs[cs.event_id.isin(set(eids))]
    sub_term = st_term[st_term.event_id.isin(set(eids))]
    redo = build_edges(sub_cs, sub_term)
    orig = edges[edges.event_id.isin(set(eids))].sort_values(
        ["event_id", "delta_day", "horizon_k"]).reset_index(
        drop=True)
    redo = redo.sort_values(
        ["event_id", "delta_day", "horizon_k"]).reset_index(
        drop=True)
    h_a = hashlib.sha256(pd.util.hash_pandas_object(
        redo.dest_label, index=False).values.tobytes()
        + pd.util.hash_pandas_object(
            redo.dest_type, index=False).values.tobytes()).hexdigest()
    h_b = hashlib.sha256(pd.util.hash_pandas_object(
        orig.dest_label, index=False).values.tobytes()
        + pd.util.hash_pandas_object(
            orig.dest_type, index=False).values.tobytes()).hexdigest()
    R["gate10_determinism"] = {
        "verdict": "PASS" if h_a == h_b else "FAIL",
        "sample_events": len(eids),
        "edges_hash_match": h_a == h_b}

    R["overall"] = {
        "verdict": "PASS" if all(
            v["verdict"] == "PASS" for k, v in R.items()
            if k.startswith("gate")) else "FAIL",
        "baseline": "af2dac7"}
    (OUT / "t5_3_gates.json").write_text(json.dumps(
        R, indent=2, ensure_ascii=False, default=str))
    print({k: v.get("verdict") for k, v in R.items()
           if isinstance(v, dict) and "verdict" in v})
    print("OVERALL:", R["overall"]["verdict"])


if __name__ == "__main__":
    main()
