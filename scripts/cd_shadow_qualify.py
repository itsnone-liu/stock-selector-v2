#!/usr/bin/env python3
"""SHADOW_QUALIFICATION daily runner.

Runs the frozen producer for a real as-of-T day, persists immutable traces, and
marks the day FOREVER_NON_EVIDENCE. Drill mode validates machinery on historical
dates and can never count toward qualification coverage.
"""
from __future__ import annotations
import argparse,gzip,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from scripts.cd_shadow_materialize_pilot import materialize_day, canon, sha, loadg
QUAL=ROOT/'data/cd/shadow_qualification'

def last_known_l1_date()->str:
 l1=loadg(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz')['rows']; return max(r['date'] for r in l1)

def run(day:str, mode:str):
 if mode=='real':
  lk=last_known_l1_date()
  if day<=lk: raise SystemExit(f'REAL qualification requires a genuinely future as-of day > last frozen L1 date {lk}; refusing')
 elif mode=='drill':
  lk=last_known_l1_date()
  if day>lk: raise SystemExit(f'DRILL requires an historical date with exact frozen inputs <= {lk}')
 else: raise SystemExit('mode must be real or drill')
 out=QUAL/day
 if (out/'qualification_snapshot.json').exists(): raise SystemExit(f'qualification snapshot already frozen for {day} (immutable)')
 summary,traces=materialize_day(day, out/'authority', collect_trace=True)
 tp=out/'traces.json.gz'; tp.parent.mkdir(parents=True,exist_ok=True); tp.write_bytes(gzip.compress(canon(traces)+b'\n',mtime=0))
 files={}
 for p in sorted((out/'authority').rglob('*.json.gz')): files[str(p.relative_to(out))]=sha(p.read_bytes())
 files['traces.json.gz']=sha(tp.read_bytes())
 snap={'gate':'G-SHADOW-ACTION-QUALIFICATION','day':day,'mode':mode,'runtime_mode':'SHADOW_QUALIFICATION','forever_non_evidence':True,'prospective_evidence_eligible':False,'orders_allowed':False,'capital_allowed':False,'policy_mutation':False,'producer_summary':summary,'trace_counts':{k:len(v) for k,v in traces.items()},'files_sha256':files}
 (out/'qualification_snapshot.json').write_text(json.dumps(snap,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(snap,ensure_ascii=False))

def main():
 p=argparse.ArgumentParser();p.add_argument('--day',required=True);p.add_argument('--mode',choices=('real','drill'),required=True);a=p.parse_args();run(a.day,a.mode)
if __name__=='__main__':main()
