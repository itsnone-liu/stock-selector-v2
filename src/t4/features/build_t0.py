"""T4.2 T0 State Table：27,422 事件 × T0 收盘时点横截面状态。

设计（开工令 §二）：
- A/C/D 族以 V5 state_vector_daily @tau0 切片 **exact 继承**（不重算近似副本）；
- B 族量能基线（volume/amount）从冻结 per_stock 库确定性补充；
- E 族 market context 并入主表（PIT：T0 收盘后可知）；sector 三列
  物理分离到 retrospective companion（快照非时点，pit_eligible=false）；
- 禁止任何 post-T0 outcome 进入（Gate 4 schema scan）。
"""
from __future__ import annotations

import gzip
import json
from bisect import bisect_left, bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")

# ---- V5 svd @tau0 继承列（A/B/C/D 族，冻结定义，exact 切片） ----
SVD_INHERIT = [
    # A 价格结构
    "distance_to_ref20", "distance_to_ref60", "t0_ref60_breakout",
    "close_vs_anchored_vwap", "close_rel_t0_log",
    "drawdown_from_running_peak", "days_since_running_peak",
    "new_high_count_to_tau", "ref20_obs_n", "anchored_vwap_obs_n",
    # B 基线成交（turnover 侧，V3 冻结）
    "pre20_turn_base", "cum_turnover_since_t0", "mean_turnover_since_t0",
    "turn_n_to_tau", "cum_turnover_raw", "expected_turnover_since_s0",
    # C normalized participation
    "turnover_load_to_tau", "mean_turnover_load_to_tau",
    # D efficiency（V5 冻结公式；tau0 退化恒 0，如实保留）
    "price_progress", "efficiency_proxy",
    # QA 标志
    "row_present", "adj_factor_available", "volume_valid",
    "turn_base_available", "load_available", "load_identity_ok",
]


def load_svd_tau0() -> pd.DataFrame:
    svd = pd.read_parquet(
        ROOT / "output/research/t3_v5/state_vector_daily.parquet",
        columns=(["breakout_event_id", "code", "breakout_day", "tau"]
                 + [c for c in SVD_INHERIT
                    if c != "expected_turnover_since_s0"]))
    s0 = svd[svd["tau"] == 0].copy()
    return s0


def compute_volume_amount_baselines(events: pd.DataFrame,
                                    window: int = 20):
    """B 族补充：T0 volume/amount 与 pre20 基线（≤T0-1 数据，PIT）。

    口径对齐 V3 pre20_turn_base：T0 前 20 个**有个股数据的市场日**
    （不含 T0）的均值；turn 侧由 svd 继承并对账。
    """
    ft = pd.read_csv(ROOT / "output/research/adjustment_v1/factor_table.csv.gz")
    rec = {}
    ev_by_code = {}
    for r in events.itertuples(index=False):
        ev_by_code.setdefault(r.code, []).append(r)
    for p in sorted((ROOT / "data/adjustment_baostock/per_stock").glob(
            "*.json.gz")):
        code6 = p.name.split(".")[1]
        if code6 not in ev_by_code:
            continue
        with gzip.open(p, "rt") as f:
            j = json.load(f)
        dates, vol, amt = [], [], []
        for r in j["unadj"]:
            dates.append(r[0])
            try:
                vol.append(float(r[5]) if r[5] else None)
            except (TypeError, ValueError):
                vol.append(None)
            try:
                amt.append(float(r[6]) if r[6] else None)
            except (TypeError, ValueError):
                amt.append(None)
        for r in ev_by_code[code6]:
            t0 = r.breakout_day
            i = bisect_right(dates, t0) - 1
            if i < 0 or dates[i] != t0:
                rec[r.breakout_event_id] = {
                    "t0_volume": None, "t0_amount": None,
                    "pre20_volume_base": None, "pre20_amount_base": None}
                continue
            lo = max(0, i - window)
            v_pre = [v for v in vol[lo:i] if v]
            a_pre = [a for a in amt[lo:i] if a]
            rec[r.breakout_event_id] = {
                "t0_volume": vol[i],
                "t0_amount": amt[i],
                "pre20_volume_base": (float(np.mean(v_pre))
                                      if len(v_pre) == window else None),
                "pre20_amount_base": (float(np.mean(a_pre))
                                      if len(a_pre) == window else None),
            }
    return pd.DataFrame.from_dict(rec, orient="index",
                                  columns=["t0_volume", "t0_amount",
                                           "pre20_volume_base",
                                           "pre20_amount_base"]
                                  ).rename_axis("breakout_event_id").reset_index()


