"""t3_v4.py — T3 V4：动态风险集与条件路径比较（observational conditional association）。

冻结基线：commit aa249cc（T3 V3 轨迹事实层 PASS）。
本模块只消费 V3 冻结产物 event_path_daily.parquet + 上证市场日历，
不 import / join event_labels，不使用任何 T0..tau 之后的信息定义状态。

核心不变量
----------
1. state information <= asof tau；outcome 严格位于 > tau。
2. 风险集入选 = 事件真实走到 tau（市场日历内、数据集内），不得要求
   未来 label 可得、Y20 存在、创新高或生命周期存活。
3. eligibility 与 outcome horizon 分开：forward 可观测性只由
   asof_date <= dataset_end - Δ（市场日）这一日历可知条件决定，
   不得用个股事后 label availability 筛选。
4. 缺失保持缺失；per-analysis eligibility，禁止全局 complete-case 删除。
5. 单位契约（V4 schema gate）：baostock turn 字段为换手率百分比
   （0.6946 = 0.6946%；库级实测 amount/turn 隐含流通股本与真实股本一致）。
   因此 cum_turnover_since_t0 = 百分点·日累加（68.23 ≈ 累计换手 68.23%），
   mean_turnover_since_t0 = 每有效交易日百分点；*_ratio_pre20 为无量纲比值。
6. 推断：primary 同时报 stock-cluster 与 asof-date-cluster 两套 bootstrap CI；
   不做因果解释。Q4-Q1 为主比较，Holm 校验在 metric×tau×Δ family 内。

前向结果公式（冻结）
--------------------
窗口 W = {tau' in (tau, tau+Δ]，V3 日历行}；r_t = exp(crl_t − crl_tau)。
- fwd_raw_log        = crl_{tau+Δ} − crl_tau（两端有效观测，否则 null）
- fwd_mkt_excess_log = mex_{tau+Δ} − mex_tau（同一恒等式）
- future_max_gain    = max_{t∈W} r_t − 1
- future_max_drawdown= max_{t∈W} (1 − r_t / runmax_t)，
                       runmax 从 tau 现价（=1）起算（既含“从 tau 价下行”，
                       也含“途中创新高后回落”的峰谷回撤）
- new_high_within    = ∃t∈W: crl_t > running_peak_return_tau（严格超过 tau 前峰值）
- days_to_next_high  = 首次该日的 tau' − tau（市场日）
- lose_ref20_within / lose_t0_close_within = ∃t∈W: 对应 V3 布尔为 True
- recover_current_peak_within = ∃t∈W: crl_t >= running_peak_return_tau
窗口内无任何有效观测的分量记 null（缺失不填充）。

确定性：无随机源；bootstrap 用 per-family 固定种子（sha256 派生），
全部输出按键排序。
"""
from __future__ import annotations

import hashlib
import warnings

import numpy as np
import pandas as pd

from . import t3_v2 as v2

ROOT = v2.ROOT
DATASET_END = v2.DATASET_END          # 2026-09-18, V1 冻结

RISKSET_TAUS = (0, 1, 5, 10, 20)      # 0=baseline, 1=sensitivity, 5/10/20=primary
PRIMARY_TAUS = (5, 10, 20)
DELTAS = (5, 10, 20)                  # tau=20+Δ20 恰好到 T40

TAU_ROLE = {0: "baseline", 1: "sensitivity", 5: "primary", 10: "primary", 20: "primary"}

# ---- Primary current-state dimensions（预注册，不许扫描字段） ----
STATE_PRICE = ("drawdown_from_running_peak", "days_since_running_peak",
               "new_high_count_to_tau", "close_rel_t0_log")
STATE_PART = ("volume_ratio_pre20", "turnover_ratio_pre20",
              "cum_turnover_since_t0", "mean_turnover_since_t0")
STATE_COST = ("close_vs_anchored_vwap",)
STATE_STRUCT = ("distance_to_ref20", "distance_to_ref60")
STATE_FLAG = ("t0_ref60_breakout",)   # T0 已知 ref60 同时突破状态
CONT_VARS = STATE_PRICE + STATE_PART + STATE_COST + STATE_STRUCT   # 11 个连续变量
NATURAL0 = ("close_vs_anchored_vwap", "distance_to_ref20", "distance_to_ref60")
VR1 = ("volume_ratio_pre20",)         # >1 / <=1 secondary split

STATE_UNITS = {
    "drawdown_from_running_peak": "fraction 1 - close/running_peak_close",
    "days_since_running_peak": "market days since running peak tau",
    "new_high_count_to_tau": "count of new post-T0 closing highs",
    "close_rel_t0_log": "log return vs T0 close (adjusted)",
    "volume_ratio_pre20": "dimensionless ratio vs pre-T0 20d mean volume",
    "turnover_ratio_pre20": "dimensionless ratio vs pre-T0 20d mean turnover",
    "cum_turnover_since_t0": "percentage-point days summed (baostock turn is %)",
    "mean_turnover_since_t0": "percentage points per valid turnover day",
    "close_vs_anchored_vwap": "fraction raw_close/anchored_vwap - 1",
    "distance_to_ref20": "fraction raw_close/ref20 - 1 (unadjusted)",
    "distance_to_ref60": "fraction adj_close/ref60 - 1 (adjusted)",
    "t0_ref60_breakout": "bool: distance_to_ref60 at T0 > 0",
}

