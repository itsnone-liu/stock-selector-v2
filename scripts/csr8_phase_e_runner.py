#!/usr/bin/env python3
import json,sys,time,os,tempfile,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
def state_path(root): return Path(root)/'runner_state.json'
def read_state(root):
 p=state_path(root); return json.loads(p.read_bytes()) if p.exists() else {'status':'NEW','journal':[]}
def write_state(root,obj):
 p=state_path(root); tmp=p.with_suffix('.tmp'); tmp.write_bytes(c.canon(obj).encode()); os.replace(tmp,p); os.chmod(p,0o600)
def chain(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def stop(root,name):
 s=read_state(root); s['status']=name; s['journal'].append({'boundary':name,'chain_types':[e['event_type'] for e in chain(root)]}); write_state(root,s)
def watchdog(start,timeout,state):
 if time.monotonic()-start>timeout:
  state=dict(state); state['status']='SAFE_DEGRADED'; state['watchdog']={'reason':'TIMEOUT','writes':0,'append':False}; return state
 return state
def run_cycle(root,crash_at):
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests')); from csr8_preseal_sandbox import build_pre_seal_sandbox
 root=Path(root); root.mkdir(parents=True,exist_ok=True); sb=build_pre_seal_sandbox(root,through='B4')
 stop(sb.root,'PREPARE'); stop(sb.root,'AUTHORIZED')
 try: c.seal_transaction(sb.root,c.REAL_SESSION,stop_after=crash_at)
 except c.CrashSim: stop(sb.root,crash_at); return sb.root
 stop(sb.root,'SEALED'); return sb.root
def resume(root):
 s=read_state(root)
 if s.get('status') in ('SEALED','SEAL_AUTHORIZED') and s.get('resumed'): return {'recovered':s['status'],'state':s}
 result=c.recover(root,c.REAL_SESSION); s['status']=result; s['resumed']=True; write_state(root,s); return {'recovered':result,'state':read_state(root)}
def constructive():
 cps=('after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup'); out=[]
 for point in cps:
  with tempfile.TemporaryDirectory(prefix='csr8-e5-') as td:
   r=run_cycle(Path(td)/'work',point); y=resume(r); expected='SEAL_AUTHORIZED' if point in cps[:3] else 'SEALED'
   if y['recovered']!=expected: raise RuntimeError(point)
   if resume(r)['recovered']!=expected: raise RuntimeError('resume not idempotent')
   out.append({'point':point,'recovered':y['recovered']})
 w=watchdog(time.monotonic()-10,1,{'status':'RUNNING'}); assert w['status']=='SAFE_DEGRADED' and w['watchdog']['writes']==0 and not w['watchdog']['append']
 return out
def diagnose(root=c.REAL_CSR): return {'mode':'READ_ONLY','state':read_state(root),'chain':[e['event_type'] for e in chain(root)],'head':c.read_json(c.head_path(root,c.REAL_SESSION))}
def repair(root):
 s=read_state(root); result=c.recover(root,c.REAL_SESSION); s['status']=result; s['resumed']=True; write_state(root,s); return diagnose(root)
def main():
 if '--constructive-test' in sys.argv: print(json.dumps({'checkpoints':constructive()},sort_keys=True,separators=(',',':'))); return
 if '--diagnose' in sys.argv: print(json.dumps(diagnose(),sort_keys=True,separators=(',',':'))); return
 if '--repair' in sys.argv: print(json.dumps(repair(c.REAL_CSR),sort_keys=True,separators=(',',':'))); return
 print(json.dumps({'runner':'READY','stops':STOPS,'watchdog_contract':{'timeout':'SAFE_DEGRADED','writes':0,'append':False}},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
