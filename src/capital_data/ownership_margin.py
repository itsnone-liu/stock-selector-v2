#!/usr/bin/env python3
"""R2-0 E4: holder-count history via cninfo (per report date, full market).
E5: SSE+SZSE market margin balance history. Append-only, provenance meta.
"""
from __future__ import annotations
import argparse,json,time
from pathlib import Path
import akshare as ak
ROOT=Path(__file__).resolve().parents[2]; O4=ROOT/'data/r2/holders'; O5=ROOT/'data/r2/margin'
QDATES=[f'{y}{md}' for y in range(2021,2027) for md in ('0331','0630','0930','1231') if f'{y}{md}'<='20260930']
def holders():
 O4.mkdir(parents=True,exist_ok=True); ok=[];fail=[]
 for d in QDATES:
  dst=O4/f'{d}.json'
  if dst.exists(): ok.append(d); continue
  try:
   df=ak.stock_hold_num_cninfo(date=d)
   rows=[{'code':str(r['证券代码']).zfill(6),'name':r['证券简称'],'chg_date':str(r['变动日期']),'holders':r['本期股东人数'],'holders_prev':r['上期股东人数'],'holders_chg_pct':r['股东人数增幅'],'avg_hold':r['本期人均持股数量'],'avg_hold_prev':r['上期人均持股数量']} for _,r in df.iterrows()]
   meta={'source':'cninfo:stock_hold_num_cninfo','fetched_at':time.strftime('%Y-%m-%dT%H:%M:%SZ'),'report_date':d,'n':len(rows)}
   dst.write_text(json.dumps({'meta':meta,'rows':rows},ensure_ascii=False)); ok.append(d)
   print(d,len(rows),flush=True); time.sleep(1)
  except Exception as e:
   fail.append({'date':d,'error':str(e)[:120]})
 print(json.dumps({'ok':len(ok),'fail':fail}))
def margin():
 O5.mkdir(parents=True,exist_ok=True); ok=0
 for y in range(2021,2027):
  dst=O5/f'sse_{y}.json'
  if dst.exists(): ok+=1; continue
  try:
   df=ak.stock_margin_sse(start_date=f'{y}0101',end_date=f'{y}1231')
   rows=[{'date':str(r['信用交易日期']),'rzye':float(r['融资余额']),'rzbuy':float(r['融资买入额'])} for _,r in df.iterrows()]
   dst.write_text(json.dumps({'meta':{'source':'sse:stock_margin_sse','year':y,'n':len(rows)},'rows':rows},ensure_ascii=False)); ok+=1
   print('sse',y,len(rows),flush=True); time.sleep(1)
  except Exception as e:
   print('FAIL sse',y,str(e)[:80],flush=True)
 for y in range(2021,2027):
  dst=O5/f'szse_{y}.json'
  if dst.exists(): continue
  try:
   df=ak.stock_margin_szse(start_date=f'{y}-01-01',end_date=f'{y}-12-31') if hasattr(ak,'stock_margin_szse') else None
   if df is None or len(df)==0: continue
   rows=[{'date':str(r.iloc[0]),'rzye':float(r.iloc[1])} for _,r in df.iterrows()]
   dst.write_text(json.dumps({'meta':{'source':'szse:stock_margin_szse','year':y,'n':len(rows)},'rows':rows},ensure_ascii=False)); ok+=1
   print('szse',y,len(rows),flush=True); time.sleep(1)
  except Exception as e:
   print('FAIL szse',y,str(e)[:80],flush=True)
 print('margin files ok',ok)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('--what',default='all');a=ap.parse_args()
 if a.what in('all','holders'): holders()
 if a.what in('all','margin'): margin()