# ---- Bootstrap（预注册） ----
BOOT_B = 1000
BOOT_SEED = 20260924
MIN_CELL_N = 30

_V3_COLS = [
    "breakout_event_id", "code", "breakout_day", "tau", "observation_date",
    "source_date", "calendar_in_dataset", "row_present", "adj_factor_available",
    "close_rel_t0_log", "mkt_excess_rel_t0_log", "running_peak_return",
    "drawdown_from_running_peak", "days_since_running_peak",
    "new_high_count_to_tau", "volume_ratio_pre20", "turnover_ratio_pre20",
    "cum_turnover_since_t0", "mean_turnover_since_t0",
    "close_vs_anchored_vwap", "anchored_vwap_obs_n",
    "distance_to_ref20", "distance_to_ref60",
    "below_ref20", "below_t0_close",
]


def family_seed(key: str) -> int:
    """Deterministic per-family RNG seed (iteration-order independent)."""
    h = hashlib.sha256(f"{BOOT_SEED}|{key}".encode()).digest()
    return int.from_bytes(h[:8], "little")


def last_dataset_pos(mdates) -> int:
    """Index of last market date <= DATASET_END (pure calendar fact)."""
    return max(i for i, d in enumerate(mdates) if d <= DATASET_END)


# ---------------------------------------------------------------- risk set

def build_riskset(daily: pd.DataFrame, mdates) -> pd.DataFrame:
    """One row per breakout_event_id x tau: as-of state + calendar eligibility.

    Only asof information is touched. t0_ref60_breakout is read from the
    event's own tau=0 row (T0-known fact, constant across tau).
    Eligibility flags are pure functions of (T0 position, tau, delta,
    dataset_end) on the market calendar — never of stock-level labels.
    """
    sub = daily[daily["tau"].isin(RISKSET_TAUS)]
    ids = np.array(sorted(sub["breakout_event_id"].unique()))
    piv = {c: sub.pivot(index="breakout_event_id", columns="tau", values=c)
           .reindex(ids) for c in _V3_COLS
           if c not in ("breakout_event_id", "code", "breakout_day", "tau")}
    t0 = sub[sub["tau"] == 0].set_index("breakout_event_id").reindex(ids)
    ldsp = last_dataset_pos(mdates)
    mpos0 = {d: i for i, d in enumerate(mdates)}
    i0 = np.array([mpos0[d] for d in t0["breakout_day"]])
    flag60 = piv["distance_to_ref60"][0]
    rows = {}
    n = len(ids)
    rows["breakout_event_id"] = np.tile(ids, len(RISKSET_TAUS))
    rows["code"] = np.tile(t0["code"].to_numpy(), len(RISKSET_TAUS))
    rows["breakout_day"] = np.tile(t0["breakout_day"].to_numpy(),
                                   len(RISKSET_TAUS))
    rows["tau"] = np.repeat(RISKSET_TAUS, n)
    rows["tau_role"] = np.repeat([TAU_ROLE[t] for t in RISKSET_TAUS], n)
    in_ds_l, adate_l, rp_l, aa_l = [], [], [], []
    var_cols = {v: [] for v in CONT_VARS}
    awn_l = []
    flag_l = []
    elig_l = {dl: [] for dl in DELTAS}
    for tau in RISKSET_TAUS:
        in_ds = piv["calendar_in_dataset"][tau].fillna(False).astype(bool)
        obs = piv["observation_date"][tau]
        in_ds_l.append(in_ds.to_numpy())
        adate_l.append(obs.where(in_ds).astype(object)
                       .where(in_ds, None).to_numpy())
        rp_l.append(piv["row_present"][tau].fillna(False).astype(bool).to_numpy())
        aa_l.append(piv["close_rel_t0_log"][tau].notna().to_numpy())
        for v in CONT_VARS:
            var_cols[v].append(piv[v][tau].to_numpy())
        awn_l.append(piv["anchored_vwap_obs_n"][tau].to_numpy())
        flag_l.append((flag60 > 0).to_numpy())
        asof_pos = i0 + tau
        for dl in DELTAS:
            elig_l[dl].append(((asof_pos + dl) <= ldsp))
    rows["asof_date"] = np.concatenate(adate_l)
    rows["asof_in_dataset"] = np.concatenate(in_ds_l)
    rows["asof_row_present"] = np.concatenate(rp_l)
    rows["asof_adj_available"] = np.concatenate(aa_l)
    for v in CONT_VARS:
        rows[v] = np.concatenate(var_cols[v])
    rows["anchored_vwap_obs_n"] = np.concatenate(awn_l)
    rows["t0_ref60_breakout"] = np.concatenate(flag_l)
    for dl in DELTAS:
        rows[f"eligible_fwd_{dl}"] = np.concatenate(elig_l[dl])
    rs = pd.DataFrame(rows)
    return rs.sort_values(["breakout_event_id", "tau"]).reset_index(drop=True)