def build_t0_state(events: pd.DataFrame) -> dict[str, pd.DataFrame]:
    s0 = load_svd_tau0()
    s0 = s0.rename(columns={
        "cum_turnover_since_t0": "t0_turn",
        "turnover_load_to_tau": "turnover_load_t0",
        "new_high_count_to_tau": "new_high_count_t0"})
    # market PIT context（T4.1 窗口特征 + T0 当日行，全部 ≤T0）
    ctx = pd.read_parquet(ROOT / "output/research/t4/context/"
                                 "t4_event_context.parquet",
                          columns=["breakout_event_id", "mkt_ret_20d",
                                   "mkt_amount_pctile_60d",
                                   "mkt_breadth_5d", "stock_ret_20d"])
    mkt = pd.read_parquet(ROOT / "output/research/t4/context/"
                             "market_daily.parquet").set_index("date")
    idates = list(mkt.index)
    t0_mkt = mkt.reindex(events["breakout_day"]).reset_index().rename(
        columns={"index": "breakout_day"})
    t0_mkt = pd.concat([events["breakout_event_id"], t0_mkt], axis=1)
    t0_mkt = t0_mkt[["breakout_event_id", "mkt_amount_yi", "pct_up",
                     "eq_ret_median", "new_high_20d_count"]].rename(
        columns={"mkt_amount_yi": "mkt_day_amount_yi",
                 "pct_up": "mkt_day_pct_up",
                 "eq_ret_median": "mkt_day_eq_ret_median",
                 "new_high_20d_count": "mkt_day_new_high_20d"})
    # B 族补充
    vb = compute_volume_amount_baselines(events)
    vb["volume_load_t0"] = np.where(
        vb["t0_volume"].notna() & vb["pre20_volume_base"].notna()
        & (vb["pre20_volume_base"] > 0),
        vb["t0_volume"] / vb["pre20_volume_base"], None)

    s0 = s0.drop(columns=["code", "breakout_day"], errors="ignore")
    t = events[["breakout_event_id", "code", "breakout_day",
                "end_day"]].merge(s0, on=["breakout_event_id"], how="left")
    t = t.merge(ctx, on="breakout_event_id", how="left")
    t = t.merge(t0_mkt, on="breakout_event_id", how="left")
    t = t.merge(vb, on="breakout_event_id", how="left")
    t["pit_primary_eligible"] = True
    t = t.sort_values("breakout_event_id").reset_index(drop=True)

    # sector retrospective companion（物理分离，pit=false）
    sc = pd.read_parquet(ROOT / "output/research/t4/context/"
                            "t4_event_context.parquet",
                         columns=["breakout_event_id", "industry_gate",
                                  "sector_ret_20d", "sector_vs_mkt_20d",
                                  "stock_vs_sector_20d"])
    sc["pit_primary_eligible"] = False
    sc["is_point_in_time"] = False
    sc["retrospective_context_only"] = True
    sc["membership_snapshot_date"] = "2026-09-21"
    sc = sc.sort_values("breakout_event_id").reset_index(drop=True)
    return {"t4_t0_state": t, "t4_t0_sector_retrospective": sc}


FORBIDDEN_OUTCOME_PATTERNS = (
    "y5", "y10", "y20", "y40", "future", "ret_net", "mfe", "mae", "mdd",
    "policy_outcome", "outcome", "h5", "h10", "h20", "h40", "new_high_entry",
    "excess", "fill", "tranche", "wait_days", "entry_premium")
