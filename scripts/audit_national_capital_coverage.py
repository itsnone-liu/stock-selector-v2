#!/usr/bin/env python3
"""Deterministic stage report for national-capital history coverage."""
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; RAW=ROOT/'data/csr8_national_capital/raw/holdings'; OUT=ROOT/'output/research/csr/national_capital'
def main():
 metas=list(RAW.glob('*.meta.json')); success=[]; failed=[]
 for p in metas:
  x=json.loads(p.read_text()); (success if x.get('outcome')=='SUCCESS_NONEMPTY' else failed).append(x)
 norm=OUT/'national_holdings_pit.csv'; rows=list(csv.DictReader(norm.open())) if norm.exists() else []
 report={'raw_meta_files':len(metas),'success_nonempty':len(success),'failed_or_empty':len(failed),'normalized_rows':len(rows),'actor_matched_rows':sum(bool(x.get('actor_id')) for x in rows),'distinct_stocks':len({x.get('stock_code') for x in rows}),'distinct_report_periods':sorted({x.get('report_period') for x in rows}),'pit_available_rows':sum(x.get('pit_status')=='AVAILABLE_PIT' for x in rows),'publication_date_missing_rows':sum(not x.get('publication_date') or x.get('publication_date')=='UNKNOWN' for x in rows),'status':'PIT_READY_FOR_RESOLVED_ROWS'}
 OUT.mkdir(parents=True,exist_ok=True); (OUT/'national_capital_coverage_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
