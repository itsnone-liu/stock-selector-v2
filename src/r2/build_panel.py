#!/usr/bin/env python3
"""R2 §14-18 support: monthly PIT panel with markup labels, streaming build."""
from __future__ import annotations
import argparse,gzip,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.capital_inference.features import snapshot
from src.capital_inference.state_engine import infer
D=ROOT/'data/cd/daily_fullmarket'; EXT=ROOT/'data/r2/market_ext'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',default=str(ROOT/'data/r2/panel_monthly.jsonl'));a=ap.parse_args()
 t0=time.time(); n=0
 with open(a.out,'w') as f:
  for p in sorted(D.glob('*.json.gz')):
   code=p.name[:-8]
   try: r=json.load(gzip.open(p,'rt'))
   except Exception: continue
   ds=r['dates']; cl=[float(x[2]) for x in r['qfq']]; hi=[float(x[3]) for x in r['qfq']]; lo=[float(x[4]) for x in r['qfq']]; vol=[float(x[5]) for x in r['unadj']]
   amt=None
   ep=EXT/f'{code}.json'
   if ep.exists():
    try:
     ex=json.loads(ep.read_text()); m={row['date']:row.get('amount') for row in ex['rows']}; amt=[m.get(d) for d in ds]
    except Exception: amt=None
   seen=set()
   for i in range(119,len(ds)):
    if ds[i][8:10]<'24' or ds[i][5:7]==ds[i-1][5:7] and i+1<len(ds) and ds[i+1][5:7]==ds[i][5:7]: pass
    if i+1<len(ds) and ds[i+1][5:7]!=ds[i][5:7]: pass
    # month-end bar: last bar of its month
    if i+1<len(ds) and ds[i+1][5:7]==ds[i][5:7]: continue
    ym=ds[i][:7]
    if ym in seen: continue
    seen.add(ym)
    f_=snapshot(cl,hi,lo,vol,amt,i)
    if f_ is None: continue
    # forward labels (never features): max ret within next 60/120/250 bars
    lab={}
    for name,w in (('f60',60),('f120',120),('f250',250)):
     seg=cl[i+1:min(len(cl),i+1+w)]
     lab[name]=round(max(seg)/cl[i]-1,4) if seg else None
    st=infer(f_)
    row={'stock':code,'ym':ym,'close':cl[i],**f_,**st,**lab}
    f.write(json.dumps(row,ensure_ascii=False)+'\n'); n+=1
 print(json.dumps({'rows':n,'secs':round(time.time()-t0,1)}))
if __name__=='__main__':main()
