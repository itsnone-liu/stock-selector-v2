"""T5.1 构建器：事件×相对日展开 + 逐日 PIT 状态特征。

关键纪律：
- 状态构造只读 <= state_date 的数据（PIT），绝不触碰未来；
- 与 V3 tau 同源（指数市场日历序号），row_present 标停牌；
- T4 继承字段（E 档/policy/budget/pre20 基数/end_day）逐事件对账，
  不重算；ref20/ref60 按 V3 冻结公式重算（水平值不在冻结表中）。
"""
from __future__ import annotations

import json
import struct
import gzip
from pathlib import Path

import numpy as np
import pandas as pd

from t5.constants import ROOT, MAX_HORIZON
from t5 import primitives as P
from t5.schemas import STATE_COLS

INDEX_DAY = Path("/root/tdx_data/vipdoc/sh/lday/sh999999.day")
PER_STOCK = ROOT / "data/adjustment_baostock/per_stock"


# ---------------------------------------------------------------- 输入
def load_market_calendar():
    b = INDEX_DAY.read_bytes()
    dates = []
    for i in range(len(b) // 32):
        u = struct.unpack("<I", b[i * 32:i * 32 + 4])[0]
        dates.append(f"{u // 10000}-{u // 100 % 100:02d}-{u % 100:02d}")
    return dates


def load_market_daily():
    m = pd.read_parquet(ROOT / "output/research/t4/context/"
                        "market_daily.parquet")
    m = m.sort_values("date").reset_index(drop=True)
    m["breadth_5d"] = m["pct_up"].rolling(5, min_periods=5).mean()
    return m


def load_events_with_inheritance() -> pd.DataFrame:
    """事件级继承表：T4.5 E 档 + T4.6 policy/budget + T4.2 冻结基数。"""
    ea = pd.read_parquet(ROOT / "output/research/t4/exposure/"
                         "t4_exposure_assignment.parquet")
    cs = pd.read_parquet(ROOT / "output/research/t4/context_path/"
                         "t4_context_state.parquet",
                         columns=["breakout_event_id", "code",
                                  "breakout_day", "end_day",
                                  "pre20_volume_base", "pre20_amount_base",
                                  "pre20_turn_base"])
    rb = pd.read_csv(ROOT / "output/research/t4/entry_policy/"
                     "t4_6c_risk_budget_classes.csv")
    ev = ea.merge(cs, on=["breakout_event_id"], how="left",
                  suffixes=("", "_cs"))
    for col in ("code", "breakout_day"):
        cs_col = f"{col}_cs"
        if cs_col in ev.columns:
            ev[col] = ev[cs_col].where(ev[cs_col].notna(), ev[col])
    ev = ev.drop(columns=[c for c in ev.columns if c.endswith("_cs")])
    rb_small = rb[["E_class", "participation_policy",
                   "risk_budget_class"]].rename(
        columns={"risk_budget_class": "initial_risk_budget_class"})
    ev = ev.merge(rb_small, on="E_class", how="left")
    ev["participation_policy"] = ev["participation_policy"].fillna(
        "P0_no_participation")
    ev["initial_risk_budget_class"] = ev[
        "initial_risk_budget_class"].fillna("zero_or_exception_only")
    return ev


# ---------------------------------------------------------------- 个股读
def iter_stock_full(per_stock_dir: Path = PER_STOCK):
    """yield (code, dates, adj, raw, pch, amt, turn, vol)。
    与 t4.context.build.iter_stock_daily 同源，额外带 raw close 与 volume。
    """
    ft = pd.read_csv(ROOT / "output/research/adjustment_v1/"
                     "factor_table.csv.gz")
    fmap = {}
    for row in ft.itertuples(index=False):
        fmap.setdefault(row.code, {})[str(row.date)] = float(row.F)
    for p in sorted(Path(per_stock_dir).glob("*.json.gz")):
        code = p.name.replace(".json.gz", "")
        with gzip.open(p, "rt") as f:
            j = json.load(f)
        dates, adj, raw, pch, amt, turn, vol = [], [], [], [], [], [], []
        m = fmap.get(code, {})
        for r in j["unadj"]:
            d = r[0]
            try:
                c = float(r[4])
            except (TypeError, ValueError):
                continue
            f_ = m.get(d)
            adj.append(c * f_ if f_ is not None else None)
            raw.append(c)
            dates.append(d)
            pch.append(_tof(r[8]))
            amt.append(_tof(r[6]))
            turn.append(_tof(r[7]))
            vol.append(_tof(r[5]))
        yield code, dates, adj, raw, pch, amt, turn, vol


def _tof(x):
    try:
        return float(x) if x else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- 展开
def event_span(mpos, m0, end_day, n_mdates):
    """事件行数与终止原因（取最先到达的边界）。

    last = min(40, end_pos-m0, 日历末-m0)；到达哪个边界就记哪个原因：
    日历先尽 -> DATA_END；end_day 先到 -> LIFECYCLE_END；否则 MAX_HORIZON。
    """
    e = mpos.get(end_day, n_mdates - 1)
    cap_life, cap_data = e - m0, n_mdates - 1 - m0
    last = min(MAX_HORIZON, cap_life, cap_data)
    if cap_data <= min(MAX_HORIZON, cap_life):
        reason = "DATA_END"   # 日历/数据边界先至或同时至（end_day 未观测）
    elif cap_life <= MAX_HORIZON:
        reason = "LIFECYCLE_END"
    else:
        reason = "MAX_HORIZON"
    return last, reason


def build_dynamic_state(events: pd.DataFrame, mkt: pd.DataFrame,
                        stocks, mdates, *, max_horizon: int = MAX_HORIZON):
    """主构建：返回 (state_df)。stocks=iter_stock_full 的迭代器（已排序）。
    """
    mpos = {d: i for i, d in enumerate(mdates)}
    mkt_idx = mkt.set_index("date")
    mkt_cols = ["breadth_5d", "new_high_20d_count", "mkt_amount_yi"]
    mkt_rec = mkt_idx[mkt_cols].to_dict("index")

    rows_out = []
    for code_full, dates, adj, raw, pch, amt, turn, vol in stocks:
        code = code_full.split(".")[1] if "." in code_full else code_full
        evs = events[events["code"] == code]
        if not len(evs):
            continue
        dpos = {d: i for i, d in enumerate(dates)}
        # 预备：有效（有成交额）日集合，V3 的 vpos 同款
        vpos = {d for d, a in zip(dates, amt) if a}
        for ev in evs.itertuples(index=False):
            t0 = ev.breakout_day
            i0 = dpos.get(t0)
            if i0 is None:
                continue
            m0 = mpos.get(t0)
            if m0 is None:
                continue
            last, reason = event_span(mpos, m0, ev.end_day, len(mdates))
            # V3 冻结公式重算参考位（水平值）
            prior_d = [d for d in dates if d < t0]
            ref20_raw = max((raw[dates.index(d)] for d in prior_d[-20:]),
                            default=None) if len(prior_d) >= 20 else None
            prior_valid = [d for d in dates
                           if d < t0 and adj[dates.index(d)] is not None]
            ref60_adj = max((adj[dates.index(d)]
                             for d in prior_valid[-60:]),
                            default=None) if len(prior_valid) >= 60 else None
            adj0 = adj[i0]
            raw0 = raw[i0]

            # as-of 游标
            adj_valid = []          # [(delta, adj)] 有效日
            pch_valid = []
            load_seq = []           # turnover_load per 有效日
            peak_ret = None
            runmax = -np.inf
            mdd = 0.0
            nh_count = 0
            prev_peak_nh = None     # 截至前一有效日的运行峰值（含 T0）
            for delta in range(last + 1):
                gi = m0 + delta
                if gi >= len(mdates):
                    reason = "DATA_END"
                    break
                d = mdates[gi]
                present = d in dpos
                j = dpos.get(d)
                a_t = adj[j] if (present and j is not None) else None
                row = {
                    "event_id": ev.breakout_event_id, "code": code,
                    "breakout_day": t0, "delta_day": delta,
                    "state_date": d,
                    "row_present": bool(present),
                    "adj_available": bool(a_t is not None),
                    "volume_valid": bool(d in vpos),
                    "termination_reason": (reason if delta == last
                                           else None),
                    "exposure_class": ev.E_class,
                    "participation_policy": ev.participation_policy,
                    "initial_risk_budget_class":
                        ev.initial_risk_budget_class,
                    "M_cell": ev.M_cell, "L_q": ev.L_q, "R60": ev.R60,
                    "year": ev.year,
                }
                if a_t is not None and adj0:
                    adj_valid.append((delta, a_t))
                    if pch[j] is not None:
                        pch_valid.append(pch[j])
                    tl = P.load_vs_base(turn[j], ev.pre20_turn_base)
                    if tl is not None:
                        load_seq.append(tl)
                    pr = P.price_primitives(adj_valid)
                    row.update(pr)
                    dm = P.dist_metrics(a_t, raw[j], ref20_raw, ref60_adj,
                                        adj0, raw0,
                                        pr["post_t0_peak_ret_log"],
                                        pr["cum_ret_from_t0_log"])
                    row.update(dm)
                    row["close_adj"] = a_t
                    row["close_raw"] = raw[j]
                    # 21 窗新高（含 T0 前历史；None 剔除后不足 20→None）
                    hist20 = [adj[x] for x in range(max(0, j - 20), j)
                              if adj[x] is not None]
                    row["is_new_high_20d"] = P.new_high_flag(hist20, a_t)
                    # T0 起创新高计数（V3 口径：严格超过此前含 T0 的峰）
                    if prev_peak_nh is not None and a_t > prev_peak_nh:
                        nh_count += 1
                    prev_peak_nh = max(prev_peak_nh, a_t) if (
                        prev_peak_nh is not None) else a_t
                    row["new_high_count_since_t0"] = nh_count
                    u3, d3 = P.updown_days(pch_valid, 3)
                    u5, d5 = P.updown_days(pch_valid, 5)
                    row["up_days_3"], row["down_days_3"] = u3, d3
                    row["up_days_5"], row["down_days_5"] = u5, d5
                    # 参与族
                    vl = P.load_vs_base(vol[j], ev.pre20_volume_base)
                    al = P.load_vs_base(amt[j], ev.pre20_amount_base)
                    row["turnover_load_vs_prebreak"] = tl
                    row["volume_load_vs_prebreak"] = vl
                    row["amount_load_vs_prebreak"] = al
                    row["turnover_load_change_1d"] = P.load_change(
                        tl, load_seq[-2] if len(load_seq) >= 2 else None)
                    row["turnover_load_change_3d"] = P.load_change(
                        tl, load_seq[-4] if len(load_seq) >= 4 else None)
                    r3 = (float(np.mean(load_seq[-3:]))
                          if len(load_seq) >= 3 else None)
                    p3 = (float(np.mean(load_seq[-6:-3]))
                          if len(load_seq) >= 6 else None)
                    row["turnover_load_3d_mean"] = r3
                    row["turnover_load_3d_prev_mean"] = p3
                    ct, ex = P.contraction_expansion(r3, p3)
                    row["turnover_contraction_3d"] = ct
                    row["turnover_expansion_3d"] = ex
                    # 效率族
                    prog1 = row.get("ret_1d_log")
                    prog3 = row.get("ret_3d_log")
                    row["price_progress_1d_log"] = prog1
                    row["price_progress_3d_log"] = prog3
                    l1 = load_seq[-1] if load_seq else None
                    l3s = float(np.sum(load_seq[-3:])) if len(
                        load_seq) >= 3 else None
                    row["efficiency_signed_1"] = P.efficiency_signed(
                        prog1, l1)
                    row["efficiency_signed_3"] = P.efficiency_signed(
                        prog3, l3s)
                    row["efficiency_change_3"] = None  # 由后处理填
                    row["marginal_progress_log"] = prog1
                # 市场背景（对全行可用，不依赖个股行情）
                mr = mkt_rec.get(d, {})
                mr1 = mkt_rec.get(mdates[gi - 1], {}) if gi >= 1 else None
                mr3 = mkt_rec.get(mdates[gi - 3], {}) if gi >= 3 else None
                mc = P.market_context(
                    {"breadth_5d": mr.get("breadth_5d"),
                     "new_high_20d_count": mr.get("new_high_20d_count"),
                     "mkt_amount_yi": mr.get("mkt_amount_yi")},
                    {"breadth_5d": (mr1 or {}).get("breadth_5d"),
                     "new_high_20d_count":
                         (mr1 or {}).get("new_high_20d_count")}
                    if mr1 is not None else None,
                    {"breadth_5d": (mr3 or {}).get("breadth_5d"),
                     "new_high_20d_count":
                         (mr3 or {}).get("new_high_20d_count")}
                    if mr3 is not None else None)
                row.update(mc)
                rows_out.append(row)
    df = pd.DataFrame(rows_out, columns=STATE_COLS)
    # efficiency_change_3：eff_signed_1(t) − eff_signed_1(t-3 有效日)
    df["efficiency_change_3"] = df.groupby("event_id", sort=False)[
        "efficiency_signed_1"].transform(lambda s: s - s.shift(3))
    return df
