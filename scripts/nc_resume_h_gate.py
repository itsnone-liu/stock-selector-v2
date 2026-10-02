#!/usr/bin/env python3
"""Read-only resume gate. Requires an independent NC_FINAL approval marker."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/audit/evidence';CSR=ROOT/'data/csr8_phase_c/production/c4-prod-0002'
def main():
 inv=json.loads((OUT/'national_capital_production_invariance.json').read_text()); audit=json.loads((OUT/'national_capital_context_extension_final_audit.json').read_text()); frozen=OUT/'national_capital_context_extension_frozen.json'; checks={'freeze_marker_valid':frozen.exists(),'independent_approve':False,'nc0_invariance':inv.get('passed') is True,'audit_complete':audit.get('state')=='PREREQUISITES_COMPLETE','chain_still_paused':len([x for x in (CSR/'sealing/sealing_log.jsonl').read_text().splitlines() if x.strip()])==6,'candidate_prefix_3':inv['checks'].get('candidate_prefix_unchanged') is True}; report={'state':'READY_FOR_ORDINAL_4' if all(checks.values()) else 'BLOCKED','ordinal':4,'evidence_profile':'BASE_V1+NATIONAL_CTX_V1','checks':checks,'mutation':'NONE'};print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report['state']=='READY_FOR_ORDINAL_4' else 1)
if __name__=='__main__':main()
