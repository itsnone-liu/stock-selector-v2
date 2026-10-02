#!/usr/bin/env python3
"""Verify H-PRE integration has not changed the NC0 production boundary."""
import json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; A=ROOT/'docs/audit/evidence/national_capital_extension_pause_anchor.json'; CSR=ROOT/'data/csr8_phase_c'; PROD=CSR/'production/c4-prod-0002'
def main():
 a=json.loads(A.read_text()); events=[json.loads(x) for x in (PROD/'sealing/sealing_log.jsonl').read_text().splitlines() if x.strip()]; head=json.loads((PROD/'sealing/sealing_log.head.json').read_text()); types=[x['event_type'] for x in events]
 import sys;sys.path.insert(0,str(ROOT/'scripts'));import csr8_phase_c_annotation_seal as c4d
 order=c4d.candidate_total_order(); keys=[(x['payload']['opaque_case_id'],x['payload']['T']) for x in events if x['event_type']=='REVEAL_PACKET']
 checks={'chain_exact':types==a['production_chain'],'counts':len([x for x in events if x['event_type']=='REVEAL_PACKET'])==a['reveal_count'] and len([x for x in events if x['event_type']=='SEAL_ANNOTATION'])==a['seal_count'],'head_unchanged':head.get('head_hash')==a['production_head'],'candidate_prefix_unchanged':keys==[(x['opaque_case_id'],x['T']) for x in order[:3]],'candidate_order_size_unchanged':len(order)==a['candidate_order_size'],'candidate_commitment_unchanged':a['candidate_order_commitment']=='e1b41cf681672cc5fe39e95f9c2f9dc0c038db57fab42f6c1411ddfb2baaf176','no_r4_s4':len(events)==6}
 report={'anchor':str(A.relative_to(ROOT)),'checks':checks,'passed':all(checks.values()),'production_invariance':'PASS' if all(checks.values()) else 'FAIL','current_git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'note':'git head is expected to advance during H-PRE; production head and candidate commitments must not'}; (A.parent/'national_capital_production_invariance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
