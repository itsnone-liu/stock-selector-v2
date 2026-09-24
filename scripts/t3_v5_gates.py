#!/usr/bin/env python3
"""T3 V5 integrity gates (work order §17).

G1 Turnover Confound   raw/baseline/normalized turnover decomposed, identity
                       holds, verdict recorded, independent base recompute
G2 State PIT           physical truncation -> V3 rebuild -> state recompute
G3 State Determinism   full double-build identical (runner artifact)
G4 Transition Integrity daily states reproduce checkpoint states, counts,
                       dwell/first-entry/revisit recomputed independently
G5 Active Anchor       latest-breakout anchor rule 100% deterministic
G6 Realtime Replay     random historical asof replays match truncated recompute
G7 No-Future           realtime products contain no outcome fields/dates
G8 Prospective Ledger  append-only, hash chain, versions/hash complete
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
from stock_selector.research import t3_v2 as v2  # noqa: E402
from stock_selector.research import t3_v3 as v3  # noqa: E402
from stock_selector.research import t3_v5 as v5  # noqa: E402

OUT = ROOT / "output/research/t3_v5"
REPORT = {}
RNG = np.random.default_rng(20260925)


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def truncate_sd(sd, asof):
    """Physically remove every observation strictly after asof."""
    f = lambda dd: {k: v for k, v in dd.items() if k <= asof}  # noqa: E731
    return v2.StockData(
        code_pfx=sd.code_pfx, dates=[d for d in sd.dates if d <= asof],
        o=None,
        h=f(sd.h), l=f(sd.l), c=f(sd.c), vol=f(sd.vol), amt=f(sd.amt),
        turn=f(sd.turn), hfq_h=f(sd.hfq_h), hfq_c=f(sd.hfq_c),
        F=f(sd.F), valid=[d for d in sd.valid if d <= asof],
        vpos={d for d in sd.vpos if d <= asof})


def map_compact(struct, pos, part, ext):
    if struct is None or pos is None or part is None or ext is None:
        return "insufficient_data"
    if struct == "broken":
        return "structural_break"
    if pos == "below_event_cost":
        return "structural_pressure"
    if ext == "pullback":
        return "controlled_pullback"
    if ext == "consolidation":
        return "consolidation"
    return "continuation" if part == "normal" else \
        "high_participation_extension"


def state_from_row(row, tau, turn_base, turn_n):
    load = (row["cum_turnover_since_t0"] / (turn_base * turn_n)
            if turn_base is not None and turn_n
            and row["cum_turnover_since_t0"] is not None else None)
    d20 = row["distance_to_ref20"]
    struct = (None if d20 is None or (isinstance(d20, float)
              and np.isnan(d20)) else ("intact" if d20 >= 0 else "broken"))
    vw = row["close_vs_anchored_vwap"]
    pos = (None if vw is None or (isinstance(vw, float) and np.isnan(vw))
           else ("above_event_cost" if vw >= 0 else "below_event_cost"))
    part = None if load is None else ("normal" if load <= 1.0 else "elevated")
    dd = row["drawdown_from_running_peak"]
    dsp = row["days_since_running_peak"]
    ext = None
    b = REF_BINS.get(int(tau))
    if b and dd is not None and dsp is not None:
        if dsp > b["median_days_since_peak"]:
            ext = "consolidation"
        else:
            ext = "extending" if dd <= b["median_drawdown"] else "pullback"
    return struct, pos, part, ext, load


def eq(a, b):
    if a is None and (b is None or (isinstance(b, float) and np.isnan(b))):
        return True
    if b is None and (a is None or (isinstance(a, float) and np.isnan(a))):
        return True
    if isinstance(a, float) and isinstance(b, float):
        return bool(np.isclose(a, b, rtol=1e-9, atol=1e-12, equal_nan=True))
    return a == b


def main():
    global REF_BINS
    svd = pd.read_parquet(OUT / "state_vector_daily.parquet")
    defn = json.loads((OUT / "compact_state_definition.json").read_text())
    REF_BINS = {int(k): v for k, v in
        defn["axes"]["extension"]["bins"].items()}
    audit = pd.read_parquet(OUT / "turnover_normalization_audit.parquet")
    events = v2.load_events()
    factors = v2.load_factor_cache(ROOT / "output/research/t3_v2")
    mdates, mclose = v2.market_calendar_and_close()
    mpos = {d: i for i, d in enumerate(mdates)}
    manifest = json.loads((OUT / "state_run_manifest.json").read_text())

    # ---------------- G1 Turnover Confound ----------------
    conf = pd.read_parquet(OUT / "turnover_confound_contrasts.parquet")
    ident_bad = int((~audit["load_identity_ok"].astype(bool)).sum())
    cells = (conf.groupby(["tau", "state_var", "bin_set", "delta"])
             .ngroups)
    have_all = all(
        len(conf[(conf.tau == t) & (conf.state_var == v)
                 & (conf.delta == d) & (conf.bin_label == "top_minus_bottom")])
        for t in v5.CONF_ALL_TAUS for d in (5, 10, 20)
        for v in v5.CONF_EXPOSURES)
    # independent pre20_turn_base recompute from raw (sampled 40 events)
    ev_s = events.sample(40, random_state=7)
    base_bad = 0
    aud = audit.set_index("breakout_event_id")
    for r in ev_s.itertuples(index=False):
        pref = v3.stock_prefix(r.code)
        sd = v2.load_stock_data(pref, factors)
        b = v5.pre20_turn_base(sd, r.breakout_day)
        got = aud.loc[r.breakout_event_id, "pre20_turn_base"].iloc[0]
        if not eq(b, got):
            base_bad += 1
    verdict = defn["turnover_confound_verdict"]
    g1 = {"verdict": "PASS" if (
        ident_bad == 0 and have_all and base_bad == 0
        and verdict["verdict"] in ("PASS_norm_persistent",
                                   "FAIL_confound_dominant")) else "FAIL",
        "identity_violations": ident_bad, "contrast_families": cells,
        "exposures_complete": bool(have_all),
        "independent_base_mismatches": base_bad,
        "confound_verdict": verdict}
    REPORT["gate1_turnover_confound"] = g1

    # ---------------- G2 State PIT ----------------
    ins = svd[svd["source_date"].notna()]
    picks = []
    for st in v5.COMPACT_STATES + (None,):
        pool = ins[ins["compact_state"] == st] if st else ins[
            ins["compact_state"].isna()]
        if len(pool):
            p = pool.sample(min(12, len(pool)), random_state=11)
            picks.append(p)
    # add structural coverage across taus
    for t in (0, 1, 5, 10, 20, 37, 40):
        pool = ins[ins["tau"] == t]
        if len(pool):
            picks.append(pool.sample(min(6, len(pool)), random_state=t))
    pit = pd.concat(picks).drop_duplicates(
        ["breakout_event_id", "tau"]).sample(
        min(120, len(pd.concat(picks))), random_state=3)
    ev_by_id = events.set_index("breakout_event_id", drop=False)
    sd_cache = {}
    bad = []
    for r in pit.itertuples(index=False):
        eid, tau = r.breakout_event_id, r.tau
        ev_row = ev_by_id.loc[eid]
        pref = v3.stock_prefix(ev_row["code"])
        sd_full = sd_cache.get(pref)
        if sd_full is None:
            sd_full = v2.load_stock_data(pref, factors)
            sd_cache[pref] = sd_full
        asof = r.observation_date
        sdt = truncate_sd(sd_full, asof)
        # truncation proof: no observation beyond asof survives
        assert all(d <= asof for d in sdt.dates)
        built = v3.build_event_daily(sdt, ev_row, mdates, mclose, mpos)
        row = built[built["tau"] == tau].iloc[0]
        turn_n = sum(1 for t_ in range(tau + 1)
                     if (d_ := mdates[mpos[r.breakout_day] + t_]) in sdt.turn
                     and sdt.turn[d_] and sdt.turn[d_] > 0)
        base_ = v5.pre20_turn_base(sdt, r.breakout_day)
        st, po, pa, ex, load = state_from_row(row, tau, base_, turn_n)
        cmp_ = map_compact(st, po, pa, ex)
        ref = svd[(svd.breakout_event_id == eid) & (svd.tau == tau)].iloc[0]
        checks = [eq(st, ref["structure_state"]),
                  eq(po, ref["cost_position_state"]),
                  eq(pa, ref["participation_state"]),
                  eq(ex, ref["extension_state"]),
                  eq(cmp_, ref["compact_state"]),
                  eq(load, ref["turnover_load_to_tau"])]
        if not all(checks):
            bad.append({"id": eid, "tau": int(tau), "checks": checks})
    g2 = {"verdict": "PASS" if not bad else "FAIL",
          "checked": len(pit), "mismatches": len(bad), "bad": bad[:5],
          "note": "physical truncation at asof; state rebuilt from frozen "
                  "V3 builder + independent mapping"}
    REPORT["gate2_state_pit"] = g2

    # ---------------- G3 State Determinism ----------------
    det = json.loads((OUT / "state_determinism.json").read_text())
    g3 = {"verdict": "PASS" if det["identical"] else "FAIL",
          "double_build_identical": det["identical"],
          "confound_verdict": det["verdict"]}
    REPORT["gate3_state_determinism"] = g3

    # ---------------- G4 Transition Integrity ----------------
    tr = pd.read_parquet(OUT / "state_transitions.parquet")
    d = svd[svd["compact_state"].notna()][
        ["breakout_event_id", "tau", "compact_state"]].sort_values(
        ["breakout_event_id", "tau"])
    nxt = d.groupby("breakout_event_id").shift(-1)
    d2 = d.assign(next_tau=nxt["tau"], next_state=nxt["compact_state"])
    d2 = d2[(d2["next_tau"] - d2["tau"]) == 1]
    rec = (d2.groupby(["tau", "compact_state", "next_state"]).size()
           .rename("n").reset_index())
    prod = tr[tr["scope"] == "daily"].set_index(
        ["tau_from", "state_from", "state_to"])[["n"]]
    mism = 0
    for r in rec.itertuples(index=False):
        try:
            pn = int(prod.loc[(r.tau, r.compact_state, r.next_state), "n"])
        except KeyError:
            mism += 1
            continue
        mism += int(pn != int(r.n))
    # checkpoint states == daily states
    ck_bad = 0
    ck = pd.read_parquet(OUT / "state_checkpoints.parquet")
    for t in v5.CHECKPOINTS:
        a = ck[ck.tau == t].set_index("breakout_event_id")["compact_state"]
        b_ = svd[svd.tau == t].set_index("breakout_event_id")["compact_state"]
        ck_bad += int(sum(1 for k in a.index if not eq(a[k], b_[k])))
    # dwell / first entry / revisit recompute (independent run extraction)
    run_bad = 0
    run_rows = []
    for eid, g in d.groupby("breakout_event_id", sort=False):
        st = g["compact_state"].tolist()
        ta = g["tau"].tolist()
        i = 0
        while i < len(st):
            j = i
            while j + 1 < len(st) and st[j + 1] == st[i]:
                j += 1
            run_rows.append({"state": st[i], "length": int(ta[j] - ta[i] + 1)})
            i = j + 1
    rr = pd.DataFrame(run_rows).groupby("state")["length"].agg(
        ["size", "sum"])
    runs = pd.read_parquet(OUT / "state_run_stats.parquet")
    pr = runs.groupby("state")["length"].agg(["size", "sum"])
    for st in rr.index:
        if st not in pr.index or rr.loc[st, "size"] != pr.loc[st, "size"] \
                or rr.loc[st, "sum"] != pr.loc[st, "sum"]:
            run_bad += 1
    g4 = {"verdict": "PASS" if mism == 0 and ck_bad == 0 and run_bad == 0
          else "FAIL",
          "daily_transition_count_mismatches": int(mism),
          "checkpoint_state_mismatches": ck_bad,
          "run_stat_mismatches": int(run_bad),
          "note": "transitions/checkpoints/run stats recomputed "
                  "independently from state_vector_daily"}
    REPORT["gate4_transition_integrity"] = g4

    # ---------------- G5 Active Anchor + G6 Replay + G7 No-Future -------
    snap = pd.read_parquet(OUT / "realtime_state_snapshot.parquet")
    led = pd.read_parquet(OUT / "prospective_state_ledger.parquet")
    last_pos = max(i for i, d_ in enumerate(mdates) if d_ <= v2.DATASET_END)
    anchor_bad = replay_bad = 0
    test_dates = [mdates[i] for i in sorted(RNG.choice(
        last_pos - 5, 12, replace=False))]
    test_dates.append(v2.DATASET_END)
    replay_rows = []
    for asof in test_dates:
        ap = mpos[asof]
        # independent anchor computation
        per_stock = {}
        for r in events.itertuples(index=False):
            i0 = mpos[r.breakout_day]
            if i0 > ap or ap > min(i0 + 40, last_pos):
                continue
            per_stock.setdefault(str(r.code).zfill(6), []).append(
                (i0, r.breakout_event_id))
        expect = {}
        for code, lst in per_stock.items():
            lst.sort()
            expect[str(code).zfill(6)] = (
                lst[-1][1], len(lst),
                lst[-2][1] if len(lst) > 1 else None)
        got = v5.build_snapshot(asof, svd, events, mdates, mpos, "g")
        for r in got.itertuples(index=False):
            e = expect.get(r.code6)
            prior = r.prior_breakout_event_id
            prior = None if (prior is None or (isinstance(prior, float)
                                               and np.isnan(prior))) \
                else prior
            if e is None or e[0] != r.breakout_event_id \
                    or e[1] != r.overlapping_event_count \
                    or e[2] != prior:
                anchor_bad += 1
        replay_rows.append(len(got))
    # replay determinism + truncated state recompute for 10 anchored events
    for asof in test_dates[:4]:
        s1 = v5.build_snapshot(asof, svd, events, mdates, mpos, "g")
        s2 = v5.build_snapshot(asof, svd, events, mdates, mpos, "g")
        if not s1.equals(s2):
            replay_bad += 1
        for r in s1.head(4).itertuples(index=False):
            ev_row = ev_by_id.loc[r.breakout_event_id]
            pref = v3.stock_prefix(ev_row["code"])
            sd_full = sd_cache.get(pref)
            if sd_full is None:
                sd_full = v2.load_stock_data(pref, factors)
                sd_cache[pref] = sd_full
            sdt = truncate_sd(sd_full, asof)
            built = v3.build_event_daily(sdt, ev_row, mdates, mclose, mpos)
            row = built[built["tau"] == r.tau].iloc[0]
            turn_n = sum(1 for t_ in range(int(r.tau) + 1)
                         if (d_ := mdates[mpos[r.breakout_day] + t_])
                         in sdt.turn and sdt.turn[d_]
                         and sdt.turn[d_] > 0)
            st, po, pa, ex, load = state_from_row(
                row, r.tau, v5.pre20_turn_base(sdt, r.breakout_day), turn_n)
            cmp_ = map_compact(st, po, pa, ex)
            if not (eq(st, r.structure_state) and eq(po, r.cost_position_state)
                    and eq(pa, r.participation_state)
                    and eq(ex, r.extension_state)
                    and eq(cmp_, r.compact_state)):
                replay_bad += 1
    g5 = {"verdict": "PASS" if anchor_bad == 0 else "FAIL",
          "asof_dates_tested": len(test_dates),
          "anchor_mismatches": int(anchor_bad)}
    REPORT["gate5_active_anchor"] = g5
    g6 = {"verdict": "PASS" if replay_bad == 0 else "FAIL",
          "asof_dates_tested": 4, "state_recompute_mismatches": int(
              replay_bad),
          "snapshot_rows_per_date": replay_rows}
    REPORT["gate6_realtime_replay"] = g6
    banned = ("fwd_", "future_", "new_high_within", "lose_ref",
              "days_to_next_high", "recover_")
    bad_cols = [c for c in snap.columns if any(b in c for b in banned)]
    bad_cols += [c for c in led.columns if any(b in c for b in banned)]
    sv = svd.set_index(["breakout_event_id", "tau"])
    date_bad = 0
    for r in snap.itertuples(index=False):
        srow = sv.loc[(r.breakout_event_id, r.tau)]
        if pd.notna(srow["source_date"]) and srow["source_date"] != r.asof_date:
            date_bad += 1
    g7 = {"verdict": "PASS" if not bad_cols and date_bad == 0 else "FAIL",
          "banned_columns_found": bad_cols,
          "source_date_mismatches": int(date_bad),
          "note": "outcome names banned; every snapshot row's as-of equals "
                  "its panel source_date"}
    REPORT["gate7_no_future"] = g7

    # ---------------- G8 Prospective Ledger ----------------
    chain = v5.verify_ledger_chain(OUT / "prospective_state_ledger.parquet")
    need = {"asof_date", "code6", "breakout_event_id", "compact_state",
            "schema_version", "rule_version", "input_manifest_hash",
            "row_sha256"}
    have = set(led.columns)
    versions_ok = bool((led["rule_version"] == v5.COMPACT_RULE_VERSION).all()
                       and (led["schema_version"]
                            == v5.STATE_SCHEMA_VERSION).all())
    g8 = {"verdict": "PASS" if (
        chain["hash_chain_mismatches"] == 0 and chain["asof_monotonic"]
        and need <= have and versions_ok
        and led["input_manifest_hash"].notna().all()) else "FAIL",
        **chain, "missing_fields": sorted(need - have),
        "versions_frozen": versions_ok}
    REPORT["gate8_prospective_ledger"] = g8

    REPORT["overall"] = {"verdict": "PASS" if all(
        v["verdict"] == "PASS" for k, v in REPORT.items()
        if k.startswith("gate")) else "FAIL",
        "baseline": "64a2a22",
        "products": {p.name: sha(p) for p in sorted(OUT.glob("*.parquet"))}}
    (OUT / "state_integrity_gates.json").write_text(json.dumps(
        REPORT, indent=2, ensure_ascii=False, default=str))
    print(json.dumps({k: v.get("verdict") for k, v in REPORT.items()
                      if isinstance(v, dict) and "verdict" in v}, indent=0))
    print("OVERALL:", REPORT["overall"]["verdict"])


if __name__ == "__main__":
    main()