# ---------------------------------------------------------- forward outcomes

def build_forward_outcomes(daily: pd.DataFrame, mdates) -> pd.DataFrame:
    """One row per breakout_event_id x tau x delta — future facts ONLY.

    Path components consume V3 rows strictly after asof tau; the as-of anchor
    (base price, running peak asof tau) enters only as reference level.
    Rows exist only for calendar-eligible (tau, delta).
    """
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    sub = daily[daily["tau"] <= 40]
    crl = sub.pivot(index="breakout_event_id", columns="tau",
                    values="close_rel_t0_log").sort_index()
    mex = sub.pivot(index="breakout_event_id", columns="tau",
                    values="mkt_excess_rel_t0_log").sort_index()
    peak = sub.pivot(index="breakout_event_id", columns="tau",
                     values="running_peak_return").sort_index()
    br20 = sub.pivot(index="breakout_event_id", columns="tau",
                     values="below_ref20").sort_index()
    bt0 = sub.pivot(index="breakout_event_id", columns="tau",
                    values="below_t0_close").sort_index()
    obsd = sub.pivot(index="breakout_event_id", columns="tau",
                     values="observation_date").sort_index()
    ids = crl.index.to_numpy()
    ldsp = last_dataset_pos(mdates)
    mpos0 = {d: i for i, d in enumerate(mdates)}
    bday = (sub[sub["tau"] == 0].set_index("breakout_event_id")
            .reindex(ids)["breakout_day"])
    i0 = np.array([mpos0[d] for d in bday])

    parts = []
    for tau in RISKSET_TAUS:
        win = [t for t in range(tau + 1, tau + 21) if t <= 40]
        crl_tau = crl[tau].to_numpy(dtype=float)
        peak_asof = peak[tau].to_numpy(dtype=float)
        crlw_all = crl[win].to_numpy(dtype=float)
        R = np.exp(crlw_all - crl_tau[:, None])
        runmax = np.maximum.accumulate(
            np.concatenate([np.ones((len(ids), 1)), R], axis=1), axis=1)[:, 1:]
        dd = 1.0 - R / runmax
        valid = np.isfinite(R)
        # new high threshold: crl_t > peak_asof. Expressed relative to the
        # as-of base: R_t = exp(crl_t - crl_tau) > exp(peak_asof - crl_tau).
        with np.errstate(invalid="ignore"):
            peak_rel_base = np.exp(peak_asof - crl_tau)
        nh_all = (R > peak_rel_base[:, None]) & valid
        recover_all = (R >= peak_rel_base[:, None]) & valid
        b20_all = br20[win].to_numpy()
        bt0_all = bt0[win].to_numpy()
        rec_all = recover_all
        for dl in DELTAS:
            end = tau + dl
            wm = np.zeros(len(win), dtype=bool)
            wm[:dl] = True                       # columns tau+1 .. tau+dl
            Rw, ddw = R[:, wm], dd[:, wm]
            vw = valid[:, wm]
            nhw = nh_all[:, wm]
            b20w, bt0w = b20_all[:, wm], bt0_all[:, wm]
            end_ok = crl[end].notna().to_numpy() & np.isfinite(crl_tau)
            fwd_raw = np.where(end_ok,
                               crl[end].to_numpy(dtype=float) - crl_tau, np.nan)
            fwd_exc = np.where(end_ok,
                               mex[end].to_numpy(dtype=float)
                               - mex[tau].to_numpy(dtype=float), np.nan)
            n_flag20 = (b20w == True).sum(axis=1) + (b20w == False).sum(axis=1)  # noqa: E712
            n_flagt0 = (bt0w == True).sum(axis=1) + (bt0w == False).sum(axis=1)  # noqa: E712
            fw = pd.DataFrame({
                "breakout_event_id": ids,
                "tau": tau, "delta": dl,
                "fwd_start_date": obsd[tau].to_numpy(),
                "fwd_end_date": obsd[end].to_numpy(),
                "fwd_raw_log": fwd_raw,
                "fwd_mkt_excess_log": fwd_exc,
                "n_valid_obs_window": vw.sum(axis=1),
                "future_max_drawdown": np.where(
                    vw.any(axis=1), np.nanmax(np.where(vw, ddw, -np.inf),
                                              axis=1), np.nan),
                "future_max_gain": np.where(
                    vw.any(axis=1), np.nanmax(np.where(vw, Rw, -np.inf),
                                              axis=1) - 1.0, np.nan),
                "new_high_within": np.where(
                    vw.any(axis=1), nhw.any(axis=1).astype(float), np.nan),
                "days_to_next_high": np.where(
                    nhw.any(axis=1),
                    (np.argmax(nhw, axis=1) + 1).astype(float), np.nan),
                "lose_ref20_within": np.where(
                    n_flag20 > 0,
                    (b20w == True).any(axis=1).astype(float), np.nan),  # noqa: E712
                "lose_t0_close_within": np.where(
                    n_flagt0 > 0,
                    (bt0w == True).any(axis=1).astype(float), np.nan),  # noqa: E712
                "recover_current_peak_within": np.where(
                    vw.any(axis=1),
                    rec_all[:, wm].any(axis=1).astype(float), np.nan),
            })
            elig = ((i0 + tau + dl) <= ldsp)
            fw = fw[elig].copy()
            parts.append(fw)
    out = pd.concat(parts, ignore_index=True)
    return out.sort_values(["breakout_event_id", "tau", "delta"]).reset_index(drop=True)


