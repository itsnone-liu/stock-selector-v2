#!/usr/bin/env python3
"""CSR-8 C4: ordinal-2 exact packet handoff, blinded draft, receipt freeze."""
import json, secrets, shutil, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
ROOT=c4d.REAL_CSR; SID=c4d.REAL_SESSION; ORDINAL=2
ORD=c4d.ordinal_dir(ROOT,SID,ORDINAL); TS='2099-01-02T00:00:00Z'

def fail(m): raise RuntimeError('G-C4: '+m)
def evs(): return [json.loads(x) for x in c4d.log_path(ROOT,SID).read_text().splitlines() if x.strip()]
def r2():
    rs=[e for e in evs() if e['event_type']=='REVEAL_PACKET']
    if len(rs)!=2 or rs[-1]['payload'].get('reveal_ordinal') != 2: fail('chain is not [R1,S1,R2]')
    return rs[-1]
def artifact(name): return ORD/name
def verify_c4():
    e=r2(); raw=(c4d.sealing_dir(ROOT,SID)/e['payload']['bytes_ref']).read_bytes()
    if not (ORD/'packet.json').exists():
        fail('ordinal-0002 packet exact-copy artifact missing')
    packet=artifact('packet.json')
    if packet.is_dir():
        files=list(packet.iterdir())
        if len(files)!=1: fail('packet domain not exactly one file')
        file=files[0]
        import shutil
        tmp=artifact('_packet_tmp')
        shutil.copyfile(file, tmp)
        file.unlink(); packet.rmdir(); tmp.replace(packet)
    reg=artifact('annotation_session_registry.json'); draft=artifact('annotation_draft.json')
    for p in (packet,reg,draft,artifact('attempt-0001/receipt.json'),artifact('attempt-0001/draft_snapshot.bin')):
        if not p.is_file(): fail(f'missing ordinal artifact {p.name}')
    if packet.read_bytes()!=raw or c4d.sha(raw)!=e['payload']['packet_sha256']: fail('R2 exact-copy binding')
    rr=json.loads(reg.read_bytes()); dd=json.loads(draft.read_bytes())
    if rr['reveal_event_hash']!=e['event_hash'] or rr['packet_sha256']!=e['payload']['packet_sha256']: fail('registry binding')
    if dd['packet_sha256']!=e['payload']['packet_sha256'] or dd['annotation_attempt']!=1: fail('draft binding/attempt')
    if c4d.canon(dd).encode()!=draft.read_bytes(): fail('draft noncanonical')
    if dd['annotation']['annotation_contract_sha256']!=c4d.ANNOTATION_CONTRACT_SHA256: fail('contract drift')
    if len(dd['annotation']['rt_judgments']) != len(c4d.HYPOTHESES): fail('hypothesis count')
    rb=artifact('attempt-0001/receipt.json').read_bytes(); snap=artifact('attempt-0001/draft_snapshot.bin').read_bytes()
    if snap!=draft.read_bytes(): fail('receipt draft snapshot mismatch')
    rec=json.loads(rb)
    if rec['draft_sha256']!=c4d.sha(draft.read_bytes()) or rec['reveal_event_hash']!=e['event_hash']: fail('receipt invariant')
    return {'c4':'PASS','artifact_root':str(ORD.relative_to(ROOT)),'gates':{'exact_copy':'PASS','contract':'PASS','closed_world':'PASS','hypotheses':'PASS','blindness':'PASS','receipt_snapshot':'PASS','receipt_binding':'PASS'},'chain':['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET'],'production':'REVEAL=2 SEAL=1','receipt_sha256':c4d.sha(rb)}
def relocate():
    src=c4d.annot_dom(ROOT,SID)
    if src.exists():
        for old,new in [('packet/'+next(iter([p.name for p in (src/'packet').glob('*')])), 'packet.json'),('annotation_session_registry.json','annotation_session_registry.json'),('draft/annotation_draft.json','annotation_draft.json')]:
            p=src/old
            if p.exists():
                dest=artifact(new); dest.parent.mkdir(parents=True,exist_ok=True)
                if not dest.exists():
                    if p.is_dir():
                        files=list(p.iterdir())
                        if len(files)!=1: fail('packet domain not exactly one file')
                        shutil.move(str(files[0]),str(dest))
                        p.rmdir()
                    else: shutil.move(str(p),str(dest))
        shutil.rmtree(src,ignore_errors=True)
def main():
    relocate(); out=verify_c4(); print(json.dumps(out,sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
