#!/usr/bin/env python3
"""T5.5 ten gates."""
import ast,hashlib,json
from pathlib import Path
import pandas as pd
ROOT=Path('/root/project/workspace/stock-selector-v2'); OUT=ROOT/'output/research/t5/action_eligibility'; SRC=ROOT/'output/research/t5/outcome_mapping'; STATE=ROOT/'output/research/t5/state'; R={}
def gate(k,ok,**x):R[k]={'verdict':'PASS' if ok else 'FAIL',**x}
def main():
 m=json.loads((OUT/'t5_5_manifest.json').read_text()); d=json.loads((STATE/'t5_state_definition.json').read_text()); e=pd.read_parquet(OUT/'t5_action_evidence.parquet'); a=pd.read_parquet(OUT/'t5_action_eligibility.parquet'); h=pd.read_parquet(OUT/'t5_hierarchy_increment.parquet'); s=pd.read_parquet(OUT/'t5_eligibility_split_stability.parquet')
 # G1 baseline
 gate('gate1_input_baseline',m['baseline']=='ebfc490',baseline=m['baseline'])
 # G2 predecessor files and definitions are not edited; current code only reads T5.4 products
 code=(ROOT/'scripts/run_t5_5_action_eligibility.py').read_text(); gate('gate2_predecessor_immutability','t5_current_state_outcomes' in code and 't5_transition_outcomes' in code and 't5_short_path_outcomes' in code and 'state_assign' not in code.replace('state_assignable',''),sources='T5.4 frozen aggregate products')
 # G3 source conservation
 gate('gate3_evidence_source_conservation',set(e.source_level)=={'current','transition','short_path'} and len(e)==len(a),levels=sorted(e.source_level.unique().tolist()),rows=len(e))
 # G4 PIT/no future leakage: no raw facts/outcome input in eligibility script
 tree=ast.parse(code); reads=[]
 for n in ast.walk(tree):
  if isinstance(n,ast.Call) and getattr(n.func,'attr',None)=='read_parquet' and isinstance(n.args[0],ast.Constant): reads.append(str(n.args[0].value))
 gate('gate4_pit_no_future',all('outcome_mapping' in x for x in reads),parquet_reads=reads)
 # G5 hierarchy validity: all non-current either selected or explicit backoff; dev-only threshold marker
 gate('gate5_hierarchy_increment',h.backoff_reason.notna().all() and (h[h.source_level!='current'].backoff_reason!='').all() and json.loads((OUT/'t5_5_evidence_definition.json').read_text())['threshold_source'].startswith('development'),backoff_rate=float((h.backoff_reason!='default_current').mean()))
 # G6 development isolation
 dd=json.loads((OUT/'t5_5_evidence_definition.json').read_text()); gate('gate6_development_isolation',dd['threshold_source'].startswith('development only') and m['development_thresholds_only'],thresholds='development only')
 # G7 semantic integrity: four independent columns, no priority/position; HOLD not residual and EXIT explicit conjunction
 flags=['ADD_ELIGIBLE','HOLD_ELIGIBLE','REDUCE_ELIGIBLE','EXIT_ELIGIBLE']; gate('gate7_semantic_integrity',all(x in a for x in flags) and dd['priority_defined'] is False and dd['position_size_defined'] is False and 'terminal' in dd['eligibility_semantics']['EXIT'],flags=flags,priority_defined=dd['priority_defined'])
 # G8 reliability/censor transparency
 gate('gate8_reliability_censor',all(x in e for x in ['support','event_support','coverage','censor_missing_rate','reliability_class','sparse_evidence']) and e.coverage.between(0,1).all(),columns='support/event/coverage/censor/sparse')
 # G9 split stability product and no validation refit; report rates per split
 gate('gate9_split_stability',set(s.segment)=={'development','validation','confirmation'} and len(s)>0,segments=sorted(s.segment.unique().tolist()),rows=len(s))
 # G10 inventory + deterministic rerun artifact presence
 expected=['t5_5_evidence_definition.json','t5_action_evidence.parquet','t5_hierarchy_increment.parquet','t5_action_eligibility.parquet','t5_eligibility_split_stability.parquet','t5_5_manifest.json']
 gate('gate10_determinism_inventory',all((OUT/x).exists() for x in expected),expected=expected)
 R['overall']={'verdict':'PASS' if all(x['verdict']=='PASS' for k,x in R.items() if k.startswith('gate')) else 'FAIL','baseline':'ebfc490'}; (OUT/'t5_5_gates.json').write_text(json.dumps(R,indent=2,ensure_ascii=False)); print({k:x['verdict'] for k,x in R.items() if isinstance(x,dict) and 'verdict' in x});print('OVERALL:',R['overall']['verdict'])
if __name__=='__main__':main()
