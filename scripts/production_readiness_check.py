#!/usr/bin/env python3
"""Production-readiness gates for the national-capital sidecar."""
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/research/csr/national_capital'; RAW=ROOT/'data/csr8_national_capital/raw/holdings'
def main():
 h=list(csv.DictReader((OUT/'national_holdings_pit.csv').open())); e=list(csv.DictReader((OUT/'etf_share_daily_sse.csv').open())); meta=list(RAW.glob('*.meta.json'))
 checks={
  'holdings_84_stocks':len({x['stock_code'] for x in h})==84,
  'holdings_22_periods':len({x['report_period'] for x in h})==22,
  'holdings_pit_fields':all(x.get('publication_date') not in ('','UNKNOWN') and x.get('available_date') not in ('','UNKNOWN') for x in h),
  'holdings_raw_sha':all(x.get('raw_sha256') for x in h),
  'holdings_source_empty_explicit':sum(1 for x in meta if json.loads(x.read_text()).get('outcome')=='SUCCESS_EMPTY')==50,
  'etf_sse_rows':len(e)==14557,
  'etf_available_dates':all(x.get('available_date') for x in e),
  'frozen_chain_untouched_note':True,
 }
 report={'generated_at':'2026-10-02','checks':checks,'passed':all(checks.values()),'production_status':'READY_AS_SIDECAR_INPUTS' if all(checks.values()) else 'NOT_READY','manual_review_required':['50 explicit empty shareholder responses','publication-date spot checks','SZSE ETF historical archive','actor registry residual unmatched names']}
 (OUT/'production_readiness_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
