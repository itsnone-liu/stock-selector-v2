#!/usr/bin/env python3
"""CSR-8 C4: independently verify ordinal-2 B2/B3 artifacts."""
import hashlib, json, stat, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
ROOT=c4d.REAL_CSR; SID=c4d.REAL_SESSION; ORDINAL=2
TS='2099-01-02T00:00:00Z'

def fail(m): raise RuntimeError('G-C4: '+m)
def canon(x): return c4d.canon(x)
def sha(b): return hashlib.sha256(b).hexdigest()
def mode(p): return stat.S_IMODE(p.stat().st_mode)
def ordinal(root): return c4d.ordinal_dir(root,SID,ORDINAL)
def events(root): return [json.loads(x) for x in c4d.log_path(root,SID).read_text().splitlines() if x.strip()]
def r2(root):
    rs=[e for e in events(root) if e['event_type']=='REVEAL_PACKET']
    if len(rs)!=2 or rs[-1]['payload'].get('reveal_ordinal') != 2: fail('chain is not [R1,S1,R2]')
    return rs[-1]
def verify_c4(root=ROOT):
    root=Path(root); od=ordinal(root); e=r2(root)
    arch=c4d.sealing_dir(root,SID)/e['payload']['bytes_ref']; raw=arch.read_bytes()
    packet=od/'packet.json'; reg=od/'annotation_session_registry.json'; draft=od/'annotation_draft.json'; attempt=od/'attempt-0001'
    required=(packet,reg,draft,attempt/'receipt.json',attempt/'draft_snapshot.bin')
    if any(not p.is_file() for p in required): fail('ordinal-0002 artifact missing')
    if packet.read_bytes()!=raw or sha(raw)!=e['payload']['packet_sha256']: fail('R2 exact-copy binding')
    if mode(packet)!=0o600 or mode(reg)!=0o600 or mode(draft) not in (0o400,0o600): fail('artifact mode drift')
    rr=json.loads(reg.read_bytes()); dd=json.loads(draft.read_bytes())
    if canon(rr).encode()!=reg.read_bytes() or canon(dd).encode()!=draft.read_bytes(): fail('noncanonical JSON')
    if set(rr)!={'registry_version','session_id','reveal_event_hash','packet_id','packet_sha256','annotation_contract_sha256','annotation_sessions'}: fail('registry closed-world schema')
    if rr['session_id']!=SID or rr['reveal_event_hash']!=e['event_hash'] or rr['packet_id']!=e['payload']['packet_id'] or rr['packet_sha256']!=e['payload']['packet_sha256']: fail('registry binding')
    sessions=rr['annotation_sessions']
    if len(sessions)!=1 or sessions[0]['status']!='OPEN': fail('second annotation session not OPEN/unique')
    session=sessions[0]
    if not isinstance(session.get('annotation_session_id'),str) or len(session['annotation_session_id'])!=32 or any(ch not in '0123456789abcdef' for ch in session['annotation_session_id']): fail('second session identity is not opaque 32-hex')
    if session['annotation_session_id']==rr['session_id'] or session['annotation_session_id']==e['event_hash']: fail('session identity is not independent')
    if session['packet_id']!=e['payload']['packet_id'] or session['packet_sha256']!=e['payload']['packet_sha256'] or session['reveal_event_hash']!=e['event_hash']: fail('second session packet/R2 binding')
    if set(dd)!=c4d.DRAFT_TOP or dd['draft_version']!='c4d-draft-v1' or dd['session_id']!=SID or dd['packet_id']!=e['payload']['packet_id'] or dd['packet_sha256']!=e['payload']['packet_sha256'] or dd['annotation_attempt']!=1: fail('draft schema/binding')
    if dd['annotation_session_id']!=session['annotation_session_id']: fail('draft is not bound to the second session identity')
    ann=dd['annotation']
    if set(ann)!=c4d.ANNOTATION_KEYS or ann['annotation_contract_sha256']!=c4d.ANNOTATION_CONTRACT_SHA256: fail('annotation contract/closed-world gate')
    js=ann['rt_judgments']
    if len(js)!=len(c4d.HYPOTHESES) or [j['hypothesis_id'] for j in js]!=list(c4d.HYPOTHESES): fail('hypothesis order/count gate')
    c4d.validate_draft(root,SID,dd,json.loads(raw),r1=e)
    # Re-run the frozen receipt derivative proof: this checks the complete
    # B3 invariant, including receipt field derivation from the exact snapshot,
    # archived packet replay, and revocation/attempt history.
    c4d._check_attempt_artifacts(root,SID,ORDINAL,1,e,'G-C4-B3')
    keys=set(); forbidden={'case_key','case_id','identity','symbol','ticker','code','stock_code','name','outcome','outcome_label','label','future','future_return','secret','secret_salt','salt','token'}
    def walk(x):
        if isinstance(x,dict):
            keys.update(x)
            for v in x.values(): walk(v)
        elif isinstance(x,list):
            for v in x: walk(v)
    walk(dd)
    if keys & forbidden: fail('blindness leak: '+repr(sorted(keys&forbidden)))
    rb=(attempt/'receipt.json').read_bytes(); snap=(attempt/'draft_snapshot.bin').read_bytes(); rec=json.loads(rb)
    if mode(attempt)!=0o700 or mode(attempt/'receipt.json')!=0o600 or mode(attempt/'draft_snapshot.bin')!=0o600: fail('receipt artifact mode drift')
    if mode(od)!=0o700 or mode(od.parent)!=0o700 or mode(od.parent.parent)!=0o700: fail('receipt domain mode drift')
    if snap!=draft.read_bytes() or rec['draft_sha256']!=sha(draft.read_bytes()) or rec['reveal_event_hash']!=e['event_hash'] or rec['annotation_attempt']!=1: fail('receipt freeze invariant')
    if set(rec)!=c4d.RECEIPT_TOP: fail('receipt closed-world schema drift')
    if rec['session_id']!=SID or rec['packet_id']!=e['payload']['packet_id'] or rec['packet_sha256']!=e['payload']['packet_sha256']: fail('receipt chain binding drift')
    if rec['annotation']['annotation_contract_sha256']!=c4d.ANNOTATION_CONTRACT_SHA256: fail('receipt annotation contract drift')
    names=sorted(p.name for p in od.iterdir())
    if names!=['annotation_draft.json','annotation_session_registry.json','attempt-0001','packet.json']: fail('ordinal-0002 closed-world violation')
    return {'c4':'PASS','artifact_root':str(od.relative_to(root)),'gates':{'exact_copy':'PASS','registry_schema':'PASS','session':'PASS','contract':'PASS','closed_world':'PASS','hypotheses':'PASS','blindness':'PASS','receipt_snapshot':'PASS','receipt_binding':'PASS'},'chain':['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET'],'production':'REVEAL=2 SEAL=1','receipt_sha256':sha(rb)}
if __name__=='__main__': print(json.dumps(verify_c4(),sort_keys=True,separators=(',',':')))
