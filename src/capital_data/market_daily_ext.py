#!/usr/bin/env python3
"""R2-0 market daily extension: amount / turnover_rate / free-float history.

Appends per-stock extended daily bars (amount, turnover) via akshare
stock_zh_a_hist (adjust='') beside the existing qfq bars. Append-only,
resumable, provenance-meta per file. Pilot with --limit; full run in batches.
"""
from __future__ import annotations
import argparse,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'data/r2/market_ext'
import akshare as ak

def fetch(code:str, start:str, end:str):
 sym=('sh' if code.startswith('6') else 'sz')+code
 df=ak.stock_zh_a_daily(symbol=sym,start_date=start,end_date=end)
 rows=[]
 for _,r in df.iterrows():
  def g(k):
   v=r[k] if k in r else None
   return None if v is None or v!=v else float(v)
  rows.append({'date':str(r['date'])[:10],'open':g('open'),'close':g('close'),'high':g('high'),'low':g('low'),'volume':g('volume'),'amount':g('amount'),'outstanding_share':g('outstanding_share'),'turnover_rate':g('turnover')})
 return rows

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--limit',type=int,default=20);ap.add_argument('--start',default='20210101');ap.add_argument('--end',default='20260930');a=ap.parse_args()
 import gzip
 codes=sorted(p.name[:-8] for p in (ROOT/'data/cd/daily_fullmarket').glob('*.json.gz'))[:a.limit]
 OUT.mkdir(parents=True,exist_ok=True); ok=0; fails=[]
 for i,code in enumerate(codes):
  dst=OUT/f'{code}.json'
  if dst.exists(): ok+=1; continue
  try:
   rows=fetch(code,a.start,a.end)
   meta={'code':code,'source':'akshare:stock_zh_a_daily(sina)','fetched_at':time.strftime('%Y-%m-%dT%H:%M:%SZ'),'start':a.start,'end':a.end,'n':len(rows)}
   dst.write_text(json.dumps({'meta':meta,'rows':rows},ensure_ascii=False)); ok+=1
   if i%5==0: print(f'{i+1}/{len(codes)} {code} {len(rows)} rows',flush=True)
  except Exception as e:
   fails.append({'code':code,'error':str(e)[:200]})
  time.sleep(0.4)
 print(json.dumps({'ok':ok,'fails':len(fails),'fail_sample':fails[:5]},ensure_ascii=False))
if __name__=='__main__':main()
