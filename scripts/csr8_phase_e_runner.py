#!/usr/bin/env python3
"""Phase E production runner.

Write-separation contract (no cross-process state race):
  - runner_state.json is written ONLY by the worker process executing the
    real transaction — one fsynced record per HARD STOP, in place, before any
    re-entry.
  - watchdog_state.json is written ONLY by the monitoring parent (heartbeat,
    checks, SAFE_DEGRADED flag). The two files never share a writer, so the
    watchdog can never clobber recovery state.
Recovery (resume/repair) runs in fresh processes from persisted state alone."""
import argparse,json,os,sys,time,tempfile,subprocess
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
PASSED=STOPS[2:-1]; PRE=PASSED[:3]
EVIDENCE_PATH=Path(__file__).resolve().parents[1]/'docs/audit/evidence/e_phase_runner_matrix.json'
def state_path(root): return Path(root)/'runner_state.json'
def watch_path(root): return Path(root)/'watchdog_state.json'
def _read_json(p): return json.loads(p.read_bytes()) if p.exists() else None
def read_state(root): return _read_json(state_path(root)) or {'status':'NEW','journal':[]}
def read_watch(root): return _read_json(watch_path(root)) or {}
def _write(p,obj):
 p.parent.mkdir(parents=True,exist_ok=True); tmp=p.with_suffix('.tmp'); tmp.write_bytes(c.canon(obj).encode()); fd=os.open(tmp,os.O_RDONLY); os.fsync(fd); os.close(fd); os.replace(tmp,p); os.chmod(p,0o600); fd=os.open(p.parent,os.O_RDONLY); os.fsync(fd); os.close(fd)
