#!/usr/bin/env python3
import argparse,json,os,sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
def state_path(root): return Path(root)/'runner_state.json'
def read_state(root): return json.loads(state_path(root).read_bytes()) if state_path(root).exists() else {'status':'NEW','journal':[]}
def write_state(root,x):
 p=state_path(root); t=p.with_suffix('.tmp'); t.write_bytes(c.canon(x).encode()); fd=os.open(t,os.O_RDONLY); os.fsync(fd); os.close(fd); os.replace(t,p); os.chmod(p,0o600); fd=os.open(p.parent,os.O_RDONLY); os.fsync(fd); os.close(fd)
def events(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def stop(root,name):
 s=read_state(root); s.update(status=name,chain_count=len(events(root))); s['journal'].append({'boundary':name,'events':[e['event_type'] for e in events(root)]}); write_state(root,s)
def watchdog(start,timeout,root):
 s=read_state(root); s['heartbeat']=time.time()
 if time.monotonic()-start>timeout: s.update(status='SAFE_DEGRADED',watchdog={'reason':'TIMEOUT','writes':0,'append':False}); write_state(root,s)
 return s
def run(root,crash=None):
 root=Path(root); ev=events(root); started=time.monotonic()
 if [e['event_type'] for e in ev]!=['REVEAL_PACKET','SEAL_ANNOTATION']: raise RuntimeError('supplied root must be runnable pre-cycle')
 watchdog(started,999999,root); stop(root,'PREPARE'); stop(root,'AUTHORIZED')
 if crash:
  try:c.seal_transaction(root,c.REAL_SESSION,stop_after=crash)
  except c.CrashSim: stop(root,crash); return read_state(root)
 return resume(root)
def resume(root):
 s=read_state(root)
 if s.get('resumed') and s.get('status') in ('SEALED','SEAL_AUTHORIZED'): return s
 result=c.recover(root,c.REAL_SESSION); s.update(status=result,resumed=True); write_state(root,s); return s
def evidence():
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests')); from csr8_preseal_sandbox import build_pre_seal_sandbox
 out=[]
 for p in STOPS[2:-1]:
  with tempfile.TemporaryDirectory(prefix='csr8-e15-') as td:
   root=build_pre_seal_sandbox(Path(td),through='B4').root; stop(root,'PREPARE'); stop(root,'AUTHORIZED')
   try:c.seal_transaction(root,c.REAL_SESSION,stop_after=p)
   except c.CrashSim: stop(root,p)
   s=resume(root); want='SEAL_AUTHORIZED' if p in STOPS[2:5] else 'SEALED'
   if s['status']!=want or resume(root)['status']!=want: raise RuntimeError(p)
   out.append({'point':p,'status':s['status'],'journal':len(s['journal'])})
 w=watchdog(time.monotonic()-10,1,Path(tempfile.mkdtemp(prefix='csr8-watch-'))); assert w['status']=='SAFE_DEGRADED' and w['watchdog']['writes']==0 and not w['watchdog']['append']; return out
def main():
 a=argparse.ArgumentParser(); a.add_argument('--root',type=Path,default=c.REAL_CSR); a.add_argument('--run',action='store_true'); a.add_argument('--resume',action='store_true'); a.add_argument('--evidence',action='store_true'); args=a.parse_args()
 if args.evidence: print(json.dumps({'checkpoints':evidence()},sort_keys=True,separators=(',',':'))); return
 if args.run: print(json.dumps(run(args.root),sort_keys=True,separators=(',',':'))); return
 if args.resume: print(json.dumps(resume(args.root),sort_keys=True,separators=(',',':'))); return
 print(json.dumps({'runner':'READY','hard_stops':STOPS},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
