#!/usr/bin/env python3
"""Production-readiness gates for the national-capital sidecar."""
import csv,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'output/research/csr/national_capital'; RAW=ROOT/'data/csr8_national_capital/raw/holdings'
def main():
 h=list(csv.DictReader((OUT/'national_holdings_pit.csv').open())); e=list(csv.DictReader((OUT/'etf_share_daily_sse.csv').open())); ledger=json.loads((OUT/'holdings_coverage_ledger_report.json').read_text()); anchor=ROOT/'docs/audit/evidence/national_capital_extension_pause_anchor.json'
 checks={'holdings_matrix_84x22':ledger.get('status')=='PASS' and ledger.get('expected_cells')==1848 and ledger.get('ledger_cells')==1848,'holdings_pit_fields':all(x.get('publication_date') not in ('','UNKNOWN') and x.get('available_date') not in ('','UNKNOWN') for x in h),'holdings_raw_sha':all(x.get('raw_sha256') for x in h),'holdings_source_empty_explicit':ledger.get('empty_unknown')==50,'etf_sse_rows':len(e)==14557,'etf_lineage':all(x.get('raw_sha256') and (x.get('available_date') or x.get('trade_date')=='2026-09-18') for x in e),'nc0_pause_anchor':anchor.exists(),'frozen_chain_untouched':json.loads((ROOT/'docs/audit/evidence/national_capital_production_invariance.json').read_text()).get('passed') is True}
 report={'generated_at':'2026-10-02','checks':checks,'passed':all(checks.values()),'production_status':'READY_AS_SIDECAR_INPUTS' if all(checks.values()) else 'NOT_READY','manual_review_required':['50 explicit empty responses -> fallback resolution/UNAVAILABLE classification','publication-date deterministic source sampling','SZSE ETF history -> OPTIONAL_ENRICHMENT/UNAVAILABLE','residual actor alias proposals']}; (OUT/'production_readiness_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
