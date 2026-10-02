#!/usr/bin/env python3
"""Normalize raw TOP10 rows using only the declared registry policy."""
from __future__ import annotations
import argparse, hashlib, json, re, csv
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; RAW=ROOT/'data/csr8_national_capital/raw/holdings'; OUT=ROOT/'output/research/csr/national_capital'; REG=ROOT/'config/csr/national_actor_registry_v1.json'
def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--out',default='national_holdings_history.csv'); a=ap.parse_args(); reg=json.loads(REG.read_text()); actors={x['actor_id']:x for x in reg['actors']}; alias={v:x for x in reg['actors'] for v in x['aliases']}; wrappers=reg.get('matching_policy',{}).get('wrapper_rules',[])
 def match(name):
  if not name:return None
  if name in alias:return alias[name]
  for rule in wrappers:
   if re.search(rule['regex'],name):return actors.get(rule['actor_id'])
  return None
 rows=[]; files=sorted(RAW.glob('*.json'))
 for fp in files:
  mp=fp.with_suffix('.meta.json')
  if not mp.exists():continue
  m=json.loads(mp.read_text())
  if m.get('outcome')!='SUCCESS_NONEMPTY':continue
  src=(json.loads(fp.read_text()).get('response') or {}).get('sdltgd') or []; token=fp.stem.split('__',1)[0]; market,bare=token.split('_',1); stock_code=f'{market}.{bare}'
  for x in src:
   actor=match(x.get('HOLDER_NAME')); rows.append({'stock_code':stock_code,'report_period':x.get('END_DATE',m['request']['date'])[:10],'holder_rank':x.get('HOLDER_RANK'),'holder_name_raw':x.get('HOLDER_NAME'),'actor_id':actor['actor_id'] if actor else None,'shares':x.get('HOLD_NUM'),'holding_ratio':x.get('FREE_HOLDNUM_RATIO'),'change_shares':x.get('HOLD_NUM_CHANGE'),'publication_date':None,'available_date':None,'retrieved_at':m.get('retrieved_at'),'source_doc_id':None,'raw_sha256':m.get('sha256'),'table_complete':len(src)==10,'source_grade':'aggregated_unverified_publication','pit_status':'UNKNOWN_PENDING_PUBLICATION_JOIN'})
 OUT.mkdir(parents=True,exist_ok=True); path=OUT/a.out; fields=list(rows[0]) if rows else ['stock_code','report_period']
 with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(rows)
 manifest={'generated_at':now(),'raw_files':len(files),'normalized_rows':len(rows),'matched_actor_rows':sum(bool(x.get('actor_id')) for x in rows),'pit_status':'UNKNOWN_PENDING_PUBLICATION_JOIN','sha256':sha(path.read_bytes())};(OUT/'national_holdings_normalized_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(json.dumps(manifest,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
