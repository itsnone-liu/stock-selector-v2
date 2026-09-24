#!/usr/bin/env python3
"""T5.3 主构建：edges / matrices / runs / churn / terminal hazard /
Markov order（一阶 vs 二阶 backoff）。

raw_state_v1 只读（af2dac7 冻结）；本脚本不读取任何 outcome 表
（G7）；治理候选在 run_t5_3_operational.py 独立生成。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/root/project/workspace/stock-selector-v2")
sys.path.insert(0, str(ROOT / "src"))
from t5.transitions import (build_edges, transition_matrix,  # noqa
                            state_runs, one_day_reversal)

OUT = ROOT / "output/research/t5/transition"
OUT.mkdir(parents=True, exist_ok=True)
FACTS = ROOT / "output/research/t5/facts"
STATE = ROOT / "output/research/t5/state"

EV_COLS = None   # 由 cs 列推断


def main():
    t0 = time.time()
    cs = pd.read_parquet(STATE / "t5_candidate_state_daily.parquet")
    st_term = pd.read_parquet(FACTS / "t5_daily_state.parquet",
                              columns=["event_id", "delta_day",
                                       "termination_reason"])
    print(f"loaded cs={cs.shape} {time.time() - t0:.0f}s", flush=True)

    # ---------- edges ----------
    edges = build_edges(cs, st_term)
    edges.to_parquet(OUT / "t5_transition_edges.parquet", index=False)
    print("edges", edges.shape, f"{time.time() - t0:.0f}s", flush=True)

    # ---------- matrices（全样本 + year + E-class 条件层） ----------
    mats = {}
    for k in (1, 3, 5):
        m = transition_matrix(edges, k)
        m.insert(0, "horizon_k", k)
        mats[k] = m
    pd.concat(mats.values(), ignore_index=True).to_parquet(
        OUT / "t5_transition_matrix_1d.parquet"
        if False else OUT / "t5_transition_matrix.parquet",
        index=False)
    for k in (1, 3, 5):   # 单文件分开（任务书命名）
        mats[k].to_parquet(OUT / f"t5_transition_matrix_{k}d.parquet",
                           index=False)
    # E-class 条件层（1d）
    e = edges[(edges.horizon_k == 1) & edges.state_assignable.astype(
        bool) & (edges.raw_state_t != "STATE_UNAVAILABLE")].merge(
        cs[["event_id", "delta_day", "exposure_class"]],
        on=["event_id", "delta_day"], how="left")
    em = (e.groupby(["exposure_class", "raw_state_t", "dest_label"])
          .size().rename("n").reset_index())
    em.to_parquet(OUT / "t5_transition_by_eclass.parquet", index=False)
    # 守恒摘要
    cons = {k: bool(mats[k].conserved.all()) for k in mats}
    print("matrix conservation:", cons, flush=True)

    # ---------- runs ----------
    runs = state_runs(cs)
    runs.to_parquet(OUT / "t5_state_runs.parquet", index=False)
    dw = runs[runs.state != "STATE_UNAVAILABLE"].groupby(
        ["state", "segment"]).agg(
        n_runs=("state", "size"),
        median_dwell=("dwell_market_days", "median"),
        q25=("dwell_market_days", lambda s: s.quantile(.25)),
        q75=("dwell_market_days", lambda s: s.quantile(.75)),
        p_dwell1=("dwell_market_days", lambda s: (s == 1).mean()),
        p_dwell_le2=("dwell_market_days", lambda s: (s <= 2).mean()),
        p_dwell_ge3=("dwell_market_days", lambda s: (s >= 3).mean()),
    ).reset_index()
    print(dw.to_string(index=False), flush=True)
    # E-class 分层 dwell
    runs.groupby(["state", "exposure_class"])[
        "dwell_market_days"].median().rename("median_dwell").to_frame(
    ).to_parquet(OUT / "t5_dwell_by_eclass.parquet")

    # ---------- terminal hazard（C6 audit） ----------
    st_full = pd.read_parquet(FACTS / "t5_daily_state.parquet",
                              columns=["event_id", "delta_day",
                                       "termination_reason"])
    last_delta = st_full.groupby("event_id")["delta_day"].max()
    term_map = st_full.dropna(subset=["termination_reason"]).set_index(
        "event_id")["termination_reason"]
    hz = edges[edges.horizon_k == 1][
        ["event_id", "delta_day", "raw_state_t"]].copy()
    hz["last_delta"] = hz.event_id.map(last_delta)
    hz["term_reason"] = hz.event_id.map(term_map)
    hz["remaining"] = hz.last_delta - hz.delta_day
    hza = hz[hz.raw_state_t != "STATE_UNAVAILABLE"]
    haz = []
    for st_, g in hza.groupby("raw_state_t"):
        lc = g[g.term_reason == "LIFECYCLE_END"]
        haz.append({
            "state": st_, "n": len(g),
            "p_end_next_day_any": float((g.remaining == 0).mean()),
            "p_lifecycle_end_next_day": float(
                (lc.remaining == 0).mean()) if len(lc) else 0.0,
            "p_lifecycle_end_le3": float((lc.remaining <= 3).mean())
            if len(lc) else 0.0,
            "p_lifecycle_end_le5": float((lc.remaining <= 5).mean())
            if len(lc) else 0.0,
            "median_remaining_days": float(
                lc.remaining.median()) if len(lc) else None,
            "median_remaining_all": float(g.remaining.median()),
        })
    pd.DataFrame(haz).to_parquet(OUT / "t5_terminal_hazard.parquet",
                                 index=False)
    print(pd.DataFrame(haz).to_string(index=False), flush=True)

    # ---------- churn audit ----------
    rev = one_day_reversal(cs)
    # 边频溯源（1d 状态变化 pair，含方向）
    ch = cs.sort_values(["event_id", "delta_day"]).copy()
    ch["prev_state"] = ch.groupby("event_id")[
        "final_candidate_state"].shift(1)
    chg = ch[(ch.prev_state.notna())
             & (ch.prev_state != ch.final_candidate_state)]
    pairs = (chg.groupby(["prev_state", "final_candidate_state"])
             .size().rename("n").reset_index())
    KEY = [("C0", "C1"), ("C1", "C0"), ("C1", "C3"), ("C3", "C1"),
           ("C1", "C4"), ("C4", "C1"), ("C2", "C3"), ("C3", "C2"),
           ("C4", "C5"), ("C5", "C4"), ("C5", "C6"), ("C6", "C5")]
    pairs["group"] = pairs.apply(
        lambda r: f"{r.prev_state}<->{r.final_candidate_state}"
        if (r.prev_state, r.final_candidate_state) in KEY
        or (r.final_candidate_state, r.prev_state) in KEY else "other",
        axis=1)
    grp = pairs.groupby("group")["n"].sum().sort_values(
        ascending=False)
    churn_rows = [{"metric": "one_day_reversal_rate",
                   "value": float(rev.one_day_reversal.mean())},
                  {"metric": "any_daily_change_rate",
                   "value": float((ch.prev_state.notna()
                                   & (ch.prev_state != ch[
                                       "final_candidate_state"])
                                   ).mean())}]
    for gname, n in grp.items():
        churn_rows.append({"metric": f"edge_group:{gname}", "value":
                           int(n)})
    # C1 dwell=1 归因：dwell=1 的 C1 段，下一行是否新高布尔转 False
    ev = cs[["event_id", "delta_day", "final_candidate_state",
             "ev_is_new_high_20d", "ev_dist_to_ref20",
             "ev_drawdown_from_peak_log", "ev_days_since_peak",
             "ev_efficiency_signed_3", "ev_cum_ret_from_t0_log",
             "ev_max_dd_to_date_log", "ev_ret_3d_log",
             "ev_turnover_contraction_3d",
             "ev_turnover_load_3d_mean"]]
    ev = ev.sort_values(["event_id", "delta_day"])
    c1 = ev[ev.final_candidate_state == "C1"]
    nxt_nh = ev.groupby("event_id")[
        "ev_is_new_high_20d"].shift(-1)
    c1_idx = c1.index
    c1_next_nh = nxt_nh.reindex(c1_idx)
    single_day_c1 = runs[(runs.state == "C1")
                         & (runs.dwell_market_days == 1)]
    # 对 dwell=1 的 C1 行：退出当天（下一行）新高布尔关而其他证据仍好
    sd = single_day_c1.merge(
        ev[["event_id", "delta_day", "ev_is_new_high_20d"]],
        left_on=["event_id", "start_delta"], right_on=[
            "event_id", "delta_day"], how="left")
    nxt = ev[["event_id", "delta_day", "ev_is_new_high_20d",
              "final_candidate_state"]].copy()
    nxt["delta_day"] = nxt["delta_day"] - 1
    sd = sd.merge(nxt, on=["event_id", "delta_day"],
                  suffixes=("_t", "_next"), how="left")
    n_sd = len(sd)
    n_nh_off = int(((sd.ev_is_new_high_20d_next == False)).sum())
    churn_rows.append({"metric": "C1_dwell1_runs", "value": n_sd})
    churn_rows.append({"metric":
                       "C1_dwell1_nextday_newhigh_off",
                       "value": n_nh_off})
    churn_rows.append({"metric": "C1_dwell1_nextday_newhigh_off_frac",
                       "value": n_nh_off / n_sd if n_sd else None})
    # reversal 当天 primitive 翻转贡献（数值跨过 0/结构位）
    rev2 = rev.merge(ev, on=["event_id", "delta_day"], how="left")
    rev2["prev_nh"] = rev2.groupby("event_id")[
        "ev_is_new_high_20d"].shift(1)
    rr = rev2[rev2.one_day_reversal]
    flips = {
        "new_high_bool_changed": int(
            (rr.ev_is_new_high_20d != rr.prev_nh).sum()),
        "n_reversals": int(len(rr)),
    }
    for k, v in flips.items():
        churn_rows.append({"metric": f"reversal_{k}", "value": v})
    pd.DataFrame(churn_rows).to_parquet(
        OUT / "t5_churn_audit.parquet", index=False)
    print(pd.DataFrame(churn_rows).to_string(index=False), flush=True)

    # ---------- Markov order ----------
    markov = markov_order_audit(cs)
    pd.DataFrame(markov["rows"]).to_parquet(
        OUT / "t5_markov_order_audit.parquet", index=False)
    print(json.dumps(markov["summary"], indent=2), flush=True)

    man = {"stage": "T5.3_transition", "baseline": "af2dac7",
           "raw_state_source": "t5_candidate_state_daily.parquet "
                               "(af2dac7 frozen)",
           "rows": {"edges": len(edges), "runs": len(runs)},
           "conservation": cons,
           "markov_summary": markov["summary"],
           "elapsed_sec": round(time.time() - t0, 1)}
    (OUT / "t5_3_manifest.json").write_text(json.dumps(
        man, indent=2, ensure_ascii=False))


def markov_order_audit(cs):
    """2024 fit / 2025 val / 2026 conf；multiclass Brier primary。"""
    d = cs.sort_values(["event_id", "delta_day"])[
        ["event_id", "delta_day", "final_candidate_state",
         "segment"]].copy()
    d["prev"] = d.groupby("event_id")["final_candidate_state"].shift(1)
    d["next"] = d.groupby("event_id")["final_candidate_state"].shift(-1)
    d = d.dropna(subset=["next"])          # 末行无 next（terminal 边在 edges 层）
    # 目标空间：C0–C6 + STATE_UNAVAILABLE（terminal 不入模型集，
    # 末行已 drop；edges 层已单独守恒）
    classes = sorted(d.final_candidate_state.unique())

    def probs_from(counts):
        tot = counts.sum()
        return counts / tot if tot else None

    dev = d[d.segment == "development"]
    # 一阶
    fo = (dev.groupby(["final_candidate_state", "next"]).size()
          .rename("n").reset_index())
    fo_tab = {}
    for _, r in fo.iterrows():
        fo_tab.setdefault(r.final_candidate_state, {})[r.next] = r.n
    # 二阶
    so = (dev.groupby(["prev", "final_candidate_state", "next"]).size()
          .rename("n").reset_index())
    so_tab = {}
    for _, r in so.iterrows():
        so_tab.setdefault((r.prev, r.final_candidate_state), {})[
            r.next] = r.n

    def pred_fo(s_t):
        c = fo_tab.get(s_t)
        if not c:
            return None
        return probs_from(pd.Series(c))

    def pred_so(s_prev, s_t):
        if s_prev is None or (isinstance(s_prev, float)
                              and np.isnan(s_prev)):
            return pred_fo(s_t)
        c = so_tab.get((s_prev, s_t))
        if not c:
            return pred_fo(s_t)     # backoff：dev 未见 context
        return probs_from(pd.Series(c))

    def brier(pred, actual, classes):
        if pred is None:
            return None, None
        p = pred.reindex(classes).fillna(0.0)
        # 归一（dev counts 平滑后仍和为 1）
        p = p / p.sum()
        y = pd.Series(0.0, index=classes)
        y[actual] = 1.0
        return float(((p - y) ** 2).sum()), float(p.idxmax() == actual)

    rows = []
    for seg in ("validation", "confirmation"):
        s = d[d.segment == seg]
        for name in ("first_order", "second_order"):
            bs, hits, n = [], 0, 0
            for r in s.itertuples(index=False):
                pred = (pred_fo(r.final_candidate_state)
                        if name == "first_order"
                        else pred_so(r.prev, r.final_candidate_state))
                b, hit = brier(pred, r.next, classes)
                if b is not None:
                    bs.append(b)
                    hits += hit
                    n += 1
            rows.append({"segment": seg, "model": name, "n": n,
                         "brier_multiclass": float(np.mean(bs)),
                         "top1_acc": hits / n})
    # sparse context 统计（val 中二阶 context 在 dev 的频数）
    val = d[d.segment == "validation"]
    dev_ctx = dev.dropna(subset=["prev"]).groupby(
        ["prev", "final_candidate_state"]).size()
    seen = val.dropna(subset=["prev"]).apply(
        lambda r: (r.prev, r.final_candidate_state) in dev_ctx.index,
        axis=1)
    summary = {
        "classes": classes,
        "val_second_order_context_unseen_frac":
            float((~seen).mean()) if len(seen) else None,
        "dev_second_order_contexts": int(len(dev_ctx)),
        "note": "second order backs off to first order on unseen "
                "context; terminal rows excluded from model set "
                "(handled by edge conservation layer)",
    }
    return {"rows": rows, "summary": summary}


if __name__ == "__main__":
    main()
