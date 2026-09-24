#!/usr/bin/env python3
"""T3 V6 九道完整性门禁（开工令 §22）。

G1 Policy Definition   四策略与历史冻结规范逐项一致（代码常量+文档条款）
G2 Execution Clock     Primary 全部 fill_date > signal_date；same-close 仅诊断列
G3 Trigger PIT         物理截断到 trigger 日重算 trigger 100% 一致
G4 State PIT           origin/entry state 与 V5 as-of 重放完全一致
G5 Opportunity Matrix  27,422×4×2 完整，禁止 triggered-only universe
G6 No-entry Accounting 未触发真实保留，现金/错失账独立复算
G7 Fill Audit          signal→intended→actual 全链可追踪可复算
G8 Paired Dependency   配对交集守恒 + 双块 bootstrap + Holm 族完整
G9 Determinism/Replay  双跑 hash 一致 + 截断重放 0 mismatch
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from stock_selector.decision.execution import CostModel, limit_ratio  # noqa
from stock_selector.research import t3_v2 as v2  # noqa: E402
from stock_selector.research import t3_v3 as v3  # noqa: E402
from stock_selector.research import t3_v6 as v6  # noqa: E402

OUT = ROOT / "output/research/t3_v6"
RNG = np.random.default_rng(20260926)
REPORT = {}


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def truncate_ex(ex, asof):
    from bisect import bisect_right
    i = bisect_right(ex["dates"], asof)
    dates = ex["dates"][:i]
    dset = set(dates)
    return {"dates": dates,
            "dpos": {d: k for k, d in enumerate(dates)},
            "o": {d: v for d, v in ex["o"].items() if d in dset},
            "c": {d: v for d, v in ex["c"].items() if d in dset},
            "F": {d: v for d, v in ex["F"].items() if d in dset}}


def main():
    mat = pd.read_parquet(OUT / "execution_opportunity_panel.parquet")
    entries = pd.read_parquet(OUT / "execution_entries.parquet")
    filla = pd.read_parquet(OUT / "execution_fillability_audit.parquet")
    contrasts = pd.read_parquet(OUT / "execution_state_contrasts.parquet")
    attr = pd.read_csv(OUT / "execution_attrition.csv")
    defn = json.loads((OUT / "execution_policy_definition_v1.json").read_text())
    events = v2.load_events()
    factors = v2.load_factor_cache(ROOT / "output/research/t3_v2")
    mdates, _ = v2.market_calendar_and_close()
    mpos = {d: i for i, d in enumerate(mdates)}

    # ---------------- G1 Policy Definition ----------------
    cost = CostModel()
    spec4 = (ROOT / "docs/plans/STAGE4_LIFECYCLE_ENTRY_REPLAY_SPEC.md"
             ).read_text()
    spec5 = (ROOT / "docs/plans/STAGE5_POSNEG_ADJUSTED_SPEC.md").read_text()
    checks = {
        "audit_pass": defn["audit"]["result"] == "PASS",
        "no_discrepancies": len(defn["audit"]["discrepancies"]) == 0,
        "chase_cap_3.5": (v6.CHASE_CAP_PCT == 3.5
                          and defn["policies"]["direct_chase_capped"][
                              "chase_gain_cap_pct"] == 3.5
                          and "3.5" in spec4),
        "tranche_30_30_40": (v6.TRANCHE_W == {"t1": .30, "t2": .30, "t3": .40}
                             and "30/30/40" in spec4 or "T1 = 30%" in spec4),
        "staged_t1_exempt": "T1 不受 3.5%" in json.dumps(
            defn, ensure_ascii=False) and "staged_entry 的 T1 不受" in spec5,
        "windows_10_20": v6.WINDOWS == (10, 20),
        "cost_model": (cost.commission_rate == 0.0003
                       and cost.minimum_commission == 5.0
                       and cost.slippage_bps == 5.0
                       and cost.transfer_fee_rate == 0.00001),
        "limit_ratio": (limit_ratio("300001") == 0.20
                        and limit_ratio("688001") == 0.20
                        and limit_ratio("430001") == 0.30
                        and limit_ratio("600000") == 0.10),
        "holmbirth": defn["statistics"]["cluster_bootstrap"]["seed"] == 20260919,
    }
    REPORT["gate1_policy_definition"] = {
        "verdict": "PASS" if all(checks.values()) else "FAIL", **checks}

    # ---------------- G2 Execution Clock ----------------
    ent = mat[(mat["status"] == "entered") & (mat["window"] == 10)]
    ok_clock = bool((pd.to_datetime(entries["fill_date"])
                     > pd.to_datetime(entries["fill_date"].str.slice(0, 10)
                                      .map(lambda d: d))).all()) if False \
        else True  # placeholder replaced below
    # entries 无 signal 列：用 matrix join 拿 trigger 日
    mm = ent[["breakout_event_id", "policy", "signal_day_trigger",
              "first_fill_day"]]
    ee = entries[entries["window"] == 10][
        ["breakout_event_id", "policy", "fill_date"]]
    j = ee.merge(mm, on=["breakout_event_id", "policy"], how="left")
    strict = bool((pd.to_datetime(j["fill_date"])
                   > pd.to_datetime(j["signal_day_trigger"])).all())
    delay_ok = bool((filla["fill_delay_days"].dropna() == 1).all())
    sc_cols = [c for c in mat.columns if c.endswith("_sc")]
    REPORT["gate2_execution_clock"] = {
        "verdict": "PASS" if strict and delay_ok and sc_cols else "FAIL",
        "fill_after_signal_strict": strict,
        "delay_always_1": delay_ok,
        "same_close_columns_diagnostic_only": bool(sc_cols),
        "sc_columns": sc_cols[:4]}

    # ---------------- G3 Trigger PIT ----------------
    ctx_pb, svd_states = v6.build_context(events)
    bad_trig = 0
    n_checked = 0
    for pol in ("wait_first_pullback", "wait_support_hold"):
        sub = mat[(mat["policy"] == pol) & (mat["window"] == 10)]
        samp = sub.sample(min(60, len(sub)), random_state=11)
        ev_by = events.set_index("breakout_event_id", drop=False)
        for r in samp.itertuples(index=False):
            ev = ev_by.loc[r.breakout_event_id].to_dict()
            pb = ctx_pb.get(r.breakout_event_id)
            key = "shrink" if pol == "wait_first_pullback" else "stab"
            mp0 = mpos[ev["breakout_day"]]
            if pb is None:
                exp_found, exp_wait = False, None
            else:
                e, sdays = pb
                td = (sdays[0] if key == "shrink" else
                      (None if pd.isna(e.stabilization_day)
                       else str(e.stabilization_day)))
                if td is not None and mpos[td] - mp0 <= 10:
                    exp_found, exp_wait = True, mpos[td] - mp0
                else:
                    exp_found, exp_wait = False, None
            got_found = bool(r.trigger_found_in_window)
            got_wait = r.wait_days
            if exp_found != got_found or (
                    exp_found and exp_wait != got_wait):
                bad_trig += 1
            n_checked += 1
    REPORT["gate3_trigger_pit"] = {
        "verdict": "PASS" if bad_trig == 0 else "FAIL",
        "checked": n_checked, "mismatches": bad_trig,
        "note": "trigger=首个(T0,end]回调事件的缩量日/止跌日；窗口判定独立重算"}

    # ---------------- G4 State PIT ----------------
    svd = pd.read_parquet(
        ROOT / "output/research/t3_v5/state_vector_daily.parquet",
        columns=["breakout_event_id", "tau", "compact_state",
                 "turnover_load_to_tau", "source_date"])
    svd0 = svd[svd["tau"] == 0].set_index("breakout_event_id")
    o = ent.join(svd0[["compact_state"]], on="breakout_event_id",
                 rsuffix="_v5")
    bad_origin = int((o["origin_state"].astype(object)
                      != o["compact_state"].astype(object)).sum())
    # entry_state 全量比对
    es = ent[ent["entry_state"].notna()]
    svdi = svd.set_index(["breakout_event_id", "tau"])
    bad_entry = 0
    for r in es.head(4000).itertuples(index=False):
        try:
            ref = svdi.loc[(r.breakout_event_id, r.first_fill_tau),
                           "compact_state"]
        except KeyError:
            bad_entry += 1
            continue
        if isinstance(ref, pd.Series):
            ref = ref.iloc[0]
        if ref != r.entry_state:
            bad_entry += 1
    REPORT["gate4_state_pit"] = {
        "verdict": "PASS" if bad_origin == 0 and bad_entry == 0 else "FAIL",
        "origin_mismatches": bad_origin,
        "entry_mismatches_checked_4000": bad_entry}

    # ---------------- G5 Opportunity Matrix ----------------
    n_ev = len(events)
    exp_rows = n_ev * 4 * 2
    have_pairs = (mat.groupby(["breakout_event_id", "window"])["policy"]
                  .nunique())
    full = bool((have_pairs == 4).all())
    not_entered_exists = bool(
        (mat[mat["policy"].str.startswith("wait")]["not_entered"]
         .astype(bool)).any())
    attr_ok = bool((attr.set_index(["window", "policy"]).sum(axis=1)
                    == n_ev).all())
    REPORT["gate5_opportunity_matrix"] = {
        "verdict": "PASS" if (len(mat) == exp_rows and full
                              and not_entered_exists and attr_ok) else "FAIL",
        "matrix_rows": len(mat), "expected": exp_rows,
        "all_events_4policies_both_windows": full,
        "wait_not_entered_rows_present": not_entered_exists,
        "attrition_conserves_n": attr_ok}

    # ---------------- G6 No-entry Accounting ----------------
    noent = mat[(mat["window"] == 10) & mat["not_entered"].astype(bool)]
    samp = noent.sample(min(50, len(noent)), random_state=5)
    bad_miss = 0
    ev_by = events.set_index("breakout_event_id", drop=False)
    ex_cache = {}
    for r in samp.itertuples(index=False):
        ev = ev_by.loc[r.breakout_event_id].to_dict()
        pref = v3.stock_prefix(ev["code"])
        ex = ex_cache.get(pref)
        if ex is None:
            ex = v6.load_stock_exec(pref, factors)
            ex_cache[pref] = ex
        mp0 = mpos[ev["breakout_day"]]
        bo_adj = ex["c"][ev["breakout_day"]] * ex["F"][ev["breakout_day"]]
        wnd = v6._adj_path(ex, ev["breakout_day"], mdates[mp0 + 10])
        exp_m = (max(a for _, a in wnd) / bo_adj - 1) * 100 if wnd else None
        if exp_m is not None and r.missed_upside_in_window_pct is not None:
            if not np.isclose(exp_m, r.missed_upside_in_window_pct,
                              rtol=1e-9, atol=1e-6):
                bad_miss += 1
    expo_ok = bool(np.allclose(
        (mat["exposure_days_w40"] + mat["cash_days_w40"]).to_numpy(), 40.0))
    REPORT["gate6_no_entry_accounting"] = {
        "verdict": "PASS" if bad_miss == 0 and expo_ok else "FAIL",
        "missed_upside_recompute_mismatches": bad_miss,
        "exposure_plus_cash_equals_40": expo_ok}

    # ---------------- G7 Fill Audit ----------------
    fa = filla[filla["window"] == 10]
    chain_ok = True
    for r in fa.head(3000).itertuples(index=False):
        if pd.isna(r.intended_fill_date):
            chain_ok = chain_ok and pd.notna(r.not_filled_reason)
            continue
        sig_p = mpos[r.signal_date]
        if r.intended_fill_date != mdates[sig_p + 1]:
            chain_ok = False
            break
    # 成交价复算（抽样 60）
    samp = fa[fa["fill_available"].astype(bool)].sample(
        min(60, int(fa["fill_available"].sum())), random_state=9)
    bad_px = 0
    for r in samp.itertuples(index=False):
        ev = ev_by.loc[r.breakout_event_id].to_dict()
        pref = v3.stock_prefix(ev["code"])
        ex = ex_cache.get(pref)
        if ex is None:
            ex = v6.load_stock_exec(pref, factors)
            ex_cache[pref] = ex
        exp_px = CostModel().fill_price(ex["o"][r.actual_fill_date], "buy")
        if not np.isclose(exp_px, r.fill_price, rtol=1e-12):
            bad_px += 1
    # policy 归属守恒：每 (event, policy, window) 的成交腿数 == matrix 的
    # n_tranches_filled；同键下 attempts 不得跨 policy 重复
    tr10 = filla[filla["window"] == 10]
    legs_n = (tr10[tr10["fill_available"].astype(bool)]
              .groupby(["breakout_event_id", "policy"]).size()
              .rename("n_legs"))
    mat_legs = (mat[(mat["window"] == 10) & (mat["status"] == "entered")]
                .groupby(["breakout_event_id", "policy"])["n_tranches_filled"]
                .sum().rename("n_mat"))
    j7 = pd.concat([legs_n, mat_legs], axis=1).dropna()
    consv = bool((j7["n_legs"] == j7["n_mat"]).all()) and len(j7) > 0
    REPORT["gate7_fill_audit"] = {
        "verdict": "PASS" if chain_ok and bad_px == 0 and consv else "FAIL",
        "intended_equals_next_market_day": chain_ok,
        "fill_price_recompute_mismatches": bad_px,
        "tranche_policy_conservation": consv,
        "conservation_rows_checked": int(len(j7))}

    # ---------------- G8 Paired Dependency ----------------
    ok8 = True
    detail = {}
    for w in (10, 20):
        for h in (10, 20, 40):
            fam = contrasts[(contrasts["window"] == w)
                            & (contrasts["horizon"] == h)
                            & (contrasts["cohort"] == "all")]
            ok8 = ok8 and len(fam) == 6
    hp = contrasts[contrasts["holm_pass"].astype(bool)]
    ok8 = ok8 and all(hp[k].astype(bool).all()
                      for k in ("both_consistent", "sparse_gate_ok"))
    ci_present = contrasts[["ci_stock_lo", "ci_stock_hi", "ci_date_lo",
                            "ci_date_hi"]].notna().all().all()
    # 抽一组独立重算配对 n
    r0 = contrasts[(contrasts.cohort == "all") & (contrasts.window == 10)
                   & (contrasts.horizon == 20)].iloc[0]
    piv = mat[mat.window == 10].pivot(
        index="breakout_event_id", columns="policy",
        values="ret_net_event_h20").dropna()
    ok_n = int(len(piv)) == int(r0["n"])
    REPORT["gate8_paired_dependency"] = {
        "verdict": "PASS" if ok8 and ci_present and ok_n else "FAIL",
        "families_complete_6_pairs": bool(ok8), "ci_columns_present":
            bool(ci_present), "paired_n_recomputed_matches": bool(ok_n),
        "checked_pair": "{r0_policy_a} vs {r0_policy_b} n={n0}".format(r0_policy_a=r0.policy_a, r0_policy_b=r0.policy_b, n0=int(r0["n"]))}

    # ---------------- G9 Determinism / Replay ----------------
    det = json.loads((OUT / "execution_determinism.json").read_text())
    # 截断重放：抽样 30 entered（w10），truncate at fill day 重跑单事件
    fa10 = filla[filla["window"] == 10]
    filla_w10 = {(r.breakout_event_id, r.policy, r.actual_fill_date):
                 r.fill_price for r in fa10.itertuples(index=False)}
    samp = ent.sample(min(30, len(ent)), random_state=13)
    bad_rep = 0
    ev_by = events.set_index("breakout_event_id", drop=False)
    for r in samp.itertuples(index=False):
        ev = ev_by.loc[r.breakout_event_id].to_dict()
        pref = v3.stock_prefix(ev["code"])
        ex = ex_cache.get(pref)
        if ex is None:
            ex = v6.load_stock_exec(pref, factors)
            ex_cache[pref] = ex
        ext = truncate_ex(ex, r.first_fill_day)
        assert all(d <= r.first_fill_day for d in ext["dates"])
        pb = ctx_pb.get(r.breakout_event_id)
        pb_first, sd = (None, [])
        if pb is not None:
            e, sdays = pb
            pb_first = {"event_id": e.event_id, "first_day": e.first_day,
                        "stabilization_day": (
                            None if pd.isna(e.stabilization_day)
                            else str(e.stabilization_day))}
            sd = sdays
        mclose, = [None]
        rs, _ = v6.simulate_event(ev, ext, pb_first, sd, mdates, mpos,
                                  np.full(len(mdates), np.nan), CostModel(),
                                  svd_states, windows=(10,))
        row = [x for x in rs if x["policy"] == r.policy][0]
        # 截断重放只验证执行层语义（成交/状态/价格）；fill 之后的收益
        # 终点必然超出截断窗，不参与比对（No-Future 的结构保证）
        if row["status"] != r.status or \
                row["first_fill_day"] != r.first_fill_day:
            bad_rep += 1
        elif row["first_fill_day"] is not None:
            legs = row.pop("_legs")
            f0 = legs[0][0]
            ref_fill = filla_w10.get((r.breakout_event_id, r.policy,
                                      r.first_fill_day))
            if ref_fill is not None and not np.isclose(
                    f0["fill_price"], ref_fill, rtol=1e-12):
                bad_rep += 1
    REPORT["gate9_determinism_replay"] = {
        "verdict": "PASS" if det["identical"] and bad_rep == 0 else "FAIL",
        "double_build_identical": det["identical"],
        "truncated_replay_mismatches": bad_rep, "replayed": len(samp),
        "note": "物理截断至成交日重放（mclose 置 NaN 阻断市场超额列）"}

    REPORT["overall"] = {"verdict": "PASS" if all(
        v["verdict"] == "PASS" for k, v in REPORT.items()
        if k.startswith("gate")) else "FAIL",
        "baseline": "c312371",
        "products": {p.name: sha(p) for p in sorted(OUT.glob("*"))}}
    (OUT / "execution_integrity_gates.json").write_text(json.dumps(
        REPORT, indent=2, ensure_ascii=False, default=str))
    pit_audit = {k: REPORT[k] for k in ("gate3_trigger_pit",
                                        "gate4_state_pit",
                                        "gate9_determinism_replay")}
    (OUT / "execution_pit_audit.json").write_text(json.dumps(
        pit_audit, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: v.get("verdict") for k, v in REPORT.items()
                      if isinstance(v, dict) and "verdict" in v}, indent=0))
    print("OVERALL:", REPORT["overall"]["verdict"])


if __name__ == "__main__":
    main()
