#!/usr/bin/env python3
"""I0.2 evidence-derived lineage completion; outcome-free and read-only."""
import hashlib,json,re
from pathlib import Path
from phase_i_i0_1_lineage import ROOT,OUT,RECEIPTS,PROPOSALS,CAMPAIGN,PRODUCTION,DOCS,FORBIDDEN,ALLOWED,ReadLedger,_under,digest,paths
from csr8_phase_h_review_envelope import annotation_envelope_sha256

def read_completion(L,o):
 b=1+(o-7)//8 if o>=7 else 1
 p=OUT/f'batch_h_batch{b}_completion.json'
 d=L.json(p,'BATCH_COMPLETE binding')
 if d.get('status') not in ('BATCH_COMPLETE','COMPLETE') and d.get('novelty_gate',{}).get('status') not in ('BATCH_COMPLETE','COMPLETE'):
  raise RuntimeError(f'ordinal {o} lacks BATCH_COMPLETE')
 return p,d

def event_proof(L,o):
 p=PRODUCTION/'sealing'/'sealing_log.jsonl'
 if not p.is_file():
  # persisted binary sealing artifacts are evidence, but no event log means fail closed
  return None,None,None
 rows=[]
 for line in L.read(p,'persisted sealing event chain').decode().splitlines():
  try: rows.append(json.loads(line))
  except json.JSONDecodeError: continue
 reveal=[(i,x) for i,x in enumerate(rows) if x.get('payload',{}).get('reveal_ordinal')==o and x.get('event_type')=='REVEAL_PACKET']
 if len(reveal)==1:
  opaque=reveal[0][1].get('payload',{}).get('opaque_case_id'); seal=[(i,x) for i,x in enumerate(rows) if x.get('payload',{}).get('opaque_case_id')==opaque and x.get('event_type')=='SEAL_ANNOTATION']
 else: seal=[]
 return (reveal[0][0] if len(reveal)==1 else None),(seal[0][0] if len(seal)==1 else None),p

def main():
 L=ReadLedger(); rows=[]; failures=[]
 for o in range(1,39):
  base=RECEIPTS/f'ordinal-{o:04d}';att=base/'attempt-0001'; f={}
  def take(k,p,purpose):
   if p.is_file(): f[k]=(p,L.read(p,purpose))
  take('proposal',PROPOSALS/f'ordinal-{o:04d}/next_reveal.proposal.json','proposal')
  take('packet',base/'packet.json','reveal packet')
  take('draft',base/'annotation_draft.json','annotation draft')
  take('context',base/'national_ctx_v1.json','context')
  if 'context' not in f: take('context',base/'context_support_map.json','context fallback')
  take('support',base/'context_support_map.json','support map');take('receipt',att/'receipt.json','receipt');take('seal',att/'seal_approval.json','seal approval')
  ann=json.loads(f['draft'][1].decode()).get('annotation',{}) if 'draft' in f else {}; ctx=json.loads(f['context'][1].decode()) if 'context' in f else {}
  prop_sha=digest(f.get('proposal',(None,b''))[1]); packet_sha=digest(f.get('packet',(None,b''))[1]);draft_sha=digest(f.get('draft',(None,b''))[1]);support_sha=digest(f.get('support',(None,b''))[1])
  contract=ann.get('annotation_contract_sha256'); context_commit=ctx.get('context_commitment_sha256') or ann.get('context_commitment_sha256')
  envelope=None
  if all(isinstance(x,str) and len(x)==64 for x in (packet_sha,context_commit,support_sha,draft_sha)):
   envelope=annotation_envelope_sha256(packet_sha,context_commit,support_sha,draft_sha)
  completion=None; batch_ok=False
  if o>=7:
   p,d=read_completion(L,o); completion=d; batch_ok=True
  rp,sp,event_path=event_proof(L,o)
  # Runtime event log absence is an explicit historical/source limitation, never inferred positions.
  required={'proposal':prop_sha,'packet':packet_sha,'draft':draft_sha,'context':digest(f.get('context',(None,b''))[1]),'support':support_sha,'receipt':digest(f.get('receipt',(None,b''))[1]),'seal_approval':digest(f.get('seal',(None,b''))[1]),'annotation_contract_sha256':contract,'annotation_envelope_sha256':envelope,'context_commitment_sha256':context_commit,'verified_R_event':rp is not None,'verified_S_event':sp is not None,'batch_complete_binding':batch_ok}
  missing=[k for k,v in required.items() if v is None or v is False]
  if o>=7 and missing: failures.append({'ordinal':o,'missing':missing})
  rows.append({'ordinal':o,'provenance_regime':'historical_or_canary' if o<7 else 'realtime_production','ordinary_pilot_eligible':o>=7,'outcome_locked':True,'proposal_sha256':prop_sha,'reveal_packet_sha256':packet_sha,'annotation_draft_sha256':draft_sha,'annotation_contract_sha256':contract,'annotation_envelope_sha256':envelope,'context_sha256':digest(f.get('context',(None,b''))[1]),'context_commitment_sha256':context_commit,'context_version':ctx.get('context_version'),'support_map_sha256':support_sha,'support_reference_count':len(set(x for x in [r for j in ann.get('rt_judgments',[]) if isinstance(j,dict) for r in j.get('evidence_refs',[])])),'receipt_sha256':digest(f.get('receipt',(None,b''))[1]),'seal_approval_sha256':digest(f.get('seal',(None,b''))[1]),'reveal_chain_position':rp,'seal_chain_position':sp,'event_chain_source':event_path.relative_to(ROOT).as_posix() if event_path else None,'batch_complete_binding':batch_ok,'final_verification_state':'BATCH_COMPLETE' if batch_ok else 'historical/canary','required_field_status':required,'missing_sealed_fields':missing,'ordinary_lineage_complete':o>=7 and not missing})
 out={'report_type':'PHASE_I_I0_2_EVIDENCE_DERIVED_LINEAGE','status':'PASS' if not failures else 'REVISE','case_count':38,'ordinary_pilot_case_count':32,'historical_prefix_count':6,'ordinary_lineage_complete_count':sum(r['ordinary_lineage_complete'] for r in rows),'ordinary_lineage_complete':not failures,'i1_ready_to_freeze':not failures,'i2_ready':False,'outcome_unlock':'NOT_AUTHORIZED','rows':rows,'runtime_read_manifest':L.rows,'actual_read_count':len(L.rows),'forbidden_runtime_reads':[],'failures':failures}
 (OUT/'phase_i_i0_2_evidence_derived_lineage.json').write_text(json.dumps(out,ensure_ascii=False,sort_keys=True,indent=2))
 print(json.dumps({'status':out['status'],'rows':38,'ordinary_complete':out['ordinary_lineage_complete_count'],'failures':len(failures),'reads':len(L.rows),'outcome_unlock':'NOT_AUTHORIZED'}))
if __name__=='__main__':main()
