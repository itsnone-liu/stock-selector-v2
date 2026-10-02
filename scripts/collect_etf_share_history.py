#!/usr/bin/env python3
"""Collect PIT-safe ETF total shares from exchange source.

SSE supports historical STAT_DATE queries. SZSE's public endpoint is current-only
in the verified interface, so SZSE rows are not fabricated; a coverage report records
that gap for a later historical archive source.
"""
from __future__ import annotations
import argparse, hashlib, json, time
from datetime import datetime, timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/research/csr/national_capital'; RAW=ROOT/'data/csr8_national_capital/raw/etf_shares'; TRACK=Path('/tmp/national-team-holdings-tracker-verify/data.json')
SSE='https://query.sse.com.cn/commonQuery.do'; SQL='COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L'
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--start',default='2021-03-01'); ap.add_argument('--end',default='2026-09-30'); ap.add_argument('--sleep',type=float,default=.12); a=ap.parse_args()
 d=json.loads(TRACK.read_text()); targets=[x for x in d['etf_data'] if x['code'].startswith('5') or x['code'].startswith('58')]; codes=sorted({x['code'] for x in targets}); RAW.mkdir(parents=True,exist_ok=True); OUT.mkdir(parents=True,exist_ok=True)
 # Use frozen project calendar when present; otherwise business-day probe dates.
 cal=ROOT/'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv'; dates=[]
 if cal.exists(): dates=[x.strip() for x in cal.read_text().splitlines()[3:] if x.strip() and a.start<=x.strip()<=a.end]
 else:
  import pandas as pd; dates=[x.strftime('%Y-%m-%d') for x in pd.bdate_range(a.start,a.end)]
 s=requests.Session(); s.headers.update({'Referer':'https://www.sse.com.cn/','User-Agent':'Mozilla/5.0'})
 rows=[]; stats={}
 for i,day in enumerate(dates,1):
  stem=day; fp=RAW/f'{stem}.json'; mp=RAW/f'{stem}.meta.json'
  if fp.exists() and mp.exists():
   try: rec=json.loads(fp.read_text()); rows.extend(rec.get('result',[])); stats['SKIP']=stats.get('SKIP',0)+1; continue
   except: pass
  params={'isPagination':'true','pageHelp.pageSize':'10000','pageHelp.pageNo':'1','pageHelp.beginPage':'1','pageHelp.cacheSize':'1','pageHelp.endPage':'1','sqlId':SQL,'STAT_DATE':day}
  try:
   r=s.get(SSE,params=params,timeout=30); body=r.content; j=r.json(); outcome='SUCCESS_NONEMPTY' if j.get('result') else 'SUCCESS_EMPTY'; fp.write_bytes(json.dumps(j,ensure_ascii=False,separators=(',',':')).encode()); mp.write_text(json.dumps({'retrieved_at':now(),'outcome':outcome,'sha256':sha(fp.read_bytes()),'endpoint':SSE,'request':params,'source':'SSE ETF scale','available_date':None},ensure_ascii=False,indent=2)+'\n'); rows.extend(j.get('result') or []); stats[outcome]=stats.get(outcome,0)+1
  except Exception as e:
   mp.write_text(json.dumps({'retrieved_at':now(),'outcome':'FAILED','error':f'{type(e).__name__}: {e}','endpoint':SSE,'request':params},ensure_ascii=False,indent=2)+'\n'); stats['FAILED']=stats.get('FAILED',0)+1
  if i%20==0: print(i,'/',len(dates),stats,flush=True)
  time.sleep(a.sleep)
 # retain only tracked codes and normalize source rows; available is conservative next trading day, filled later by calendar join
 norm=[]
 for x in rows:
  code=str(x.get('SEC_CODE','')).zfill(6)
  if code not in codes: continue
  norm.append({'etf_code':code,'trade_date':x.get('STAT_DATE'),'total_shares':x.get('TOT_VOL'),'available_date':None,'source':'SSE_ETF_SCALE','raw_sha256':None})
 path=OUT/'etf_share_daily_sse.csv'; import csv
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=norm[0].keys() if norm else ['etf_code','trade_date','total_shares','available_date','source','raw_sha256']); w.writeheader(); w.writerows(norm)
 man={'generated_at':now(),'exchange':'SSE','tracked_codes':codes,'date_count':len(dates),'rows':len(norm),'stats':stats,'pit_note':'available_date requires next-trading-day join; SZSE historical source not included'}; (OUT/'etf_share_coverage.json').write_text(json.dumps(man,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(man,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
