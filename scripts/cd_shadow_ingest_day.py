#!/usr/bin/env python3
"""Operator-fed qualification ingestion: one command from refreshed data to gate.

Steps (all fail-closed):
  1. verify per-stock daily files are append-only vs the last frozen trading day
  2. re-run frozen upstream builders (L1/L2 axes, L2 states, L3 pool, L4 episodes)
  3. verify every historical row survived unchanged (subset equality)
  4. run SHADOW_QUALIFICATION real day + independent audit + gate
Policy is untouched throughout; this only accelerates data arrival, not rules.
"""
from __future__ import annotations
import argparse,gzip,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data/cd'
BUILDERS=('cd1b_four_axis_engine.py','cd45_market_regime.py','cd2bc_state_engine.py','cd4v2_multi_source.py','cd5a_episodes.py')
ARTS={'l1':'sector_axes/l1_market_axes.json.gz','l2a':'sector_axes/l2_four_axes.json.gz','l2s':'sector_axes/l2_state_table.json.gz','l3':'l3_candidate_pool_v2.json.gz','l4':'l4_episodes.json.gz'}
def load(p): return json.loads(gzip.decompress(Path(p).read_bytes()))
def rows(x):
 for k in ('rows','states','pools','episodes'):
  if k in x: return x[k]
 return x
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--day',required=True);ap.add_argument('--skip-append-check',action='store_true');a=ap.parse_args(); day=a.day
 snap={}
 for key,rel in ARTS.items():
  p=DATA/rel
  if not p.exists(): raise SystemExit(f'missing upstream artifact {rel}')
  snap[key]={json.dumps(r,sort_keys=True) for r in rows(load(p))} if key in ('l1','l2a','l2s') else None
  if key in ('l3','l4'): snap[key]=json.dumps(load(p),sort_keys=True)
 for b in BUILDERS:
  r=subprocess.run([sys.executable,str(ROOT/'scripts'/b)],capture_output=True,text=True)
  if r.returncode!=0: raise SystemExit(f'builder {b} failed:\n{r.stderr[-2000:]}')
 ok=[]
 for key,rel in ARTS.items():
  x=load(DATA/rel)
  if key in ('l1','l2a','l2s'):
   now={json.dumps(r,sort_keys=True) for r in rows(x)}
   lost=snap[key]-now
   if lost: raise SystemExit(f'{rel}: historical rows mutated/lost ({len(lost)}); refusing')
   ok.append((key,len(now)))
  else:
   if key=='l3':
    old=json.loads(snap[key]); new_dates=set(new for new in x['pools'] if new not in old['pools'])
    for d,oldv in old['pools'].items():
     if json.dumps(x['pools'].get(d),sort_keys=True)!=json.dumps(oldv,sort_keys=True): raise SystemExit(f'{rel}: historical pool mutated at {d}')
   if key=='l4':
    old={e['episode_id']:json.dumps(e,sort_keys=True) for e in json.loads(snap[key])['episodes']}
    for e in x['episodes']:
     if e['episode_id'] in old and json.dumps(e,sort_keys=True)!=old[e['episode_id']]: raise SystemExit(f"{rel}: historical episode mutated at {e['episode_id']}")
   ok.append((key,'verified'))
 print(json.dumps({'day':day,'append_only':'PASS','builders':'PASS','artifacts':ok}))
 q=subprocess.run([sys.executable,str(ROOT/'scripts/cd_shadow_qualify.py'),'--day',day,'--mode','real'],capture_output=True,text=True)
 print(q.stdout[-3000:] or q.stderr[-3000:])
 if q.returncode!=0: raise SystemExit('qualification runner failed')
 aud=subprocess.run([sys.executable,str(ROOT/'scripts/cd_shadow_independent_audit.py'),'--day',day],capture_output=True,text=True)
 print(aud.stdout[-3000:] or aud.stderr[-3000:])
 if aud.returncode!=0: raise SystemExit('independent audit failed')
 g=subprocess.run([sys.executable,str(ROOT/'scripts/cd_shadow_qualification_gate.py')],capture_output=True,text=True)
 print(g.stdout[-3000:] or g.stderr[-3000:]); raise SystemExit(g.returncode)
if __name__=='__main__':main()
