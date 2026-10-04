#!/usr/bin/env python3
"""Exact-byte promotion transaction: pilot authority -> formal authority."""
import argparse,hashlib,json,shutil
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--pilot',required=True);p.add_argument('--formal',required=True);p.add_argument('--out',required=True);a=p.parse_args(); pilot=Path(a.pilot); formal=Path(a.formal); rows=[]
 for src in sorted(pilot.rglob('*')):
  if not src.is_file():continue
  rel=src.relative_to(pilot); dst=formal/rel; dst.parent.mkdir(parents=True,exist_ok=True)
  b=src.read_bytes()
  if dst.exists() and dst.read_bytes()!=b: raise SystemExit(f'promotion byte conflict: {dst}')
  if not dst.exists(): dst.write_bytes(b)
  rows.append({'path':str(rel),'pilot_sha256':sha(src),'formal_sha256':sha(dst),'exact_bytes':src.read_bytes()==dst.read_bytes()})
 result={'transaction':'SHADOW_AUTHORITY_EXACT_BYTE_PROMOTION','status':'PROMOTED' if rows and all(x['exact_bytes'] and x['pilot_sha256']==x['formal_sha256'] for x in rows) else 'NOT_READY','files':rows}
 Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result['status']=='PROMOTED' else 2)
if __name__=='__main__':main()
