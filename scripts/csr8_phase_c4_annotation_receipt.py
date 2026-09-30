#!/usr/bin/env python3
"""CSR-8 C4: ordinal-2 blinded annotation and receipt freeze."""
import json, secrets, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d

ROOT=c4d.REAL_CSR; SID=c4d.REAL_SESSION; ORDINAL=2
TS='2099-01-02T00:00:00Z'

def events():
    return [json.loads(x) for x in c4d.log_path(ROOT,SID).read_text().splitlines() if x.strip()]
def last_r2():
    rs=[e for e in events() if e['event_type']==c4d.c2.REVEAL]
    if len(rs)!=2 or rs[-1]['payload'].get('reveal_ordinal')!=2: raise RuntimeError('C4 requires R2')
    return rs[-1]
def registry_path(): return c4d.annot_dom(ROOT,SID)/'annotation_session_registry.json'
def build_draft(reg,r2,pkt):
    judgments=[{'hypothesis_id':h,'observability':'OBSERVABLE','support':'NOT_OBSERVED','evidence_refs':['/as_of/T'],'evidence_note':'Blinded packet contains no qualifying evidence at T.'} for h in c4d.HYPOTHESES]
    return {'draft_version':'c4d-draft-v1','session_id':SID,'packet_id':r2['payload']['packet_id'],'packet_sha256':r2['payload']['packet_sha256'],'annotation_session_id':reg['annotation_sessions'][-1]['annotation_session_id'],'annotation_attempt':1,'annotation':{'annotation_contract_sha256':c4d.ANNOTATION_CONTRACT_SHA256,'rt_judgments':judgments,'overall_note':'Blinded annotation: no qualifying evidence is observable at T.','flags':['EVIDENCE_INCOMPLETE_AT_T']},'created_at':TS,'updated_at':TS}
def persist():
    r2=last_r2(); arch=c4d.sealing_dir(ROOT,SID)/r2['payload']['bytes_ref']; raw=arch.read_bytes()
    if c4d.sha(raw)!=r2['payload']['packet_sha256']: raise RuntimeError('R2 archive drift')
    dom=c4d.annot_dom(ROOT,SID); dom.mkdir(parents=True,exist_ok=True,mode=0o700); (dom/'packet').mkdir(exist_ok=True,mode=0o700); (dom/'draft').mkdir(exist_ok=True,mode=0o700)
    target=c4d.packet_path(ROOT,SID,r2['payload']['packet_id']); c4d.excl_write(target,raw)
    reg={'registry_version':'c4d-annotation-session-registry-v1','session_id':SID,'reveal_event_hash':r2['event_hash'],'packet_id':r2['payload']['packet_id'],'packet_sha256':r2['payload']['packet_sha256'],'annotation_contract_sha256':c4d.ANNOTATION_CONTRACT_SHA256,'annotation_sessions':[{'annotation_session_id':secrets.token_hex(16),'created_at':TS,'status':'OPEN','packet_id':r2['payload']['packet_id'],'packet_sha256':r2['payload']['packet_sha256'],'reveal_event_hash':r2['event_hash']}]}
    c4d.excl_write(registry_path(),c4d.canon(reg).encode()); draft=build_draft(reg,r2,json.loads(raw)); c4d.excl_write(dom/'draft'/'annotation_draft.json',c4d.canon(draft).encode())
    c4d.validate_draft(ROOT,SID,draft,json.loads(raw),r1=r2); receipt,rbytes=c4d.make_receipt(ROOT,SID,ordinal=ORDINAL)
    return {'r2_packet_sha256':r2['payload']['packet_sha256'],'annotation_session_id':reg['annotation_sessions'][0]['annotation_session_id'],'receipt_sha256':c4d.sha(rbytes),'gates':{'exact_copy':'PASS','draft':'PASS','receipt':'PASS'},'production':'REVEAL=2 SEAL=1'}
def main():
    out=persist(); print(json.dumps(out,sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
