#!/usr/bin/env python3
"""Validate materialized authority provenance and REDUCED_OUT accounting anchors."""
import argparse,json,gzip
from pathlib import Path

def gate(root: Path, day: str):
 root=Path(root); checks={}; errors=[]
 for kind in ('lifecycle','primary_zone','decisions'):
  p=root/kind/f'{day}.json.gz'; m=p.with_suffix('.manifest.json')
  checks[f'{kind}_exists']=p.exists() and m.exists()
  if not checks[f'{kind}_exists']: errors.append(f'missing {kind} authority or manifest'); continue
  meta=json.loads(m.read_text()); checks[f'{kind}_frozen']=meta.get('authority_status')=='ROUND1_FROZEN' and meta.get('policy_mutation') is False
  checks[f'{kind}_hash']=meta.get('output_sha256')==__import__('hashlib').sha256(p.read_bytes()).hexdigest()
  if not checks[f'{kind}_frozen'] or not checks[f'{kind}_hash']: errors.append(f'invalid {kind} provenance')
 # P0 fixture must be explicit in decisions payload; absence is not silently PASS.
 p=root/'decisions'/f'{day}.json.gz'
 if p.exists():
  x=json.loads(gzip.decompress(p.read_bytes())); rows=x.get('decisions',x if isinstance(x,list) else [])
  p0=[r for r in rows if r.get('transition')=='REDUCED_OUT' or r.get('terminal_reason')=='REDUCED_OUT' or r.get('reason')=='REDUCED_OUT']
  checks['p0_reduced_out_fixture']=bool(p0) or x.get('p0_regression_checked') is True
  if not checks['p0_reduced_out_fixture']: errors.append('P0 REDUCED_OUT anchor absent')
 else: checks['p0_reduced_out_fixture']=False
 return {'gate':'G-SHADOW-AUTHORITY','status':'AUTHORITY_PASS' if not errors else 'AUTHORITY_NOT_READY','checks':checks,'errors':errors}
def main():
 p=argparse.ArgumentParser();p.add_argument('root');p.add_argument('day');a=p.parse_args();r=gate(Path(a.root),a.day);print(json.dumps(r,ensure_ascii=False,indent=2));raise SystemExit(0 if r['status']=='AUTHORITY_PASS' else 2)
if __name__=='__main__':main()
