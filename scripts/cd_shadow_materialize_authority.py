#!/usr/bin/env python3
"""Independent Round-1 historical authority materializer.

This producer is intentionally separate from the Shadow consumer. It only emits an
artifact when an explicitly supplied frozen producer returns a complete payload;
missing lifecycle/PRIMARY_ZONE/decision evidence fails closed rather than creating
circular expected artifacts.
"""
from __future__ import annotations
import argparse, hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
TYPES=('lifecycle','primary_zone','decisions')
PILOT=('2021-07-30','2022-04-29','2023-03-31','2024-06-28','2025-12-31','2026-09-30')

def canon(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def sha(b): return hashlib.sha256(b).hexdigest()
def load_json(p): return json.loads(Path(p).read_text())
def expected_manifest(day, kind, producer_commit, inputs, producer_code_sha):
 return {'asof':day,'artifact_type':kind,'authority_status':'ROUND1_FROZEN','producer_commit':producer_commit,'freeze_version':'round1-freeze-v1','input_artifacts':inputs,'input_sha256':{k:sha(Path(v).read_bytes()) for k,v in inputs.items()},'producer_code_sha256':producer_code_sha,'policy_mutation':False}
def materialize(day, out, supplied, producer_commit='2105cc3'):
 root=Path(out); root.mkdir(parents=True,exist_ok=True); statuses=[]
 for kind in TYPES:
  payload=supplied.get(kind)
  if payload is None:
   statuses.append({'date':day,'artifact_type':kind,'status':'AUTHORITY_MISSING','reason':'independent frozen producer payload not supplied'})
   continue
  if not isinstance(payload,dict) or payload.get('data_asof')!=day:
   statuses.append({'date':day,'artifact_type':kind,'status':'AUTHORITY_INVALID','reason':'payload must be mapping with exact data_asof'})
   continue
  body=payload.get('payload')
  if body is None: statuses.append({'date':day,'artifact_type':kind,'status':'AUTHORITY_INVALID','reason':'missing canonical payload'}); continue
  raw=canon(body)+b'\n'; path=root/kind/f'{day}.json.gz'; path.parent.mkdir(parents=True,exist_ok=True)
  import gzip; content=gzip.compress(raw,mtime=0)
  if path.exists() and path.read_bytes()!=content: raise RuntimeError(f'authority overwrite forbidden: {path}')
  if not path.exists(): path.write_bytes(content)
  meta=expected_manifest(day,kind,producer_commit,payload.get('input_artifacts',{}),payload.get('producer_code_sha256','unknown'))
  meta.update({'output_sha256':sha(content),'materialized_at':datetime.now(timezone.utc).isoformat()})
  mp=path.with_suffix('.manifest.json'); mp.write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
  statuses.append({'date':day,'artifact_type':kind,'status':'AUTHORITY_MATERIALIZED','path':str(path)})
 return statuses
def main():
 p=argparse.ArgumentParser(); p.add_argument('--day',choices=PILOT,required=True); p.add_argument('--out',default=str(ROOT/'data/cd/shadow_authority')); p.add_argument('--supplied',required=True); p.add_argument('--status-out',required=True); a=p.parse_args()
 result={'gate':'G-SHADOW-AUTHORITY','date':a.day,'statuses':materialize(a.day, a.out, load_json(a.supplied))}
 result['status']='AUTHORITY_PASS' if all(x['status']=='AUTHORITY_MATERIALIZED' for x in result['statuses']) else 'AUTHORITY_NOT_READY'
 Path(a.status_out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(result,ensure_ascii=False,indent=2)); raise SystemExit(0 if result['status']=='AUTHORITY_PASS' else 2)
if __name__=='__main__': main()
