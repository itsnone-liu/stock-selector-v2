#!/usr/bin/env python3
"""Materialize ETF available dates and raw SHA lineage from exchange raw metadata."""
import csv,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/research/csr/national_capital'; RAW=ROOT/'data/csr8_national_capital/raw/etf_shares'; CAL=ROOT/'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv'
def main():
 cal=sorted(x.strip() for x in CAL.read_text().splitlines()[3:] if x.strip()); rows=list(csv.DictReader((OUT/'etf_share_daily_sse.csv').open()))
 for r in rows:
  d=r['trade_date'][:10].replace('-',''); r['available_date']=next((x for x in cal if x.replace('-','')>d),'') or ('UNAVAILABLE_AFTER_CALENDAR' if d else ''); mp=RAW/(r['trade_date'][:10]+'.meta.json'); r['raw_sha256']=json.loads(mp.read_text()).get('sha256') if mp.exists() else ''
 with (OUT/'etf_share_daily_sse.csv').open('w',newline='') as f: w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 report={'rows':len(rows),'available_date_rows':sum(bool(x['available_date']) for x in rows),'raw_sha_rows':sum(bool(x['raw_sha256']) for x in rows),'status':'PASS' if all(x['available_date'] and x['raw_sha256'] for x in rows) else 'FAIL'}; (OUT/'etf_lineage_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