def write_state(root,obj): _write(state_path(root),obj)
def write_watch(root,obj): _write(watch_path(root),obj)
def events(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def head_hash(root): return c.read_json(c.head_path(root,c.REAL_SESSION)).get('head_hash')
def persist(root,boundary):
 s=read_state(root); s.update(status=boundary,chain_count=len(events(root)),heartbeat=time.time(),pid=os.getpid()); s['journal'].append({'boundary':boundary,'events':[e['event_type'] for e in events(root)]}); write_state(root,s); return s
def degraded(root): return read_watch(root).get('status')=='SAFE_DEGRADED'
def view(root):
 s=read_state(root); w=read_watch(root); s['watchdog']=w
 if w.get('status')=='SAFE_DEGRADED': s['status']='SAFE_DEGRADED'
 return s
def watchdog(start,timeout,root):
 w=read_watch(root); w.update(heartbeat=time.time(),checks=w.get('checks',0)+1,pid=os.getpid())
 if time.monotonic()-start>timeout: w.update(status='SAFE_DEGRADED',reason='TIMEOUT',writes=0,append=False)
 write_watch(root,w); return w
def _cmd(root,crash): return [sys.executable,__file__,'--worker','--root',str(root),*(('--crash',crash) if crash else ())]
def _persist_seq(root,names):
 for n in names: persist(root,n)
def worker(root,crash):
 """Executing process. Persistence contract:
  - pre-append HARD STOPS are driven as authentic ladder stops (re-entry is
    legal there: no durable writes), each persisted at the boundary itself;
  - a run whose target is a post-append boundary CROSSES after_append first —
    the worker persists that crossed boundary plus the stopped boundary at the
    stop moment, from inside the executing process;
  - the normal complete cycle runs the transaction uninterrupted (crossing
    every declared stop) and the worker persists each crossed boundary plus
    SEALED at completion. Every journal record is written by the process that
    executed the transaction, never retro-actively by a parent."""
 try:
  persist(root,'PREPARE'); persist(root,'AUTHORIZED')
  idx=PASSED.index(crash) if crash in PASSED else None
  if idx is not None and idx<3:
   for b in PRE[:idx+1]:
    try: c.seal_transaction(root,c.REAL_SESSION,stop_after=b); persist(root,b)
    except c.CrashSim: persist(root,b)
   print(json.dumps({'kind':'crash','value':crash}),flush=True); return
  for b in PRE:
   try: c.seal_transaction(root,c.REAL_SESSION,stop_after=b); persist(root,b)
   except c.CrashSim: persist(root,b)
  if crash is None:
   c.seal_transaction(root,c.REAL_SESSION)
   _persist_seq(root,('after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED'))
   print(json.dumps({'kind':'ok','value':'SEALED'}),flush=True); return
  try: c.seal_transaction(root,c.REAL_SESSION,stop_after=crash)
  except c.CrashSim:
   persist(root,'after_append'); persist(root,crash)
   print(json.dumps({'kind':'crash','value':crash}),flush=True); return
  print(json.dumps({'kind':'error','value':f'crash boundary {crash} not reached'}),flush=True)
 except BaseException as e: print(json.dumps({'kind':'error','value':repr(e)}),flush=True)
def invoke(root,crash,timeout):
 started=time.monotonic()
 p=subprocess.Popen(_cmd(root,crash),stdout=subprocess.PIPE,text=True)
 while p.poll() is None:
  watchdog(started,timeout,root)
  if degraded(root): p.kill(); p.wait(); return None
  time.sleep(0.005)
 line=p.stdout.readline().strip(); return json.loads(line) if line else {'kind':'error','value':'worker exited without result'}
def run(root,crash=None,timeout=300):
 root=Path(root); types=[e['event_type'] for e in events(root)]
 if not types or types[-1]!='REVEAL_PACKET': raise RuntimeError('supplied root must end with an open production REVEAL')
 msg=invoke(root,crash,timeout)
 if msg is None: return view(root)
 if msg['kind']=='error': raise RuntimeError(msg['value'])
 return view(root)
def resume(root):
 v=view(root)
 if v.get('status')=='SAFE_DEGRADED': return v          # no action without explicit repair
 s=read_state(root)
 if s.get('resumed') and s.get('status')=='SEALED': return view(root)
 result=c.recover(root,c.REAL_SESSION); s.update(status=result,recovery_count=s.get('recovery_count',0)+1); write_state(root,s)
 if result=='SEAL_AUTHORIZED': c.seal_transaction(root,c.REAL_SESSION); persist(root,'SEALED'); s=read_state(root); s.update(status='SEALED',resumed=True); write_state(root,s)
 else: s.update(resumed=True); write_state(root,s)
 return view(root)
def diagnose(root): return {'mode':'READ_ONLY','runner':read_state(root),'watchdog':read_watch(root),'events':[e['event_type'] for e in events(root)],'head_hash':head_hash(root)}
def repair(root):
 before=diagnose(root); result=c.recover(root,c.REAL_SESSION)
 s=read_state(root); s.update(status=result); s['journal'].append({'boundary':'REPAIR','phase':result}); write_state(root,s)
 if result=='SEAL_AUTHORIZED':
  c.seal_transaction(root,c.REAL_SESSION); result='SEALED'
  s=read_state(root); s.update(status=result,resumed=True); s['journal'].append({'boundary':'REPAIR','phase':'SEALED'}); write_state(root,s)
 w=read_watch(root); w.update(status='REPAIRED',repaired_at=time.time()); write_watch(root,w)
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
  with tempfile.TemporaryDirectory(prefix='csr8-e26-m-') as td:
   root=_sandbox(td); run(root,point); order=[j['boundary'] for j in read_state(root)['journal']]
   idx=PASSED.index(point)
   exp=['PREPARE','AUTHORIZED']+list(PASSED[:min(idx+1,3)])+((['after_append',point]) if idx>=3 else [])
   if order!=exp: raise RuntimeError(f'{point} journal {order} != {exp}')
   s=resume(root); j1=len(read_state(root)['journal']); rc1=read_state(root).get('recovery_count')
   s2=resume(root); j2=len(read_state(root)['journal']); rc2=read_state(root).get('recovery_count')
   if s['status']!='SEALED' or s2['status']!='SEALED' or (j1,rc1)!=(j2,rc2): raise RuntimeError(f'{point} resume idempotence')
   matrix.append({'crash_at':point,'persisted_boundaries':order,'resume_status':'SEALED','idempotent':True,'head_hash_after_resume':head_hash(root)})
 with tempfile.TemporaryDirectory(prefix='csr8-e26-d-') as td:
  root=_sandbox(td); run(root); st=read_state(root); order=[j['boundary'] for j in st['journal']]
  exp=['PREPARE','AUTHORIZED']+list(PRE)+['after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED']
  if order!=exp or st.get('status')!='SEALED': raise RuntimeError(f'full cycle {order} {st.get("status")}')
  if not watch_path(root).exists(): raise RuntimeError('watchdog never ran')
  full_cycle={'status':'SEALED','persisted_boundaries':order,'head_hash':head_hash(root),'watchdog_checks':read_watch(root).get('checks')}
 kill_race=[]
 for delay in (0.02,0.06,0.12,0.2):
  with tempfile.TemporaryDirectory(prefix='csr8-e26-k-') as td:
   root=_sandbox(td); p=subprocess.Popen(_cmd(root,'after_replay'),stdout=subprocess.DEVNULL); time.sleep(delay); p.kill(); p.wait()
   killed=[j['boundary'] for j in read_state(root)['journal']]
   direct=_cli(root,'--resume'); again=_cli(root,'--resume')
   if direct['status']!='SEALED' or again['status']!='SEALED': raise RuntimeError(f'kill race {delay}: {direct["status"]}/{again["status"]}')
   kill_race.append({'kill_after_s':delay,'boundaries_at_kill':killed,'direct_resume':'SEALED','idempotent':True,'head_hash':head_hash(root)})
 with tempfile.TemporaryDirectory(prefix='csr8-e26-t-') as td:
  root=_sandbox(td); v=run(root,None,timeout=0)
  if v['status']!='SAFE_DEGRADED' or v['watchdog'].get('writes') or v['watchdog'].get('append'): raise RuntimeError('timeout degradation')
  j=len(read_state(root)['journal']); noop=resume(root)
  if noop['status']!='SAFE_DEGRADED' or len(read_state(root)['journal'])!=j: raise RuntimeError('degraded resume must be a no-op')
  rep=_cli(root,'--repair')
  if rep['result']!='SEALED' or read_watch(root).get('status')!='REPAIRED': raise RuntimeError('repair coordination')
  timeout_repair={'degraded':'SAFE_DEGRADED','watchdog':{'writes':0,'append':False},'resume_noop':True,'repair_result':'SEALED','watch_status_after':'REPAIRED','head_hash':head_hash(root)}
 art={'runner':'csr8_phase_e_runner','session':c.REAL_SESSION,'persistence':'worker-in-place','write_separation':{'runner_state.json':'worker-only','watchdog_state.json':'monitor-only'},'checkpoints':matrix,'full_cycle':full_cycle,'kill_race':kill_race,'timeout_repair':timeout_repair}
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