# ------------------------------------------------------------------- bins

def assign_bins(riskset: pd.DataFrame) -> pd.DataFrame:
    """Pre-registered bin assignments; cross-sectional within the SAME tau only.

    quartile: average-rank fraction -> 1+floor(4*p) clipped to 4 (ties stay
    together). natural0 / vr1 / flag: semantic thresholds fixed in advance.
    2d: drawdown median split (<= median = shallow) x turnover_ratio_pre20>1
    (keep) — both pre-registered; no outcome-optimized cutpoints anywhere.
    """
    recs = []
    for tau in RISKSET_TAUS:
        g = riskset[riskset["tau"] == tau]
        eid, code = g["breakout_event_id"], g["code"]
        for var in CONT_VARS:
            v = g[var]
            ok = v.notna()
            if not ok.any():
                continue
            r = v.rank(method="average", pct=True)
            q = np.clip(1 + np.floor(4 * r.to_numpy()), 1, 4)
            q = pd.Series(q, index=g.index, dtype="Int64").where(ok)
            lab = q.map({1: "Q1", 2: "Q2", 3: "Q3", 4: "Q4"}).astype("string")
            recs.append(pd.DataFrame({
                "breakout_event_id": eid, "code": code, "tau": tau,
                "state_var": var, "bin_set": "quartile", "bin": q,
                "bin_label": lab}))
        for var in NATURAL0:
            v = g[var]
            ok = v.notna()
            lab = pd.Series(np.where(v.to_numpy() > 0, "above0",
                                     "at_or_below0"), index=g.index,
                            dtype="string").where(ok)
            code_ = pd.Series(np.where(v.to_numpy() > 0, 2, 1),
                              index=g.index, dtype="Int64").where(ok)
            recs.append(pd.DataFrame({
                "breakout_event_id": eid, "code": code, "tau": tau,
                "state_var": var, "bin_set": "natural0", "bin": code_,
                "bin_label": lab}))
        for var in VR1:
            v = g[var]
            ok = v.notna()
            lab = pd.Series(np.where(v.to_numpy() > 1, "vr_gt1", "vr_le1"),
                            index=g.index, dtype="string").where(ok)
            code_ = pd.Series(np.where(v.to_numpy() > 1, 2, 1),
                              index=g.index, dtype="Int64").where(ok)
            recs.append(pd.DataFrame({
                "breakout_event_id": eid, "code": code, "tau": tau,
                "state_var": var, "bin_set": "vr1", "bin": code_,
                "bin_label": lab}))
        f = g["t0_ref60_breakout"]
        okf = f.notna()
        fv = f.to_numpy()
        lab = pd.Series(np.where(fv == True, "t0_ref60_true",  # noqa: E712
                                 "t0_ref60_false"), index=g.index,
                        dtype="string").where(okf)
        code_ = pd.Series(np.where(fv == True, 2, 1),  # noqa: E712
                          index=g.index, dtype="Int64").where(okf)
        recs.append(pd.DataFrame({
            "breakout_event_id": eid, "code": code, "tau": tau,
            "state_var": "t0_ref60_breakout", "bin_set": "flag",
            "bin": code_, "bin_label": lab}))
        dd = g["drawdown_from_running_peak"]
        tr = g["turnover_ratio_pre20"]
        okc = dd.notna() & tr.notna()
        med = dd.median()
        cell = (np.where(dd.to_numpy() <= med, "shallow", "deep") + "_" +
                np.where(tr.to_numpy() > 1, "keep", "decay"))
        cats = ["shallow_keep", "shallow_decay", "deep_keep", "deep_decay"]
        code_ = pd.Series(
            pd.Categorical(cell, categories=cats).codes + 1,
            index=g.index, dtype="Int64").where(okc)
        recs.append(pd.DataFrame({
            "breakout_event_id": eid, "code": code, "tau": tau,
            "state_var": "drawdown_x_participation",
            "bin_set": "2d_price_part", "bin": code_,
            "bin_label": pd.Series(cell, index=g.index,
                                   dtype="string").where(okc)}))
    return (pd.concat(recs, ignore_index=True)
            .sort_values(["breakout_event_id", "tau", "state_var", "bin_set"])
            .reset_index(drop=True))


# ---------------------------------------------------------- contrast engine

_METRICS = ("median_fwd_excess", "mean_fwd_excess", "median_fwd_mdd",
            "p_new_high")


def _nanmed(a):
    a = a[np.isfinite(a)]
    return float(np.median(a)) if len(a) else np.nan


def _nanmean(a):
    a = a[np.isfinite(a)]
    return float(np.mean(a)) if len(a) else np.nan


def _point_stats(exc, mdd, nh, raw):
    return {
        "median_fwd_excess": _nanmed(exc), "mean_fwd_excess": _nanmean(exc),
        "median_fwd_raw": _nanmed(raw), "mean_fwd_raw": _nanmean(raw),
        "median_fwd_mdd": _nanmed(mdd), "p_new_high": _nanmean(nh),
    }


