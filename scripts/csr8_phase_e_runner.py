#!/usr/bin/env python3
"""E production runner command: cycle execution, resume, watchdog, recovery."""
import json,os,sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
def sp(root): return Path(root)/'runner_state.json'
def read(root): return json.loads(sp(root).read_bytes()) if sp(root).exists() else {'status':'NEW','journal':[]}
def write(root,x):
 p=sp(root); t=p.with_suffix('.tmp'); t.write_bytes(c.canon(x).encode()); os.replace(t,p); os.chmod(p,0o600)
def ev(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def hard_stop(root,name):
 s=read(root); s['status']=name; s['journal'].append({'boundary':name,'events':[e['event_type'] for e in ev(root)]}); write(root,s)
def watchdog(start,timeout):
 if time.monotonic()-start>timeout:return {'status':'SAFE_DEGRADED','writes':0,'append':False,'reason':'TIMEOUT'}
 return {'status':'RUNNING','writes':0,'append':False}
def run(root,crash):
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests')); from csr8_preseal_sandbox import build_pre_seal_sandbox
 sb=build_pre_seal_sandbox(Path(root),through='B4'); hard_stop(sb.root,'PREPARE'); hard_stop(sb.root,'AUTHORIZED')
 try:c.seal_transaction(sb.root,c.REAL_SESSION,stop_after=crash)
 except c.CrashSim: hard_stop(sb.root,crash); return sb.root
 hard_stop(sb.root,'SEALED'); return sb.root
def resume(root):
 s=read(root)
 if s.get('resumed'): return s
 s['status']=c.recover(root,c.REAL_SESSION); s['resumed']=True; write(root,s); return s
def recovery_diagnose(root): return {'mode':'READ_ONLY','state':read(root),'events':[e['event_type'] for e in ev(root)]}
def recovery_repair(root):
 d=recovery_diagnose(root); result=c.recover(root,c.REAL_SESSION); return {'mode':'EXPLICIT_REPAIR','before':d,'result':result,'append':False}
def constructive():
 cps=STOPS[2:-1]; out=[]
 for point in cps:
  with tempfile.TemporaryDirectory(prefix='csr8-e8-') as td:
   r=run(Path(td)/'run',point); first=resume(r); second=resume(r)
   want='SEAL_AUTHORIZED' if point in cps[:3] else 'SEALED'
   if first['status']!=want or second['status']!=want: raise RuntimeError(point)
   out.append({'point':point,'status':first['status'],'journal':len(first['journal'])})
 w=watchdog(time.monotonic()-10,1); assert w['status']=='SAFE_DEGRADED' and w['writes']==0 and not w['append']
 return out
if __name__=='__main__': print(json.dumps({'constructive':constructive(),'watchdog':watchdog(time.monotonic()-10,1)},sort_keys=True,separators=(',',':')))
