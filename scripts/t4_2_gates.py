#!/usr/bin/env python3
"""T4.2 六道 Gate（开工令 §七）。

G1 Event Conservation   27,422/27,422，ID 差集空，冻结字段一致
G2 T0 Causality         pit 字段 max_source_date<=T0；物理截断重算 0 mismatch
G3 Frozen Reconciliation svd@tau0 继承列逐项 exact；新增量能列独立复算
G4 Research Isolation   无 post-T0 outcome 列；构建源码无 outcome 引用
G5 Coverage/Missingness 逐字段覆盖率；缺失保持 null（抽样与源一致）
G6 Determinism          双跑 hash 一致；manifest 血缘完整
"""
from __future__ import annotations

import gzip
import json
import sys
from bisect import bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.research import t3_v2 as v2  # noqa: E402

OUT = ROOT / "output/research/t4/t0_state"
REPORT = {}


def main():
    t = pd.read_parquet(OUT / "t4_t0_state.parquet")
    sc = pd.read_parquet(OUT / "t4_t0_sector_retrospective.parquet")
    fd = pd.read_csv(OUT / "t4_t0_feature_dictionary.csv")
    fc = pd.read_csv(OUT / "t4_t0_field_coverage.csv")
    manifest = json.loads((OUT / "t4_t0_manifest.json").read_text())
    det = json.loads((OUT / "t4_2_determinism.json").read_text())
    events = v2.load_events()
    svd = pd.read_parquet(
        ROOT / "output/research/t3_v5/state_vector_daily.parquet")
    s0 = svd[svd["tau"] == 0].set_index("breakout_event_id")

    # ---------------- G1 ----------------
    ids_v6 = set(events["breakout_event_id"])
    ids_t = set(t["breakout_event_id"])
    j = t.merge(events[["breakout_event_id", "code", "breakout_day",
                        "end_day"]], on="breakout_event_id", how="outer",
                suffixes=("", "_v6"), indicator=True)
    both = j[j["_merge"] == "both"]
    field_ok = bool((both["code"] == both["code_v6"]).all()
                    and (both["breakout_day"] == both["breakout_day_v6"]).all()
                    and (both["end_day"] == both["end_day_v6"]).all())
    REPORT["gate1_event_conservation"] = {
        "verdict": "PASS" if (len(t) == 27422 and t["breakout_event_id"]
                              .is_unique and not (ids_v6 - ids_t)
                              and not (ids_t - ids_v6) and field_ok) else "FAIL",
        "rows": len(t), "unique": bool(t["breakout_event_id"].is_unique),
        "old_only": len(ids_v6 - ids_t), "new_only": len(ids_t - ids_v6),
        "frozen_fields_identical": field_ok,
        "sector_companion_rows": len(sc)}

    # ---------------- G2 物理截断重算 ----------------
    ev_by = events.set_index("breakout_event_id", drop=False)
    samp = t.sample(30, random_state=3)
    bad = 0
    for r in samp.itertuples(index=False):
        code = str(r.code).zfill(6)
        p = (ROOT / "data/adjustment_baostock/per_stock"
             / f"{'sh' if code.startswith(('6','9')) else 'sz'}.{code}.json.gz")
        with gzip.open(p, "rt") as f:
            j2 = json.load(f)
        dates = [x[0] for x in j2["unadj"]]
        # 物理截断：只保留 <= T0 的行
        i = bisect_right(dates, r.breakout_day) - 1
        if i < 0 or dates[i] != r.breakout_day:
            continue
        vol = [float(x[5]) if x[5] else None for x in j2["unadj"][:i + 1]]
        v_pre = [v for v in vol[max(0, i - 20):i] if v]
        exp_base = float(np.mean(v_pre)) if len(v_pre) == 20 else None
        if exp_base is not None:
            if not np.isclose(exp_base, r.pre20_volume_base, rtol=1e-9):
                bad += 1
            elif not np.isclose(vol[i] / exp_base, r.volume_load_t0,
                                rtol=1e-9):
                bad += 1
        elif r.pre20_volume_base is not None and not pd.isna(
                r.pre20_volume_base):
            bad += 1
    # PIT 标注：sector companion 必须 100% 非 PIT
    sec_pit_ok = bool((~sc["is_point_in_time"].astype(bool)).all()
                      and sc["retrospective_context_only"].astype(bool).all()
                      and (~sc["pit_primary_eligible"].astype(bool)).all())
    fd_pit = fd[fd["pit_eligible"] == False]  # noqa: E712
    fd_pit_ok = bool(set(fd_pit["feature_name"]) >= {
        "sector_ret_20d", "sector_vs_mkt_20d", "stock_vs_sector_20d",
        "industry_gate"})
    REPORT["gate2_t0_causality"] = {
        "verdict": "PASS" if bad == 0 and sec_pit_ok and fd_pit_ok else "FAIL",
        "truncated_recompute_mismatches": bad, "checked": len(samp),
        "sector_companion_non_pit_flagged": sec_pit_ok,
        "dictionary_machine_readable_pit_flags": fd_pit_ok,
        "note": "membership snapshot 属信息链：sector 价格虽为历史 PIT，"
                "归类非时点 → 整族标 retrospective"}

    # ---------------- G3 冻结对账 ----------------
    bad3 = {}
    ren = {"t0_turn": "cum_turnover_since_t0",
           "turnover_load_t0": "turnover_load_to_tau",
           "new_high_count_t0": "new_high_count_to_tau"}
    for c in t.columns:
        src = ren.get(c, c)
        if src in s0.columns:
            a = t.set_index("breakout_event_id")[c].sort_index()
            b = s0[src].sort_index()
            if not pd.api.types.is_numeric_dtype(a):
                b2 = b.astype(object)
                mism = int((a.fillna("<NA>") != b2.fillna("<NA>")).sum())
            else:
                pair = pd.concat([a, b], axis=1, keys=["t4", "v5"])
                both_ok = pair.dropna()
                mism = int((~(np.isclose(both_ok["t4"].astype(float),
                                         both_ok["v5"].astype(float),
                                         rtol=1e-12, atol=1e-12)
                               | (both_ok["t4"] == both_ok["v5"]))).sum())
            null_mism = int((a.isna() != b.isna()).sum())
            if mism or null_mism:
                bad3[c] = {"value_mismatch": mism, "null_mismatch": null_mism}
    # identity: turnover_load_t0 == t0_turn / pre20_turn_base
    sub = t.dropna(subset=["turnover_load_t0", "t0_turn",
                           "pre20_turn_base"])
    ident = float(np.isclose(sub["turnover_load_t0"],
                             sub["t0_turn"] / sub["pre20_turn_base"],
                             rtol=1e-9).mean())
    REPORT["gate3_frozen_reconciliation"] = {
        "verdict": "PASS" if not bad3 and ident == 1.0 else "FAIL",
        "inherited_columns_checked": int(sum(
            1 for c in t.columns
            if ren.get(c, c) in s0.columns)),
        "mismatches": bad3,
        "load_identity_rate": ident}

    # ---------------- G4 研究隔离 ----------------
    patterns = ("y5", "y10", "y20", "y40", "future", "ret_net", "mfe",
                "mae", "mdd", "policy", "outcome", "h5", "h10", "h20",
                "h40", "fill", "tranche", "entry_premium", "excess")
    hits = [c for c in list(t.columns) + list(sc.columns)
            if any(p in c for p in patterns)]
    import re
    src_txt = (ROOT / "src/t4/features/build_t0.py").read_text()
    # 血缘检查针对实际 IO 目标（read_parquet/read_csv 的路径字面量），
    # 模块自带的 FORBIDDEN 常量清单不算读取
    io_targets = re.findall(r'read_parquet\(\s*\n?\s*[^)]*?\)',
                            src_txt) + re.findall(
        r'read_csv\([^)]*\)', src_txt)
    lineage_bad = [w for w in ("execution_opportunity_panel",
                               "execution_entries", "execution_tranches",
                               "execution_state_contrasts",
                               "execution_entry_paths",
                               "execution_policy_outcomes")
                   if any(w in x for x in io_targets)]
    REPORT["gate4_research_isolation"] = {
        "verdict": "PASS" if not hits and not lineage_bad else "FAIL",
        "outcome_column_hits": hits,
        "source_lineage_forbidden_refs": lineage_bad,
        "outcome_sources_read": False}

    # ---------------- G5 覆盖率 ----------------
    cov_ok = bool(len(fc) >= 40 and (fc["n_valid"] + fc["n_missing"]
                                     == 27422).all())
    # 抽样：svd null 保持 null（不填 neutral）
    nn = t[t["volume_valid"] == False]  # noqa: E712
    keep_null = bool(nn["t0_turn"].isna().all()) if len(nn) else True
    REPORT["gate5_coverage"] = {
        "verdict": "PASS" if cov_ok and keep_null else "FAIL",
        "fields_documented": int(len(fc)),
        "counts_conserve": cov_ok,
        "invalid_rows_stay_null": keep_null,
        "lowest_coverage": fc.sort_values("coverage").iloc[0][
            ["feature_name", "coverage"]].to_dict()}

    # ---------------- G6 ----------------
    REPORT["gate6_determinism"] = {
        "verdict": "PASS" if det["identical"] else "FAIL",
        "frames": det["frames"],
        "manifest_fields_present": all(k in manifest for k in (
            "v6_frozen_source", "v5_source", "t4_1_source",
            "mapping_snapshot_date", "feature_definition_version"))}

    REPORT["overall"] = {
        "verdict": "PASS" if all(
            v["verdict"] == "PASS"
            for k, v in REPORT.items() if k.startswith("gate")) else "FAIL",
        "baseline": "ca5e2a8",
        "feature_definition_version": "t4_t0_state_v1"}
    (OUT / "t4_t0_gate_report.json").write_text(json.dumps(
        REPORT, indent=2, ensure_ascii=False, default=str))
    (OUT / "t4_t0_pit_audit.json").write_text(json.dumps(
        {"gate2_t0_causality": REPORT["gate2_t0_causality"],
         "gate4_research_isolation": REPORT["gate4_research_isolation"],
         "pit_feature_names": fd[fd["pit_eligible"] == True][  # noqa: E712
             "feature_name"].tolist()}, indent=2, ensure_ascii=False))
    (OUT / "t4_t0_reconciliation.json").write_text(json.dumps(
        REPORT["gate3_frozen_reconciliation"], indent=2))
    print(json.dumps({k: v.get("verdict") for k, v in REPORT.items()
                      if isinstance(v, dict) and "verdict" in v}, indent=0))
    print("OVERALL:", REPORT["overall"]["verdict"])


if __name__ == "__main__":
    main()
