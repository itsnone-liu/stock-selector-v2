#!/usr/bin/env python3
"""Join verified publication dates and conservative PIT availability."""
import csv,json
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; IN=ROOT/'output/research/csr/national_capital/national_holdings_history.csv'; PUB=ROOT/'output/research/csr/national_capital/publication_dates.csv'; CAL=ROOT/'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv'; OUT=ROOT/'output/research/csr/national_capital/national_holdings_pit.csv'
def next_trade(d,cal):
 d=d.replace('-','')
 for x in cal:
  if x.replace('-','')>=d: return x
 return ''
def main():
 pub={(x['stock_code'],x['report_period']):x for x in csv.DictReader(PUB.open())}; cal=sorted(x.strip() for x in CAL.read_text().splitlines()[3:] if x.strip())
 rows=list(csv.DictReader(IN.open()))
 for r in rows:
  p=pub.get((r['stock_code'],r['report_period']))
  if p and p.get('publication_date'):
   r['publication_date']=p['publication_date']; r['available_date']=next_trade(p['publication_date'],cal); r['publication_source']=p['publication_source']; r['pit_status']='AVAILABLE_PIT'
  else: r['publication_date']='UNKNOWN'; r['available_date']='UNKNOWN'; r['publication_source']='UNKNOWN'; r['pit_status']='UNKNOWN_PUBLICATION_DATE'
 OUT.parent.mkdir(parents=True,exist_ok=True)
 fields=list(rows[0])
 with OUT.open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
 report={'rows':len(rows),'publication_date_resolved':sum(r['pit_status']=='AVAILABLE_PIT' for r in rows),'available_date_resolved':sum(bool(r.get('available_date') not in ('','UNKNOWN')) for r in rows),'status':'READY_WITH_CONSERVATIVE_NEXT_TRADING_DAY' if all(r['pit_status']=='AVAILABLE_PIT' for r in rows) else 'PARTIAL'}
 (OUT.parent/'publication_join_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
