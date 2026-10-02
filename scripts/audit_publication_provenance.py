#!/usr/bin/env python3
"""Verify every PIT holding row has one captured publication record and strict dates."""
import csv,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/research/csr/national_capital'; RAW=ROOT/'data/csr8_national_capital/raw/publication_dates'; CAL=ROOT/'output/research/csr/08_pilot_cases/phase_b/ingest_rt/frozen_exchange_calendar.csv'
def iso(x): return f'{x[:4]}-{x[4:6]}-{x[6:]}' if len(x)==8 and x.isdigit() else x
def main():
 pub={(x['stock_code'],x['report_period']):x for x in csv.DictReader((OUT/'publication_dates.csv').open())};cal=set(x.strip() for x in CAL.read_text().splitlines()[3:] if x.strip());rows=list(csv.DictReader((OUT/'national_holdings_pit.csv').open())); bad=[]
 for r in rows:
  p=pub.get((r['stock_code'],r['report_period'])); pd=iso(p.get('publication_date','')) if p else ''; ok=bool(p and pd and r['available_date']>pd and r['available_date'] in cal and p.get('publication_raw_sha256'))
  if ok:
   raw=RAW/(r['stock_code'].replace('.','_')+'.json'); ok=raw.exists() and hashlib.sha256(raw.read_bytes()).hexdigest()==p['publication_raw_sha256']
  if not ok:bad.append({'stock_code':r['stock_code'],'report_period':r['report_period']})
 report={'rows':len(rows),'bad_rows':len(bad),'source_grade':'SECONDARY_CAPTURED','status':'PASS' if not bad else 'FAIL','bad_sample':bad[:20]};(OUT/'publication_provenance_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if not bad else 1)
if __name__=='__main__':main()
