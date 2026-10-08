#!/usr/bin/env python3
"""R2-DU(G): daily update orchestrator — ONE command from TDX mirror to report.

Chain (fail-closed, idempotent per step; logs to data/r2/daily_update/):
  0. preconditions: TDX mirror has bars for --day; repo clean-ish
  A. daily_price_update  — tencent fqkline append + TDX cross-validate
  C. axes roll           — cd1b(L2) → cd45(L1) → cd2bc → cd4v2 → cd5a
                          with subset-equality check (history rows must survive)
  E. current_scan        — full rerun → data/r2/scans/current_scan_<day>.json
  F. daily_report        — migration diff + cross stats + BROKEN queue

Usage: .venv/bin/python src/r2/daily_update.py --day 2026-10-08 [--skip A,C,E,F]
Exit code !=0 on any failure; manifest at data/r2/daily_update/update_<day>.json
"""
from __future__ import annotations
import argparse,gzip,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DATA=ROOT/'data'; OUTD=ROOT/'data/r2/daily_update'
PY=str(ROOT/'.venv/bin/python')
BUILDERS=[('C1','scripts/cd1b_four_axis_engine.py'),('C2','scripts/cd45_market_regime.py'),
          ('C3','scripts/cd2bc_state_engine.py'),('C4','scripts/cd4v2_multi_source.py'),
          ('C5','scripts/cd5a_episodes.py')]
ARTS={'l2_four_axes':'data/cd/sector_axes/l2_four_axes.json.gz','l1_market_axes':'data/cd/sector_axes/l1_market_axes.json.gz',
      'l2_state_table':'data/cd/sector_axes/l2_state_table.json.gz','l3_pool':'data/cd/l3_candidate_pool_v2.json.gz',
      'l4_episodes':'data/cd/l4_episodes.json.gz'}
# lifecycle tables: open rows legitimately extend (end/seq mutate) -> check KEY survival, not serialization
KEYED={'l4_episodes':lambda r:(r.get('episode_id'),),
       'l3_pool':lambda r:(r.get('code'),r.get('ym') or r.get('month') or '')}

def rows_of(p):
 x=json.loads(gzip.decompress(Path(p).read_bytes()))
 for k in ('rows','states','pools','episodes'):
  if k in x: return x[k]
 return x

def tdx_has_day(day):
 import struct
 p=Path('/root/tdx_data/vipdoc/sz/lday/sz000001.day')
 b=p.read_bytes(); return any(struct.unpack('<I',b[i*32:i*32+4])[0]==int(day.replace('-','')) for i in range(len(b)//32-3,len(b)//32))

def run(step,cmd):
 t0=time.time()
 r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True)
 ok=r.returncode==0
 print(f'[{step}] {"OK" if ok else "FAIL"} {time.time()-t0:.0f}s',flush=True)
 (OUTD/f'step_{step}.log').write_text(r.stdout[-20000:]+r.stderr[-8000:])
 return ok

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--day',required=True)
 ap.add_argument('--skip',default='',help='comma list of A,C,E,F')
 a=ap.parse_args(); skip=set(a.skip.split(','))
 OUTD.mkdir(parents=True,exist_ok=True)
 day=a.day
 if not tdx_has_day(day): raise SystemExit(f'TDX mirror has no bars for {day} — sync not done?')
 # snapshot axes for subset-equality check
 old={}
 for k,rel in ARTS.items():
  p=ROOT/rel
  if p.exists(): old[k]={json.dumps(r,sort_keys=True) for r in rows_of(p)}
 if 'A' not in skip:
  if not run('A',[PY,'src/r2/daily_price_update.py','--day',day]): raise SystemExit('A failed')
 if 'C' not in skip:
  for tag,script in BUILDERS:
   if not run(tag,[PY,script]): raise SystemExit(f'{tag} failed')
  for k,rel in ARTS.items():
   newr=rows_of(ROOT/rel)
   if k in KEYED:
    kf=KEYED[k]; lost={kf(r) for r in old[k]}-{kf(r) for r in newr}
    kind='keys'
   else:
    lost=old[k]-{json.dumps(r,sort_keys=True) for r in newr}; kind='rows'
   if lost: raise SystemExit(f'HISTORY LOST in {k}: {len(lost)} {kind} vanished — aborting (files already rewritten; restore from git)')
 if 'E' not in skip:
  if not run('E',[PY,'src/r2/current_scan.py']): raise SystemExit('E failed')
 if 'F' not in skip:
  if not run('F',[PY,'src/r2/daily_report.py','--day',day]): raise SystemExit('F failed')
 print('DAILY UPDATE COMPLETE',day)
if __name__=='__main__':main()
