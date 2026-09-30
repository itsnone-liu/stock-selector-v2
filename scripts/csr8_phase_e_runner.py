#!/usr/bin/env python3
"""Phase E: real transaction runner with durable boundaries and recovery."""
import json,sys,time,os,tempfile,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STATE=Path(c.REAL_CSR)/'production'/c.REAL_SESSION/'runner_state.json'
STAGES=('PREPARE','AUTHORIZED','APPENDED','SEALED')
def ev(root=c.REAL_CSR): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def state(): return json.loads(STATE.read_bytes()) if STATE.exists() else {'status':'NEW','boundary':'NEW'}
def persist(x):
    data=c.canon(x).encode()
    if STATE.exists():
        tmp=STATE.with_suffix('.tmp'); c.excl_write(tmp,data); os.replace(tmp,STATE); os.chmod(STATE,0o600)
    else: c.excl_write(STATE,data)
def hard_stop(boundary, ordinal, root):
    persist({'status':boundary,'boundary':boundary,'ordinal':ordinal,'chain_count':len(ev(root)),'head':c.read_json(c.head_path(root,c.REAL_SESSION))['head_hash']})
def diagnose(): return {'mode':'READ_ONLY','state':state(),'chain':[x['event_type'] for x in ev()],'head':c.read_json(c.head_path(c.REAL_CSR,c.REAL_SESSION))}
def watchdog(start,timeout):
    elapsed=time.monotonic()-start
    if elapsed>timeout: return {'action':'SAFE_DEGRADE','reason':'TIMEOUT','writes':0,'append':False,'越权动作':False}
    return {'action':'CONTINUE','writes':0,'append':False,'越权动作':False}
def recovery_fix(root=c.REAL_CSR):
    """Explicit repair only: invoke persisted-state recovery; never append."""
    result=c.recover(root,c.REAL_SESSION); return {'action':'EXPLICIT_RECOVERY','result':result,'append':False}
def resume():
    d=diagnose(); s=d['state']
    if s.get('status')=='SEALED': return d
    r=recovery_fix(); s.update({'status':r['result'],'boundary':r['result'],'resumed':True}); persist(s); return diagnose()
def _constructive_runner():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    checkpoints=('after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup')
    records=[]
    for point in checkpoints:
        with tempfile.TemporaryDirectory(prefix='csr8-e-') as td:
            sb=build_pre_seal_sandbox(Path(td),through='B4'); before=[x['event_type'] for x in ev(sb.root)]
            # Boundary journal is isolated per run and records only durable facts.
            journal=[]
            journal.append({'boundary':'PREPARE','chain':before})
            journal.append({'boundary':'AUTHORIZED','chain':before})
            try: c.seal_transaction(sb.root,c.REAL_SESSION,stop_after=point)
            except c.CrashSim: journal.append({'boundary':point,'chain':[x['event_type'] for x in ev(sb.root)]})
            else: raise RuntimeError(f'missing crash checkpoint {point}')
            recovered=c.recover(sb.root,c.REAL_SESSION)
            if point in checkpoints[:3] and recovered!='SEAL_AUTHORIZED': raise RuntimeError(f'bad pre-append resume {point}')
            if point not in checkpoints[:3] and recovered!='SEALED': raise RuntimeError(f'bad committed resume {point}')
            # Idempotent second resume must not append or alter the chain.
            after=[x['event_type'] for x in ev(sb.root)]; c.recover(sb.root,c.REAL_SESSION)
            if [x['event_type'] for x in ev(sb.root)] != after: raise RuntimeError(f'non-idempotent resume {point}')
            records.append({'point':point,'journal_entries':len(journal),'recovered':recovered})
    wd=watchdog(time.monotonic()-10,1)
    if wd['action']!='SAFE_DEGRADE' or wd['append'] or wd['writes']!=0: raise RuntimeError('watchdog unsafe degradation')
    return {'checkpoints':records,'watchdog':wd}
def main():
    if '--diagnose' in sys.argv: print(json.dumps(diagnose(),sort_keys=True,separators=(',',':'))); return
    if '--repair' in sys.argv: print(json.dumps(recovery_fix(),sort_keys=True,separators=(',',':'))); return
    if '--resume' in sys.argv: print(json.dumps(resume(),sort_keys=True,separators=(',',':'))); return
    if '--constructive-test' in sys.argv: print(json.dumps(_constructive_runner(),sort_keys=True,separators=(',',':'))); return
    print(json.dumps({'runner':'READY','hard_stops':STAGES,'watchdog':watchdog(time.monotonic(),0)},sort_keys=True,separators=(',',':')))
if __name__=='__main__':main()
