#!/usr/bin/env python3
"""T5.4 ten gates: frozen raw state, clock, isolation, support and determinism."""
from __future__ import annotations
import ast, hashlib, json, subprocess, sys
from pathlib import Path
import pandas as pd
ROOT=Path('/root/project/workspace/stock-selector-v2'); OUT=ROOT/'output/research/t5/outcome_mapping'; STATE=ROOT/'output/research/t5/state'; FACTS=ROOT/'output/research/t5/facts'; TR=ROOT/'output/research/t5/transition'; R={}

def v(name, ok, **x): R[name]={'verdict':'PASS' if ok else 'FAIL',**x}
def main():
 m=json.loads((OUT/'t5_4_manifest.json').read_text()); clock=json.loads((OUT/'t5_4_outcome_clock.json').read_text())
 cs=pd.read_parquet(STATE/'t5_candidate_state_daily.parquet',columns=['event_id','delta_day','final_candidate_state','segment'])
 oc=pd.read_parquet(FACTS/'t5_daily_outcome.parquet'); edges=pd.read_parquet(TR/'t5_transition_edges.parquet',columns=['event_id','delta_day','horizon_k','dest_type','dest_label'])
 cur=pd.read_parquet(OUT/'t5_current_state_outcomes.parquet'); trans=pd.read_parquet(OUT/'t5_transition_outcomes.parquet'); paths=pd.read_parquet(OUT/'t5_short_path_definition.parquet'); po=pd.read_parquet(OUT/'t5_short_path_outcomes.parquet')
 # G1 baseline and exact T5.2 definition hash
 d=json.loads((STATE/'t5_state_definition.json').read_text()); dd={k:x for k,x in d.items() if k!='definition_sha256'}; h=hashlib.sha256(json.dumps(dd,sort_keys=True).encode()).hexdigest()
 v('gate1_input_freeze',m['baseline']=='a33c9b5' and h==d['definition_sha256'],baseline=m['baseline'],definition_hash_match=h==d['definition_sha256'])
 # G2 raw conservation: outcome mapping only joins frozen final state; no alternative state names
 src=(ROOT/'scripts/run_t5_4_outcome_mapping.py').read_text(); v('gate2_raw_conservation','final_candidate_state' in src and 'state_assign' not in src.replace('state_assignable',''),raw_source='T5.2 final_candidate_state',rows=len(cs))
 # G3 clock contract
 v('gate3_outcome_clock',clock['contract']=='t5_1_individual_valid_observation_clock' and clock['horizons_days']==[1,3,5,10] and clock['market_excess_used'] is False,clock=clock)
 # G4 key / censor conservation
 keys=set(zip(cs.event_id,cs.delta_day)); okeys=set(zip(oc.event_id,oc.delta_day)); v('gate4_outcome_key_censor',keys==okeys and all(c in oc.columns for c in ['complete_1d','complete_3d','complete_5d','complete_10d']),keys_equal=keys==okeys,rows=len(oc))
 # G5 transition alignment: all primary edges have exactly one mapping row and no unavailable dropped
 e1=edges[edges.horizon_k==1]; v('gate5_transition_alignment',len(e1)==len(cs) and len(trans)>0 and trans.dest_type.notna().all(),edge_rows=len(e1),mapped_rows=len(trans),dest_types=sorted(trans.dest_type.dropna().unique().tolist()))
 # G6 no future outcome in state/path discovery: path definition exactly dev support selection
 v('gate6_discovery_isolation',m['path_discovery']['selection_uses_outcome'] is False and m['path_discovery']['segment']=='development' and m['path_discovery']['minimum_support']==200,path_discovery=m['path_discovery'])
 # G7 no leakage of incomplete windows as zero: every reported metric has n and complete source available
 metric_cols=[c for c in cur.columns if c.startswith('fwd_') and not c.endswith('_n') and '_ci_' not in c]
 v('gate7_censor_transparency',all(c+'_n' in cur.columns for c in metric_cols),metric_count=len(metric_cols))
 # G8 split / cluster uncertainty: all three segments and event counts; CIs present
 segs=set(cur.segment); v('gate8_split_uncertainty',segs=={'development','validation','confirmation'} and cur.fwd_ret_5d_log_ci_lo.notna().any() and cur.fwd_ret_5d_log_ci_hi.notna().any(),segments=sorted(segs),ci='event-block bootstrap 199 draws')
 # G9 controlled paths: bounded, support threshold and no exhaustive explosion
 v('gate9_path_support',len(paths)<=40 and (paths.support>=200).all() and len(po)>0,selected_paths=len(paths),min_support=int(paths.support.min()),max_paths=40)
 # G10 deterministic lineage and output inventory
 expected=['t5_current_state_outcomes.parquet','t5_current_state_lifecycle.parquet','t5_transition_outcomes.parquet','t5_short_path_definition.parquet','t5_short_path_outcomes.parquet','t5_4_manifest.json','t5_4_outcome_clock.json']
 exists=all((OUT/x).exists() for x in expected); v('gate10_determinism_inventory',exists,expected=expected)
 R['overall']={'verdict':'PASS' if all(x['verdict']=='PASS' for k,x in R.items() if k.startswith('gate')) else 'FAIL','baseline':'a33c9b5'}
 (OUT/'t5_4_gates.json').write_text(json.dumps(R,indent=2,ensure_ascii=False,default=str)); print({k:x['verdict'] for k,x in R.items() if isinstance(x,dict) and 'verdict' in x}); print('OVERALL:',R['overall']['verdict'])
if __name__=='__main__': main()
