#!/usr/bin/env python3
"""Normalize collected raw top-10 rows with deterministic actor mapping.

No publication-date inference is performed. Rows are explicitly UNKNOWN for PIT
until an announcement-date join is supplied.
"""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import csv
ROOT=Path(__file__).resolve().parents[1]; RAW=ROOT/'data/csr8_national_capital/raw/holdings'; OUT=ROOT/'output/research/csr/national_capital'; REG=ROOT/'config/csr/national_actor_registry_v1.json'
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--out',default='national_holdings_history.csv'); a=ap.parse_args()
 reg=json.loads(REG.read_text()); alias={v: x for x in reg['actors'] for v in x['aliases']}
 def match(name):
  if not name: return None
  if name in alias: return alias[name]
  # Deterministic semantic wrappers: fund/custodian prefixes around an explicit actor.
  if '中央汇金' in name: return next(x for x in reg['actors'] if x['actor_id']=='A1-HUIJIN')
  if '中国证券金融' in name: return next(x for x in reg['actors'] if x['actor_id']=='A1-ZHENGJIN')
  if '社保基金' in name or '社会保障基金' in name: return next(x for x in reg['actors'] if x['actor_id']=='A2-SSF')
  if '基本养老保险基金' in name: return next(x for x in reg['actors'] if x['actor_id']=='A2-PENSION')
  if '国家集成电路产业投资基金' in name: return next(x for x in reg['actors'] if x['actor_id']=='A1-BIGFUND')
  return None
 rows=[]; files=sorted(RAW.glob('*.json'))
 for fp in files:
  mp=fp.with_suffix('.meta.json')
  if not mp.exists(): continue
  m=json.loads(mp.read_text())
  if m.get('outcome')!='SUCCESS_NONEMPTY': continue
  d=json.loads(fp.read_text()); response=d.get('response') or {}; src=response.get('sdltgd') or []
  code,period=m['request']['code'].lower().split('.',1) if '.' in m['request']['code'].lower() else (m['request']['code'].lower()[:2],m['request']['code'][2:])
  # collector request is MARKET+CODE, recover canonical code from filename
  token=fp.stem.split('__',1)[0]; market,bare=token.split('_',1); stock_code=f'{market}.{bare}'
  for x in src:
   name=x.get('HOLDER_NAME'); actor=match(name)
   rows.append({'stock_code':stock_code,'report_period':x.get('END_DATE',m['request']['date'])[:10],'holder_rank':x.get('HOLDER_RANK'),'holder_name_raw':name,'actor_id':actor['actor_id'] if actor else None,'shares':x.get('HOLD_NUM'),'holding_ratio':x.get('FREE_HOLDNUM_RATIO'),'change_shares':x.get('HOLD_NUM_CHANGE'),'publication_date':None,'available_date':None,'retrieved_at':m.get('retrieved_at'),'source_doc_id':None,'raw_sha256':m.get('sha256'),'table_complete':len(src)==10,'source_grade':'aggregated_unverified_publication','pit_status':'UNKNOWN' if not actor or True else 'AVAILABLE_PIT'})
 OUT.mkdir(parents=True,exist_ok=True); path=OUT/a.out; fields=list(rows[0]) if rows else ['stock_code','report_period'];
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)
 manifest={'generated_at':now(),'raw_files':len(files),'normalized_rows':len(rows),'matched_actor_rows':sum(1 for x in rows if x.get('actor_id')),'pit_status':'UNKNOWN_PENDING_PUBLICATION_JOIN','sha256':sha(path.read_bytes())}; (OUT/'national_holdings_normalized_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
