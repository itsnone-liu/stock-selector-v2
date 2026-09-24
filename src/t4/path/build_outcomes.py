"""T4.3 Context-conditioned Path Layer：outcome 派生 + PIT market context。

outcome 原则（开工令 §一/§二）：
- 不重新定义未来收益。H∈{5,10,20,40} 六指标全部从 V3 冻结
  event_path_daily / event_path_summary 派生（同一公式），
  并在重叠 H∈{5,10,20} 与 V4 dynamic_forward_outcomes@tau0
  逐事件 exact 对账（Gate 4），证明派生口径 == 冻结口径。

market context 原则（§三/§四/§五）：
- 三语义轴 raw 值从 T4.1 market_daily / T4.2 t4_t0_state 读取；
  as-of expanding percentile 只用 dates < T0，min_history=120，
  输出 raw_value / asof_percentile / history_n，Q1-Q4 由 25/50/75
  天然切分；不足 120 天 -> context_rank_available=false（null）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))

HORIZONS = (5, 10, 20, 40)
MIN_HISTORY = 120

# 三语义轴（字段名自动取自冻结产品）
CONTEXT_AXES = {
    "breadth_5d": {"raw": "mkt_breadth_5d",
                   "axis": "market_breadth",
                   "source": "t4_t0_state (from t4.1 market_daily)"},
    "amount_yi": {"raw": "mkt_day_amount_yi",
                  "axis": "market_participation_liquidity",
                  "source": "t4.1 market_daily @t0"},
    "new_high_20d": {"raw": "mkt_day_new_high_20d",
                     "axis": "market_leadership_new_high",
                     "source": "t4.1 market_daily @t0"},
}


def derive_outcomes() -> pd.DataFrame:
    """event × horizon 长表：六指标。

    从 V3 冻结 daily 列按 V4 冻结公式派生（窗口 W=(0,H]，r_t=exp(crl_t)）：
      fwd_raw_log        = crl_H − crl_0（两端有效，否则 null）
      fwd_mkt_excess_log = mex_H − mex_0
      future_max_gain    = max_{t∈W} r_t − 1
      future_max_drawdown= max_{t∈W} (1 − r_t / runmax_t)，runmax 从 1 起算
      new_high_within    = ∃t∈W: crl_t > running_peak_return_0
      lose_ref20_within  = ∃t∈W: below_ref20
    窗内无任何有效观测的分量记 null（V4 同规则）；H≤20 与 V4 @tau0
    逐事件 exact 对账（见 reconcile_with_v4）。
    """
    daily = pd.read_parquet(
        ROOT / "output/research/t3_v3/event_path_daily.parquet",
        columns=["breakout_event_id", "tau", "close_rel_t0_log",
                 "mkt_excess_rel_t0_log", "running_peak_return",
                 "below_ref20", "row_present"])
    rows = []
    for eid, d in daily.groupby("breakout_event_id", sort=False):
        d = d.sort_values("tau").set_index("tau")
        crl = d["close_rel_t0_log"].to_numpy(float)
        mex = d["mkt_excess_rel_t0_log"].to_numpy(float)
        rpr = d["running_peak_return"].to_numpy(float)
        b20 = d["below_ref20"].astype("float").to_numpy()
        if "below_ref20" not in d:
            b20 = None
        rp = d["row_present"].to_numpy(bool)
        crl0 = crl[0]
        for h in HORIZONS:
            if h >= len(crl):
                rows.append({"breakout_event_id": eid, "horizon": h,
                             "fwd_raw_log": None, "fwd_mkt_excess_log": None,
                             "future_max_drawdown": None,
                             "future_max_gain": None,
                             "new_high_within": None,
                             "lose_ref20_within": None,
                             "n_valid_obs_window": 0})
                continue
            w = np.arange(1, h + 1)
            valid = rp[w] & ~np.isnan(crl[w])
            n_valid = int(valid.sum())
            r_w = np.exp(crl[w])
            runmax = np.maximum.accumulate(
                np.concatenate([[1.0], r_w]))[1:]
            rec = {"breakout_event_id": eid, "horizon": h,
                   "n_valid_obs_window": n_valid,
                   "fwd_raw_log": float(crl[h] - crl0)
                   if rp[h] and not np.isnan(crl[h]) and not np.isnan(crl0)
                   else None,
                   "fwd_mkt_excess_log": float(mex[h] - mex[0])
                   if rp[h] and not np.isnan(mex[h]) and not np.isnan(mex[0])
                   else None,
                   "future_max_gain": float(r_w[valid].max() - 1.0)
                   if n_valid else None,
                   "future_max_drawdown": float(
                       (1.0 - r_w[valid] / runmax[valid]).max())
                   if n_valid else None,
                   "new_high_within": bool(
                       (crl[w][valid] > rpr[0]).any())
                   if n_valid and not np.isnan(rpr[0]) else None,
                   "lose_ref20_within": bool(np.any(b20[w] == 1.0))
                   if b20 is not None and np.isfinite(
                       b20[w]).any() else None}
            rows.append(rec)
    return pd.DataFrame(rows)


def reconcile_with_v4(out: pd.DataFrame) -> dict:
    """重叠 H∈{5,10,20} 与 V4 @tau0 逐事件对账（Gate 4 素材）。"""
    v4 = pd.read_parquet(
        ROOT / "output/research/t3_v4/dynamic_forward_outcomes.parquet")
    v4 = v4[v4["tau"] == 0]
    res = {}
    for h in (5, 10, 20):
        a = out[out["horizon"] == h].set_index("breakout_event_id")
        b = v4[v4["delta"] == h].set_index("breakout_event_id")
        j = a.join(b, rsuffix="_v4", how="inner")
        pair_ok = {}
        for c in ("fwd_raw_log", "fwd_mkt_excess_log",
                  "future_max_drawdown", "future_max_gain",
                  "new_high_within", "lose_ref20_within"):
            x, y = j[c], j[f"{c}_v4"]
            m = x.notna() & y.notna()
            if c in ("new_high_within", "lose_ref20_within"):
                mism = int((x[m].astype(bool) != y[m].astype(bool)).sum())
            else:
                mism = int((~np.isclose(x[m].astype(float),
                                        y[m].astype(float),
                                        rtol=1e-10, atol=1e-10)).sum())
            null_mism = int((x.isna() != y.isna()).sum())
            pair_ok[c] = {"value_mismatch": mism,
                          "null_pattern_mismatch": null_mism}
        res[f"h{h}"] = pair_ok
    return res


def market_daily_breadth() -> pd.DataFrame:
    m = pd.read_parquet(ROOT / "output/research/t4/context/"
                         "market_daily.parquet")
    m["breadth_5d_daily"] = m["pct_up"].rolling(5).mean()
    return m.set_index("date")


def asof_percentiles(t0_state: pd.DataFrame) -> pd.DataFrame:
    """事件级 as-of expanding percentile（只用 dates < T0）。"""
    m = market_daily_breadth()
    dates = list(m.index)
    pos = {d: i for i, d in enumerate(dates)}
    series = {
        "breadth_5d": m["breadth_5d_daily"].to_numpy(float),
        "amount_yi": m["mkt_amount_yi"].to_numpy(float),
        "new_high_20d": m["new_high_20d_count"].to_numpy(float),
    }
    out = {}
    for r in t0_state.itertuples(index=False):
        i = pos.get(r.breakout_day)
        rec = {}
        if i is None:
            for k in series:
                rec.update({f"{k}_raw": None, f"{k}_asof_pct": None,
                            f"{k}_history_n": 0})
            rec["context_rank_available"] = False
        else:
            rec["context_rank_available"] = True
            for k, arr in series.items():
                v = arr[i]
                hist = arr[:i]  # 严格 < T0
                hist = hist[~np.isnan(hist)]
                rec[f"{k}_raw"] = float(v) if not np.isnan(v) else None
                rec[f"{k}_history_n"] = int(len(hist))
                if len(hist) >= MIN_HISTORY and not np.isnan(v):
                    rec[f"{k}_asof_pct"] = float((hist < v).mean())
                else:
                    rec[f"{k}_asof_pct"] = None
                    if len(hist) < MIN_HISTORY:
                        rec["context_rank_available"] = False
        out[r.breakout_event_id] = rec
    df = pd.DataFrame.from_dict(out, orient="index")
    df.index.name = "breakout_event_id"
    return df.reset_index()


def attach_quartiles(ctx: pd.DataFrame) -> pd.DataFrame:
    for k in CONTEXT_AXES:
        p = ctx[f"{k}_asof_pct"]
        ctx[f"{k}_q"] = np.select(
            [p < .25, p < .5, p < .75], ["Q1", "Q2", "Q3"], default="Q4")
        ctx.loc[p.isna(), f"{k}_q"] = None
    return ctx


def breakout_density(events: pd.DataFrame) -> pd.DataFrame:
    d = events.groupby("breakout_day").size().rename(
        "breakout_count_on_date")
    return d.reset_index()
