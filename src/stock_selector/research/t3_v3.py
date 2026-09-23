"""T3 V3 trajectory facts: event x market-calendar tau=0..40.

This module deliberately does not import event_labels. It builds only as-of-tau
facts; retrospective summaries are derived from the daily panel by the builder.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd
from . import t3_v2 as v2

ROOT = v2.ROOT
TAUS = tuple(range(41))
CHECKPOINTS = (0, 1, 5, 10, 20, 40)


def stock_prefix(code: str) -> str:
    return ("sh." if str(code).zfill(6).startswith(("6", "9")) else "sz.") + str(code).zfill(6)


def _mean_valid(sd, dates, field):
    vals = [getattr(sd, field).get(d) for d in dates]
    vals = [float(x) for x in vals if x is not None and np.isfinite(x) and x > 0]
    return float(np.mean(vals)) if len(vals) == len(dates) and vals else None


def _ratio(x, base):
    return float(x / base) if x is not None and base is not None and base > 0 else None


def _strict_vwap(sd, dates):
    if not dates or any(d not in sd.vpos for d in dates):
        return None
    vol = sum(float(sd.vol[d]) for d in dates)
    amt = sum(float(sd.amt[d]) for d in dates)
    return float(amt / vol) if vol > 0 else None


def _ref20_raw(sd, t0):
    prior = [d for d in sd.dates if d < t0][-20:]
    return max((sd.c[d] for d in prior), default=None), len(prior)


def _ref60_adj(sd, t0):
    prior = [d for d in sd.valid if d < t0][-60:]
    return max((sd.adj[d] for d in prior), default=None), len(prior)


def build_event_daily(sd, event_row, mdates, mclose, mpos):
    """Build exactly 41 rows for one event. No future observations are read."""
    eid = event_row["breakout_event_id"]
    t0 = event_row["breakout_day"]
    i0 = mpos[t0]
    p0 = sd.adj.get(t0)
    raw0 = sd.c.get(t0)
    ref20, ref20_n = _ref20_raw(sd, t0)
    ref60, ref60_n = _ref60_adj(sd, t0)
    pre = [d for d in sd.dates if d < t0 and d in sd.vpos][-20:]
    vol_base = _mean_valid(sd, pre, "vol") if len(pre) == 20 else None
    amt_base = _mean_valid(sd, pre, "amt") if len(pre) == 20 else None
    turn_base = _mean_valid(sd, pre, "turn") if len(pre) == 20 else None
    rows = []
    adj_seen = []
    peak_tau = None
    peak_ret = None
    max_dd = None
    cum_turn = 0.0
    turn_n = 0
    peak_vol_ratio = None
    peak_turn_ratio = None
    for tau in TAUS:
        gi = i0 + tau
        d = mdates[gi] if gi < len(mdates) else None
        in_dataset = d is not None and d <= v2.DATASET_END
        row_present = bool(d in sd.dates) if d is not None else False
        factor_available = bool(d in sd.F) if d is not None else False
        vpos = bool(d in sd.vpos) if d is not None else False
        adj = sd.adj.get(d) if d is not None else None
        raw = sd.c.get(d) if d is not None else None
        source_date = d if in_dataset else None
        current_ret = float(np.log(adj / p0)) if adj is not None and p0 else None
        mkt_ex = (current_ret - float(np.log(mclose[gi] / mclose[i0]))) \
            if current_ret is not None and gi < len(mclose) else None
        if adj is not None and p0:
            if tau == 0:
                peak_tau, peak_ret = 0, 0.0
            elif peak_ret is None or current_ret > peak_ret:
                peak_tau, peak_ret = tau, current_ret
            adj_seen.append((tau, current_ret))
        drawdown = float(peak_ret - current_ret) if peak_ret is not None and current_ret is not None else None
        if drawdown is not None:
            max_dd = max(max_dd or 0.0, drawdown)
        # fixed T0 baselines; these are not redefined after breakout
        vr = _ratio(sd.vol.get(d), vol_base) if vpos else None
        ar = _ratio(sd.amt.get(d), amt_base) if vpos else None
        tr = _ratio(sd.turn.get(d), turn_base) if sd.turn.get(d) is not None and turn_base else None
        if sd.turn.get(d) is not None and sd.turn.get(d) > 0:
            cum_turn += float(sd.turn[d]); turn_n += 1
        cum_turn_out = cum_turn if turn_n else None
        mean_turn = cum_turn / turn_n if turn_n else None
        peak_vol_ratio = max([x for x in [peak_vol_ratio, vr] if x is not None], default=None)
        peak_turn_ratio = max([x for x in [peak_turn_ratio, tr] if x is not None], default=None)
        anchored_dates = [x for x in mdates[i0:gi + 1] if x <= v2.DATASET_END]
        anchored_n = sum(1 for x in anchored_dates if x in sd.vpos)
        anchored = _strict_vwap(sd, anchored_dates)
        def roll(w):
            # V2 rolling VWAP overlap: pre-T0 history plus observations through tau.
            # The event-anchored VWAP remains separate and starts at T0.
            cutoff = d if d is not None else v2.DATASET_END
            ds = [x for x in sd.dates if x <= cutoff and x in sd.vpos][-w:]
            return _strict_vwap(sd, ds), len(ds)
        rv5, rn5 = roll(5); rv10, rn10 = roll(10); rv20, rn20 = roll(20)
        prev_peak = peak_ret
        prior_returns = [r for q, r in adj_seen if q < tau]
        recovered_previous_peak = (tau > 0 and current_ret is not None and
                                   bool(prior_returns) and current_ret >= max(prior_returns))
        rows.append({
            "breakout_event_id": eid, "code": str(event_row["code"]).zfill(6),
            "breakout_day": t0, "tau": tau, "observation_date": d,
            "source_date": source_date, "calendar_in_dataset": in_dataset,
            "row_present": row_present, "adj_factor_available": factor_available,
            "volume_valid": vpos, "ref20_obs_n": ref20_n, "ref60_obs_n": ref60_n,
            "close_rel_t0_log": current_ret,
            "mkt_excess_rel_t0_log": mkt_ex,
            "distance_to_ref20": (raw / ref20 - 1.0) if raw is not None and ref20 else None,
            "distance_to_ref60": (adj / ref60 - 1.0) if adj is not None and ref60 else None,
            "running_peak_return": peak_ret,
            "drawdown_from_running_peak": drawdown,
            "max_drawdown_to_tau": max_dd,
            "new_high_count_to_tau": sum(1 for q, r in adj_seen if q > 0 and r > max(0.0, max([z for z in [x[1] for x in adj_seen if x[0] < q]], default=-np.inf))),
            "days_above_t0_to_tau": sum(1 for q, r in adj_seen if q > 0 and r > 0),
            "peak_tau": peak_tau,
            "days_since_running_peak": tau - peak_tau if peak_tau is not None else None,
            "volume_ratio_pre20": vr, "amount_ratio_pre20": ar,
            "turnover_ratio_pre20": tr, "cum_turnover_since_t0": cum_turn_out,
            "mean_turnover_since_t0": mean_turn,
            "volume_peak_ratio_to_tau": peak_vol_ratio,
            "turnover_peak_ratio_to_tau": peak_turn_ratio,
            "anchored_vwap_t0_to_tau": anchored,
            "anchored_vwap_obs_n": anchored_n,
            "close_vs_anchored_vwap": (raw / anchored - 1.0) if raw is not None and anchored else None,
            "rolling_vwap5": rv5, "rolling_vwap5_obs_n": rn5,
            "price_to_rolling_vwap5": (raw / rv5 - 1.0) if raw is not None and rv5 else None,
            "rolling_vwap10": rv10, "rolling_vwap10_obs_n": rn10,
            "price_to_rolling_vwap10": (raw / rv10 - 1.0) if raw is not None and rv10 else None,
            "rolling_vwap20": rv20, "rolling_vwap20_obs_n": rn20,
            "price_to_rolling_vwap20": (raw / rv20 - 1.0) if raw is not None and rv20 else None,
            "below_t0_close": (raw < raw0) if raw is not None and raw0 is not None else None,
            "below_ref20": (raw < ref20) if raw is not None and ref20 is not None else None,
            "below_ref60": (adj < ref60) if adj is not None and ref60 is not None else None,
            "new_post_breakout_high": tau > 0 and peak_tau == tau,
            "drawdown_from_peak": drawdown,
            "recovered_previous_peak": recovered_previous_peak,
        })
    # No retrospective first-occurrence fields are added here: every daily row
    # must remain an as-of-tau record. They are derived only in summary.
    return pd.DataFrame(rows)


def summarize_event(daily: pd.DataFrame) -> dict:
    """Retrospective facts, derived solely from event_path_daily."""
    r = {"breakout_event_id": daily.iloc[0].breakout_event_id,
         "code": daily.iloc[0].code, "breakout_day": daily.iloc[0].breakout_day}
    r["peak_tau"] = int(daily.loc[daily["running_peak_return"].idxmax(), "tau"]) if daily["running_peak_return"].notna().any() else None
    for flag in ("below_t0_close", "below_ref20", "below_ref60", "new_post_breakout_high", "recovered_previous_peak"):
        vals = daily.loc[(daily.tau > 0) & daily[flag].eq(True), "tau"]
        r["first_" + flag + "_tau"] = int(vals.iloc[0]) if len(vals) else None
    for h in (5, 10, 20, 40):
        x = daily[daily.tau <= h]
        r[f"max_drawdown_to_h{h}"] = x["drawdown_from_running_peak"].max()
        r[f"new_high_count_to_h{h}"] = x["new_post_breakout_high"].fillna(False).sum()
        r[f"first_below_t0_tau_h{h}"] = next((int(z) for z in x.loc[x.below_t0_close.eq(True), "tau"]), None)
        r[f"first_recovery_tau_h{h}"] = next((int(z) for z in x.loc[x.recovered_previous_peak.eq(True), "tau"]), None)
    return r
