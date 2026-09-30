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
    if STATE.exists(): STATE.write_bytes(data); os.chmod(STATE,0o600)
    else: c.excl_write(STATE,data)
def diagnose(): return {'mode':'READ_ONLY','state':state(),'chain':[x['event_type'] for x in ev()],'head':c.read_json(c.head_path(c.REAL_CSR,c.REAL_SESSION))}
def watchdog(start,timeout):
    if time.monotonic()-start>timeout:return {'action':'SAFE_DEGRADE','reason':'TIMEOUT','writes':0,'越权动作':False}
    return {'action':'CONTINUE','writes':0,'越权动作':False}
def recovery_fix(root=c.REAL_CSR):
    """Explicit repair only: invoke persisted-state recovery; never append."""
    result=c.recover(root,c.REAL_SESSION); return {'action':'EXPLICIT_RECOVERY','result':result,'append':False}
def resume():
    d=diagnose(); s=d['state']
    if s.get('status')=='SEALED': return d
    r=recovery_fix(); s.update({'status':r['result'],'boundary':r['result'],'resumed':True}); persist(s); return diagnose()
def _constructive_runner():
    """Run the real cycle on an isolated transaction-derived root, persisting
    each hard stop and exercising restart idempotence without touching live."""
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    with tempfile.TemporaryDirectory(prefix='csr8-e-') as td:
        sb=build_pre_seal_sandbox(Path(td),through='B4'); out=[]
        for stop in ('after_precondition','after_append'):
            try:c.seal_transaction(sb.root,c.REAL_SESSION,stop_after=stop)
            except c.CrashSim: out.append(stop)
            else: raise RuntimeError('runner crash boundary not reached')
            r=c.recover(sb.root,c.REAL_SESSION)
            out.append(r)
            if r not in ('SEAL_AUTHORIZED','SEALED'):raise RuntimeError('runner recovery failed')
        return out
def main():
    if '--diagnose' in sys.argv: print(json.dumps(diagnose(),sort_keys=True,separators=(',',':'))); return
    if '--repair' in sys.argv: print(json.dumps(recovery_fix(),sort_keys=True,separators=(',',':'))); return
    if '--resume' in sys.argv: print(json.dumps(resume(),sort_keys=True,separators=(',',':'))); return
    if '--constructive-test' in sys.argv: print(json.dumps({'boundaries':_constructive_runner()},sort_keys=True,separators=(',',':'))); return
    print(json.dumps({'runner':'READY','hard_stops':STAGES,'watchdog':watchdog(time.monotonic(),0)},sort_keys=True,separators=(',',':')))
if __name__=='__main__':main()
