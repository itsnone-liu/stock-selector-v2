#!/usr/bin/env python3
"""R2 §12-13: MARKUP_EPISODE_LIBRARY over 2021-2026 full market.

Streams daily_fullmarket per stock; identifies forward-max-return markup
episodes (labels only, never used as features); records episode fields and
pre-start (T-1) entry into the feature snapshot stage. Memory-light.
"""
from __future__ import annotations
import argparse,gzip,json,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; D=ROOT/'data/cd/daily_fullmarket'; OUT=ROOT/'data/r2'
THRESH=[('M60_50',60,0.50),('M120_100',120,1.00),('M250_200',250,2.00),('M250_300',250,3.00),('M250_500',250,5.00)]
MIN_OBS=120
def load(code):
 r=json.load(gzip.open(D/f'{code}.json.gz','rt'))
 ds=r['dates']; cl=[float(x[2]) for x in r['qfq']]
 return ds,cl
def episodes(code,ds,cl):
 """Anchor = last bar before forward window qualifying; dedupe by overlap."""
 n=len(cl); found=[]
 if n<MIN_OBS: return found
 for i in range(60,n-5):
  base=cl[i]
  if base<=0: continue
  fwd_max=0.; fwd_arg=i; j_end=min(n,i+251)
  best=i
  for j in range(i+1,j_end):
   if cl[j]>cl[best]: best=j
  run=cl[best]/base-1
  hit=None
  for name,win,thr in THRESH:
   if best-i<=win and run>=thr: hit=name  # keep strongest matched later
  if hit is None: continue
  # strongest threshold satisfied within its window
  strongest=None
  for name,win,thr in THRESH:
   if best-i<=win and run>=thr: strongest=name
  # skip if a previous episode peak is within 120 bars (same campaign)
  if found and i-found[-1]['i_peak']<120: continue
  # pre-drawdown: max drawdown over prior 250 bars
  lo=cl[max(0,i-250):i+1]; pre_hi=max(lo) if lo else base
  mdd=min((x/pre_hi-1) for x in lo) if lo else 0.0
  found.append({'i':i,'i_peak':best,'start':ds[i],'peak':ds[best],'end':ds[min(n-1,best+20)],'max_ret':round(run,4),'days_to_peak':best-i,'mdd_pre':round(mdd,4)})
 return found
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--out',default=str(OUT/'markup_episodes.jsonl'));a=ap.parse_args()
 t0=time.time(); OUT.mkdir(parents=True,exist_ok=True); n_ep=0; n_stk=0
 with open(a.out,'w') as f:
  for p in sorted(D.glob('*.json.gz')):
   code=p.name[:-8]
   try: ds,cl=load(code)
   except Exception: continue
   n_stk+=1
   for e in episodes(code,ds,cl):
    e['stock']=code; f.write(json.dumps(e,ensure_ascii=False)+'\n'); n_ep+=1
 print(json.dumps({'stocks':n_stk,'episodes':n_ep,'secs':round(time.time()-t0,1),'out':a.out}))
if __name__=='__main__':main()
