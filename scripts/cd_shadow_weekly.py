#!/usr/bin/env python3
"""Deterministic weekly Shadow health/drift/prospective cohort report scaffold."""
import argparse,json
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('--out',required=True);a=p.parse_args(); root=Path(a.root); days=[]
 for d in sorted(x for x in root.iterdir() if x.is_dir()):
  f=d/'run_manifest.json'
  if f.exists(): days.append(json.loads(f.read_text()))
 valid=sum(x.get('status')=='SHADOW_VALID' for x in days); invalid=len(days)-valid
 report={'status':'SHADOW_VALID' if invalid==0 else 'SHADOW_INVALID','valid_days':valid,'invalid_days':invalid,'accounting_gate_failures':sum(x.get('accounting_status')=='SHADOW_INVALID' for x in days),'determinism_failures':0,'structural_drift':{},'prospective_evidence':{'H5':{'matured_n':0},'H20':{'matured_n':0},'H60':{'matured_n':0}}}
 Path(a.out).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
