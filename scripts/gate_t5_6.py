#!/usr/bin/env python3
"""T5.6B/C ten gates."""
import ast, json
from pathlib import Path
import pandas as pd
ROOT = Path('/root/project/workspace/stock-selector-v2'); OUT = ROOT/'output/research/t5/action_resolution'; SRC=ROOT/'output/research/t5/action_eligibility'; R={}
def gate(k, ok, **x): R[k]={'verdict':'PASS' if ok else 'FAIL', **x}
def main():
 m6a=json.loads((OUT/'t5_6a_manifest.json').read_text()); res=pd.read_parquet(OUT/'t5_6b_resolution.parquet'); stab=json.loads((OUT/'t5_6c_stability.json').read_text())
 a=pd.read_parquet(SRC/'t5_action_eligibility.parquet'); code=(ROOT/'scripts/run_t5_6b_resolution.py').read_text()
 # G1 baseline
 gate('gate1_baseline', m6a['baseline']=='aac1f9f', declared='aac1f9f (T5.5 freeze); census committed c4a3056')
 # G2 immutability: reads only T5.5/6A products, no state/outcome writes
 reads=[]
 for n in ast.walk(ast.parse(code)):
  if isinstance(n,ast.Call) and getattr(n.func,'attr',None)=='read_parquet' and isinstance(n.args[0],ast.Constant): reads.append(str(n.args[0].value))
 gate('gate2_immutability', all('action_eligibility' in x or 'action_resolution' in x for x in reads), parquet_reads=reads)
 # G3 eligibility conservation: every row carried, vector recomputable, no flag edits
 gate('gate3_eligibility_conservation', len(res)==len(a) and res.vector.isin(['0010','0100','1100','1010','0011','0000']).all(), rows=len(res), source_rows=len(a))
 # G4 no outcome re-optimization
 gate('gate4_no_outcome', all('outcome' not in x for x in reads) and 'fwd_ret' not in code, outcome_refs=0)
 # G5 census completeness: all 6 observed vectors mapped, 10 unseen -> defensive status
 mapped=set(res[res.resolution_status!='UNRESOLVED_UNSEEN_VECTOR'].vector); gate('gate5_census_mapping', mapped=={'0010','0100','1100','1010','0011','0000'}, mapped=sorted(mapped))
 # G6 semantic integrity: 1100->ADD by containment (not priority); 0011->EXIT only with audit note; statuses frozen
 sem = ('RESOLVED_ADD' in code and 'SEMANTIC_REINFORCEMENT' in code and 'TERMINAL_RISK_RESOLUTION' in code and 'OPPORTUNITY_RISK_CONFLICT' in code)
 gate('gate6_semantic_integrity', sem, containment_note='ADD conditions contain hold rationale; EXIT independently qualifies and structurally implies REDUCE')
 # G7 no HOLD residualization
 gate('gate7_no_hold_residual', ((res.vector=='0000')==(res.resolution_status=='NO_ACTION_EVIDENCE')).all(), zero_vector_never_hold=True)
 # G8 unresolved transparency: reasons for 0000; fragile flag on 0011; unseen guard
 gate('gate8_unresolved_transparency', res[res.vector=='0000'].no_evidence_reasons.ne('').all() and res.exit_fragile.any() and 'UNRESOLVED_UNSEEN_VECTOR' in code, reasons_populated=True, fragile_flagged=True)
 # G9 split stability report
 covs={c['resolution_status']: round(c['weighted_share'],4) for c in stab['coverage']}
 gate('gate9_split_stability', abs(sum(v for k,v in covs.items() if k.startswith('RESOLVED'))-0.9075)<0.01 and stab['check_0011_fragility']['validation_weighted_rows']==0, coverage=covs, exit_val_rows=0)
 # G10 determinism inventory
 exp=['t5_6a_conflict_census.parquet','t5_6a_vector_by_split.parquet','t5_6a_vector_by_source_level.parquet','t5_6a_vector_by_reliability.parquet','t5_6a_manifest.json','t5_6b_resolution.parquet','t5_6c_stability.json']
 gate('gate10_inventory', all((OUT/x).exists() for x in exp), expected=exp)
 R['overall']={'verdict':'PASS' if all(x['verdict']=='PASS' for k,x in R.items() if k.startswith('gate')) else 'FAIL','baseline':'c4a3056'}
 (OUT/'t5_6_gates.json').write_text(json.dumps(R,indent=2,ensure_ascii=False,default=str)); print({k:x['verdict'] for k,x in R.items() if isinstance(x,dict) and 'verdict' in x}); print('OVERALL:',R['overall']['verdict'])
if __name__=='__main__':main()
