#!/usr/bin/env python3
"""Phase E operational runner over an explicit transaction root."""
import json,os,sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
def state_path(root): return Path(root)/'runner_state.json'
def read_state(root): return json.loads(state_path(root).read_bytes()) if state_path(root).exists() else {'status':'NEW','journal':[]}
def write_state(root,obj):
 p=state_path(root); tmp=p.with_suffix('.tmp'); tmp.write_bytes(c.canon(obj).encode()); os.replace(tmp,p); os.chmod(p,0o600)
def events(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def hard_stop(root,name):
 s=read_state(root); s.update(status=name,chain_count=len(events(root))); s['journal'].append({'boundary':name,'events':[e['event_type'] for e in events(root)]}); write_state(root,s)
def watchdog(start,timeout): return {'status':'SAFE_DEGRADED','writes':0,'append':False,'reason':'TIMEOUT'} if time.monotonic()-start>timeout else {'status':'RUNNING','writes':0,'append':False}
def production_run(root=c.REAL_CSR, crash_at=None):
 root=Path(root); ev=events(root)
 if [e['event_type'] for e in ev]!=['REVEAL_PACKET','SEAL_ANNOTATION','REVEAL_PACKET','SEAL_ANNOTATION']:
  raise RuntimeError('production root is not a complete frozen cycle; refusing implicit fixture construction')
 if read_state(root).get('status')=='SEALED': return read_state(root)
 hard_stop(root,'PREPARE'); hard_stop(root,'AUTHORIZED')
 if crash_at:
  raise RuntimeError('production root is already sealed; refusing replay/append')
 return resume(root)

def resume(root=c.REAL_CSR):
 s=read_state(root)
 if s.get('resumed') and s.get('status') in ('SEALED','SEAL_AUTHORIZED'): return s
 result=c.recover(root,c.REAL_SESSION); s.update(status=result,resumed=True,recovery_count=s.get('recovery_count',0)+1); write_state(root,s); return s
def recovery_diagnose(root=c.REAL_CSR): return {'mode':'READ_ONLY','state':read_state(root),'events':[e['event_type'] for e in events(root)]}
def recovery_repair(root=c.REAL_CSR): return {'mode':'EXPLICIT_REPAIR','result':c.recover(root,c.REAL_SESSION),'append':False}
def constructive():
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests')); from csr8_preseal_sandbox import build_pre_seal_sandbox
 cps=('after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup'); out=[]
 for p in cps:
  with tempfile.TemporaryDirectory(prefix='csr8-e9-') as td:
   sb=build_pre_seal_sandbox(Path(td),through='B4'); hard_stop(sb.root,'PREPARE'); hard_stop(sb.root,'AUTHORIZED')
   try:c.seal_transaction(sb.root,c.REAL_SESSION,stop_after=p)
   except c.CrashSim: hard_stop(sb.root,p)
   want='SEAL_AUTHORIZED' if p in cps[:3] else 'SEALED'; s=resume(sb.root)
   if s['status']!=want or resume(sb.root)['status']!=want: raise RuntimeError(p)
   out.append({'point':p,'status':s['status']})
 assert watchdog(time.monotonic()-10,1)['status']=='SAFE_DEGRADED'; return out
def main():
 if '--constructive-test' in sys.argv: print(json.dumps({'constructive':constructive()},sort_keys=True,separators=(',',':'))); return
 if '--run-production' in sys.argv:
  crash=sys.argv[sys.argv.index('--run-production')+1] if len(sys.argv)>sys.argv.index('--run-production')+1 else None
  print(json.dumps(production_run(crash_at=crash),sort_keys=True,separators=(',',':'))); return
 if '--resume' in sys.argv: print(json.dumps(resume(),sort_keys=True,separators=(',',':'))); return
 if '--diagnose' in sys.argv: print(json.dumps(recovery_diagnose(),sort_keys=True,separators=(',',':'))); return
 if '--repair' in sys.argv: print(json.dumps(recovery_repair(),sort_keys=True,separators=(',',':'))); return
 print(json.dumps({'runner':'READY','hard_stops':STOPS},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
