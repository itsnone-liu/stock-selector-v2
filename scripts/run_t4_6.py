#!/usr/bin/env python3
"""T4.6A-D: participation, chase/timing, initial risk budgets, guardrails."""
from __future__ import annotations
import hashlib,json,subprocess,sys
from pathlib import Path
import numpy as np,pandas as pd
ROOT=Path('/root/project/workspace/stock-selector-v2'); OUT=ROOT/'output/research/t4/entry_policy'; OUT.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'src'))
from t4.entry_policy import CHASE_BINS,CHASE_LABELS,map_participation,db_profile
BASE='1565e25'

def fh(d): return hashlib.sha256(d.sort_values(['lifecycle_id','strategy']).to_csv(index=False).encode()).hexdigest()
def main():
 h=subprocess.run(['git','rev-parse','--short','HEAD'],cwd=ROOT,text=True,capture_output=True).stdout.strip(); assert h==BASE
 exp=pd.read_parquet(ROOT/'output/research/t4/exposure/t4_exposure_assignment.parquet')
 paths=pd.read_parquet(ROOT/'output/research/t3_v3/event_path_summary.parquet')
 # Full frozen replay: one row per lifecycle x strategy; use replay partitions.
 replay=pd.read_parquet(ROOT/'output/research/lifecycle_v1/entry_replay_v5_full/partitions',columns=None)
 replay=replay.merge(exp[['breakout_event_id','E_class','M_cell','L_q','R60','year']],left_on='signal_day',right_on='breakout_event_id',how='left') if False else replay
 # lifecycle_id is the exact T4.5 event key only in context tables; map via code/day.
 ev=exp[['breakout_event_id','E_class','M_cell','L_q','R60','year']].copy(); ev[['code','day']]=ev.breakout_event_id.str.split('_',n=1,expand=True); ev=ev.rename(columns={'day':'signal_day'})
 replay=replay.merge(ev,on=['code','signal_day'],how='left')
 replay['evidence_missing'] = replay['E_class'].isna()
 replay['E_class'] = replay['E_class'].astype('string').fillna('E0')
 replay['participation_policy']=replay.E_class.astype('string').map({c:map_participation(c) for c in ['E0','E1','E2','E3']})
 replay['entry_timing']=np.where(replay.signal_day.notna(),'T0','T2_plus')
 # A: policy mapping/profile from direct chase, preserving no-fill rows.
 a=[]
 for p,g in replay.groupby(['E_class','participation_policy'],dropna=False):
  a.append({'E_class':p[0],'participation_policy':p[1],**db_profile(g,['ret_net_20_close','mfe_20_close','mae_20_close'])})
 pd.DataFrame(a).to_parquet(OUT/'t4_6a_participation.parquet',index=False)
 # B: chase response and T0/T1 timing (direct chase only; timing is fill view).
 d=replay[replay.strategy=='direct_chase'].copy(); d['chase_bin']=pd.cut(d.signal_day_gain_pct,bins=CHASE_BINS,labels=CHASE_LABELS)
 b=[]
 for (e,t,c),g in d.groupby(['E_class','chase_bin','fill_status_close'],dropna=False): b.append({'E_class':e,'chase_bin':str(c),'timing':'T0','fill_status':t,**db_profile(g,['ret_net_20_close','ret_net_20_next','mfe_20_close','mae_20_close'])})
 # all strategies with next view gives T1 as separately visible timing, not relabeled T0.
 for (e,c),g in d.groupby(['E_class','chase_bin'],dropna=False): b.append({'E_class':e,'chase_bin':str(c),'timing':'T1_view','fill_status':'filled_next',**db_profile(g,['ret_net_20_next','mfe_20_close','mae_20_close'])})
 pd.DataFrame(b).to_parquet(OUT/'t4_6b_chase_timing.parquet',index=False)
 # 3.5 diagnostic exact: below/equal/above plus no-fill and caps.
 cap=d.assign(cap_group=np.where(d.signal_day_gain_pct>3.5,'>3.5','<=3.5'))
 cap_rows=[]
 for k,g in cap.groupby(['E_class','cap_group'],dropna=False): cap_rows.append({'E_class':k[0],'cap_group':k[1],**db_profile(g,['ret_net_20_close','ret_net_20_next','mfe_20_close','mae_20_close']),'n_capped_not_entered':int((g.capped_entered==False).sum())})
 pd.DataFrame(cap_rows).to_parquet(OUT/'t4_6b_cap_35_diagnostic.parquet',index=False)
 # C: risk-budget eligibility, not percentage optimizer. P0/P1/P2/P3 semantics.
 budgets={'P0_no_participation':'zero_or_exception_only','P1_probe':'probe_budget','P2_normal':'normal_budget','P3_aggressive_eligible':'normal_or_elevated_subject_to_risk_cap'}
 c=pd.DataFrame([{'E_class':e,'participation_policy':map_participation(e),'risk_budget_class':budgets[map_participation(e)],'research_weight':w} for e,w in zip(['E0','E1','E2','E3'],[0,.25,.5,1])])
 c.to_csv(OUT/'t4_6c_risk_budget_classes.csv',index=False)
 # D guardrails are constraints, sector only concentration control.
 guards=pd.DataFrame([
 {'guardrail':'single_name_cap','value':'account_defined','role':'hard constraint'},
 {'guardrail':'total_initial_exposure_cap','value':'account_defined','role':'hard constraint'},
 {'guardrail':'same_day_entry_cap','value':'account_defined','role':'hard constraint'},
 {'guardrail':'sector_concentration_cap','value':'account_defined','role':'risk correlation control only'},])
 guards.to_csv(OUT/'t4_6d_guardrails.csv',index=False)
 # C counterfactual evidence, no portfolio equity curve.
 replay['initial_exposure_weight']=replay.E_class.astype('string').map({'E0':0.,'E1':.25,'E2':.5,'E3':1.})
 replay['initial_exposure_weight']=replay.initial_exposure_weight.fillna(0.)
 daily=replay.groupby(['signal_day','strategy'],dropna=False).agg(n=('code','size'),avg_w=('initial_exposure_weight','mean'),filled=('fill_status_close',lambda x:(x=='filled').sum())).reset_index()
 daily['capital_weighted_excess_proxy']=daily.avg_w*daily.n
 daily.to_parquet(OUT/'t4_6d_daily_exposure_audit.parquet',index=False)
 # conservation and deterministic assignment snapshot
 assign=replay[['code','signal_day','lifecycle_id','strategy','E_class','participation_policy','initial_exposure_weight','fill_status_close','fill_status_next','signal_day_gain_pct']]
 assign.to_parquet(OUT/'t4_6_assignment.parquet',index=False)
 det={'assignment_hash':fh(assign),'rows':len(assign),'unique_lifecycle_strategy':assign[['lifecycle_id','strategy']].drop_duplicates().shape[0]}
 (OUT/'t4_6_manifest.json').write_text(json.dumps({'stage':'T4.6','baseline':BASE,'chase_bins':CHASE_LABELS,'db_primary':True,'outcome_separation':True,'determinism':det},indent=2))
 print(json.dumps({'rows':len(replay),'assignment':det,'cap_rows':len(cap_rows)},indent=2))
if __name__=='__main__': main()
