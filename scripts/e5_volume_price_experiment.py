#!/usr/bin/env python3
"""E5：缩量上涨/加速上涨事件研究（预注册、非生产规则）。

缩量上涨 = 5日收益>0 且最近5日成交额均值 <= 前20日成交额中位数×0.8。
加速上涨 = 5日收益>0 且本5日收益 > 前5日收益（不额外挑阈值）。
两标签可同时成立；缺量/不足数据=unknown，不当作False。
"""
from __future__ import annotations
import argparse, json, sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
from stock_selector.data.tdx import TdxStore
from stock_selector.research.event_evaluation import deduplicate_events


def enrich(e, store):
    e=e.copy(); e["shrinking_up"]=pd.NA; e["accelerating_up"]=pd.NA
    for code, ix in e.groupby("code").groups.items():
        f=store.daily(str(code))
        if f is None: continue
        f=f.sort_index(); close=f["close"].astype(float)
        for j in ix:
            d=pd.Timestamp(e.at[j,"date"]); v=f.loc[:d]
            if len(v)<25: continue
            ret5=float(v.close.iloc[-1]/v.close.iloc[-6]-1)
            prev5=float(v.close.iloc[-6]/v.close.iloc[-11]-1) if len(v)>=11 else np.nan
            if "amount" not in v: continue
            cur5=float(v.amount.tail(5).mean()); prior20=float(v.amount.iloc[-25:-5].median())
            if prior20<=0: continue
            e.at[j,"shrinking_up"]=bool(ret5>0 and cur5/prior20<=.8)
            e.at[j,"accelerating_up"]=bool(ret5>0 and ret5>prev5)
            e.at[j,"volume_ratio_5_vs_prior20"]=cur5/prior20
            e.at[j,"ret5"]=ret5; e.at[j,"ret5_prev"]=prev5
    return e


def summarise(e):
    def agg(g):
        return pd.Series({"n":len(g),"fwd10_mean":g.fwd10.mean(),
          "fwd10_median":g.fwd10.median(),"demeaned_n":g.fwd10_industry_demeaned.notna().sum(),
          "demeaned_median":g.fwd10_industry_demeaned.median(),
          "positive_rate":(g.fwd10>0).mean()})
    out={"definitions":{"shrinking_up":"ret5>0 and mean(amount[-5:]) / median(amount[-25:-5]) <= 0.8",
      "accelerating_up":"ret5>0 and ret5 > previous ret5","missing":"unknown, not false"},
      "coverage":{"events":len(e),"shrinking_known":int(e.shrinking_up.notna().sum()),
      "accelerating_known":int(e.accelerating_up.notna().sum())}}
    for c in ["shrinking_up","accelerating_up"]:
        out[c]=e.groupby(c,dropna=False,observed=True).apply(agg,include_groups=False).reset_index().to_dict("records")
    if "half" in e:
        out["by_half"]={}
        for c in ["shrinking_up","accelerating_up"]:
            out["by_half"][c]=e.groupby(["half",c],dropna=False,observed=True).apply(agg,include_groups=False).reset_index().to_dict("records")
    return out


def main():
    p=argparse.ArgumentParser(); p.add_argument("--events",default="output/research/e4_industry_loo/enriched_events.csv"); p.add_argument("--tdx-dir",default="/root/tdx_data"); p.add_argument("--out",default="output/research/e5_volume_price"); p.add_argument("--dedup",action="store_true"); a=p.parse_args()
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True)
    e=pd.read_csv(a.events,dtype={"code":str}); e["code"]=e.code.str.zfill(6)
    if a.dedup:
        e=deduplicate_events(e.rename(columns={"date":"detection_at","label":"event_type"}),5).rename(columns={"detection_at":"date","event_type":"label"})
    e=enrich(e,TdxStore(a.tdx_dir)); e.to_csv(out/"events.csv",index=False)
    report=summarise(e); (out/"summary.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str)); print(json.dumps(report,ensure_ascii=False,indent=2,default=str))
if __name__=="__main__": main()