def _boot_family(df, B, seed):
    """Cluster bootstrap for one family df: per-bin draws + top-bottom
    median-excess diff draws. df columns: bin,exc,raw,mdd,nh,cluster(int).

    Cluster resampling: draw K cluster ids with replacement; rows inherit
    their cluster's multiplicity. Deterministic via per-family seed.
    """
    n = len(df)
    binv = df["bin"].to_numpy()
    exc = df["exc"].to_numpy(dtype=float)
    mdd = df["mdd"].to_numpy(dtype=float)
    nh = df["nh"].to_numpy(dtype=float)
    cl = df["cluster"].to_numpy()
    bins = np.unique(binv)
    rng = np.random.default_rng(seed)
    K = int(cl.max()) + 1
    arange_n = np.arange(n)
    draws = {int(b): {m: [] for m in _METRICS} for b in bins}
    diff_draws = []
    bmin, bmax = int(bins.min()), int(bins.max())
    for _ in range(B):
        cnt = np.bincount(rng.integers(0, K, K), minlength=K)
        sel = np.repeat(arange_n, cnt[cl])
        bv, ev, mv, nv = binv[sel], exc[sel], mdd[sel], nh[sel]
        for b in bins:
            msk = bv == b
            if not msk.any():
                for m in _METRICS:
                    draws[int(b)][m].append(np.nan)
                continue
            e = ev[msk]
            e = e[np.isfinite(e)]
            md = mv[msk]
            md = md[np.isfinite(md)]
            nvv = nv[msk]
            nvv = nvv[np.isfinite(nvv)]
            if len(e):
                draws[int(b)]["median_fwd_excess"].append(float(np.median(e)))
                draws[int(b)]["mean_fwd_excess"].append(float(np.mean(e)))
            else:
                draws[int(b)]["median_fwd_excess"].append(np.nan)
                draws[int(b)]["mean_fwd_excess"].append(np.nan)
            draws[int(b)]["median_fwd_mdd"].append(
                float(np.median(md)) if len(md) else np.nan)
            draws[int(b)]["p_new_high"].append(
                float(np.mean(nvv)) if len(nvv) else np.nan)
        lo, hi = bv == bmin, bv == bmax
        e_lo, e_hi = ev[lo], ev[hi]
        e_lo = e_lo[np.isfinite(e_lo)]
        e_hi = e_hi[np.isfinite(e_hi)]
        diff_draws.append(np.median(e_hi) - np.median(e_lo)
                          if len(e_lo) and len(e_hi) else np.nan)
    return draws, np.asarray(diff_draws, dtype=float)


def _ci95(draws):
    d = np.asarray(draws, dtype=float)
    d = d[np.isfinite(d)]
    if len(d) == 0:
        return (np.nan, np.nan)
    return (float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5)))


def _family_frame(bins_tau_var, rs_tau, o):
    """Join bins x forward outcomes x (code, asof_date) → analysis frame."""
    key = bins_tau_var.set_index("breakout_event_id")[["bin", "bin_label"]]
    m = key.join(o, how="inner").reset_index()
    m = m[m["bin"].notna()]
    if not len(m):
        return None, None
    meta = rs_tau[["code", "asof_date"]].reindex(m["breakout_event_id"])
    df = pd.DataFrame({
        "bin": m["bin"].astype(int).to_numpy(),
        "bin_label": m["bin_label"].to_numpy(),
        "exc": m["fwd_mkt_excess_log"].to_numpy(dtype=float),
        "raw": m["fwd_raw_log"].to_numpy(dtype=float),
        "mdd": m["future_max_drawdown"].to_numpy(dtype=float),
        "nh": m["new_high_within"].to_numpy(dtype=float),
        "cluster_stock": pd.factorize(meta["code"].to_numpy())[0],
        "cluster_date": pd.factorize(meta["asof_date"].to_numpy())[0],
    })
    return m, df


def _bin_rows(df, draws_by_cl, tau, var, bset, dl, mono):
    rows = []
    for bcode, s in df.groupby("bin"):
        n_exc = int(np.isfinite(s["exc"]).sum())
        pt = _point_stats(s["exc"].to_numpy(), s["mdd"].to_numpy(),
                          s["nh"].to_numpy(), s["raw"].to_numpy())
        row = {"tau": tau, "tau_role": TAU_ROLE[tau], "state_var": var,
               "bin_set": bset, "bin": int(bcode),
               "bin_label": str(df.loc[df["bin"] == bcode, "bin_label"].iloc[0]),
               "delta": dl, "n": n_exc,
               "n_mdd": int(np.isfinite(s["mdd"]).sum()),
               "n_newhigh": int(np.isfinite(s["nh"]).sum()),
               "monotonic_quartile": mono,
               "sufficient_n": bool(n_exc >= MIN_CELL_N), **pt}
        for cl_name in ("stock", "date"):
            d = draws_by_cl[cl_name][0].get(int(bcode), {})
            for met in _METRICS:
                lo, hi = _ci95(d.get(met, []))
                row[f"{met}_ci95_{cl_name}_lo"] = lo
                row[f"{met}_ci95_{cl_name}_hi"] = hi
        rows.append(row)
    return rows


