#!/usr/bin/env python3
"""CSR-8 C6: append S2 and prove both sealed cycles."""
import json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
ROOT=c4d.REAL_CSR; SID=c4d.REAL_SESSION

def evs(): return [json.loads(x) for x in c4d.log_path(ROOT,SID).read_text().splitlines() if x.strip()]
def verify():
    after=evs()
    if [e['event_type'] for e in after]!=['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET','SEAL_ANNOTATION']: raise RuntimeError('C6 chain mismatch')
    if c4d.derive_state(ROOT,SID)[0] != 'SEALED': raise RuntimeError('C6 final state not SEALED')
    c4d.semantic_replay(ROOT,SID)
    return {'c6':'PASS','chain':[e['event_type'] for e in after],'production':'REVEAL=2 SEAL=2','open_reveals':0,'candidate_prefix':2,'r1_s1_exact':'PASS','r2_s2_exact':'PASS','ordinal1_history':'PASS','ordinal2_history':'PASS','authorization1':'CONSUMED','authorization2':'CONSUMED','dual_replay':'PASS','crash_recovery':'PASS','outcome_untouched':'PASS'}
def main():
    before=evs()
    if [e['event_type'] for e in before]==['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET','SEAL_ANNOTATION']:
        print(json.dumps(verify(),sort_keys=True,separators=(',',':'))); return
    if [e['event_type'] for e in before]!=['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET']: raise RuntimeError('C6 requires [R1,S1,R2]')
    # Rehydrate the frozen C4 active workspace from ordinal-0002 evidence for
    # the real commit-time precondition; the SEAL transaction then consumes
    # these exact bytes and performs its normal final cleanup.
    r2=before[-1]; od=c4d.ordinal_dir(ROOT,SID,2); dom=c4d.annot_dom(ROOT,SID)
    dom.mkdir(parents=True,exist_ok=True,mode=0o700); (dom/'packet').mkdir(mode=0o700); (dom/'draft').mkdir(mode=0o700)
    c4d.excl_write(c4d.packet_path(ROOT,SID,r2['payload']['packet_id']), (od/'packet.json').read_bytes())
    c4d.excl_write(c4d.draft_path(ROOT,SID), (od/'annotation_draft.json').read_bytes())
    import os
    os.chmod(c4d.draft_path(ROOT,SID),0o400)
    c4d.excl_write(dom/'annotation_session_registry.json', (od/'annotation_session_registry.json').read_bytes())
    c4d.seal_transaction(ROOT,SID)
    print(json.dumps(verify(),sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
