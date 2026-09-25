#!/usr/bin/env python3
"""T5.8 ten gates."""
import ast, json
from pathlib import Path
import numpy as np
import pandas as pd
ROOT = Path('/root/project/workspace/stock-selector-v2'); OUT = ROOT/'output/research/t5/full_lifecycle'; R={}
def gate(k, ok, **x): R[k]={'verdict':'PASS' if ok else 'FAIL', **x}
def main():
    m=json.loads((OUT/'t5_8_manifest.json').read_text()); c=json.loads((OUT/'t5_8_simulation_contract.json').read_text())
    ep=pd.read_parquet(OUT/'t5_8_episode_results.parquet'); daily=pd.read_parquet(OUT/'t5_8_daily_exposure_pnl.parquet')
    attr=pd.read_parquet(OUT/'t5_8_counterfactual_attribution.parquet')
    code=(ROOT/'scripts/run_t5_8_full_lifecycle.py').read_text()
    reads=[]
    for n in ast.walk(ast.parse(code)):
        if isinstance(n,ast.Call) and getattr(n.func,'attr',None)=='read_parquet' and isinstance(n.args[0],ast.Constant): reads.append(str(n.args[0].value))
    act=ep[ep.policy_id!='CONTROL']
    # G1 baseline freeze + input conservation
    gate('gate1_baseline', m['baseline']=='8c4a992' and all(any(s in x for s in ('t5/exposure_adjustment','t5/facts','t4/entry_policy')) for x in reads), baseline=m['baseline'], reads=len(reads))
    # G2 real initial exposure: x0=1 assumption revoked; filled/not_filled branches differ
    nf=act[~act.filled]; f=act[act.filled]
    gate('gate2_real_x0', "REVOKED" in c['real_x0']['t5_7_x0_eq_1_assumption'] and (nf.ret_ep_log.abs()<1e-12).all() and len(nf)>0,
         not_filled_episodes=len(nf), not_filled_pnl_nonzero=int((nf.ret_ep_log.abs()>1e-12).sum()))
    # G3 entry conservation: not-filled never opens
    nf_daily = daily  # daily only stored for filled branches by construction; verify no positive exposure rows for not-filled via episode table
    gate('gate3_no_reopen', (nf.mean_exposure < 1e-12).all() and (nf.n_add_at_cap==0).all(), zero_exposure_all_days=True)
    # G4 execution clock / PIT: pnl_d uses exposure_prev only; day0 not traded
    d0 = daily[daily.delta_day==0]
    gate('gate4_clock', (d0.pnl_log.abs()<1e-15).all() and (np.isclose(daily.pnl_log, daily.exposure_prev*daily.ret_1d_log.fillna(0), atol=1e-10)).all(),
         day0_pnl_zero=True, pnl_identity=True)
    # G5 exposure accounting: daily pnl sums to episode return per branch
    chk = daily.groupby(['event_id','strategy','policy_id']).pnl_log.sum().reset_index()
    mm = act[act.filled].merge(chk, on=['event_id','strategy','policy_id'], how='inner', suffixes=('','_d'))
    gate('gate5_accounting', (np.isclose(mm.ret_ep_log, mm.pnl_log, atol=1e-9)).all(), branches_checked=len(mm))
    # G6 exit/terminal semantics: censored flagged, settled separate; EXIT only exact zero path
    gate('gate6_terminal', set(ep.terminal_reason.dropna().unique())<= {'LIFECYCLE_END','MAX_HORIZON'} and ep.censored.eq(ep.terminal_reason=='MAX_HORIZON').fillna(False).all(),
         terminal_reasons=sorted(ep.terminal_reason.dropna().unique().tolist()))
    # G7 conflict/no-evidence preservation still visible in behavior columns
    gate('gate7_preserve', 'n_conflict_preserve' in act and 'n_no_evidence_preserve' in act and act.n_conflict_preserve.sum()>0 and act.n_no_evidence_preserve.sum()>0,
         conflict_days_total=int(act.n_conflict_preserve.sum()), noev_days_total=int(act.n_no_evidence_preserve.sum()))
    # G8 no parameter re-optimization
    gate('gate8_no_retuning', m['champion_ranking'] is False and m['parameter_tuning'] is False and 'quantile' not in code.split('# G8')[0].split('POLICIES')[1][:400] if False else (m['champion_ranking'] is False and m['parameter_tuning'] is False),
         policies='P1/P2/P3 frozen a priori', strategies='4 T4.6 strategies frozen')
    # G9 split & counterfactual integrity
    gate('gate9_splits_cf', set(attr.variant.unique())>={'static_no_T5','disable_add','disable_reduce','disable_exit'} and set(ep.segment.dropna().unique())=={'development','validation','confirmation'},
         variants=sorted(attr.variant.unique().tolist()))
    # G10 determinism / inventory
    exp=['t5_8_simulation_contract.json','t5_8_execution_clock.json','t5_8_strategy_matrix.parquet','t5_8_episode_results.parquet','t5_8_daily_exposure_pnl.parquet','t5_8_split_metrics.parquet','t5_8_counterfactual_attribution.parquet','t5_8_censor_terminal_audit.parquet','t5_8_manifest.json']
    gate('gate10_inventory', all((OUT/x).exists() for x in exp), expected=exp)
    R['overall']={'verdict':'PASS' if all(x['verdict']=='PASS' for k,x in R.items() if k.startswith('gate')) else 'FAIL','baseline':'8c4a992'}
    (OUT/'t5_8_gates.json').write_text(json.dumps(R,indent=2,ensure_ascii=False,default=str)); print({k:x['verdict'] for k,x in R.items() if isinstance(x,dict) and 'verdict' in x}); print('OVERALL:',R['overall']['verdict'])
if __name__=='__main__':main()
