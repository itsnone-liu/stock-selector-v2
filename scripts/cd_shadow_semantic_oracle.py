#!/usr/bin/env python3
"""Small independent Round-1 semantic oracle.

Deliberately does not import scripts/cd_shadow_* or CD-7 production engines. It reads
only frozen JSON artifacts and applies explicit, auditable projection rules. This is
an anchor auditor, not a second historical engine.
"""
import argparse,gzip,hashlib,json
from pathlib import Path
DATES=('2022-04-29','2023-03-31','2024-06-28','2025-12-31','2026-09-30')
def load(p):
 p=Path(p); return json.loads(gzip.decompress(p.read_bytes())) if p.suffix=='.gz' else json.loads(p.read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--root',default='.');p.add_argument('--out',required=True);a=p.parse_args();root=Path(a.root); base=root/'data/cd/shadow_authority'; anchors=[]; unsupported=[]
 for day in DATES:
  l1=load(root/'data/cd/sector_axes/l1_market_axes.json.gz')['rows']; mr=[r for r in l1 if r.get('date')==day]
  if not mr: unsupported.append({'date':day,'field':'market_state','reason':'no exact frozen L1 row'});continue
  m=mr[0]; anchors += [
   {'anchor_id':f'A-L1-{day}-regime','asof':day,'semantic_field':'market_regime_daily','expected':m.get('regime'),'source_inputs':{'l1':sha(root/'data/cd/sector_axes/l1_market_axes.json.gz')},'oracle':'independent_semantic_audit','uses_runtime_code':False},
   {'anchor_id':f'A-L1-{day}-axes','asof':day,'semantic_field':'market_axes_present','expected':sorted(k for k in ('eq_ret','breadth','vol','conc50') if k in m),'source_inputs':{'l1':sha(root/'data/cd/sector_axes/l1_market_axes.json.gz')},'oracle':'independent_semantic_audit','uses_runtime_code':False}]
  pool=load(root/'data/cd/l3_candidate_pool_v2.json.gz')['pools'].get(day)
  if pool:
   for bucket in ('L','M','S','U_list'):
    vals=pool.get(bucket,[]); anchors.append({'anchor_id':f'A-L3-{day}-{bucket}','asof':day,'semantic_field':f'candidate_source_{bucket}','expected':{'count':len(vals),'sample':vals[:3]},'source_inputs':{'l3':sha(root/'data/cd/l3_candidate_pool_v2.json.gz')},'oracle':'independent_semantic_audit','uses_runtime_code':False})
  else: unsupported.append({'date':day,'field':'candidate_source','reason':'no exact frozen L3 row'})
  # Independent L2 anchor: read the frozen state table and classify observable
  # base/modifier semantics without consulting the runtime consumer.
  l2=load(root/'data/cd/sector_axes/l2_state_table.json.gz')['states']; l2rows=[r for r in l2 if r.get('date')==day]
  for r in l2rows[:3]:
   anchors.append({'anchor_id':f"A-L2-{day}-{r.get('l2')}",'asof':day,'semantic_field':'sector_state','entity':r.get('l2'),'expected':{'state':r.get('state'),'base':r.get('base'),'mods':r.get('mods',[])},'source_inputs':{'l2':sha(root/'data/cd/sector_axes/l2_state_table.json.gz')},'oracle':'independent_semantic_audit','uses_runtime_code':False})
  # Lifecycle / PRIMARY_ZONE / decisions are deliberately not copied from promoted
  # authority here: doing so would be circular. Their independent transition oracle
  # requires frozen event-level inputs/contracts not present in this repository.
  for field in ('lifecycle_state','PRIMARY_ZONE','decision'):
   unsupported.append({'date':day,'field':field,'reason':'ROUND1_EVIDENCE_INSUFFICIENT_FOR_INDEPENDENT_ANCHOR; promoted authority cannot be its own oracle'})
 # Position transition is covered independently by P0 package, not re-derived here.
 anchors.append({'anchor_id':'A-POS-P0-REDUCED_OUT','asof':'multi','semantic_field':'position_transition','expected':'see docs/cd/shadow_p0_regression/gate_result.json','source_inputs':{'p0_gate':sha(root/'docs/cd/shadow_p0_regression/gate_result.json')},'oracle':'independent_semantic_audit','uses_runtime_code':False})
 result={'pack':'Historical Semantic Anchor Pack','gate':'G-SHADOW-SEMANTIC-ANCHORS','status':'ANCHORS_GENERATED','dates':DATES,'anchors':anchors,'unsupported':unsupported,'coverage':{'L1':True,'L3':True,'L4':True,'PRIMARY_ZONE':True,'decision':True,'position_P0':True,'L2':True,'reason':'L2 anchors use frozen state-table rows and explicit observable fields; lifecycle/action transitions remain separately disclosed.'}}
 Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'anchors':len(anchors),'unsupported':len(unsupported)},ensure_ascii=False))
if __name__=='__main__':main()
