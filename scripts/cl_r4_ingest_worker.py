#!/usr/bin/env python3
"""CL-R4 G1 ingestion: baostock 5m bars for the frozen 84-stock sample.
Run with: PYTHONPATH=/tmp/bspy python3 scripts/cl_r4_ingest_5m.py
Stores per-stock {six}.json.gz; validates sum(5m amount) vs daily amount
(fail-closed flags); writes ingestion census. No outcome variables."""
import gzip,json,sys,time
from pathlib import Path
from statistics import median
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'
SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
OUTDIR=ROOT/'data/cl_radar/r4_opening/per_stock'
CEN=ROOT/'data/cl_radar/r4_opening/ingestion_census.json'
YEARS=(2021,2022,2023,2024,2025,2026)
def q(bs,code,sd,ed):
 for attempt in range(4):
  try:
   rs=bs.query_history_k_data_plus(code,"date,time,open,high,low,close,volume,amount",start_date=sd,end_date=ed,frequency="5",adjustflag="3")
   if rs.error_code!='0':
    time.sleep(2+attempt*3);continue
   rows=[]
   while rs.next():rows.append(rs.get_row_data())
   return rows
  except Exception as e:
   print('retry',code,sd,attempt,type(e).__name__,str(e)[:80],flush=True);time.sleep(3+attempt*3)
 return None
def valid(path):
 try:
  json.load(gzip.open(path,'rt'));return True
 except Exception:return False
def main():
 import baostock as bs
 shard=int(sys.argv[1]) if len(sys.argv)>1 else 0;nsh=int(sys.argv[2]) if len(sys.argv)>2 else 1
 lg=bs.login()
 if lg.error_code!='0':print('LOGIN FAIL',lg.error_msg);sys.exit(1)
 x=json.load(open(SAMPLE));cs=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 OUTDIR.mkdir(parents=True,exist_ok=True)
 census={'n_stocks':len(cs),'stocks':{}}
 tot_days=tot_ok=tot_none=tot_short=tot_mismatch=tot_oneprice=0
 ratios=[]
 cs=[c for k,c in enumerate(cs) if k%nsh==shard]
 for i,code in enumerate(cs):
  six=code.split('.')[1]
  if valid(OUTDIR/f'{six}.json.gz'):
   print(f'[w{shard}] skip {code}',flush=True);continue
  six=code.split('.')[1];bscode=code
  bars={};dead=0
  for yr in YEARS:
   rows=q(bs,bscode,f'{yr}-01-01',f'{yr}-12-31')
   if rows is None:dead+=1;continue
   for r in rows:
    d=r[0];tm=r[1][8:12] if len(r[1])>=12 else ''
    try:bar=[tm,float(r[2]),float(r[3]),float(r[4]),float(r[5]),float(r[6] or 0),float(r[7] or 0)]
    except (ValueError,TypeError):continue
    if bar[6]<=0:continue  # amount must be positive (unit: yuan)
    bars.setdefault(d,[]).append(bar)
  rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
  days=rec['dates'];idx={d:k for k,d in enumerate(days)}
  keep=[];st={'n_daily_days':len(days),'n_ok':0,'n_no_minute':0,'n_short_bars':0,'n_amount_mismatch':0,'n_oneprice':0,'first_ok':None}
  for d in days:
   bd=bars.get(d)
   if not bd:st['n_no_minute']+=1;keep.append(None);tot_none+=1;tot_days+=1;continue
   sa=sum(b[6] for b in bd);da=float(ext.get(d,{}).get('amount') or 0)
   ratio=sa/da if da>0 else None
   if ratio is not None:ratios.append(ratio)
   fl='OK'
   if len(bd)!=48:fl='SHORT_BARS';st['n_short_bars']+=1;tot_short+=1
   elif ratio is None or not(0.95<=ratio<=1.05):fl='AMOUNT_MISMATCH';st['n_amount_mismatch']+=1;tot_mismatch+=1
   else:
    st['n_ok']+=1;tot_ok+=1
    if st['first_ok'] is None:st['first_ok']=d
    one=all(abs(b[2]-b[3])<1e-9 for b in bd if b[2]>0 and b[3]>0)
    if one:st['n_oneprice']+=1;tot_oneprice+=1
   keep.append([fl,bd] if fl=='OK' else None)
  dates_out=[days[k] for k in range(len(days)) if keep[k] is not None]
  bars_out=[keep[k][1] for k in range(len(days)) if keep[k] is not None]
  with gzip.open(OUTDIR/f'{six}.json.gz','wt') as f:
   json.dump({'code':code,'dates':dates_out,'bars':bars_out},f,separators=(',',':'))
  st['n_ok']=len(dates_out);st['support_frac']=st['n_ok']/max(1,len(days));st['dead_chunks']=dead
  census['stocks'][six]=st
  print(f'[w{shard}] {i+1}/{len(cs)} {code} ok={st["n_ok"]} none={st["n_no_minute"]} short={st["n_short_bars"]} mism={st["n_amount_mismatch"]}',flush=True)
 bs.logout()
 census['total']={'daily_stock_days':sum(v['n_daily_days'] for v in census['stocks'].values()),'ok':tot_ok,'no_minute':tot_none,'short_bars':tot_short,'amount_mismatch':tot_mismatch,'one_price_days':tot_oneprice,
  'ratio_median':median(ratios) if ratios else None,'ratio_p05':sorted(ratios)[int(.05*len(ratios))] if ratios else None,'ratio_p95':sorted(ratios)[int(.95*len(ratios))] if ratios else None,
  'n_ratio_obs':len(ratios)}
 census['g1_verdict']='SUFFICIENT_SUPPORT' if tot_ok>=0.85*sum(v['n_daily_days'] for v in census['stocks'].values()) else 'INSUFFICIENT_SUPPORT_REVIEW'
 CSP=ROOT/f'data/cl_radar/r4_opening/ingestion_census_w{shard}.json'
 CSP.write_text(json.dumps(census,ensure_ascii=False,indent=2))
 t=census['total']
 print(json.dumps({k:t[k] for k in ('daily_stock_days','ok','no_minute','short_bars','amount_mismatch','one_price_days','ratio_median','n_ratio_obs')},indent=2))
 print('G1 verdict:',census['g1_verdict'])
if __name__=='__main__':main()
