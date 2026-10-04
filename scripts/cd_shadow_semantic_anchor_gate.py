#!/usr/bin/env python3
import argparse,json
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('pack');a=p.parse_args();x=json.loads(Path(a.pack).read_text()); checks={
 'five_dates':len(x.get('dates',[]))==5,
 'independent_oracle':all(not z.get('uses_runtime_code') and z.get('oracle')=='independent_semantic_audit' for z in x.get('anchors',[])),
 'provenance_complete':all(z.get('source_inputs') for z in x.get('anchors',[])),
 'p0_present':any(z.get('semantic_field')=='position_transition' for z in x.get('anchors',[])),
 'critical_action_semantics':x.get('coverage',{}).get('PRIMARY_ZONE') and x.get('coverage',{}).get('decision') and x.get('coverage',{}).get('position_P0') and not any(z.get('field') in ('PRIMARY_ZONE','decision') for z in x.get('unsupported',[])),
 'l2_coverage':x.get('coverage',{}).get('L2') is True,
 'bounded_unsupported_disclosed':all('ROUND1_EVIDENCE_INSUFFICIENT' in z.get('reason','') for z in x.get('unsupported',[]))}
 # L2 is production-critical context but intentionally unsupported by this bounded oracle.
 errors=[k for k,v in checks.items() if not v]; result={'gate':'G-SHADOW-SEMANTIC-ANCHORS','status':'PASS' if not errors else 'NOT_READY','checks':checks,'unsupported':x.get('unsupported',[]),'errors':errors}
 print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['status']=='PASS' else 2)
if __name__=='__main__':main()
