#!/usr/bin/env python3
"""Phase E production runner: explicit root, durable journal, recovery CLI."""
import argparse,json,os,sys,time,tempfile,threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
def state_path(root): return Path(root)/'runner_state.json'
def read_state(root): return json.loads(state_path(root).read_bytes()) if state_path(root).exists() else {'status':'NEW','journal':[]}
def write_state(root,obj):
 p=state_path(root); p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix('.tmp'); tmp.write_bytes(c.canon(obj).encode()); fd=os.open(tmp,os.O_RDONLY); os.fsync(fd); os.close(fd); os.replace(tmp,p); os.chmod(p,0o600); fd=os.open(p.parent,os.O_RDONLY); os.fsync(fd); os.close(fd)
def events(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def persist(root,boundary):
 s=read_state(root); s.update(status=boundary,chain_count=len(events(root)),heartbeat=time.time()); s['journal'].append({'boundary':boundary,'events':[e['event_type'] for e in events(root)]}); write_state(root,s); return s
def watchdog(start,timeout,root):
 s=read_state(root); s['heartbeat']=time.time(); s['watchdog_checks']=s.get('watchdog_checks',0)+1
 if time.monotonic()-start>timeout:
  s.update(status='SAFE_DEGRADED',watchdog={'reason':'TIMEOUT','writes':0,'append':False}); write_state(root,s)
 return s
def _seal_worker(root,crash,result):
 try: result.extend([('ok',c.seal_transaction(root,c.REAL_SESSION,stop_after=crash))])
 except c.CrashSim as e: result.extend([('crash',str(e))])
 except BaseException as e: result.extend([('error',repr(e))])
def run(root,crash=None,timeout=300):
 root=Path(root); types=[e['event_type'] for e in events(root)]
 if not types or types[-1]!='REVEAL_PACKET': raise RuntimeError('supplied root must end with an open production REVEAL')
 started=time.monotonic(); persist(root,'PREPARE'); persist(root,'AUTHORIZED')
 result=[]; t=threading.Thread(target=_seal_worker,args=(root,crash,result),daemon=True); t.start()
 while t.is_alive():
  watchdog(started,timeout,root)
  if read_state(root).get('status')=='SAFE_DEGRADED':
   t.join(timeout=0.2); return read_state(root)
  time.sleep(0.01)
 t.join(); kind,value=result[0] if result else ('error','worker exited without result')
 if kind=='crash': persist(root,value); return read_state(root)
 if kind=='error': raise RuntimeError(value)
 persist(root,'SEALED'); return value or read_state(root)
def resume(root):
 s=read_state(root)
 if s.get('status')=='SAFE_DEGRADED': return s
 if s.get('resumed') and s.get('status')=='SEALED': return s
 result=c.recover(root,c.REAL_SESSION); s.update(status=result,recovery_count=s.get('recovery_count',0)+1); write_state(root,s)
 if result=='SEAL_AUTHORIZED':
  final=c.seal_transaction(root,c.REAL_SESSION); persist(root,'SEALED'); s=read_state(root); s.update(status='SEALED',resumed=True); write_state(root,s)
 else:
  s.update(resumed=True); write_state(root,s)
 return s
def diagnose(root): return {'mode':'READ_ONLY','state':read_state(root),'events':[e['event_type'] for e in events(root)]}
def repair(root):
 before=diagnose(root); result=c.recover(root,c.REAL_SESSION); return {'mode':'EXPLICIT_REPAIR','before':before,'result':result,'append':False}
def evidence():
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests')); from csr8_preseal_sandbox import build_pre_seal_sandbox
 out=[]
 for point in STOPS[2:-1]:
  with tempfile.TemporaryDirectory(prefix='csr8-e17-') as td:
   root=build_pre_seal_sandbox(Path(td),through='B4').root
   s=run(root,point); journal_before=len(s['journal']); s=resume(root); want='SEALED'
   if s['status']!=want or resume(root)['status']!=want or journal_before<3: raise RuntimeError(point)
   out.append({'point':point,'status':s['status'],'journal':len(s['journal']),'persisted_before_resume':journal_before})
 with tempfile.TemporaryDirectory(prefix='csr8-watch-') as td:
  root=build_pre_seal_sandbox(Path(td),through='B4').root; w=watchdog(time.monotonic()-10,1,root)
  assert w['status']=='SAFE_DEGRADED' and w['watchdog']['writes']==0 and not w['watchdog']['append']
 return {'checkpoints':out,'watchdog':'SAFE_DEGRADED'}
def main():
 a=argparse.ArgumentParser(); a.add_argument('--root',type=Path,default=c.REAL_CSR); a.add_argument('--run',action='store_true'); a.add_argument('--resume',action='store_true'); a.add_argument('--diagnose',action='store_true'); a.add_argument('--repair',action='store_true'); a.add_argument('--evidence',action='store_true'); args=a.parse_args()
 if args.evidence: print(json.dumps(evidence(),sort_keys=True,separators=(',',':'))); return
 if args.run: print(json.dumps(run(args.root),sort_keys=True,separators=(',',':'))); return
 if args.resume: print(json.dumps(resume(args.root),sort_keys=True,separators=(',',':'))); return
 if args.diagnose: print(json.dumps(diagnose(args.root),sort_keys=True,separators=(',',':'))); return
 if args.repair: print(json.dumps(repair(args.root),sort_keys=True,separators=(',',':'))); return
 print(json.dumps({'runner':'READY','hard_stops':STOPS},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
