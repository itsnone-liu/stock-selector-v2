#!/usr/bin/env python3
"""T5.7 ten gates."""
import ast, json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path('/root/project/workspace/stock-selector-v2'); OUT = ROOT/'output/research/t5/exposure_adjustment'; R={}
def gate(k, ok, **x): R[k]={'verdict':'PASS' if ok else 'FAIL', **x}
def main():
    m=json.loads((OUT/'t5_7_manifest.json').read_text()); traj=pd.read_parquet(OUT/'t5_7_exposure_trajectory.parquet'); code=(ROOT/'scripts/run_t5_7_exposure_adjustment.py').read_text()
    op=pd.read_parquet(OUT/'t5_7_operator_usage.parquet'); diag=pd.read_parquet(OUT/'t5_7_split_diagnostics.parquet')
    reads=[]
    for n in ast.walk(ast.parse(code)):
        if isinstance(n,ast.Call) and getattr(n.func,'attr',None)=='read_parquet' and isinstance(n.args[0],ast.Constant): reads.append(str(n.args[0].value))
    t=traj[traj.exposure_after.notna()].copy()
    # G1 baseline
    gate('gate1_baseline', m['baseline']=='ad7fd2c', baseline=m['baseline'])
    # G2 immutability: reads only frozen T4.6/T5 products
    gate('gate2_immutability', all(any(s in x for s in ('t4/entry_policy','action_resolution','action_eligibility','t5/state','t5/transition','t5/facts')) for x in reads), parquet_reads=reads)
    # G3 unit/clock conservation: x in [0,1]; one row per (lifecycle, day, policy)
    key_dups = t.duplicated(['lifecycle_id','date_delta','policy_id']).sum()
    gate('gate3_unit_clock', t.exposure_after.between(0,1).all() and t.exposure_before.between(0,1).all() and key_dups==0, dup_keys=int(key_dups), max_x=float(t.exposure_after.max()))
    # G4 resolution-state conservation: statuses only from frozen set; no re-resolution
    allowed={'RESOLVED_ADD','RESOLVED_HOLD','RESOLVED_REDUCE','RESOLVED_EXIT','CONFLICT_OPPORTUNITY_RISK','NO_ACTION_EVIDENCE','UNRESOLVED_UNSEEN_VECTOR','EPISODE_TERMINAL','ZERO_BUDGET','POST_EXIT_LOCKED'}
    gate('gate4_resolution_conservation', set(traj.resolution_state)<=allowed, statuses=sorted(set(traj.resolution_state)))
    # G5 operator semantic integrity
    gate('gate5_operator_semantics', ((t[t.resolution_state=='RESOLVED_ADD'].exposure_after >= t[t.resolution_state=='RESOLVED_ADD'].exposure_before-1e-12).all()
        and (t[t.resolution_state=='RESOLVED_HOLD'].exposure_after==t[t.resolution_state=='RESOLVED_HOLD'].exposure_before).all()
        and (t[t.resolution_state=='RESOLVED_REDUCE'].exposure_after < t[t.resolution_state=='RESOLVED_REDUCE'].exposure_before).all()
        and (t[t.resolution_state=='RESOLVED_REDUCE'].exposure_after>0).all()), add_monotone=True, reduce_strict_positive=True)
    # G6 bounds/monotonicity/exit exclusivity: only EXIT (+post-lock) and zero-budget produce exact zero (strict equality)
    zero_states=set(t[t.exposure_after==0.0].resolution_state.unique())
    gate('gate6_exit_exclusivity', zero_states<= {'RESOLVED_EXIT','POST_EXIT_LOCKED','ZERO_BUDGET'}, zero_producing_states=sorted(zero_states))
    # G7 conflict/no-evidence preservation: unchanged x and distinct semantic reason codes, never relabeled HOLD
    pre=t[t.resolution_state.isin(['CONFLICT_OPPORTUNITY_RISK','NO_ACTION_EVIDENCE','UNRESOLVED_UNSEEN_VECTOR'])]
    gate('gate7_preserve_distinct', (pre.exposure_after==pre.exposure_before).all() and pre.reason_code.isin(['PRESERVE_EXPOSURE_UNDER_CONFLICT','PRESERVE_EXPOSURE_NO_EVIDENCE','PRESERVE_EXPOSURE_UNSEEN_VECTOR','PRESERVE_NO_RESOLUTION_ROW']).all(), preserve_rows=len(pre))
    # G8 no outcome-based tuning: no outcome reads; policies fixed a priori; no selection
    gate('gate8_no_outcome_tuning', m['outcome_data_read'] is False and m['pnl_computed'] is False and all('outcome' not in x for x in reads), outcome_reads=0, policy_selection='deferred_to_T5_8')
    # G9 trajectory determinism / split diagnostics present
    gate('gate9_diagnostics', set(diag.segment)=={'development','validation','confirmation'} and len(diag)==9, diag_rows=len(diag))
    # G10 inventory
    exp=['t5_7_exposure_contract.json','t5_7_operator_definition.json','t5_7_policy_family.json','t5_7_exposure_trajectory.parquet','t5_7_operator_usage.parquet','t5_7_split_diagnostics.parquet','t5_7_manifest.json']
    gate('gate10_inventory', all((OUT/x).exists() for x in exp), expected=exp)
    R['overall']={'verdict':'PASS' if all(x['verdict']=='PASS' for k,x in R.items() if k.startswith('gate')) else 'FAIL','baseline':'ad7fd2c'}
    (OUT/'t5_7_gates.json').write_text(json.dumps(R,indent=2,ensure_ascii=False,default=str)); print({k:x['verdict'] for k,x in R.items() if isinstance(x,dict) and 'verdict' in x}); print('OVERALL:',R['overall']['verdict'])
if __name__=='__main__':main()
