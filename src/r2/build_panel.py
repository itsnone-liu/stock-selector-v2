#!/usr/bin/env python3
"""R2 §14-18 support: monthly PIT panel with markup labels, streaming build."""
from __future__ import annotations
import argparse,gzip,json,sqlite3,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.capital_inference.features import snapshot
from src.capital_inference.state_engine import infer
def load_holders():
 H={}
 for f in sorted((ROOT/'data/r2/holders').glob('*.json')):
  for row in json.loads(f.read_text())['rows']:
   H.setdefault(row['code'],[]).append((row['chg_date'],row.get('holders_chg_pct'),row.get('avg_hold')))
 for c in H: H[c].sort()
 return H
D=ROOT/'data/cd/daily_fullmarket'; EXT=ROOT/'data/r2/market_ext'
def _avail(chg_date,asof):
 from datetime import date
 y,m,d=int(chg_date[:4]),int(chg_date[5:7]),int(chg_date[8:10])
 ay,am,ad=int(asof[:4]),int(asof[5:7]),int(asof[8:10])
 return (date(ay,am,ad)-date(y,m,d)).days>=60

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',default=str(ROOT/'data/r2/panel_monthly.jsonl'));a=ap.parse_args()
 t0=time.time(); n=0; H=load_holders()
 e5=sqlite3.connect(str(ROOT/'data/r2/e5/e5.db'))
 def e5_feats(code,ds,i):
  out={'margin_chg20':None,'lhb_inst_net60':None,'lhb_events60':0,'block_amt60':None}
  win=[d.replace('-','') for d in ds[max(0,i-59):i+1]]
  lo,hi=win[0],win[-1]
  mg=e5.execute('SELECT date,rzye FROM margin WHERE code=? AND date<=? ORDER BY date DESC LIMIT 40',(code,hi)).fetchall()
  if len(mg)>=21 and mg[0][1] and mg[20][1]:
   out['margin_chg20']=round(mg[0][1]/mg[20][1]-1,4)
  lh=e5.execute('SELECT date,inst_net FROM lhb WHERE code=? AND date BETWEEN ? AND ?',(code,lo,hi)).fetchall()
  if lh:
   out['lhb_events60']=len(lh); out['lhb_inst_net60']=round(sum(x[1] or 0 for x in lh)/1e8,4)
  bl=e5.execute('SELECT amount FROM block WHERE code=? AND date BETWEEN ? AND ?',(code,lo,hi)).fetchall()
  if bl: out['block_amt60']=round(sum(x[0] or 0 for x in bl)/1e8,4)
  return out
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
    e4=None; e4b=None
    hs=H.get(code,[])
    ok=[h for h in hs if h[0] and (h[0][:7]<=ds[i][:7] and _avail(h[0],ds[i]))]
    if ok:
     e4=ok[-1][1]; e4b=sum((x[1] or 0) for x in ok[-2:])/min(2,len(ok))
    f_['holders_chg_pct']=e4; f_['holders_chg2_pct']=e4b if e4b is not None else None
    f_.update(e5_feats(code,ds,i))
    st=infer(f_)
    row={'stock':code,'ym':ym,'close':cl[i],**f_,**st,**lab}
    f.write(json.dumps(row,ensure_ascii=False)+'\n'); n+=1
 print(json.dumps({'rows':n,'secs':round(time.time()-t0,1)}))
if __name__=='__main__':main()
