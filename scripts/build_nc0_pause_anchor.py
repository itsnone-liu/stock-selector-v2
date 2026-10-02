#!/usr/bin/env python3
"""Build NC0 pause anchor from the live H production chain, read-only."""
import hashlib,json,subprocess
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; CSR=ROOT/'data/csr8_phase_c'; SID='c4-prod-0002'; PROD=CSR/'production'/SID; CAMPAIGN=CSR/'h_campaign/hc-46195669974db3b25610bef4d047d927'; OUT=ROOT/'docs/audit/evidence/national_capital_extension_pause_anchor.json'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 log=PROD/'sealing/sealing_log.jsonl'; events=[json.loads(x) for x in log.read_text().splitlines() if x.strip()]; types=[x['event_type'] for x in events]; head=json.loads((PROD/'sealing/sealing_log.head.json').read_text());
 if types!=['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET','SEAL_ANNOTATION']: raise SystemExit(f'NC0 chain mismatch: {types}')
 if head.get('count')!=6: raise SystemExit('NC0 head count mismatch')
 import sys; sys.path.insert(0,str(ROOT/'scripts')); import csr8_phase_c_annotation_seal as c4d
 order=c4d.candidate_total_order(); reveals=[x for x in events if x['event_type']=='REVEAL_PACKET']; keys=[(x['payload']['opaque_case_id'],x['payload']['T']) for x in reveals]
 if keys != [(x['opaque_case_id'],x['T']) for x in order[:3]]: raise SystemExit('NC0 candidate prefix mismatch')
 manifest=ROOT/'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927/campaign_manifest.json'; m=json.loads(manifest.read_text());
 anchor={'anchor_version':'csr8-national-capital-nc0-v1','created_at':datetime.now(timezone.utc).isoformat(),'status':'H_PRE_PAUSED','production_chain':types,'reveal_count':3,'seal_count':3,'open_reveals':0,'candidate_prefix':3,'candidate_order_size':len(order),'production_head':head['head_hash'],'sealing_log_head_sha256':sha(PROD/'sealing/sealing_log.head.json'),'campaign_id':m['campaign_id'],'review_ledger_head':sha(CAMPAIGN / m.get('review_ledger','reviews.jsonl')),'candidate_order_commitment':m['candidate_order_commitment'],'git_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'no_r4':True,'no_s4':True,'machine_checks':{'chain_exact':'PASS','candidate_prefix':'PASS','semantic_replay':'DEFERRED_TO_FROZEN_H_GATE','ordinal_1_to_3_history':'DEFERRED_TO_FROZEN_H_GATE'}}
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(anchor,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(anchor,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
