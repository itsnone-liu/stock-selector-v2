#!/usr/bin/env python3
"""Phase E production runner, resume, watchdog, and recovery diagnostics."""
import json,time,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent)); import csr8_phase_c_annotation_seal as c
STATE=Path(c.REAL_CSR)/'production'/c.REAL_SESSION/'runner_state.json'
HARD_STOPS=('PREPARE','AUTHORIZED','APPENDED','SEALED')
def load_state():
    if not STATE.exists(): return {'status':'NEW','ordinal':0,'boundary':'NEW'}
    return json.loads(STATE.read_bytes())
def save_state(obj):
    c.excl_write(STATE,c.canon(obj).encode()) if not STATE.exists() else STATE.write_bytes(c.canon(obj).encode())
def diagnose():
    s=load_state(); ev=[json.loads(x) for x in c.log_path(c.REAL_CSR,c.REAL_SESSION).read_text().splitlines() if x.strip()]
    return {'mode':'READ_ONLY','state':s,'chain':[e['event_type'] for e in ev],'head':c.read_json(c.head_path(c.REAL_CSR,c.REAL_SESSION))}
def watchdog(start,timeout):
    elapsed=time.monotonic()-start
    if elapsed>timeout: return {'action':'SAFE_DEGRADE','reason':'TIMEOUT','越权动作':False}
    return {'action':'CONTINUE','越权动作':False}
def resume():
    d=diagnose(); s=d['state'];
    if s.get('status')=='SEALED': return d
    # Recovery is delegated to the frozen persisted-state classifier only.
    state=c.recover(c.REAL_CSR,c.REAL_SESSION)
    s.update({'status':state,'boundary':state,'resumed':True}); save_state(s); return diagnose()
def main():
    if '--diagnose' in sys.argv: print(json.dumps(diagnose(),sort_keys=True,separators=(',',':'))); return
    if '--resume' in sys.argv: print(json.dumps(resume(),sort_keys=True,separators=(',',':'))); return
    print(json.dumps({'runner':'READY','boundaries':HARD_STOPS,'watchdog':watchdog(time.monotonic(),0)},sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
