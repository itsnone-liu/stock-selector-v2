#!/usr/bin/env python3
"""E6：近期VWAP与事件后短/中期风险（研究，不改变交易规则）。

固定分层：事件收盘相对5/10/20日VWAP <=-5%、[-5%,5%]、>=5%。
主窗口1/3/30日；10日仅辅助。VWAP按TDX量额单位换算100股/手。
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from stock_selector.data.tdx import TdxStore


def enrich(e, store):
    e=e.copy()
    for w in (5,10,20): e[f"price_to_vwap_{w}d"] = np.nan
    for h in ("fwd1","fwd3","fwd30","mae3","mfe3","mae30","mfe30"): e[h]=np.nan
    for code, ix in e.groupby("code").groups.items():
        f=store.daily(str(code))
        if f is None: continue
        f=f.sort_index()
        for j in ix:
            d=pd.Timestamp(e.at[j,"date"]); v=f.loc[:d]
            if len(v)<21 or "amount" not in v or "volume" not in v: continue
            for w in (5,10,20):
                x=v.tail(w); vol=x.volume.sum()
                if len(x)==w and vol>0:
                    vw=x.amount.sum()/vol/100.0
                    e.at[j,f"price_to_vwap_{w}d"]=float(v.close.iloc[-1]/vw-1)
            pos=f.index.searchsorted(d)+1
            if pos>=len(f): continue
            entry=float(f.iloc[pos].open)
            for h in (1,3,30):
                x=f.iloc[pos:pos+h]
                if len(x)>=h: e.at[j,f"fwd{h}"]=float(x.iloc[h-1].close/entry-1)
            x=f.iloc[pos:pos+3]
            if len(x): e.at[j,"mae3"]=float(x.low.min()/entry-1); e.at[j,"mfe3"]=float(x.high.max()/entry-1)
            x=f.iloc[pos:pos+30]
            if len(x): e.at[j,"mae30"]=float(x.low.min()/entry-1); e.at[j,"mfe30"]=float(x.high.max()/entry-1)
    for w in (5,10,20):
        e[f"vwap_bin_{w}d"]=pd.cut(e[f"price_to_vwap_{w}d"],[-np.inf,-.05,.05,np.inf],labels=["below_-5%","within_5%","above_5%"])
    return e


def summarize(e):
    def agg(g):
        return pd.Series({"n":len(g), **{f"{h}_median":g[h].median() for h in ("fwd1","fwd3","fwd30","mae3","mfe3","mae30","mfe30")},
            "fwd1_positive_rate":(g.fwd1>0).mean(),"fwd3_positive_rate":(g.fwd3>0).mean(),"fwd30_positive_rate":(g.fwd30>0).mean()})
    out={"definitions":{"vwap":"sum(amount)/sum(volume)/100","bins":"<=-5%, [-5%,5%], >=5%"},"events":len(e)}
    for w in (5,10,20): out[f"vwap_{w}d"]=e.groupby(f"vwap_bin_{w}d",dropna=False,observed=True).apply(agg,include_groups=False).reset_index().to_dict("records")
    return out

def main():
    p=argparse.ArgumentParser(); p.add_argument("--events",default="output/research/e5_horizon/events.csv"); p.add_argument("--tdx-dir",default="/root/tdx_data"); p.add_argument("--out",default="output/research/e6_vwap"); a=p.parse_args()
    out=Path(a.out); out.mkdir(parents=True,exist_ok=True); e=pd.read_csv(a.events,dtype={"code":str}); e.code=e.code.str.zfill(6)
    e=enrich(e,TdxStore(a.tdx_dir)); e.to_csv(out/"events.csv",index=False); r=summarize(e); (out/"summary.json").write_text(json.dumps(r,ensure_ascii=False,indent=2,default=str)); print(json.dumps(r,ensure_ascii=False,indent=2,default=str))
if __name__=="__main__": main()
