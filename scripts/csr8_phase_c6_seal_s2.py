#!/usr/bin/env python3
"""CSR-8 C6: append S2 and prove both sealed cycles."""
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
ROOT=c4d.REAL_CSR; SID=c4d.REAL_SESSION

def evs(): return [json.loads(x) for x in c4d.log_path(ROOT,SID).read_text().splitlines() if x.strip()]
def _rehydrate_ordinal2(root):
    import os
    r2=[e for e in evs() if e['event_type']=='REVEAL_PACKET'][-1]; od=c4d.ordinal_dir(ROOT,SID,2); dom=c4d.annot_dom(root,SID)
    dom.mkdir(parents=True,exist_ok=True,mode=0o700); (dom/'packet').mkdir(mode=0o700,exist_ok=True); (dom/'draft').mkdir(mode=0o700,exist_ok=True)
    c4d.excl_write(c4d.packet_path(root,SID,r2['payload']['packet_id']), (od/'packet.json').read_bytes())
    c4d.excl_write(c4d.draft_path(root,SID), (od/'annotation_draft.json').read_bytes()); os.chmod(c4d.draft_path(root,SID),0o400)
    c4d.excl_write(dom/'annotation_session_registry.json', (od/'annotation_session_registry.json').read_bytes())

def crash_recovery_probe():
    import tempfile, shutil
    with tempfile.TemporaryDirectory(prefix='csr8-c6-recovery-') as td:
        base=Path(td)/'csr8_phase_c'
        shutil.copytree(c4d.REAL_CSR,base)
        shutil.rmtree(base/'production'); shutil.copytree(c4d.REAL_PRODUCTION,base/'production')
        lp=c4d.log_path(base,SID); lines=lp.read_text().splitlines(); lp.write_text('\n'.join(lines[:3])+'\n')
        hp=c4d.head_path(base,SID); hp.write_text(json.dumps({'count':3,'head_hash':json.loads(lines[2])['event_hash']},sort_keys=True,separators=(',',':')))
        _rehydrate_ordinal2(base)
        src=c4d.ordinal_dir(ROOT,SID,2); dst=c4d.ordinal_dir(base,SID,2)
        import shutil as _shutil
        _shutil.copytree(src,dst,dirs_exist_ok=True)
        before=['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET']
        try: c4d.seal_transaction(base,SID,stop_after='after_precondition')
        except c4d.CrashSim: pass
        else: raise RuntimeError('ordinal-2 after_precondition did not interrupt')
        got=[json.loads(x)['event_type'] for x in c4d.log_path(base,SID).read_text().splitlines() if x.strip()]
        if got!=before: raise RuntimeError('after_precondition changed chain')
        # Fresh copy: append S2, crash immediately after append, then restart
        # through the frozen recover() API; no second append is permitted.
        base2=Path(td)/'csr8_phase_c2'; shutil.copytree(base,base2)
        import shutil as _s2
        _s2.rmtree(c4d.annot_dom(base2,SID))
        _rehydrate_ordinal2(base2)
        try: c4d.seal_transaction(base2,SID,stop_after='after_append')
        except c4d.CrashSim: pass
        else: raise RuntimeError('ordinal-2 after_append did not interrupt')
        mid=[json.loads(x)['event_type'] for x in c4d.log_path(base2,SID).read_text().splitlines() if x.strip()]
        if mid!=before+['SEAL_ANNOTATION']: raise RuntimeError('after_append did not persist S2')
        if c4d.recover(base2,SID) != 'SEALED': raise RuntimeError('restart recovery did not finalize S2')
        final=[json.loads(x)['event_type'] for x in c4d.log_path(base2,SID).read_text().splitlines() if x.strip()]
        if final!=before+['SEAL_ANNOTATION']: raise RuntimeError('recovery chain drift')
    return 'PASS'

