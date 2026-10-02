#!/usr/bin/env python3
"""Collect report publication dates for the frozen 84 cases from Sina finance metadata."""
import argparse,hashlib,json,time
from datetime import datetime,timezone
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[1]; SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'; RAW=ROOT/'data/csr8_national_capital/raw/publication_dates'; OUT=ROOT/'output/research/csr/national_capital'; URL='https://quotes.sina.cn/cn/api/openapi.php/CompanyFinanceService.getFinanceReport2022'
PERIODS={f'{y}{m:02d}{d}':f'{y}-{m:02d}-{d}' for y in range(2021,2027) for m,d in ((3,31),(6,30),(9,30),(12,31)) if y<2026 or m<=6}
def now(): return datetime.now(timezone.utc).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()
def codes():
 d=json.loads(SAMPLE.read_text()); return sorted({x['code'] for g in d['groups'].values() for x in g['chosen']})
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--sleep',type=float,default=.1); a=ap.parse_args(); RAW.mkdir(parents=True,exist_ok=True); s=requests.Session(); s.headers['User-Agent']='Mozilla/5.0'; stats={}
 for code in codes():
  bare=code.split('.')[1]; m='sh' if code.startswith('sh.') else 'sz'; stem=code.replace('.','_'); fp=RAW/(stem+'.json'); mp=RAW/(stem+'.meta.json')
  if fp.exists() and mp.exists(): stats['SKIP']=stats.get('SKIP',0)+1; continue
  params={'paperCode':m+bare,'source':'fzb','type':'0','page':'1','num':'1000'}; started=now()
  try:
   r=s.get(URL,params=params,timeout=60); j=r.json(); raw=json.dumps(j,ensure_ascii=False,separators=(',',':')).encode(); fp.write_bytes(raw); out='SUCCESS_NONEMPTY' if j.get('result',{}).get('data',{}).get('report_list') else 'SUCCESS_EMPTY'; mp.write_text(json.dumps({'retrieved_at':started,'outcome':out,'sha256':sha(raw),'endpoint':URL,'request':params,'source':'Sina CompanyFinanceService','stock_code':code},ensure_ascii=False,indent=2)+'\n'); stats[out]=stats.get(out,0)+1
  except Exception as e: mp.write_text(json.dumps({'retrieved_at':started,'outcome':'FAILED','error':f'{type(e).__name__}: {e}','endpoint':URL,'request':params},ensure_ascii=False,indent=2)+'\n'); stats['FAILED']=stats.get('FAILED',0)+1
  time.sleep(a.sleep)
 rows=[]
 for fp in RAW.glob('*.json'):
  if fp.name.endswith('.meta.json'): continue
  try: j=json.loads(fp.read_text()); code=fp.stem; code=code.replace('_','.');
  except: continue
  for period,v in (j.get('result',{}).get('data',{}).get('report_list') or {}).items():
   if period in PERIODS: rows.append({'stock_code':code,'report_period':PERIODS[period],'publication_date':str(v.get('publish_date') or '')[:10],'publication_source':'Sina CompanyFinanceService','publication_raw_sha256':sha(fp.read_bytes())})
 import csv
 path=OUT/'publication_dates.csv'; fields=['stock_code','report_period','publication_date','publication_source','publication_raw_sha256']
 with path.open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
 report={'generated_at':now(),'stats':stats,'rows':len(rows),'codes':len(codes()),'periods':len(PERIODS)}; (OUT/'publication_dates_manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
