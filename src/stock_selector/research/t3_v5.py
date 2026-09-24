"""T3 V5: state engine — turnover normalization, 4-axis state vector,
compact state, transitions, realtime snapshot, prospective ledger.

Research question (work order 2026-09-24, baseline 64a2a22):

    对一只已经发生 lifecycle20 突破的股票，站在今天收盘时，根据今天
    已经知道的信息，它当前处于什么趋势状态？

This is a PIT, deterministic, interpretable state machine — NOT a return
prediction model. Everything below is pre-registered; no outcome-optimized
thresholds anywhere; compact states are descriptive labels with NO ordering
(not A/B/C/D, not strong/medium/weak, not buy/hold/sell).

Turnover normalization (V5 §1, resolves the V4 confound):
    pre20_turn_base      V3 frozen baseline: mean of turn over the last 20
                         vpos-valid trading days strictly before T0. Fixed
                         event property, never redefined after breakout
                         (t3_v3.build_event_daily line "fixed T0 baselines").
    expected_turnover_since_t0 = pre20_turn_base * turn_n_to_tau
                         where turn_n_to_tau = number of T0..tau days that
                         contributed turn>0 to cum_turnover_since_t0
                         (exact V3 accumulation condition).
    turnover_load_to_tau = cum_turnover_since_t0 / expected_turnover_since_t0
    mean_turnover_load_to_tau = mean_turnover_since_t0 / pre20_turn_base
                         (identical to the cumulative definition whenever
                         both are finite — recorded as an IDENTITY CHECK,
                         not an independent discovery).
    Units (V4 schema gate, frozen): turn in percentage points; cum_turnover
    in percentage-point-days; load dimensionless.

Axes (as-of only; ref60 stays background, never overrides lifecycle20):
    structure  distance_to_ref20 >= 0 -> intact ; < 0 -> broken
    position   close_vs_anchored_vwap >= 0 -> above_event_cost ; < 0 -> below
    participation turnover_load_to_tau <= 1 -> normal ; > 1 -> elevated
               (pre-registered threshold 1.0 = own pre-breakout pace)
    extension  tau-specific frozen reference bins (per-tau medians of
               drawdown_from_running_peak and days_since_running_peak over
               the frozen V4 event universe, 0..40, frozen at build):
                 days_since <= med & dd <= med -> extending
                 days_since <= med & dd >  med -> pullback
                 days_since >  med              -> consolidation

Compact state v1 — exhaustive deterministic map over non-null axes:
    broken                          -> structural_break
    intact & below cost             -> structural_pressure
    intact & above cost:
        extending  & load <= 1      -> continuation
        extending  & load >  1      -> high_participation_extension
        pullback                    -> controlled_pullback
        consolidation               -> consolidation
    any axis missing                -> insufficient_data (not a 6-state)
Efficiency primitive (exploratory only, never a primary axis):
    price_progress = close_rel_t0_log ; turnover_load as above;
    efficiency_proxy = price_progress / max(turnover_load, 0.25)
    (pre-registered denominator floor; 2-D components always kept alongside).

Historical validation is internal temporal robustness only — never called
out-of-sample. Prospective evidence starts strictly after DATASET_END
(2026-09-18) via the append-only ledger.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from stock_selector.research import t3_v2 as v2
from stock_selector.research import t3_v3 as v3
from stock_selector.research import t3_v4 as v4

ROOT = Path("/root/project/workspace/stock-selector-v2")
OUT = ROOT / "output/research/t3_v5"

STATE_SCHEMA_VERSION = "state_vector_v1"
COMPACT_RULE_VERSION = "compact_state_v1"
LOAD_THRESHOLD = 1.0          # pre-registered: own pre-breakout pace
EFF_DENOM_FLOOR = 0.25        # pre-registered floor for efficiency proxy
TAUS_ALL = tuple(range(41))   # lifecycle20 observation grid (T0..T40)
CHECKPOINTS = (0, 1, 5, 10, 20)
CONF_PRIMARY_TAUS = (5, 10, 20)
CONF_ALL_TAUS = (0, 1, 5, 10, 20)
CONF_EXPOSURES = ("cum_turnover_since_t0", "pre20_turn_base",
                  "turnover_load_to_tau", "mean_turnover_since_t0")
LIFECYCLE_MARKET_DAYS = 40    # event active window T0..T40 (frozen V2/V3)

COMPACT_STATES = (
    "continuation", "high_participation_extension", "controlled_pullback",
    "consolidation", "structural_pressure", "structural_break",
    "insufficient_data")

# columns consumed from the frozen V3 panel
_PANEL_COLS = [
    "breakout_event_id", "code", "breakout_day", "tau", "observation_date",
    "source_date", "calendar_in_dataset", "row_present",
    "adj_factor_available", "volume_valid", "ref20_obs_n",
    "close_rel_t0_log", "distance_to_ref20", "distance_to_ref60",
    "drawdown_from_running_peak", "days_since_running_peak",
    "new_high_count_to_tau", "cum_turnover_since_t0",
    "mean_turnover_since_t0", "anchored_vwap_obs_n",
    "close_vs_anchored_vwap",
]


# ----------------------------------------------------------------- turnover

def pre20_turn_base(sd, t0):
    """V3 frozen pre-T0 turnover baseline (identical skeleton & filter).

    pre = last 20 vpos-valid trading dates strictly before t0;
    mean over turn requires exactly 20 non-null values (_mean_valid).
    """
    pre = [d for d in sd.dates if d < t0 and d in sd.vpos][-20:]
    if len(pre) != 20:
        return None
    vals = [sd.turn.get(d) for d in pre]
    if any(v is None for v in vals):
        return None
    return float(np.mean(vals))


def build_turnover_load(events, mdates, factors, log=None):
    """Raw recompute of per-event pre20_turn_base and per-tau accumulation.

    Returns long frame: breakout_event_id, tau(0..40), pre20_turn_base,
    turn_n_to_tau, cum_turnover_raw. Accumulation condition is exactly
    V3's: market date exists in stock data and turn > 0.
    """
    mpos = {d: i for i, d in enumerate(mdates)}
    by_code = {}
    for r in events.itertuples(index=False):
        by_code.setdefault(r.code, []).append(r._asdict())
    recs = []
    n_codes = len(by_code)
    for ci, code in enumerate(sorted(by_code)):
        pref = v3.stock_prefix(code)
        fp = ROOT / f"data/adjustment_baostock/per_stock/{pref}.json.gz"
        if not fp.exists():
            continue
        sd = v2.load_stock_data(pref, factors)
        for row in by_code[code]:
            eid = row["breakout_event_id"]
            t0 = row["breakout_day"]
            base = pre20_turn_base(sd, t0)
            i0 = mpos[t0]
            cum, turn_n = 0.0, 0
            for tau in TAUS_ALL:
                gi = i0 + tau
                if gi < len(mdates):
                    d = mdates[gi]
                    tv = sd.turn.get(d)
                    if tv is not None and tv > 0:
                        cum += float(tv)
                        turn_n += 1
                recs.append((eid, tau, base, turn_n, round(cum, 10)))
        if log and ci % 500 == 499:
            log(f"[v5] turnover load {ci + 1}/{n_codes} codes")
    return pd.DataFrame(recs, columns=[
        "breakout_event_id", "tau", "pre20_turn_base", "turn_n_to_tau",
        "cum_turnover_raw"])


def attach_load_columns(daily, load_long):
    """Merge load fields into the panel frame and derive the normalized
    quantities. Identity check column included (must hold exactly).
    """
    m = daily.merge(load_long, on=["breakout_event_id", "tau"], how="left")
    n = m["turn_n_to_tau"].astype(float)
    expected = m["pre20_turn_base"] * n
    with np.errstate(invalid="ignore", divide="ignore"):
        m["expected_turnover_since_t0"] = expected.where(n > 0)
        ok = (n > 0) & (expected > 0)
        m["turnover_load_to_tau"] = (
            m["cum_turnover_since_t0"] / expected).where(ok)
        m["mean_turnover_load_to_tau"] = (
            m["mean_turnover_since_t0"] / m["pre20_turn_base"])
    ident = np.isclose(m["turnover_load_to_tau"].astype(float),
                       m["mean_turnover_load_to_tau"].astype(float),
                       rtol=1e-9, atol=1e-12, equal_nan=True)
    m["load_identity_ok"] = np.where(
        m["turnover_load_to_tau"].isna()
        & m["mean_turnover_load_to_tau"].isna(), True, ident)
    return m


# ------------------------------------------------------------ reference bins

def freeze_reference_bins(daily):
    """Per-tau (0..40) medians of the two extension primitives over the
    frozen event universe (in-dataset rows only). Frozen once at V5 build
    into compact_state_definition.json; realtime never refits.
    """
    ins = daily[daily["source_date"].notna()]
    g = ins.groupby("tau")
    med_dd = g["drawdown_from_running_peak"].median()
    med_dsp = g["days_since_running_peak"].median()
    bins = {}
    for tau in TAUS_ALL:
        if tau in med_dd.index:
            bins[int(tau)] = {
                "median_drawdown": (None if pd.isna(med_dd.get(tau))
                                    else float(med_dd.get(tau))),
                "median_days_since_peak": (None if pd.isna(med_dsp.get(tau))
                                           else float(med_dsp.get(tau))),
                "n": int(((ins["tau"] == tau)
                          & ins["drawdown_from_running_peak"].notna()).sum()),
            }
    return bins


# ------------------------------------------------------------------- states

def _ext_state(dd, dsp, med_dd, med_dsp):
    if pd.isna(dd) or pd.isna(dsp) or med_dd is None or med_dsp is None:
        return None
    if dsp > med_dsp:
        return "consolidation"
    return "extending" if dd <= med_dd else "pullback"


def assign_states(daily_with_load, ref_bins):
    """4-axis + compact states, runs (state_since / previous_state).

    States exist only on in-dataset rows; suspension gaps break runs
    (no forward fill — V3 discipline).
    """
    df = daily_with_load.sort_values(
        ["breakout_event_id", "tau"]).reset_index(drop=True)
    # background structure flag from tau=0 row (event property)
    r0 = df[df["tau"] == 0].set_index("breakout_event_id")["distance_to_ref60"]
    r0v = r0.reindex(df["breakout_event_id"]).to_numpy(dtype=float)
    df["t0_ref60_breakout"] = pd.Series(
        np.where(np.isnan(r0v), None, r0v > 0),
        index=df.index, dtype="object")
    d20 = df["distance_to_ref20"].to_numpy(dtype=float)
    ddraw = df["drawdown_from_running_peak"].to_numpy(dtype=float)
    vwap = df["close_vs_anchored_vwap"].to_numpy(dtype=float)
    load = df["turnover_load_to_tau"].to_numpy(dtype=float)
    dsp = df["days_since_running_peak"].to_numpy(dtype=float)
    taus = df["tau"].to_numpy()
    in_ds = df["source_date"].notna().to_numpy()

    struct = np.where(np.isnan(d20), None,
                      np.where(d20 >= 0, "intact", "broken"))
    pos = np.where(np.isnan(vwap), None,
                   np.where(vwap >= 0, "above_event_cost",
                            "below_event_cost"))
    part = np.where(np.isnan(load), None,
                    np.where(load <= LOAD_THRESHOLD, "normal", "elevated"))
    ext = [None] * len(df)
    med_dd_arr = np.array([np.nan if (ref_bins.get(int(t)) or {})
                           .get("median_drawdown") is None
                           else ref_bins[int(t)]["median_drawdown"]
                           for t in taus], dtype=float)
    med_dsp_arr = np.array([np.nan if (ref_bins.get(int(t)) or {})
                            .get("median_days_since_peak") is None
                            else ref_bins[int(t)]["median_days_since_peak"]
                            for t in taus], dtype=float)
    for i in range(len(df)):
        if not in_ds[i]:
            continue
        dd_i, dsp_i = ddraw[i], dsp[i]
        mdd_i, mdsp_i = med_dd_arr[i], med_dsp_arr[i]
        if (np.isnan(dd_i) or np.isnan(dsp_i) or np.isnan(mdd_i)
                or np.isnan(mdsp_i)):
            continue
        ext[i] = ("consolidation" if dsp_i > mdsp_i
                  else ("extending" if dd_i <= mdd_i else "pullback"))
    # compact map (axes null off-dataset or on missing primitives)
    compact = []
    for s, p, e, pa, ok in zip(struct, pos, ext, part, in_ds):
        if s is None or p is None or e is None or pa is None:
            compact.append(None if not ok else "insufficient_data")
        elif s == "broken":
            compact.append("structural_break")
        elif p == "below_event_cost":
            compact.append("structural_pressure")
        elif e == "pullback":
            compact.append("controlled_pullback")
        elif e == "consolidation":
            compact.append("consolidation")
        else:
            compact.append("continuation" if pa == "normal"
                           else "high_participation_extension")
    df["structure_state"] = struct
    df["cost_position_state"] = pos
    df["participation_state"] = part
    df["extension_state"] = ext
    df["compact_state"] = compact
    # exploratory efficiency primitive (pre-registered floor)
    pp = df["close_rel_t0_log"].to_numpy(dtype=float)
    with np.errstate(invalid="ignore", divide="ignore"):
        eff = pp / np.maximum(load, EFF_DENOM_FLOOR)
    df["price_progress"] = df["close_rel_t0_log"]
    df["efficiency_proxy"] = np.where(
        np.isnan(pp) | np.isnan(load), np.nan, eff)
    # runs over consecutive non-null compact states
    since = np.zeros(len(df), dtype=int)
    prev = np.array([None] * len(df), dtype=object)
    eid = df["breakout_event_id"].to_numpy()
    last_eid, cur_state, run, prev_state = None, None, 0, None
    for i in range(len(df)):
        c = compact[i]
        if eid[i] != last_eid:
            last_eid, cur_state, run, prev_state = eid[i], None, 0, None
        if c is None:
            since[i], prev[i] = 0, None
            cur_state, run, prev_state = None, 0, None
        elif c == cur_state:
            run += 1
            since[i], prev[i] = run, prev_state
        else:
            prev_state = cur_state if cur_state is not None else prev_state
            cur_state, run = c, 1
            since[i], prev[i] = run, prev_state
    df["state_since_tau"] = since
    df["previous_state"] = prev
    df["turn_base_available"] = df["pre20_turn_base"].notna()
    df["load_available"] = df["turnover_load_to_tau"].notna()
    return df


# -------------------------------------------------------------- transitions

def build_transitions(svd):
    """Daily + checkpoint transitions, dwell, first entry, revisits."""
    d = svd[svd["compact_state"].notna()][
        ["breakout_event_id", "code", "tau", "compact_state"]].copy()
    d = d.sort_values(["breakout_event_id", "tau"])
    nxt = d.groupby("breakout_event_id").shift(-1)
    d["next_tau"] = nxt["tau"]
    d["next_state"] = nxt["compact_state"]
    adj = d[(d["next_tau"] - d["tau"]) == 1]
    daily_tr = (adj.groupby(["tau", "compact_state", "next_state"])
                .size().reset_index(name="n")
                .rename(columns={"compact_state": "state_from",
                                 "next_state": "state_to"}))
    daily_tr["scope"] = "daily"
    # per (tau, state_from) probability
    tot = daily_tr.groupby(["tau", "state_from"])["n"].transform("sum")
    daily_tr["p_transition"] = daily_tr["n"] / tot

    rows = []
    for a, b in zip(CHECKPOINTS[:-1], CHECKPOINTS[1:]):
        pa = d[d["tau"] == a].set_index("breakout_event_id")["compact_state"]
        pb = d[d["tau"] == b]["compact_state"].set_axis(
            d[d["tau"] == b]["breakout_event_id"])
        j = pd.DataFrame({"a": pa, "b": pb}).dropna()
        for (sa, sb), n in j.groupby(["a", "b"]).size().items():
            rows.append({"tau_from": a, "tau_to": b, "state_from": sa,
                         "state_to": sb, "n": int(n),
                         "p_transition": float(n) / len(j)})
    cp_tr = pd.DataFrame(rows)
    cp_tr["scope"] = "checkpoint"

    # runs -> dwell / first entry / revisit
    run_rows, first_rows, revisit_rows = [], [], []
    for eid, g in d.groupby("breakout_event_id", sort=False):
        st = g["compact_state"].tolist()
        ta = g["tau"].tolist()
        seen = {}
        runs = {}
        i = 0
        while i < len(st):
            j = i
            while j + 1 < len(st) and st[j + 1] == st[i]:
                j += 1
            length = int(ta[j] - ta[i] + 1)
            run_rows.append({"breakout_event_id": eid, "state": st[i],
                             "start_tau": int(ta[i]), "end_tau": int(ta[j]),
                             "length": length,
                             "right_censored": bool(ta[j] >= 40)})
            if st[i] not in seen:
                first_rows.append({"breakout_event_id": eid, "state": st[i],
                                   "first_entry_tau": int(ta[i])})
                seen[st[i]] = 0
            seen[st[i]] += 1
            runs[st[i]] = runs.get(st[i], 0) + 1
            i = j + 1
        for s_, k in runs.items():
            revisit_rows.append({"breakout_event_id": eid, "state": s_,
                                 "run_count": k, "revisit_count": k - 1})
    runs_df = pd.DataFrame(run_rows)
    dwell = (runs_df.groupby("state")["length"]
             .agg(n_runs="size", median_dwell="median",
                  p90_dwell=lambda x: float(np.percentile(x, 90)))
             .reset_index())
    return {"daily_transitions": daily_tr,
            "checkpoint_transitions": cp_tr,
            "runs": runs_df,
            "dwell": dwell,
            "first_entry": pd.DataFrame(first_rows),
            "revisits": pd.DataFrame(revisit_rows)}


# ------------------------------------------------------------- realtime

def active_anchor(asof, events, mdates, mpos):
    """Latest-breakout anchor rule per stock at asof (work order §13).

    active := breakout_day <= asof <= min(t0 + 40 market days, DATASET_END).
    Returns frame: code, breakout_event_id (anchor), breakout_day,
    overlapping_event_count, prior_breakout_event_id.
    """
    last_pos = v4.last_dataset_pos(mdates)
    if asof not in mpos or mpos[asof] > last_pos:
        raise ValueError(f"asof {asof} not a usable market date")
    ap = mpos[asof]
    rows = []
    for r in events.itertuples(index=False):
        t0 = r.breakout_day
        i0 = mpos[t0]
        if i0 > ap:
            continue
        end = min(i0 + LIFECYCLE_MARKET_DAYS, last_pos)
        if ap > end:
            continue
        rows.append((r.code, r.breakout_event_id, t0, i0))
    a = pd.DataFrame(rows, columns=["code", "breakout_event_id",
                                    "breakout_day", "i0"])
    a = a.sort_values(["code", "i0"]).reset_index(drop=True)
    out = []
    for code, g in a.groupby("code", sort=True):
        gs = g.reset_index(drop=True)
        out.append({"code": code,
                    "breakout_event_id": gs["breakout_event_id"].iat[-1],
                    "breakout_day": gs["breakout_day"].iat[-1],
                    "overlapping_event_count": int(len(gs)),
                    "prior_breakout_event_id": (
                        gs["breakout_event_id"].iat[-2]
                        if len(gs) > 1 else None)})
    cols = ["code", "breakout_event_id", "breakout_day",
            "overlapping_event_count", "prior_breakout_event_id"]
    if not out:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(out, columns=cols).sort_values(
        "code").reset_index(drop=True)


def build_snapshot(asof, svd, events, mdates, mpos, input_manifest_hash=""):
    """Realtime state snapshot at asof — anchors + current states.

    Contains NO forward outcome fields (No-Future gate).
    """
    anchors = active_anchor(asof, events, mdates, mpos)
    if not len(anchors):
        return pd.DataFrame()
    ap = mpos[asof]
    sv = svd.set_index(["breakout_event_id", "tau"])
    rows = []
    for r in anchors.itertuples(index=False):
        i0 = mpos[r.breakout_day]
        tau = ap - i0
        try:
            s = sv.loc[(r.breakout_event_id, tau)]
        except KeyError:
            continue
        rows.append({
            "asof_date": asof, "code6": str(r.code).zfill(6),
            "breakout_event_id": r.breakout_event_id,
            "breakout_day": r.breakout_day, "tau": int(tau),
            "structure_state": s["structure_state"],
            "cost_position_state": s["cost_position_state"],
            "participation_state": s["participation_state"],
            "extension_state": s["extension_state"],
            "compact_state": s["compact_state"],
            "distance_to_ref20": s["distance_to_ref20"],
            "distance_to_ref60": s["distance_to_ref60"],
            "t0_ref60_breakout": s["t0_ref60_breakout"],
            "close_vs_anchored_vwap": s["close_vs_anchored_vwap"],
            "close_rel_t0_log": s["close_rel_t0_log"],
            "drawdown_from_running_peak": s["drawdown_from_running_peak"],
            "days_since_running_peak": s["days_since_running_peak"],
            "new_high_count_to_tau": s["new_high_count_to_tau"],
            "cum_turnover_since_t0": s["cum_turnover_since_t0"],
            "mean_turnover_since_t0": s["mean_turnover_since_t0"],
            "turnover_load_to_tau": s["turnover_load_to_tau"],
            "efficiency_proxy": s["efficiency_proxy"],
            "row_present": bool(s["row_present"]),
            "adj_factor_available": bool(s["adj_factor_available"]),
            "turn_base_available": bool(s["turn_base_available"]),
            "load_available": bool(s["load_available"]),
            "ref20_obs_n": s["ref20_obs_n"],
            "anchored_vwap_obs_n": s["anchored_vwap_obs_n"],
            "state_since_tau": int(s["state_since_tau"]),
            "previous_state": s["previous_state"],
            "overlapping_event_count": int(r.overlapping_event_count),
            "prior_breakout_event_id": r.prior_breakout_event_id,
            "schema_version": STATE_SCHEMA_VERSION,
            "rule_version": COMPACT_RULE_VERSION,
            "input_manifest_hash": input_manifest_hash,
        })
    return pd.DataFrame(rows)


def ledger_row_hash(prev_hash, row):
    canon = json.dumps({k: (None if pd.isna(v) and not isinstance(v, str)
                            else v) for k, v in row.items()
                        if k != "row_sha256"},
                       sort_keys=True, ensure_ascii=False, default=str)
    h = hashlib.sha256()
    h.update((prev_hash or "").encode())
    h.update(canon.encode())
    return h.hexdigest()


def ledger_append(ledger_path, snapshot, asof, note=""):
    """Append-only, hash-chained prospective ledger rows."""
    snap = snapshot.copy()
    if ledger_path.exists():
        led = pd.read_parquet(ledger_path)
        if len(led):
            if asof <= led["asof_date"].max():
                raise ValueError("ledger is append-only: asof must increase")
            prev = led["row_sha256"].iat[-1]
        else:
            prev = None
    else:
        led, prev = None, None
    recs = []
    for r in snap.to_dict("records"):
        r["ledger_note"] = note
        rh = ledger_row_hash(prev, r)
        r["row_sha256"] = rh
        recs.append(r)
        prev = rh
    new = pd.DataFrame(recs)
    out = new if led is None else pd.concat([led, new], ignore_index=True)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(ledger_path, index=False, compression="snappy")
    return out


def verify_ledger_chain(ledger_path):
    led = pd.read_parquet(ledger_path)
    prev = None
    bad = 0
    for r in led.to_dict("records"):
        if ledger_row_hash(prev, r) != r["row_sha256"]:
            bad += 1
        prev = r["row_sha256"]
    mono = bool(led["asof_date"].is_monotonic_increasing)
    return {"n_rows": len(led), "hash_chain_mismatches": bad,
            "asof_monotonic": mono}


# ------------------------------------------------------- internal validation

def internal_validation(svd, fwd):
    """Compact states x V4 forward outcomes — semantic consistency only.

    No maximization, no ranking; contradictions are preserved as-is.
    """
    ck = svd[svd["tau"].isin(CONF_PRIMARY_TAUS)
             & svd["compact_state"].notna()][
        ["breakout_event_id", "tau", "compact_state", "structure_state",
         "participation_state", "turnover_load_to_tau"]]
    fw = fwd.set_index(["breakout_event_id", "tau", "delta"])
    rows = []
    for (tau, dl), o in fw.groupby(level=["tau", "delta"]):
        if tau not in CONF_PRIMARY_TAUS:
            continue
        g = ck[ck["tau"] == tau].merge(
            o.reset_index()[["breakout_event_id", "fwd_mkt_excess_log",
                             "future_max_drawdown", "new_high_within",
                             "lose_ref20_within"]],
            on="breakout_event_id", how="inner")
        for st, s in g.groupby("compact_state"):
            rows.append({
                "scope": "compact_state", "tau": int(tau), "delta": int(dl),
                "cell": st, "n": int(np.isfinite(
                    s["fwd_mkt_excess_log"]).sum()),
                "median_fwd_excess": float(np.nanmedian(
                    s["fwd_mkt_excess_log"])),
                "median_fwd_mdd": float(np.nanmedian(
                    s["future_max_drawdown"])),
                "p_new_high": float(np.nanmean(s["new_high_within"])),
                "p_lose_ref20": float(np.nanmean(s["lose_ref20_within"])),
            })
        # §9 grid: structure integrity x load
        g["cell2"] = np.where(g["structure_state"] == "intact",
                              "intact", "impaired") + "_" + \
            np.where(g["participation_state"] == "elevated",
                     "highload", "lowload")
        for st, s in g.groupby("cell2"):
            rows.append({
                "scope": "structure_x_load", "tau": int(tau),
                "delta": int(dl), "cell": st,
                "n": int(np.isfinite(s["fwd_mkt_excess_log"]).sum()),
                "median_fwd_excess": float(np.nanmedian(
                    s["fwd_mkt_excess_log"])),
                "median_fwd_mdd": float(np.nanmedian(
                    s["future_max_drawdown"])),
                "p_new_high": float(np.nanmean(s["new_high_within"])),
                "p_lose_ref20": float(np.nanmean(s["lose_ref20_within"])),
            })
    return pd.DataFrame(rows)


# --------------------------------------------------------- confound engine

def _quartile_bins(values):
    ok = values.notna()
    if not ok.any():
        return None
    r = values.rank(method="average", pct=True)
    q = np.clip(1 + np.floor(4 * r.to_numpy()), 1, 4)
    return pd.Series(q, index=values.index, dtype="Int64").where(ok)


def confound_contrasts(audit, riskset, fwd, B=v4.BOOT_B):
    """Four-exposure decomposition + within-baseline-stratum re-analysis.

    Reuses the V4 cluster-bootstrap machinery verbatim (stock and date
    clusterings, percentile CIs, add-one smoothed two-sided p).
    """
    rs = riskset[["breakout_event_id", "tau", "code", "asof_date"]]
    fw = fwd.set_index(["breakout_event_id", "tau", "delta"])
    frames = []           # bins frames: tau -> var/bin/bin_label/eid
    strat_frames = []
    for tau in CONF_ALL_TAUS:
        g = audit[audit["tau"] == tau].set_index("breakout_event_id")
        for var in CONF_EXPOSURES:
            q = _quartile_bins(g[var])
            if q is None:
                continue
            frames.append(pd.DataFrame({
                "breakout_event_id": q.index, "tau": tau, "state_var": var,
                "bin_set": "quartile", "bin": q,
                "bin_label": q.map({1: "Q1", 2: "Q2", 3: "Q3",
                                    4: "Q4"}).astype("string")}))
        # baseline quartile strata (event property, frozen at tau=0)
        bq = _quartile_bins(g["pre20_turn_base"])
        if bq is not None:
            lq = _quartile_bins(g["turnover_load_to_tau"])
            if lq is not None:
                for s in (1, 2, 3, 4):
                    m = (bq == s) & lq.notna()
                    q = _quartile_bins(g["turnover_load_to_tau"][m])
                    frames.append(pd.DataFrame({
                        "breakout_event_id": g.index[m], "tau": tau,
                        "state_var": f"load_in_baseQ{s}",
                        "bin_set": "stratified", "bin": q,
                        "bin_label": q.map(
                            {1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}
                        ).astype("string")}))
    bins = pd.concat(frames, ignore_index=True)
    rows, pvals = [], []
    for tau in CONF_ALL_TAUS:
        rs_tau = rs[rs["tau"] == tau].set_index("breakout_event_id")
        bins_tau = bins[bins["tau"] == tau]
        for dl in v4.DELTAS:
            try:
                o = fw.xs(tau, level="tau").xs(dl, level="delta")
            except KeyError:
                continue
            for var in list(CONF_EXPOSURES) + [
                    f"load_in_baseQ{s}" for s in (1, 2, 3, 4)]:
                for bset in ("quartile", "stratified"):
                    btv = bins_tau[(bins_tau["state_var"] == var)
                                   & (bins_tau["bin_set"] == bset)]
                    if not len(btv):
                        continue
                    m, df = v4._family_frame(btv, rs_tau, o)
                    if df is None:
                        continue
                    meds = [v4._nanmed(df.loc[df["bin"] == q,
                                              "exc"].to_numpy())
                            for q in (1, 2, 3, 4)]
                    mono = bool(np.all(np.diff(meds) >= 0)
                                or np.all(np.diff(meds) <= 0)) \
                        if all(np.isfinite(meds)) else False
                    draws = {}
                    for cl_name, cl_col in (("stock", "cluster_stock"),
                                            ("date", "cluster_date")):
                        fkey = f"v5conf|{tau}|{var}|{bset}|{dl}|{cl_name}"
                        draws[cl_name] = v4._boot_family(
                            df[["bin", "exc", "raw", "mdd", "nh", cl_col]]
                            .rename(columns={cl_col: "cluster"}), B,
                            v4.family_seed(fkey))
                    rows.extend(v4._bin_rows(df, draws, tau, var, bset,
                                             dl, mono))
                    drow = v4._diff_row(df, draws, tau, var, bset, dl, mono)
                    if drow is not None:
                        pvals.append({"tau": tau, "delta": dl,
                                      "state_var": var, "bin_set": bset,
                                      "p": drow["p_boot_stock"],
                                      "row_ref": len(rows)})
                        rows.append(drow)
    con = pd.DataFrame(rows)
    if pvals:
        pv = pd.DataFrame(pvals)
        for (tau, dl, bset), g in pv.groupby(["tau", "delta", "bin_set"]):
            m_ = len(g)
            prev = 0.0
            for i, (_, r) in enumerate(g.sort_values("p").iterrows()):
                adj = min(max(prev, r["p"] * m_ / (m_ - i)), 1.0)
                con.loc[r["row_ref"], "p_holm_stock"] = adj
                con.loc[r["row_ref"], "reject_holm05"] = bool(adj < 0.05)
                prev = adj
    return con.sort_values(
        ["tau", "state_var", "bin_set", "bin", "delta"]).reset_index(drop=True)


def confound_verdict(con):
    """Pre-registered readout of the Turnover Confound Gate.

    PASS_norm_persistent requires, under stock clustering:
      - raw cum_turnover Q4-Q1 < 0 and Holm-significant at all primary taus
        (reproduces V4);
      - normalized turnover_load Q4-Q1 < 0 and Holm-significant at >=2 of 3
        primary taus for at least one delta each;
      - within >=3 of 4 baseline strata: load Q4-Q1 < 0 at tau=10 for
        delta=20.
    Otherwise the gradient is attributed to the high-turnover-stock
    population (confounded) and MUST NOT be named turnover pressure.
    """
    def diff(tau, var, dl, bset="quartile"):
        r = con[(con.tau == tau) & (con.state_var == var)
                & (con.delta == dl) & (con.bin_set == bset)
                & (con.bin_label == "top_minus_bottom")]
        if not len(r):
            return None
        r = r.iloc[0]
        return {"diff": float(r["median_fwd_excess"]),
                "sig": bool(r.get("reject_holm05") is True or
                            (pd.notna(r.get("p_holm_stock"))
                             and r["p_holm_stock"] < 0.05))}
    raw_ok = all(diff(t, "cum_turnover_since_t0", dl) is not None
                 and diff(t, "cum_turnover_since_t0", dl)["diff"] < 0
                 and diff(t, "cum_turnover_since_t0", dl)["sig"]
                 for t in CONF_PRIMARY_TAUS
                 for dl in v4.DELTAS)
    load_cells = 0
    for t in CONF_PRIMARY_TAUS:
        if any((diff(t, "turnover_load_to_tau", dl) or {}).get("diff", 1) < 0
               and (diff(t, "turnover_load_to_tau", dl) or {}).get("sig")
               for dl in v4.DELTAS):
            load_cells += 1
    strat_ok = 0
    for s in (1, 2, 3, 4):
        d_ = diff(10, f"load_in_baseQ{s}", 20, bset="stratified")
        if d_ is not None and d_["diff"] < 0:
            strat_ok += 1
    return {
        "raw_reproduced_all_primary": bool(raw_ok),
        "load_negative_primary_taus": int(load_cells),
        "load_negative_strata_tau10_d20": int(strat_ok),
        "verdict": ("PASS_norm_persistent"
                    if raw_ok and load_cells >= 2 and strat_ok >= 3
                    else "FAIL_confound_dominant"),
    }


# ------------------------------------------------------------ definitions

def definition_json(ref_bins, verdict=None):
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "rule_version": COMPACT_RULE_VERSION,
        "axes": {
            "structure": {"primitive": "distance_to_ref20",
                          "threshold": 0.0,
                          "states": {"intact": ">= 0",
                                     "broken": "< 0"},
                          "background": ["distance_to_ref60",
                                         "t0_ref60_breakout"]},
            "position": {"primitive": "close_vs_anchored_vwap",
                         "threshold": 0.0,
                         "states": {"above_event_cost": ">= 0",
                                    "below_event_cost": "< 0"},
                         "semantics": "current close vs event-anchored "
                                      "VWAP cost proxy only"},
            "participation": {
                "primitive": "turnover_load_to_tau",
                "formula": "cum_turnover_since_t0 / "
                           "(pre20_turn_base * turn_n_to_tau)",
                "pre20_turn_base": "V3 frozen: mean turn over last 20 "
                                   "vpos-valid dates strictly before T0; "
                                   "event property, never redefined",
                "threshold": LOAD_THRESHOLD,
                "states": {"normal": "<= 1", "elevated": "> 1"},
                "realtime_rule": "fixed threshold; never re-cut on the "
                                 "day's cross-section"},
            "extension": {
                "primitives": ["drawdown_from_running_peak",
                               "days_since_running_peak"],
                "reference_bins": "per-tau medians over the frozen V4 "
                                  "event universe (tau 0..40), frozen at "
                                  "V5 build; realtime never refits",
                "mapping": {"extending": "days_since <= med & dd <= med",
                            "pullback": "days_since <= med & dd > med",
                            "consolidation": "days_since > med"},
                "bins": ref_bins},
        },
        "compact_state_v1": {
            "mapping": {
                "structural_break": "structure == broken",
                "structural_pressure": "intact & below_event_cost",
                "controlled_pullback": "intact & above & extension == "
                                       "pullback",
                "consolidation": "intact & above & extension == "
                                 "consolidation",
                "continuation": "intact & above & extending & load <= 1",
                "high_participation_extension": "intact & above & "
                                                "extending & load > 1",
                "insufficient_data": "any axis missing"},
            "ordering": "none — descriptive labels, not A/B/C/D, not "
                        "strong/weak, not buy/hold/sell"},
        "efficiency_primitive": {
            "name": "efficiency_proxy", "exploratory": True,
            "formula": f"close_rel_t0_log / max(turnover_load_to_tau, "
                       f"{EFF_DENOM_FLOOR})",
            "denominator_floor": EFF_DENOM_FLOOR,
            "note": "2-D components (price_progress, turnover_load) always "
                    "reported alongside; never a primary axis"},
        "turnover_confound_verdict": verdict,
        "provenance": {
            "baseline_commit": "64a2a22",
            "dataset_end": v2.DATASET_END,
            "bootstrap": {"B": v4.BOOT_B, "seed": v4.BOOT_SEED,
                          "clusters": ["stock", "as-of date"]}},
    }