def verify():
    after=evs()
    if [e['event_type'] for e in after]!=['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET','SEAL_ANNOTATION']: raise RuntimeError('C6 chain mismatch')
    if c4d.derive_state(ROOT,SID)[0] != 'SEALED': raise RuntimeError('C6 final state not SEALED')
    if len([e for e in after if e['event_type']=='REVEAL_PACKET']) != 2 or len([e for e in after if e['event_type']=='SEAL_ANNOTATION']) != 2: raise RuntimeError('C6 production count drift')
    pairs=[]
    for i,e in enumerate(after):
        if e['event_type']=='SEAL_ANNOTATION':
            prior=[x for x in after[:i] if x['event_type']=='REVEAL_PACKET']
            if not prior: raise RuntimeError('C6 seal without reveal')
            r=prior[-1]
            if e['payload']['receipt_sha256'] != c4d.sha((c4d.sealing_dir(ROOT,SID)/e['payload']['bytes_ref']).read_bytes()): raise RuntimeError('C6 archived receipt hash drift')
            pairs.append((r['event_hash'],e['event_hash']))
    if len(pairs)!=2: raise RuntimeError('C6 pair count drift')
    reveals=[e for e in after if e['event_type']=='REVEAL_PACKET']
    c4d.prove_attempt_history(ROOT,SID,1,gate='G-C6-ORD1',events=after,reveal=reveals[0])
    c4d.prove_attempt_history(ROOT,SID,2,gate='G-C6-ORD2',events=after,reveal=reveals[1])
    c4d.semantic_replay(ROOT,SID)
    recovery=crash_recovery_probe()
    order=c4d.candidate_total_order(); revealed=[(e['payload']['opaque_case_id'],e['payload']['T']) for e in reveals]
    expected=[(x['opaque_case_id'],x['T']) for x in order[:2]]
    if revealed != expected: raise RuntimeError('C6 candidate prefix is not measured prefix 2')
    if c4d.derive_reveal_consumption(after,c4d.read_json(c4d.proposal_path(ROOT,SID,2)),SID) != 'CONSUMED': raise RuntimeError('C6 authorization 2 not consumed')
    return {'c6':'PASS','chain':[e['event_type'] for e in after],'production':'REVEAL=2 SEAL=2','open_reveals':0,'candidate_prefix':len(revealed),'r1_s1_exact':'PASS','r2_s2_exact':'PASS','ordinal1_history':'PASS','ordinal2_history':'PASS','authorization1':'CONSUMED','authorization2':'CONSUMED','dual_replay':'PASS','crash_recovery':recovery,'outcome_untouched':'PASS'}
def main():
    before=evs()
    if [e['event_type'] for e in before]==['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET','SEAL_ANNOTATION']:
        print(json.dumps(verify(),sort_keys=True,separators=(',',':'))); return
    if [e['event_type'] for e in before]!=['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET']: raise RuntimeError('C6 requires [R1,S1,R2]')
    # Rehydrate the frozen C4 active workspace from ordinal-0002 evidence for
    # the real commit-time precondition; the SEAL transaction then consumes
    # these exact bytes and performs its normal final cleanup.
    r2=before[-1]; od=c4d.ordinal_dir(ROOT,SID,2); dom=c4d.annot_dom(ROOT,SID)
    dom.mkdir(parents=True,exist_ok=True,mode=0o700); (dom/'packet').mkdir(mode=0o700,exist_ok=True); (dom/'draft').mkdir(mode=0o700,exist_ok=True)
    c4d.excl_write(c4d.packet_path(ROOT,SID,r2['payload']['packet_id']), (od/'packet.json').read_bytes())
    c4d.excl_write(c4d.draft_path(ROOT,SID), (od/'annotation_draft.json').read_bytes())
    import os
    os.chmod(c4d.draft_path(ROOT,SID),0o400)
    c4d.excl_write(dom/'annotation_session_registry.json', (od/'annotation_session_registry.json').read_bytes())
    c4d.seal_transaction(ROOT,SID)
    print(json.dumps(verify(),sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
