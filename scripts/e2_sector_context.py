#!/usr/bin/env python3
"""E2：将行业两融背景作为标签加入事件，不限制交易、不自动切换规则。

严格PIT：事件T 15:05只能使用 available_at<=T 15:05 的行业事实，故通常
使用T-1融资余额；同一行业融资余额20日变化和全市场占比仅作背景标签。
"""
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
import numpy as np
import pandas as pd


def load_margin(db: Path) -> pd.DataFrame:
    q = """select subject_key as industry, effective_at as margin_date,
                   metric, value, available_at
            from fact_observation
            where source_id='exchange.margin_detail_sw_l1'
              and metric in ('margin_balance','margin_buy')
              and quality_status not in ('failed','stale')"""
    d = pd.read_sql(q, sqlite3.connect(db))
    d["margin_date"] = pd.to_datetime(d.margin_date)
    d["available_ts"] = pd.to_datetime(d.available_at)
    return d


def attach(events: pd.DataFrame, margin: pd.DataFrame) -> pd.DataFrame:
    e = events.copy()
    margin = margin.copy()
    if "available_ts" not in margin:
        margin["available_ts"] = pd.to_datetime(margin["available_at"])
    e["event_ts"] = pd.to_datetime(e["date"]) + pd.Timedelta(hours=15, minutes=5)
    e["industry_margin_date"] = pd.NaT
    e["margin_balance"] = np.nan
    e["margin_buy"] = np.nan
    e["margin_balance_chg20"] = np.nan
    e["margin_share"] = np.nan
    if margin.empty:
        return e
    # 每个事实在其 available_at 后才可用于事件；先构造行业日表，再逐事件as-of取值。
    for industry, ix in e.groupby("industry", dropna=True).groups.items():
        m = margin[margin.industry == industry]
        bal = m[m.metric == "margin_balance"].sort_values("available_ts")
        buy = m[m.metric == "margin_buy"].sort_values("available_ts")
        if bal.empty:
            continue
        for j in ix:
            t = e.at[j, "event_ts"]
            b = bal[bal.available_ts <= t]
            q = buy[buy.available_ts <= t]
            if b.empty:
                continue
            cur = b.iloc[-1]
            e.at[j, "industry_margin_date"] = cur.margin_date
            e.at[j, "margin_balance"] = cur.value
            if len(b) >= 21:
                e.at[j, "margin_balance_chg20"] = cur.value / b.iloc[-21].value - 1
            if not q.empty:
                e.at[j, "margin_buy"] = q.iloc[-1].value
    # 同一可得时点附近的行业融资余额占比；只在已有标签之间计算，避免跨期混合。
    for date, ix in e.groupby("industry_margin_date", dropna=True).groups.items():
        available = e.loc[ix, ["industry", "margin_balance"]].drop_duplicates("industry")
        total = available["margin_balance"].sum()
        if total > 0:
            shares = available.set_index("industry")["margin_balance"] / total
            e.loc[ix, "margin_share"] = e.loc[ix, "industry"].map(shares)
    e["margin_context_known"] = e.margin_balance.notna()
    e["margin_balance_bin"] = pd.qcut(e.margin_balance, 4, labels=["q1","q2","q3","q4"], duplicates="drop")
    e["margin_chg20_bin"] = pd.cut(e.margin_balance_chg20,
        [-np.inf, -.1, 0, .1, np.inf], labels=["<-10%","-10~0","0~10%",">10%"])
    return e


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--events", default="output/research/e4_industry_loo/enriched_events.csv")
    p.add_argument("--margin-db", default="/root/project/workspace/capital-observer/data/capobs.db")
    p.add_argument("--out", default="output/research/e2_sector_context")
    a=p.parse_args(); out=Path(a.out); out.mkdir(parents=True, exist_ok=True)
    e=attach(pd.read_csv(a.events, dtype={"code":str}), load_margin(Path(a.margin_db)))
    e.to_csv(out/"events_with_context.csv", index=False)
    report={"pit_rule":"available_at <= event_date 15:05; normally T-1 margin fact",
            "events":len(e), "industry_known":int(e.industry.notna().sum()),
            "margin_context_known":int(e.margin_context_known.sum()),
            "margin_unknown":int((~e.margin_context_known).sum()),
            "no_trade_restriction":True}
    (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
