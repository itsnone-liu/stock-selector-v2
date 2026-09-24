"""T4.6 Entry Policy & Position Sizing descriptive analysis helpers."""
from __future__ import annotations
import numpy as np
import pandas as pd

CHASE_BINS = [-np.inf, 1, 2, 3.5, 5, 7, np.inf]
CHASE_LABELS = ["0-1", "1-2", "2-3.5", "3.5-5", "5-7", ">7"]
POLICIES = ("P0_no_participation", "P1_probe", "P2_normal", "P3_aggressive_eligible")


def load_inputs(root):
    exp = pd.read_parquet(root/"output/research/t4/exposure/t4_exposure_assignment.parquet")
    paths = pd.read_parquet(root/"output/research/t3_v3/event_path_summary.parquet")
    state = pd.read_parquet(root/"output/research/t4/context_path/t4_context_state.parquet")
    return exp, paths, state


def map_participation(x):
    return {"E0":"P0_no_participation", "E1":"P1_probe",
            "E2":"P2_normal", "E3":"P3_aggressive_eligible"}.get(x)


def profile(g, ret="ret_net_20_close"):
    out={"n":len(g), "n_dates":g.signal_day.nunique()}
    for c in [ret,"mfe_20_close","mae_20_close"]:
        out[c]=float(g[c].median()) if c in g and g[c].notna().any() else np.nan
    return out


def db_profile(g, value_cols):
    out={"n_events":len(g),"n_dates":g.signal_day.nunique()}
    for c in value_cols:
        if c not in g or not g[c].notna().any(): out[c]=np.nan; continue
        z=g.dropna(subset=[c]).groupby("signal_day")[c].median()
        out[c]=float(z.median()) if len(z) else np.nan
    return out
