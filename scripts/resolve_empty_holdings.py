#!/usr/bin/env python3
"""Classify explicit empty cells without inventing absence evidence.

This creates a machine-readable fallback ledger. Until an official fallback row is
captured, an empty structured response is UNAVAILABLE, never NOT_DISCLOSED_IN_TOP10.
"""
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/research/csr/national_capital'
def main():
 p=OUT/'holdings_coverage_ledger.csv'; rows=list(csv.DictReader(p.open()))
 for r in rows:
  if r['source_status']=='SUCCESS_EMPTY': r['resolution_status']='UNAVAILABLE'; r['absence_semantics']='UNKNOWN'; r['fallback_chain']='Eastmoney_EMPTY>official_fallback_not_yet_captured>UNAVAILABLE'
  elif r['source_status']=='SUCCESS_NONEMPTY': r['resolution_status']='RESOLVED_PRIMARY'; r['fallback_chain']='Eastmoney_STRUCTURED'
  else: r['resolution_status']='INCOMPLETE'; r['fallback_chain']='NOT_RUN'
 with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 report={'cells':len(rows),'unavailable_cells':sum(x['resolution_status']=='UNAVAILABLE' for x in rows),'not_disclosed_cells':0,'status':'MACHINE_CLASSIFIED_NO_ABSENCE_INFERENCE'}; (OUT/'empty_resolution_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