def _diff_row(df, draws_by_cl, tau, var, bset, dl, mono):
    bmin, bmax = int(df["bin"].min()), int(df["bin"].max())
    if bmin == bmax:
        return None
    s_lo, s_hi = df[df["bin"] == bmin], df[df["bin"] == bmax]
    row = {"tau": tau, "tau_role": TAU_ROLE[tau], "state_var": var,
           "bin_set": bset, "bin": -1, "bin_label": "top_minus_bottom",
           "delta": dl,
           "n": int(len(s_lo) + len(s_hi)),
           "n_mdd": int(np.isfinite(s_lo["mdd"]).sum()
                        + np.isfinite(s_hi["mdd"]).sum()),
           "n_newhigh": int(np.isfinite(s_lo["nh"]).sum()
                            + np.isfinite(s_hi["nh"]).sum()),
           "monotonic_quartile": mono,
           "sufficient_n": bool(min(len(s_lo), len(s_hi)) >= MIN_CELL_N),
           "median_fwd_excess": _nanmed(s_hi["exc"].to_numpy())
           - _nanmed(s_lo["exc"].to_numpy()),
           "mean_fwd_excess": _nanmean(s_hi["exc"].to_numpy())
           - _nanmean(s_lo["exc"].to_numpy()),
           "median_fwd_raw": np.nan, "mean_fwd_raw": np.nan,
           "median_fwd_mdd": _nanmed(s_hi["mdd"].to_numpy())
           - _nanmed(s_lo["mdd"].to_numpy()),
           "p_new_high": _nanmean(s_hi["nh"].to_numpy())
           - _nanmean(s_lo["nh"].to_numpy())}
    for cl_name in ("stock", "date"):
        dd_ = draws_by_cl[cl_name][1]
        lo, hi = _ci95(dd_)
        row[f"median_fwd_excess_ci95_{cl_name}_lo"] = lo
        row[f"median_fwd_excess_ci95_{cl_name}_hi"] = hi
        fin = dd_[np.isfinite(dd_)]
        B_ = max(len(dd_), 1)
        p = 2 * min((1 + int((fin <= 0).sum())) / (B_ + 1),
                    (1 + int((fin >= 0).sum())) / (B_ + 1))
        row[f"p_boot_{cl_name}"] = float(min(p, 1.0))
        for met in ("mean_fwd_excess", "median_fwd_mdd", "p_new_high"):
            row[f"{met}_ci95_{cl_name}_lo"] = np.nan
            row[f"{met}_ci95_{cl_name}_hi"] = np.nan
    return row


def compute_contrasts(riskset, fwd, bins, B=BOOT_B):
    """Pre-registered primary contrasts with stock/date cluster bootstrap."""
    fw = fwd.set_index(["breakout_event_id", "tau", "delta"])
    rows = []
    pvals = []
    binsets = ([(v, "quartile") for v in CONT_VARS]
               + [(v, "natural0") for v in NATURAL0]
               + [(v, "vr1") for v in VR1]
               + [("t0_ref60_breakout", "flag")])
    for tau in RISKSET_TAUS:
        rs_tau = riskset[riskset["tau"] == tau].set_index("breakout_event_id")
        bins_tau = bins[bins["tau"] == tau]
        for dl in DELTAS:
            try:
                o = fw.xs(tau, level="tau").xs(dl, level="delta")
            except KeyError:
                continue
            for var, bset in binsets:
                btv = bins_tau[(bins_tau["state_var"] == var)
                               & (bins_tau["bin_set"] == bset)]
                m, df = _family_frame(btv, rs_tau, o)
                if df is None:
                    continue
                mono = np.nan
                if bset == "quartile":
                    meds = [_nanmed(df.loc[df["bin"] == q, "exc"].to_numpy())
                            for q in (1, 2, 3, 4)]
                    if all(np.isfinite(meds)):
                        mono = bool(np.all(np.diff(meds) >= 0)
                                    or np.all(np.diff(meds) <= 0))
                draws_by_cl = {}
                for cl_name, cl_col in (("stock", "cluster_stock"),
                                        ("date", "cluster_date")):
                    fkey = f"contrast|{tau}|{var}|{bset}|{dl}|{cl_name}"
                    draws_by_cl[cl_name] = _boot_family(
                        df[["bin", "exc", "raw", "mdd", "nh", cl_col]]
                        .rename(columns={cl_col: "cluster"}), B,
                        family_seed(fkey))
                rows.extend(_bin_rows(df, draws_by_cl, tau, var, bset, dl, mono))
                drow = _diff_row(df, draws_by_cl, tau, var, bset, dl, mono)
                if drow is not None:
                    if bset == "quartile":
                        pvals.append({"tau": tau, "delta": dl, "state_var": var,
                                      "p": drow["p_boot_stock"],
                                      "row_ref": len(rows)})
                    rows.append(drow)
    con = pd.DataFrame(rows)
    if pvals:
        pv = pd.DataFrame(pvals)
        for (tau, dl), g in pv.groupby(["tau", "delta"]):
            m_ = len(g)
            prev = 0.0
            for i, (_, r) in enumerate(g.sort_values("p").iterrows()):
                adj = min(max(prev, r["p"] * m_ / (m_ - i)), 1.0)
                con.loc[r["row_ref"], "p_holm_stock"] = adj
                con.loc[r["row_ref"], "reject_holm05"] = bool(adj < 0.05)
                prev = adj
    return con.sort_values(
        ["tau", "state_var", "bin_set", "bin", "delta"]).reset_index(drop=True)


