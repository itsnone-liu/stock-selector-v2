#!/usr/bin/env python3
import csv,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; REG=ROOT/'config/csr/national_actor_registry_v1.json'; PIT=ROOT/'output/research/csr/national_capital/national_holdings_pit.csv'
def main():
 r=json.loads(REG.read_text()); actors={x['actor_id'] for x in r['actors']}; aliases={};dups=[]
 for a in r['actors']:
  for x in a['aliases']:
   if x in aliases and aliases[x]!=a['actor_id']:dups.append(x)
   aliases[x]=a['actor_id']
 wrappers=r.get('matching_policy',{}).get('wrapper_rules',[]); bad=[x for x in wrappers if x['actor_id'] not in actors]; rows=list(csv.DictReader(PIT.open())); report={'registry_sha256':hashlib.sha256(REG.read_bytes()).hexdigest(),'actor_count':len(actors),'alias_count':len(aliases),'wrapper_rule_count':len(wrappers),'duplicate_aliases':dups,'invalid_wrapper_targets':bad,'matched_actor_rows':sum(bool(x.get('actor_id')) for x in rows),'unmatched_holder_name_count':len({x['holder_name_raw'] for x in rows if not x.get('actor_id')}),'status':'PASS' if not dups and not bad else 'FAIL'}; (ROOT/'output/research/csr/national_capital/actor_registry_audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n'); print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
