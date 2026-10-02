#!/usr/bin/env python3
"""Fail-closed, read-only NC_FINAL resume gate."""
import hashlib,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/audit/evidence';CSR=ROOT/'data/csr8_phase_c/production/c4-prod-0002'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def canon(x):return json.dumps({k:v for k,v in x.items() if k!='review_packet_sha256'},ensure_ascii=False,sort_keys=True,separators=(',',':'))
def main():
 packet_p=OUT/'nc_final_review_packet.json';verdict_p=OUT/'nc_final_review_verdict.json';frozen=OUT/'national_capital_context_extension_frozen.json';inv=json.loads((OUT/'national_capital_production_invariance.json').read_text());audit=json.loads((OUT/'national_capital_context_extension_final_audit.json').read_text());pre=json.loads((OUT/'national_capital_context_preflight.json').read_text());checks={}
 if packet_p.exists():
  packet=json.loads(packet_p.read_text());packet_hash=hashlib.sha256(canon(packet).encode()).hexdigest();checks['review_packet_hash_exact']=packet_hash==packet.get('review_packet_sha256')
 else:packet={};packet_hash='';checks['review_packet_hash_exact']=False
 if verdict_p.exists():
  verdict=json.loads(verdict_p.read_text());checks['independent_approve']=verdict.get('operation')=='NC_FINAL' and verdict.get('review_version')=='csr8-nc-final-review-v1' and verdict.get('state')=='APPROVE' and verdict.get('input_commitment_sha256')==packet_hash
 else:verdict={};checks['independent_approve']=False
 if frozen.exists():
  fr=json.loads(frozen.read_text());checks['freeze_marker_valid']=fr.get('status')=='NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN' and fr.get('final_verdict')=='APPROVE' and fr.get('review_packet_sha256')==packet_hash and fr.get('review_verdict_sha256')==sha(verdict_p) and fr.get('final_audit_sha256')==sha(OUT/'national_capital_context_extension_final_audit.json') and fr.get('context_preflight_sha256')==sha(OUT/'national_capital_context_preflight.json')
 else:checks['freeze_marker_valid']=False
 events=[x for x in (CSR/'sealing/sealing_log.jsonl').read_text().splitlines() if x.strip()];checks.update({'nc0_invariance':inv.get('passed') is True,'audit_complete':audit.get('state')=='PREREQUISITES_COMPLETE','context_preflight_pass':pre.get('status')=='PASS','chain_still_paused':len(events)==6,'candidate_prefix_3':inv.get('checks',{}).get('candidate_prefix_unchanged') is True,'candidate_for_ordinal_4':True})
 ok=all(checks.values());report={'state':'READY_FOR_ORDINAL_4' if ok else 'BLOCKED','ordinal':4,'evidence_profile':'BASE_V1+NATIONAL_CTX_V1','checks':checks,'mutation':'NONE'};print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if ok else 1)
if __name__=='__main__':main()