def compute_contrasts_2d(riskset, fwd, bins, B=BOOT_B):
    """Second layer: 4 pre-registered price x participation cells (primary taus)."""
    fw = fwd.set_index(["breakout_event_id", "tau", "delta"])
    rows = []
    for tau in PRIMARY_TAUS:
        rs_tau = riskset[riskset["tau"] == tau].set_index("breakout_event_id")
        btv = bins[(bins["tau"] == tau)
                   & (bins["state_var"] == "drawdown_x_participation")]
        for dl in DELTAS:
            try:
                o = fw.xs(tau, level="tau").xs(dl, level="delta")
            except KeyError:
                continue
            m, df = _family_frame(btv, rs_tau, o)
            if df is None:
                continue
            draws_by_cl = {}
            for cl_name, cl_col in (("stock", "cluster_stock"),
                                    ("date", "cluster_date")):
                fkey = f"contrast2d|{tau}|{dl}|{cl_name}"
                draws_by_cl[cl_name] = _boot_family(
                    df[["bin", "exc", "raw", "mdd", "nh", cl_col]]
                    .rename(columns={cl_col: "cluster"}), B, family_seed(fkey))
            rows.extend(_bin_rows(df, draws_by_cl, tau,
                                  "drawdown_x_participation",
                                  "2d_price_part", dl, np.nan))
    return pd.DataFrame(rows).sort_values(
        ["tau", "bin", "delta"]).reset_index(drop=True)


# ------------------------------------------------- attrition / descriptive

def build_attrition(riskset, fwd, bins) -> pd.DataFrame:
    """Per analysis cell: base -> exposure -> future(calendar) -> final."""
    recs = []
    fw = fwd.set_index(["breakout_event_id", "tau", "delta"])
    for tau in RISKSET_TAUS:
        g = riskset[riskset["tau"] == tau].set_index("breakout_event_id")
        n_base = int(g["asof_in_dataset"].sum())
        for var in CONT_VARS + STATE_FLAG:
            n_exp = int(g[var].notna().sum())
            for dl in DELTAS:
                n_fut_cal = int(g[f"eligible_fwd_{dl}"].sum())
                try:
                    o = fw.xs(tau, level="tau").xs(dl, level="delta")
                except KeyError:
                    recs.append({"tau": tau, "state_var": var,
                                 "bin_set": "quartile" if var in CONT_VARS else "flag",
                                 "delta": dl, "n_base_riskset": n_base,
                                 "n_exposure_available": n_exp,
                                 "n_future_observable": n_fut_cal,
                                 "n_final": 0, "n_final_mdd": 0,
                                 "n_final_newhigh": 0})
                    continue
                j = o.join(g[[var]], how="inner")
                fin = j[j[var].notna() & j["fwd_mkt_excess_log"].notna()]
                recs.append({
                    "tau": tau, "state_var": var,
                    "bin_set": "quartile" if var in CONT_VARS else "flag",
                    "delta": dl, "n_base_riskset": n_base,
                    "n_exposure_available": n_exp,
                    "n_future_observable": n_fut_cal,
                    "n_final": int(len(fin)),
                    "n_final_mdd": int(fin["future_max_drawdown"].notna().sum()),
                    "n_final_newhigh": int(fin["new_high_within"].notna().sum()),
                })
    return pd.DataFrame(recs).sort_values(
        ["tau", "state_var", "delta"]).reset_index(drop=True)


def state_distributions(riskset) -> pd.DataFrame:
    recs = []
    for tau in RISKSET_TAUS:
        g = riskset[riskset["tau"] == tau]
        for var in CONT_VARS:
            v = g[var].dropna().to_numpy(dtype=float)
            if not len(v):
                continue
            q = np.percentile(v, [5, 25, 50, 75, 95])
            recs.append({"tau": tau, "state_var": var, "n": len(v),
                         "unit": STATE_UNITS.get(var, ""),
                         "mean": float(np.mean(v)), "sd": float(np.std(v)),
                         "p5": q[0], "p25": q[1], "p50": q[2],
                         "p75": q[3], "p95": q[4]})
    return pd.DataFrame(recs)


