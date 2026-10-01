#!/usr/bin/env python3
"""Phase E production runner: boundary-driven cycle, watchdog, recovery CLI."""
import argparse,json,os,sys,time,tempfile,subprocess
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
 if time.monotonic()-start>timeout: s.update(status='SAFE_DEGRADED',watchdog={'reason':'TIMEOUT','writes':0,'append':False}); write_state(root,s)
 return s
def worker(root,crash):
 try: print(json.dumps({'kind':'ok','value':c.seal_transaction(root,c.REAL_SESSION,stop_after=crash)}),flush=True)
 except c.CrashSim as e: print(json.dumps({'kind':'crash','value':str(e)}),flush=True)
 except BaseException as e: print(json.dumps({'kind':'error','value':repr(e)}),flush=True)
def invoke(root,crash,timeout):
 """Run one seal step in a killable subprocess; None => safe-degraded."""
 started=time.monotonic()
 p=subprocess.Popen([sys.executable,__file__,'--worker','--root',str(root),*(('--crash',crash) if crash else ())],stdout=subprocess.PIPE,text=True)
 while p.poll() is None:
  watchdog(started,timeout,root)
  if read_state(root).get('status')=='SAFE_DEGRADED': p.kill(); p.wait(); return None
  time.sleep(0.01)
 line=p.stdout.readline().strip(); return json.loads(line) if line else {'kind':'error','value':'worker exited without result'}
def run(root,crash=None,timeout=300):
 root=Path(root); types=[e['event_type'] for e in events(root)]
 if not types or types[-1]!='REVEAL_PACKET': raise RuntimeError('supplied root must end with an open production REVEAL')
 persist(root,'PREPARE'); persist(root,'AUTHORIZED')
 msg=invoke(root,crash,timeout)
 if msg is None: return read_state(root)
 if msg['kind']=='crash': persist(root,msg['value']); return read_state(root)
 if msg['kind']=='error': raise RuntimeError(msg['value'])
 persist(root,'SEALED'); return msg['value'] or read_state(root)
def drive(root,timeout=300):
 """Full successful cycle driven boundary-by-boundary: the transaction is
 re-entered (pre-append boundaries are durable-write-free) and every passed
 HARD STOP is persisted before the next step; after_append is the first
 durable boundary, completion goes through frozen recover()."""
 root=Path(root); types=[e['event_type'] for e in events(root)]
 if not types or types[-1]!='REVEAL_PACKET': raise RuntimeError('supplied root must end with an open production REVEAL')
 persist(root,'PREPARE'); persist(root,'AUTHORIZED')
 for boundary in ('after_verify','after_derive','after_precondition','after_append'):
  msg=invoke(root,boundary,timeout)
  if msg is None: return read_state(root)
  if msg['kind']!='crash' or msg['value']!=boundary: raise RuntimeError(f'boundary drive failed at {boundary}: {msg}')
  persist(root,boundary)
 return resume(root)
def resume(root):
 s=read_state(root)
 if s.get('status')=='SAFE_DEGRADED': return s
 if s.get('resumed') and s.get('status')=='SEALED': return s
 result=c.recover(root,c.REAL_SESSION); s.update(status=result,recovery_count=s.get('recovery_count',0)+1); write_state(root,s)
 if result=='SEAL_AUTHORIZED': c.seal_transaction(root,c.REAL_SESSION); persist(root,'SEALED'); s=read_state(root); s.update(status='SEALED',resumed=True); write_state(root,s)
 else: s.update(resumed=True); write_state(root,s)
 return s
def diagnose(root): return {'mode':'READ_ONLY','state':read_state(root),'events':[e['event_type'] for e in events(root)]}
def repair(root):
 """Explicit recovery command: coordinates any partial transaction left by a
 crash or a watchdog kill through the frozen recovery path to a terminal state."""
 before=diagnose(root); result=c.recover(root,c.REAL_SESSION)
 s=read_state(root); s.update(status=result); s['journal'].append({'boundary':'REPAIR','phase':result}); write_state(root,s)
 if result=='SEAL_AUTHORIZED':
  c.seal_transaction(root,c.REAL_SESSION); result='SEALED'
  s=read_state(root); s.update(status=result,resumed=True); s['journal'].append({'boundary':'REPAIR','phase':'SEALED'}); write_state(root,s)
 return {'mode':'EXPLICIT_REPAIR','before':before,'result':result,'append':False}
def evidence():
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests')); from csr8_preseal_sandbox import build_pre_seal_sandbox
 matrix=[]
 for point in STOPS[2:-1]:
  with tempfile.TemporaryDirectory(prefix='csr8-e23-m-') as td:
   root=build_pre_seal_sandbox(Path(td),through='B4').root; s=run(root,point); before=len(s['journal']); s=resume(root)
   if s['status']!='SEALED' or resume(root)['status']!='SEALED' or before<3: raise RuntimeError(point)
   matrix.append({'point':point,'status':s['status'],'persisted':before})
 with tempfile.TemporaryDirectory(prefix='csr8-e23-d-') as td:
  root=build_pre_seal_sandbox(Path(td),through='B4').root; d=drive(root)
  order=[j['boundary'] for j in d['journal']]
  expected=['PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append']
  if d['status']!='SEALED' or order!=expected: raise RuntimeError(f'boundary drive: {order}')
  drive_result={'status':d['status'],'persisted_boundaries':order}
 with tempfile.TemporaryDirectory(prefix='csr8-e23-t-') as td:
  root=build_pre_seal_sandbox(Path(td),through='B4').root; s=run(root,None,timeout=0)
  if s['status']!='SAFE_DEGRADED' or s['watchdog']['writes'] or s['watchdog']['append']: raise RuntimeError('timeout degradation')
  r=repair(root); resumed=resume(root)
  if r['result']!='SEALED' or resumed['status']!='SEALED': raise RuntimeError('repair coordination')
  timeout_result={'degraded':s['status'],'watchdog':s['watchdog'],'repair':r['result'],'final':resumed['status']}
 return {'checkpoints':matrix,'boundary_drive':drive_result,'timeout_repair':timeout_result}
def main():
 a=argparse.ArgumentParser(); a.add_argument('--root',type=Path,default=c.REAL_CSR); a.add_argument('--run',action='store_true'); a.add_argument('--drive',action='store_true'); a.add_argument('--resume',action='store_true'); a.add_argument('--diagnose',action='store_true'); a.add_argument('--repair',action='store_true'); a.add_argument('--evidence',action='store_true'); a.add_argument('--worker',action='store_true'); a.add_argument('--crash'); a.add_argument('--timeout',type=float,default=300); x=a.parse_args()
 if x.worker: worker(x.root,x.crash); return
 if x.evidence: print(json.dumps(evidence(),sort_keys=True,separators=(',',':'))); return
 if x.run: print(json.dumps(run(x.root,x.crash,x.timeout),sort_keys=True,separators=(',',':'))); return
 if x.drive: print(json.dumps(drive(x.root,x.timeout),sort_keys=True,separators=(',',':'))); return
 if x.resume: print(json.dumps(resume(x.root),sort_keys=True,separators=(',',':'))); return
 if x.diagnose: print(json.dumps(diagnose(x.root),sort_keys=True,separators=(',',':'))); return
 if x.repair: print(json.dumps(repair(x.root),sort_keys=True,separators=(',',':'))); return
 print(json.dumps({'runner':'READY','hard_stops':STOPS,'commands':['--run','--drive','--resume','--diagnose','--repair','--evidence']},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
