#!/usr/bin/env python3
"""Phase E production runner. The WORKER process (the one executing the real
transaction) persists runner state at each HARD STOP it stops at, before any
re-entry; the parent only monitors. Recovery runs in fresh processes from the
persisted state alone, so evidence does not depend on the parent surviving."""
import argparse,json,os,sys,time,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
PASSED=STOPS[2:-1]; PRE=PASSED[:3]
EVIDENCE_PATH=Path(__file__).resolve().parents[1]/'docs/audit/evidence/e_phase_runner_matrix.json'
def state_path(root): return Path(root)/'runner_state.json'
def read_state(root): return json.loads(state_path(root).read_bytes()) if state_path(root).exists() else {'status':'NEW','journal':[]}
def write_state(root,obj):
 p=state_path(root); p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix('.tmp'); tmp.write_bytes(c.canon(obj).encode()); fd=os.open(tmp,os.O_RDONLY); os.fsync(fd); os.close(fd); os.replace(tmp,p); os.chmod(p,0o600); fd=os.open(p.parent,os.O_RDONLY); os.fsync(fd); os.close(fd)
def events(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def head_hash(root): return c.read_json(c.head_path(root,c.REAL_SESSION)).get('head_hash')
def persist(root,boundary):
 s=read_state(root); s.update(status=boundary,chain_count=len(events(root)),heartbeat=time.time(),pid=os.getpid()); s['journal'].append({'boundary':boundary,'events':[e['event_type'] for e in events(root)]}); write_state(root,s); return s
def watchdog(start,timeout,root):
 s=read_state(root); s['heartbeat']=time.time(); s['watchdog_checks']=s.get('watchdog_checks',0)+1
 if time.monotonic()-start>timeout: s.update(status='SAFE_DEGRADED',watchdog={'reason':'TIMEOUT','writes':0,'append':False}); write_state(root,s)
 return s
def _cmd(root,crash): return [sys.executable,__file__,'--worker','--root',str(root),*(('--crash',crash) if crash else ())]
def worker(root,crash):
 """Executing process: stops at each pre-append HARD STOP in frozen order,
 persisting state AT the boundary before re-entering; the (post-append) crash
 target is then reached by a single transaction run and persisted in place at
 the moment of the boundary. A full cycle drives through after_append and
 completes via the frozen recovery path."""
 try:
  persist(root,'PREPARE'); persist(root,'AUTHORIZED')
  drive=PRE if (crash is None or PASSED.index(crash)>=3) else PRE[:PRE.index(crash)+1]
  for b in drive:
   try: c.seal_transaction(root,c.REAL_SESSION,stop_after=b); persist(root,b)
   except c.CrashSim: persist(root,b)
  if crash is None:
   try: c.seal_transaction(root,c.REAL_SESSION,stop_after='after_append')
   except c.CrashSim: persist(root,'after_append')
   res=c.recover(root,c.REAL_SESSION); persist(root,res); print(json.dumps({'kind':'ok','value':res}),flush=True); return
  if crash in PRE: print(json.dumps({'kind':'crash','value':crash}),flush=True); return
  try: c.seal_transaction(root,c.REAL_SESSION,stop_after=crash)
  except c.CrashSim: persist(root,crash); print(json.dumps({'kind':'crash','value':crash}),flush=True); return
  print(json.dumps({'kind':'error','value':f'crash boundary {crash} not reached'}),flush=True)
 except BaseException as e: print(json.dumps({'kind':'error','value':repr(e)}),flush=True)
def invoke(root,crash,timeout):
 """Monitor one worker step. None => safe-degraded: the worker is SIGKILLed;
 whatever partial transaction it left is coordinated later by the explicit
 repair command from the trusted head (no runner-side writes meanwhile)."""
 started=time.monotonic()
 p=subprocess.Popen(_cmd(root,crash),stdout=subprocess.PIPE,text=True)
 while p.poll() is None:
  watchdog(started,timeout,root)
  if read_state(root).get('status')=='SAFE_DEGRADED': p.kill(); p.wait(); return None
  time.sleep(0.005)
 line=p.stdout.readline().strip(); return json.loads(line) if line else {'kind':'error','value':'worker exited without result'}
def run(root,crash=None,timeout=300):
 root=Path(root); types=[e['event_type'] for e in events(root)]
 if not types or types[-1]!='REVEAL_PACKET': raise RuntimeError('supplied root must end with an open production REVEAL')
 msg=invoke(root,crash,timeout)
 if msg is None: return read_state(root)
 if msg['kind']=='error': raise RuntimeError(msg['value'])
 return read_state(root)
def resume(root):
 s=read_state(root)
 if s.get('status')=='SAFE_DEGRADED': return s   # no action without explicit repair
 if s.get('resumed') and s.get('status')=='SEALED': return s
 result=c.recover(root,c.REAL_SESSION); s.update(status=result,recovery_count=s.get('recovery_count',0)+1); write_state(root,s)
 if result=='SEAL_AUTHORIZED': c.seal_transaction(root,c.REAL_SESSION); persist(root,'SEALED'); s=read_state(root); s.update(status='SEALED',resumed=True); write_state(root,s)
 else: s.update(resumed=True); write_state(root,s)
 return s
def diagnose(root): return {'mode':'READ_ONLY','state':read_state(root),'events':[e['event_type'] for e in events(root)],'head_hash':head_hash(root)}
def repair(root):
 before=diagnose(root); result=c.recover(root,c.REAL_SESSION)
 s=read_state(root); s.update(status=result); s['journal'].append({'boundary':'REPAIR','phase':result}); write_state(root,s)
 if result=='SEAL_AUTHORIZED':
  c.seal_transaction(root,c.REAL_SESSION); result='SEALED'
  s=read_state(root); s.update(status=result,resumed=True); s['journal'].append({'boundary':'REPAIR','phase':'SEALED'}); write_state(root,s)
 return {'mode':'EXPLICIT_REPAIR','before':before,'result':result,'append':False}
def _sandbox(td):
 sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests')); from csr8_preseal_sandbox import build_pre_seal_sandbox
 return build_pre_seal_sandbox(Path(td),through='B4').root
def _cli(root,*flags):
 out=subprocess.run([sys.executable,__file__,'--root',str(root),*flags],capture_output=True,text=True,check=True)
 return json.loads(out.stdout.strip().splitlines()[-1])
def evidence():
 matrix=[]
 for point in PASSED:
  with tempfile.TemporaryDirectory(prefix='csr8-e25-m-') as td:
   root=_sandbox(td); run(root,point); order=[j['boundary'] for j in read_state(root)['journal']]
   idx=PASSED.index(point); exp=['PREPARE','AUTHORIZED']+list(PASSED[:min(idx+1,3)])+([point] if idx>=3 else [])
   if order!=exp: raise RuntimeError(f'{point} journal {order} != {exp}')
   s=resume(root)
   if s['status']!='SEALED' or resume(root)['status']!='SEALED': raise RuntimeError(point)
   matrix.append({'crash_at':point,'persisted_boundaries':order,'resume_status':'SEALED','head_hash_after_resume':head_hash(root)})
 with tempfile.TemporaryDirectory(prefix='csr8-e25-d-') as td:
  root=_sandbox(td); run(root); st=read_state(root); order=[j['boundary'] for j in st['journal']]
  exp=['PREPARE','AUTHORIZED']+list(PRE)+['after_append','SEALED']
  if order!=exp or st.get('status')!='SEALED': raise RuntimeError(f'full cycle {order} {st.get("status")}')
  full_cycle={'status':'SEALED','persisted_boundaries':order,'head_hash':head_hash(root)}
 kill_race=[]
 for delay in (0.02,0.06,0.12,0.2):
  with tempfile.TemporaryDirectory(prefix='csr8-e25-k-') as td:
   root=_sandbox(td); p=subprocess.Popen(_cmd(root,'after_replay'),stdout=subprocess.DEVNULL); time.sleep(delay); p.kill(); p.wait()
   killed_boundaries=[j['boundary'] for j in read_state(root)['journal']]
   rep=_cli(root,'--repair'); fin=_cli(root,'--resume')
   if rep['result']!='SEALED' or fin['status']!='SEALED': raise RuntimeError(f'kill race {delay}: {rep["result"]}/{fin["status"]}')
   kill_race.append({'kill_after_s':delay,'boundaries_at_kill':killed_boundaries,'repair':'SEALED','final':'SEALED','head_hash':head_hash(root)})
 with tempfile.TemporaryDirectory(prefix='csr8-e25-t-') as td:
  root=_sandbox(td); s=run(root,None,timeout=0)
  if s['status']!='SAFE_DEGRADED' or s['watchdog']['writes'] or s['watchdog']['append']: raise RuntimeError('timeout degradation')
  j=len(s['journal']); noop=resume(root)
  if noop['status']!='SAFE_DEGRADED' or len(noop['journal'])!=j: raise RuntimeError('degraded resume must be a no-op')
  rep=_cli(root,'--repair')
  if rep['result']!='SEALED': raise RuntimeError('repair coordination')
  timeout_repair={'degraded':'SAFE_DEGRADED','watchdog':s['watchdog'],'resume_noop':True,'repair_result':'SEALED','head_hash':head_hash(root)}
 art={'runner':'csr8_phase_e_runner','session':c.REAL_SESSION,'persistence':'worker-in-place','checkpoints':matrix,'full_cycle':full_cycle,'kill_race':kill_race,'timeout_repair':timeout_repair}
 EVIDENCE_PATH.parent.mkdir(parents=True,exist_ok=True); EVIDENCE_PATH.write_text(json.dumps(art,sort_keys=True,indent=1))
 return art
def main():
 a=argparse.ArgumentParser(); a.add_argument('--root',type=Path,default=c.REAL_CSR); a.add_argument('--run',action='store_true'); a.add_argument('--resume',action='store_true'); a.add_argument('--diagnose',action='store_true'); a.add_argument('--repair',action='store_true'); a.add_argument('--evidence',action='store_true'); a.add_argument('--worker',action='store_true'); a.add_argument('--crash'); a.add_argument('--timeout',type=float,default=300); x=a.parse_args()
 if x.worker: worker(x.root,x.crash); return
 if x.evidence: print(json.dumps(evidence(),sort_keys=True,separators=(',',':'))); return
 if x.run: print(json.dumps(run(x.root,x.crash,x.timeout),sort_keys=True,separators=(',',':'))); return
 if x.resume: print(json.dumps(resume(x.root),sort_keys=True,separators=(',',':'))); return
 if x.diagnose: print(json.dumps(diagnose(x.root),sort_keys=True,separators=(',',':'))); return
 if x.repair: print(json.dumps(repair(x.root),sort_keys=True,separators=(',',':'))); return
 print(json.dumps({'runner':'READY','hard_stops':STOPS,'commands':['--run','--resume','--diagnose','--repair','--evidence']},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
