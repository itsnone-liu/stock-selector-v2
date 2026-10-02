#!/usr/bin/env python3
"""Materialize ETF PIT availability and byte-verified raw lineage."""
import csv,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/research/csr/national_capital'; RAW=ROOT/'data/csr8_national_capital/raw/etf_shares'; CAL=ROOT/'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv'
def main():
 cal=sorted(x.strip() for x in CAL.read_text().splitlines()[3:] if x.strip()); rows=list(csv.DictReader((OUT/'etf_share_daily_sse.csv').open()))
 for r in rows:
  d=r['trade_date'][:10].replace('-',''); nxt=next((x for x in cal if x.replace('-','')>d),''); r['available_date']=nxt; r['availability_status']='AVAILABLE_PIT' if nxt else 'OUTSIDE_FROZEN_CALENDAR'; mp=RAW/(r['trade_date'][:10]+'.meta.json'); raw=RAW/(r['trade_date'][:10]+'.json'); meta=json.loads(mp.read_text()) if mp.exists() else {}; r['raw_sha256']=hashlib.sha256(raw.read_bytes()).hexdigest() if raw.exists() else ''; r['raw_sha_verified']=bool(raw.exists() and r['raw_sha256']==meta.get('sha256'))
 with (OUT/'etf_share_daily_sse.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 eligible=[x for x in rows if x['availability_status']=='AVAILABLE_PIT']; report={'rows':len(rows),'available_date_rows':sum(bool(x['available_date']) for x in rows),'tail_rows':sum(x['availability_status']=='OUTSIDE_FROZEN_CALENDAR' for x in rows),'raw_sha_rows':sum(x['raw_sha_verified'] for x in rows),'status':'PASS' if all(x['raw_sha_verified'] and (x['availability_status']=='AVAILABLE_PIT' or x['availability_status']=='OUTSIDE_FROZEN_CALENDAR') for x in rows) else 'FAIL','context_eligible_rows':len(eligible)};(OUT/'etf_lineage_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
