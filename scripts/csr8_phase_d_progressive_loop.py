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
def ordinal_contract_matrix():
    # Exercise the generic ordinal API over the complete frozen candidate
    # order, and prove unsupported jumps fail closed on a real transaction
    # sandbox rather than being represented by a synthetic PASS label.
    order=c.candidate_total_order()
    if not order: raise RuntimeError('D candidate order empty')
    for n in range(1,len(order)+1):
        got=c.candidate_for_ordinal(n)
        if got != order[n-1]: raise RuntimeError(f'D candidate ordinal {n} drift')
    sb,sid=c.prepared_sandbox()
    for bad in (0,2,3,len(order)+1):
        try: c.prove_next_reveal_eligible(sb,sid,bad)
        except (RuntimeError,SystemExit): pass
        else: raise RuntimeError(f'D accepted invalid next ordinal {bad}')
    return {'candidate_ordinals':len(order),'invalid_jumps_rejected':4}
def constructive_progressive_loop(count=3):
    # Each iteration is a fresh, transaction-derived loop: prerequisite
    # eligibility is evaluated from persisted chain, real receipt/approval
    # bytes authorize the seal, and seal_transaction appends/finalizes.
    loops=[]
    for i in range(1,count+1):
        sb,sid=c.prepared_authorized(case=f'D-ordinal-{i}',T=f'2021-04-{i:02d}')
        before=events(sb)
        if c.derive_state(sb,sid)[0] not in ('SEAL_AUTHORIZED','SEAL_PENDING_FINALIZE'): raise RuntimeError('D prerequisite not derived')
        result=c.seal_transaction(sb,sid)
        after=events(sb)
        if result.get('state') != 'SEALED' or [e['event_type'] for e in after] != ['REVEAL_PACKET','SEAL_ANNOTATION']: raise RuntimeError('D real append/seal loop failed')
        c.semantic_replay(sb,sid)
        h=c.prove_attempt_history(sb,sid,1,gate=f'G-D-LOOP-{i}',events=after,reveal=after[0])
        if h['seal_bound'] is None: raise RuntimeError('D loop history not seal-bound')
        loops.append({'ordinal':i,'prerequisite':'PASS','authorization':'PASS','append':'PASS','seal':'PASS','history':'PASS'})
    return loops
def same_chain_progressive_loop(count=3):
    with tempfile.TemporaryDirectory(prefix='csr8-d-chain-') as td:
        sb=Path(td)/'csr8_phase_c'; shutil.copytree(c.REAL_CSR,sb); sid=SID; trace=[]
        for n in range(3,count+3):
            ev=events(sb); prefix=c._current_prefix_head(sb,sid); cand=c.candidate_for_ordinal(n)
            # H0-aware (taskbook v1.1 §8/§31): the copied live tree may
            # already carry the Phase H PREPARED NEXT_REVEAL proposal for
            # the starting ordinal, bound to this exact sealed prefix head.
            # The frozen one-time builder is O_EXCL by design, so re-prove
            # the persisted proposal and consume it rather than collide.
            if c.proposal_path(sb,sid,n).is_file():
                c._check_proposal(sb,sid,n)
            else:
                c.build_next_reveal_proposal(sb,sid,n,prefix,cand)
            c.approve_next_reveal(sb,sid,n); c.materialize_next_permit(sb,sid,n); c.reveal_transaction(sb,sid,n)
            pid=c.sha(f"{cand['opaque_case_id']}|{cand['T']}".encode()); pkt=(c.c4ab.C3_STATE/'packets'/f'{pid}.json').read_bytes()
            c.handoff(sb,sid,cand['opaque_case_id'],cand['T'],bytes_override=pkt); pobj=json.loads(pkt); draft=c.sample_draft(sb,sid)
            if not pobj.get('evidence'):
                for j in draft['annotation']['rt_judgments']:
                    j['observability']='UNOBSERVABLE'; j['support']=None; j['evidence_refs']=[]
            c.write_draft(sb,sid,draft); c.make_receipt(sb,sid,ordinal=n); c.make_seal_approval(sb,sid,ordinal=n)
            if c.seal_transaction(sb,sid).get('state') != 'SEALED': raise RuntimeError(f'D seal {n} failed')
            ev=events(sb); reveals=[x for x in ev if x['event_type']==c.c2.REVEAL]
            for k,r in enumerate(reveals,1):
                if c.prove_attempt_history(sb,sid,k,gate=f'G-D-CHAIN-{n}-{k}',events=ev,reveal=r)['seal_bound'] is None: raise RuntimeError('D history missing')
            trace.append({'ordinal':n,'prefix_events':len(ev),'prerequisite':'PASS','authorization':'PASS','append':'PASS','seal':'PASS','history_prefixes':n})
        return trace
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
    contract=ordinal_contract_matrix()
    loops=constructive_progressive_loop()
    same_chain=same_chain_progressive_loop()
    c.semantic_replay(ROOT,SID)
    recovered=recovery_matrix()
    return {'d':'PASS','contract':contract,'loops':loops,'same_chain':same_chain,'prefixes':prefixes,'recovery_checkpoints':recovered,'recovery_count':len(recovered),'semantic_replay':'PASS','chain':types}
if __name__=='__main__': print(json.dumps(verify(),sort_keys=True,separators=(',',':')))
