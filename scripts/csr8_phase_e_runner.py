#!/usr/bin/env python3
"""Production runner for the frozen CSR-8 transaction."""
import json,os,sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
def state_path(root): return Path(root)/'runner_state.json'
def read_state(root):
 p=state_path(root); return json.loads(p.read_bytes()) if p.exists() else {'status':'NEW','journal':[]}
def write_state(root,x):
 p=state_path(root); tmp=p.with_suffix('.tmp'); tmp.write_bytes(c.canon(x).encode()); os.replace(tmp,p); os.chmod(p,0o600)
def chain(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def checkpoint(root,name):
 s=read_state(root); s.update(status=name,last_event_count=len(chain(root))); s['journal'].append({'boundary':name,'chain_types':[e['event_type'] for e in chain(root)]}); write_state(root,s)
def watchdog(start,timeout,state):
 if time.monotonic()-start>timeout:
  x=dict(state); x.update(status='SAFE_DEGRADED',watchdog={'reason':'TIMEOUT','writes':0,'append':False}); return x
 return state
def production_cycle(root,crash_at=None):
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests')); from csr8_preseal_sandbox import build_pre_seal_sandbox
 sb=build_pre_seal_sandbox(Path(root),through='B4'); checkpoint(sb.root,'PREPARE'); checkpoint(sb.root,'AUTHORIZED')
 try: result=c.seal_transaction(sb.root,c.REAL_SESSION,stop_after=crash_at)
 except c.CrashSim: checkpoint(sb.root,crash_at); return sb.root
 checkpoint(sb.root,'SEALED'); return sb.root
def resume(root):
 s=read_state(root)
 if s.get('resumed'): return s
 result=c.recover(root,c.REAL_SESSION); s.update(status=result,resumed=True); write_state(root,s); return s
def constructive():
 cps=('after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup'); out=[]
 for p in cps:
  with tempfile.TemporaryDirectory(prefix='csr8-e7-') as td:
   root=production_cycle(Path(td)/'run',p); s=resume(root); expected='SEAL_AUTHORIZED' if p in cps[:3] else 'SEALED'
   if s['status']!=expected or resume(root)['status']!=expected: raise RuntimeError('resume '+p)
   out.append({'point':p,'status':s['status'],'journal':len(s['journal'])})
 w=watchdog(time.monotonic()-10,1,{'status':'RUNNING'}); assert w['status']=='SAFE_DEGRADED' and w['watchdog']['writes']==0 and not w['watchdog']['append']
 return out
def main():
 if '--constructive-test' in sys.argv: print(json.dumps({'checkpoints':constructive()},sort_keys=True,separators=(',',':'))); return
 print(json.dumps({'runner':'READY','hard_stops':STOPS,'watchdog':'SAFE_DEGRADE_ON_TIMEOUT'},sort_keys=True,separators=(',',':')))
if __name__=='__main__':main()
