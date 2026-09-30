#!/usr/bin/env python3
"""CSR-8 C5: persist ordinal-2 unattended receipt approval."""
import importlib.util, json, hashlib, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
ROOT=Path(__file__).resolve().parents[1]; SID=c4d.REAL_SESSION; ORDINAL=2; ATTEMPT=1
spec=importlib.util.spec_from_file_location('b4c5',ROOT/'scripts/csr8_phase_b4_human_approval.py'); b4=importlib.util.module_from_spec(spec); spec.loader.exec_module(b4)
b4.ORDINAL=ORDINAL; b4.ATTEMPT=ATTEMPT
b4.RECEIPT=c4d.attempt_dir(c4d.REAL_CSR,SID,ORDINAL,ATTEMPT)/'receipt.json'
b4.APPROVAL=c4d.attempt_dir(c4d.REAL_CSR,SID,ORDINAL,ATTEMPT)/'seal_approval.json'
b4.REVEAL=[e for e in [json.loads(x) for x in c4d.log_path(c4d.REAL_CSR,SID).read_text().splitlines() if x.strip()] if e['event_type']=='REVEAL_PACKET'][-1]['event_hash']
b4.STAGE='C5'; b4.ITERATION=1
RECORD=ROOT/'docs/audit/evidence/c5_unattended_approval2.json'
def approval_proof(root, receipt_bytes):
    c4d._check_attempt_artifacts(root,SID,ORDINAL,ATTEMPT,[e for e in [json.loads(x) for x in c4d.log_path(root,SID).read_text().splitlines() if x.strip()] if e['event_type']=='REVEAL_PACKET'][-1],'G-C5-B3')
    rsha=hashlib.sha256(receipt_bytes).hexdigest(); ap=b4.APPROVAL.read_bytes()
    obj=json.loads(ap)
    if set(obj)!=c4d.APPROVAL_KEYS or c4d.canon(obj).encode()!=ap or obj['approved_receipt_sha256']!=rsha or obj['session_id']!=SID or obj['reveal_event_hash']!=b4.REVEAL or obj['annotation_attempt']!=ATTEMPT or obj['approved'] is not True: raise RuntimeError('C5 approval binding drift')
    if c4d.mode_of(b4.APPROVAL)!=0o600: raise RuntimeError('C5 approval mode drift')
    return ap,rsha
def main():
    if RECORD.exists(): raise RuntimeError('C5 record already exists')
    receipt=b4.RECEIPT.read_bytes(); ap,rsha=approval_proof(c4d.REAL_CSR,receipt) if b4.APPROVAL.exists() else (None,hashlib.sha256(receipt).hexdigest())
    if ap is None: c4d.make_seal_approval(c4d.REAL_CSR,SID,ordinal=ORDINAL,attempt=ATTEMPT,receipt_sha=rsha); ap=b4.APPROVAL.read_bytes(); approval_proof(c4d.REAL_CSR,receipt)
    rec=b4.expected_record(rsha,ap,c4d.REAL_CSR); c4d.excl_write(RECORD,c4d.canon(rec).encode()); b4._verify_unattended_record(RECORD,rsha,ap,c4d.REAL_CSR)
    print(json.dumps({'c5':'APPROVAL2_PERSISTED','ordinal':2,'receipt_sha256':rsha,'approved_by':'UNATTENDED_POLICY','artifact':str(RECORD.relative_to(ROOT))},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
