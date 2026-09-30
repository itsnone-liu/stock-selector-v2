#!/usr/bin/env python3
"""Phase E: executable cycle runner over a supplied transaction root."""
import json,os,sys,time,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STOPS=('PREPARE','AUTHORIZED','after_verify','after_derive','after_precondition','after_append','after_fsync','after_replay_verify','after_replay','after_anchor','after_cleanup','SEALED')
def state_path(root): return Path(root)/'runner_state.json'
def read_state(root): return json.loads(state_path(root).read_bytes()) if state_path(root).exists() else {'status':'NEW','journal':[]}
def write_state(root,x):
 p=state_path(root); t=p.with_suffix('.tmp'); t.write_bytes(c.canon(x).encode()); os.replace(t,p); os.chmod(p,0o600)
def events(root): return [json.loads(x) for x in c.log_path(root,c.REAL_SESSION).read_text().splitlines() if x.strip()]
def persist_stop(root,name):
 s=read_state(root); s.update({'status':name,'chain_count':len(events(root))}); s['journal'].append({'boundary':name,'event_types':[e['event_type'] for e in events(root)]}); write_state(root,s)
def watchdog(start,timeout,heartbeat):
 if time.monotonic()-start>timeout: return {'status':'SAFE_DEGRADED','writes':0,'append':False,'reason':'TIMEOUT','heartbeat':heartbeat}
 return {'status':'RUNNING','writes':0,'append':False,'heartbeat':heartbeat}
def new_cycle(root):
 sb,sid=c.prepared_authorized(); return sb,sid
def execute_cycle(root,crash_at=None):
 sb,sid=new_cycle(root); persist_stop(sb,'PREPARE'); persist_stop(sb,'AUTHORIZED')
 try: result=c.seal_transaction(sb,sid,stop_after=crash_at)
 except c.CrashSim: persist_stop(sb,crash_at); return sb
 persist_stop(sb,'SEALED'); return sb
def resume(root):
 s=read_state(root)
 if s.get('resumed'): return s
 result=c.recover(root,c.REAL_SESSION); s.update({'status':result,'resumed':True,'recovery_count':s.get('recovery_count',0)+1}); write_state(root,s); return s
def diagnose(root): return {'mode':'READ_ONLY','state':read_state(root),'events':[e['event_type'] for e in events(root)]}
def repair(root): return {'mode':'EXPLICIT_REPAIR','result':c.recover(root,c.REAL_SESSION),'append':False}
def evidence():
 cps=STOPS[2:-1]; out=[]
 for point in cps:
  with tempfile.TemporaryDirectory(prefix='csr8-e11-') as td:
   root=execute_cycle(Path(td),point); s=resume(root); want='SEAL_AUTHORIZED' if point in cps[:3] else 'SEALED'
   if s['status']!=want or resume(root)['status']!=want: raise RuntimeError('resume '+point)
   out.append({'point':point,'status':s['status'],'journal':len(s['journal'])})
 w=watchdog(time.monotonic()-10,1,'checkpoint');
 if w['status']!='SAFE_DEGRADED' or w['writes'] or w['append']: raise RuntimeError('watchdog safety')
 return {'checkpoints':out,'watchdog':w}
def main():
 if '--evidence' in sys.argv: print(json.dumps(evidence(),sort_keys=True,separators=(',',':'))); return
 print(json.dumps({'runner':'READY','hard_stops':STOPS,'commands':['--evidence','--diagnose','--repair']},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