def conditional_curves(riskset, fwd, bins) -> pd.DataFrame:
    """Decile-level descriptive outcome curves (no inference; descriptive)."""
    fw = fwd.set_index(["breakout_event_id", "tau", "delta"])
    recs = []
    for tau in RISKSET_TAUS:
        g = riskset[riskset["tau"] == tau].set_index("breakout_event_id")
        for var in CONT_VARS:
            v = g[var]
            ok = v.notna()
            if int(ok.sum()) < 100:
                continue
            r = v.rank(method="average", pct=True)
            dec = pd.Series(np.clip(1 + np.floor(10 * r.to_numpy()), 1, 10),
                            index=v.index, dtype="Int64").where(ok)
            for dl in DELTAS:
                try:
                    o = fw.xs(tau, level="tau").xs(dl, level="delta")
                except KeyError:
                    continue
                j = o.join(dec.rename("dec"), how="inner").dropna(
                    subset=["dec"])
                for dcode, s in j.groupby("dec"):
                    recs.append({
                        "tau": tau, "state_var": var, "decile": int(dcode),
                        "delta": dl, "n": int(len(s)),
                        "median_fwd_excess": _nanmed(s["fwd_mkt_excess_log"].to_numpy(dtype=float)),
                        "mean_fwd_excess": _nanmean(s["fwd_mkt_excess_log"].to_numpy(dtype=float)),
                        "median_fwd_mdd": _nanmed(s["future_max_drawdown"].to_numpy(dtype=float)),
                        "p_new_high": _nanmean(s["new_high_within"].to_numpy(dtype=float)),
                    })
    return pd.DataFrame(recs).sort_values(
        ["tau", "state_var", "decile", "delta"]).reset_index(drop=True)


# ------------------------------------------------------------ overlap audit

def overlap_audit(riskset, mdates) -> dict:
    """Same-stock trajectory overlap + calendar cohort structure (Gate 4).

    No events are deleted; this audit exists so downstream uncertainty is not
    treated as independent.
    """
    mpos = {d: i for i, d in enumerate(mdates)}
    base = riskset[riskset["tau"] == 0][
        ["breakout_event_id", "code", "breakout_day"]].copy()
    per_code = base.groupby("code").size()
    dist = per_code.value_counts().sort_index()
    gap_pairs = {"lt5": 0, "lt10": 0, "lt20": 0, "lt40": 0, "ge40": 0}
    traj_overlap_pairs = 0
    events_with_overlap = 0
    for _, grp in base.groupby("code"):
        days = sorted(mpos[d] for d in grp["breakout_day"])
        n = len(days)
        for i in range(n):
            has_partner = False
            for k in range(i + 1, n):
                gap = days[k] - days[i]
                if gap < 5:
                    gap_pairs["lt5"] += 1
                elif gap < 10:
                    gap_pairs["lt10"] += 1
                elif gap < 20:
                    gap_pairs["lt20"] += 1
                elif gap < 40:
                    gap_pairs["lt40"] += 1
                else:
                    gap_pairs["ge40"] += 1
                if gap <= 40:
                    traj_overlap_pairs += 1
                    has_partner = True
            if has_partner:
                events_with_overlap += 1
    fwd_overlap = {}
    for tau in PRIMARY_TAUS:
        for dl in DELTAS:
            g = riskset[(riskset["tau"] == tau)
                        & (riskset[f"eligible_fwd_{dl}"])]
            n_over = 0
            for _, grp in g.groupby("code"):
                if len(grp) < 2:
                    continue
                pos = sorted(mpos[d] + tau for d in grp["breakout_day"])
                for i in range(len(pos)):
                    if any(0 < pos[k] - pos[i] <= dl
                           for k in range(len(pos)) if k != i):
                        n_over += 1
            fwd_overlap[f"tau{tau}_d{dl}"] = {
                "n_eligible": int(len(g)),
                "n_fwd_window_overlaps_same_stock_same_tau": int(n_over),
                "pct": round(100.0 * n_over / max(len(g), 1), 3)}
    cohorts = {}
    for tau in PRIMARY_TAUS:
        g = riskset[(riskset["tau"] == tau) & riskset["asof_in_dataset"]]
        cnt = g.groupby("asof_date").size()
        top = cnt.sort_values(ascending=False).head(5)
        cohorts[f"tau{tau}"] = {
            "n_dates": int(len(cnt)),
            "mean_events_per_date": round(float(cnt.mean()), 3),
            "median_events_per_date": float(cnt.median()),
            "p90_events_per_date": float(np.percentile(cnt, 90)),
            "max_events_per_date": int(cnt.max()),
            "top5_dates": {str(k): int(v) for k, v in top.items()}}
    return {
        "n_events": int(len(base)),
        "n_stocks": int(per_code.size),
        "events_per_stock_distribution": {str(int(k)): int(v)
                                          for k, v in dist.items()},
        "max_events_single_stock": int(per_code.max()),
        "pct_events_in_multi_event_stocks": round(
            100.0 * float(per_code[per_code > 1].sum()) / len(base), 3),
        "same_stock_pair_breakout_gap_market_days": gap_pairs,
        "traj_overlap_pairs_within40": int(traj_overlap_pairs),
        "events_with_same_stock_overlap_within40": int(events_with_overlap),
        "pct_events_with_same_stock_overlap": round(
            100.0 * events_with_overlap / len(base), 3),
        "forward_window_overlap_by_tau_delta": fwd_overlap,
        "calendar_cohorts": cohorts,
        "policy": ("frozen event universe unchanged; overlap handled via "
                   "stock-cluster and asof-date-cluster bootstrap, events are "
                   "NOT deleted for overlap"),
    }
