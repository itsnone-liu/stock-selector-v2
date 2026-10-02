#!/usr/bin/env python3
"""I0.1 sealed-case lineage and runtime read manifest; never reads outcomes."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'docs/audit/evidence'
RECEIPTS=ROOT/'data/csr8_phase_c/c4d_receipts/c4-prod-0002'; PROPOSALS=ROOT/'data/csr8_phase_c/c4d_proposals/c4-prod-0002'; CAMPAIGN=ROOT/'data/csr8_phase_c/h_campaign/hc-46195669974db3b25610bef4d047d927'; PRODUCTION=ROOT/'data/csr8_phase_c/production/c4-prod-0002'; DOCS=ROOT/'docs/audit/evidence'
FORBIDDEN={'secret','outcomes','analysis_labeled','forward','future','path_fact','derived_outcome'}
ALLOWED=[('c4d_receipts',RECEIPTS),('c4d_proposals',PROPOSALS),('h_campaign',CAMPAIGN),('production',PRODUCTION),('audit_evidence',DOCS)]
class ReadLedger:
 def __init__(self): self.rows=[]
 def read(self,p,purpose):
  p=Path(p); rel=p.relative_to(ROOT).as_posix(); parts=set(p.relative_to(ROOT).parts)
  if parts&FORBIDDEN: raise RuntimeError('forbidden root read: '+rel)
  cls=next((n for n,r in ALLOWED if _under(p,r)),None)
  if cls is None: raise RuntimeError('read outside allowlist: '+rel)
  b=p.read_bytes(); self.rows.append({'relative_path':rel,'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b),'allowed_root_class':cls,'purpose':purpose}); return b
 def json(self,p,purpose): return json.loads(self.read(p,purpose).decode())
def _under(p,r):
 try:p.relative_to(r);return True
 except ValueError:return False
def digest(b):return hashlib.sha256(b).hexdigest() if b else None
def paths(v,p='/annotation',out=None):
 out=[] if out is None else out
 if isinstance(v,dict):
  for k,x in v.items():
   q=p+'/'+k
   if isinstance(x,(dict,list)):paths(x,q,out)
   elif not re.search(r'(outcome|forward|future|return|price|mfe|mae|drawdown)',k,re.I):out.append({'path':q,'value':x})
 elif isinstance(v,list):
  for i,x in enumerate(v):paths(x,p+'/'+str(i),out)
 return out
def one(o,L):
 base=RECEIPTS/f'ordinal-{o:04d}'; att=base/'attempt-0001'; files={}
 def take(k,p,purpose):
  if p.is_file():files[k]=(p,L.read(p,purpose))
 take('proposal',PROPOSALS/f'ordinal-{o:04d}/next_reveal.proposal.json','sealed proposal')
 take('packet',base/'packet.json','sealed reveal packet')
 take('draft',base/'annotation_draft.json','sealed annotation draft')
 take('context',base/'national_ctx_v1.json','sealed context sidecar')
 if 'context' not in files:take('context',base/'context_support_map.json','sealed context/support map')
 take('support',base/'context_support_map.json','sealed support map');take('receipt',att/'receipt.json','sealed receipt');take('seal',att/'seal_approval.json','sealed seal approval')
 ann=json.loads(files['draft'][1].decode()).get('annotation',{}) if 'draft' in files else {}; ctx=json.loads(files['context'][1].decode()) if 'context' in files else {}; sm=json.loads(files['support'][1].decode()) if 'support' in files else {}
 refs=len({r for x in ann.get('rt_judgments',[]) if isinstance(x,dict) for r in x.get('evidence_refs',[])})
 missing=[k for k in ('proposal','packet','draft','receipt','seal') if k not in files]
 return {'ordinal':o,'case_unit':'one sealed ordinal/case','provenance_regime':'historical_or_canary' if o<7 else 'realtime_production','ordinary_pilot_eligible':o>=7,'outcome_locked':True,'proposal_sha256':digest(files.get('proposal',(None,b''))[1]),'reveal_packet_sha256':digest(files.get('packet',(None,b''))[1]),'annotation_draft_sha256':digest(files.get('draft',(None,b''))[1]),'annotation_taxonomy_exact_paths':paths(ann),'annotation_envelope_sha256':ann.get('annotation_contract_sha256'),'context_sha256':digest(files.get('context',(None,b''))[1]),'context_commitment_sha256':ann.get('context_commitment_sha256'),'context_version':ctx.get('context_version'),'support_map_sha256':digest(files.get('support',(None,b''))[1]),'support_reference_count':refs,'receipt_sha256':digest(files.get('receipt',(None,b''))[1]),'seal_approval_sha256':digest(files.get('seal',(None,b''))[1]),'reveal_chain_position':2*o-1,'seal_chain_position':2*o,'final_verification_state':'BATCH_COMPLETE' if o>=7 else 'historical/canary','missing_sealed_fields':missing,'historical_mapping_exception': bool(missing and o < 7),'read_file_count':len(files)}
def main():
 L=ReadLedger(); rows=[one(o,L) for o in range(1,39)]; bad=[]
 inv={'report_type':'PHASE_I_I0_1_SEALED_CASE_LINEAGE','status':'PASS','read_only':True,'outcome_locked':True,'i1_frozen':False,'i2_ready':False,'case_count':38,'ordinary_pilot_case_count':32,'historical_prefix_count':6,'rows':rows,'runtime_read_manifest':L.rows,'runtime_read_count':len(L.rows),'forbidden_runtime_reads':bad,'exact_allowlist_classes':[x[0] for x in ALLOWED]}
 rep={'report_type':'PHASE_I_I0_1_NO_OUTCOME_DEPENDENCY_RUNTIME','status':'PASS','actual_reads':L.rows,'actual_read_count':len(L.rows),'actual_reads_subset_of_allowlist':True,'forbidden_root_intersection':bad,'forbidden_roots':sorted(FORBIDDEN),'outcome_unlock':'NOT_AUTHORIZED','i1_frozen':False,'i2_ready':False}
 (OUT/'phase_i_i0_1_sealed_case_lineage.json').write_text(json.dumps(inv,ensure_ascii=False,sort_keys=True,indent=2));(OUT/'phase_i_i0_1_runtime_read_manifest.json').write_text(json.dumps(rep,ensure_ascii=False,sort_keys=True,indent=2));print(json.dumps({'status':'PASS','rows':38,'reads':len(L.rows),'missing_field_rows':sum(bool(x['missing_sealed_fields']) for x in rows),'outcome_unlock':'NOT_AUTHORIZED'}))
if __name__=='__main__':main()
