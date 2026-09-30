#!/usr/bin/env python3
"""Phase D: constructive ordinal-N invariant, prefix, and recovery matrix."""
import json,sys,tempfile,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
ROOT=c.REAL_CSR; SID=c.REAL_SESSION

def events(root=ROOT): return [json.loads(x) for x in c.log_path(root,SID).read_text().splitlines() if x.strip()]
def prefix_history_matrix(ev):
    reveals=[e for e in ev if e['event_type']==c.c2.REVEAL]
    if not reveals: raise RuntimeError('D requires revealed prefix')
    out=[]
    for n,r in enumerate(reveals,1):
        # Each ordinal is derived from the n-th reveal and its bounded chain
        # window; no ordinal-specific fixture or label is used.
        h=c.prove_attempt_history(ROOT,SID,n,gate=f'G-D-PREFIX-{n}',events=ev,reveal=r)
        if not isinstance(h,dict) or not isinstance(h.get('published'),list): raise RuntimeError('D prefix proof malformed')
        out.append({'ordinal':n,'published':len(h['published']),'live':len(h['live'])})
    return out
def recovery_matrix():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    checkpoints=('after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup')
    results=[]
    for point in checkpoints:
        with tempfile.TemporaryDirectory(prefix='csr8-d-recovery-') as td:
            sb=build_pre_seal_sandbox(Path(td),through='B4')
            before=events(sb.root)
            try: c.seal_transaction(sb.root,SID,stop_after=point)
            except c.CrashSim: pass
            else: raise RuntimeError(f'D checkpoint not interruptible: {point}')
            # Restart is always routed through the real recovery classifier.
            state=c.recover(sb.root,SID)
            after=events(sb.root)
            if point in ('after_verify','after_derive','after_precondition') and after != before: raise RuntimeError(f'D pre-append recovery drift: {point}')
            if point in ('after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup') and [e['event_type'] for e in after] != ['REVEAL_PACKET','SEAL_ANNOTATION']: raise RuntimeError(f'D append recovery chain drift: {point}')
            if point in ('after_verify','after_derive','after_precondition') and state != 'SEAL_AUTHORIZED': raise RuntimeError(f'D precondition recovery state drift: {point} -> {state}')
            if point in ('after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup') and state != 'SEALED': raise RuntimeError(f'D recovery did not converge: {point} -> {state}')
            results.append(point)
    return results
def verify():
    ev=events(); types=[e['event_type'] for e in ev]
    if types != ['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET','SEAL_ANNOTATION']: raise RuntimeError('D frozen production chain drift')
    prefixes=prefix_history_matrix(ev)
    c.semantic_replay(ROOT,SID)
    recovered=recovery_matrix()
    return {'d':'PASS','prefixes':prefixes,'recovery_checkpoints':recovered,'recovery_count':len(recovered),'semantic_replay':'PASS','chain':types}
if __name__=='__main__': print(json.dumps(verify(),sort_keys=True,separators=(',',':')))
