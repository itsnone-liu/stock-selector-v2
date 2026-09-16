#!/usr/bin/env python3
"""E4首轮事件后处理：申万L1控制×趋势年龄×放量滞涨。

输入为已通过PIT周线扫描的 candidates.csv；不改交易规则、不重新挑阈值。
定义预注册：trend_age=日线MA5>MA10>MA20连续日数；volume_stagnation=
amount_relative_20d>=1.5 且 -2%<=return_realized_5d<=2%。
同日同行业控制：fwd10减去同日同申万L1组中位数；行业未知不猜并单独报告。
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

from stock_selector.behavior_features import behavior_features, trend_age
from stock_selector.data.tdx import TdxStore


def load_membership(db: Path) -> pd.DataFrame:
    import sqlite3
    q = """select ma.asset_key as stock_key, ga.asset_key as group_key,
                   am.effective_from, am.effective_to
            from asset_membership am
            join asset ma on ma.id=am.asset_id
            join asset ga on ga.id=am.group_asset_id
            where am.classification_version='sw_l1_2021'"""
    d = pd.read_sql(q, sqlite3.connect(db))
    d["code"] = d.stock_key.str.replace("stock:", "", regex=False)
    d["date_from"] = pd.to_datetime(d.effective_from)
    d["date_to"] = pd.to_datetime(d.effective_to)
    return d.sort_values(["code", "date_from"])


def enrich(events: pd.DataFrame, store: TdxStore, membership: pd.DataFrame) -> pd.DataFrame:
    e = events.copy()
    e["date_ts"] = pd.to_datetime(e["date"])
    e["industry"] = None
    e["trend_age"] = np.nan
    e["amount_relative_20d"] = np.nan
    e["return_realized_5d"] = np.nan
    for code, ix in e.groupby("code").groups.items():
        frame = store.daily(str(code))
        if frame is None or frame.empty:
            continue
        frame = frame.sort_index()
        for j in ix:
            day = e.at[j, "date_ts"]
            visible = frame.loc[frame.index <= day]
            if len(visible) < 21:
                continue
            feat = behavior_features(visible)
            e.at[j, "trend_age"] = trend_age(visible["close"])
            e.at[j, "amount_relative_20d"] = feat.get("amount_relative_20d")
            e.at[j, "return_realized_5d"] = feat.get("return_realized_5d")
    # 生效区间映射：只在 effective_from<=event_date 且未过 effective_to 时赋值
    for code, ix in e.groupby("code").groups.items():
        m = membership[membership.code == str(code)]
        for j in ix:
            hit = m[(m.date_from <= e.at[j, "date_ts"]) &
                    (m.date_to.isna() | (e.at[j, "date_ts"] < m.date_to))]
            if len(hit):
                e.at[j, "industry"] = hit.iloc[-1].group_key
    e["hard_gate"] = e["trend"].ne("none")
    e["age_bin"] = pd.cut(e["trend_age"], [-1, 5, 20, 60, np.inf],
                           labels=["0-5", "6-20", "21-60", "61+"])
    e["volume_stagnation"] = (
        e["amount_relative_20d"].ge(1.5) &
        e["return_realized_5d"].between(-0.02, 0.02))
    valid = e.dropna(subset=["fwd10", "industry"]).copy()
    # 事件自身不能进入控制中位数；否则组内去均值中位数被机械压到0。
    def _leave_one_out(g):
        vals = g["fwd10"].to_numpy(dtype=float)
        out = np.full(len(vals), np.nan)
        for k in range(len(vals)):
            peers = np.delete(vals, k)
            if len(peers):
                out[k] = np.nanmedian(peers)
        return pd.Series(out, index=g.index)
    peer_med = valid.groupby(["date", "industry"], observed=True, group_keys=False).apply(
        _leave_one_out, include_groups=False)
    valid["fwd10_industry_peer_median"] = peer_med.reindex(valid.index)
    valid["fwd10_industry_demeaned"] = (
        valid["fwd10"] - valid["fwd10_industry_peer_median"])
    e["fwd10_industry_peer_median"] = np.nan
    e["fwd10_industry_demeaned"] = np.nan
    e.loc[valid.index, "fwd10_industry_peer_median"] = valid["fwd10_industry_peer_median"]
    e.loc[valid.index, "fwd10_industry_demeaned"] = valid["fwd10_industry_demeaned"]
    return e


def summary(e: pd.DataFrame) -> dict:
    def agg(g):
        return pd.Series({"n": len(g), "fwd10_mean": g.fwd10.mean(),
                          "fwd10_median": g.fwd10.median(),
                          "demeaned_n": g.fwd10_industry_demeaned.notna().sum(),
                          "demeaned_median": g.fwd10_industry_demeaned.median()})
    cols = ["hard_gate", "trend", "age_bin", "volume_stagnation"]
    out = {"definitions": {"trend_age": "consecutive daily MA5>MA10>MA20",
                             "volume_stagnation": "amount_rel>=1.5 and abs(return5)<=2%",
                             "control": "same date + same SW L1 median"},
           "coverage": {"events": len(e), "industry_known": int(e.industry.notna().sum()),
                        "industry_unknown": int(e.industry.isna().sum())}}
    for c in cols:
        x = e.groupby(c, dropna=False, observed=True).apply(agg, include_groups=False)
        out[c] = x.reset_index().to_dict(orient="records")
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--events", default="output/research/trend_gate/candidates.csv")
    p.add_argument("--tdx-dir", default="/root/tdx_data")
    p.add_argument("--membership-db", default="/root/project/workspace/capital-observer/data/capobs.db")
    p.add_argument("--out", default="output/research/e4_industry")
    args = p.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    events = pd.read_csv(args.events, dtype={"code": str})
    events["code"] = events.code.str.zfill(6)
    e = enrich(events, TdxStore(args.tdx_dir), load_membership(Path(args.membership_db)))
    e.to_csv(out / "enriched_events.csv", index=False)
    (out / "summary.json").write_text(json.dumps(summary(e), ensure_ascii=False, indent=2, default=str))
    print(json.dumps(summary(e), ensure_ascii=False, indent=2, default=str))

if __name__ == "__main__":
    main()
