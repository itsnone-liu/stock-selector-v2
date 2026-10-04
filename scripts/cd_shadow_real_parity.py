#!/usr/bin/env python3
"""Run a declared historical parity matrix against real artifact adapters."""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.cd_shadow_real_adapters import RealArtifactAdapters

def run(root, cases):
 a=RealArtifactAdapters(Path(root)); out=[]
 for case in cases.get('dates', cases) if isinstance(cases, dict) else cases:
  day=case['date']; row={'date':day,'expected':case.get('expected',{}),'actual':{},'fields':{}}
  try:
   actual={'market_state':a.load_market_state(day),'sector_states':a.load_sector_states(day),'candidate_pool':a.load_candidate_pool(day),'episodes':a.load_episode_state(day),'lifecycle':a.load_lifecycle_state(day),'primary_zone':a.derive_primary_zone(day),'decisions':a.derive_frozen_decisions(day)}
   row['actual']=actual; row['status']='PARITY_PENDING_EXPECTED_AUTHORITY'
  except Exception as e:
   row['status']='PARITY_INPUT_MISSING'; row['error']={'type':type(e).__name__,'message':str(e)}
  out.append(row)
 return {'gate':'G-SHADOW-PARITY','status':'PARITY_PASS' if out and all(x['status']=='PARITY_PASS' for x in out) else 'PARITY_NOT_READY','cases':out}
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--matrix',required=True);p.add_argument('--out',required=True);a=p.parse_args(); r=run(a.root,json.loads(Path(a.matrix).read_text())); Path(a.out).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
