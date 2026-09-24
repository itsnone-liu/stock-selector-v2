#!/usr/bin/env python3
"""T5.4 State / Transition -> Outcome mapping.

Outcome clock is the T5.1 frozen individual-security clock: horizons are
following valid adjusted-price observations (1/3/5/10), beginning after t.
No market-excess proxy is used here; T5.2 market excess had a calendar-clock
mismatch and is descriptive-only. This script never changes raw C0-C6.

Discovery is development-only and outcome-free: short paths are selected by
support only, with a fixed minimum support and a capped top-N set, then
frozen and evaluated in validation/confirmation.
"""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path('/root/project/workspace/stock-selector-v2'); sys.path.insert(0,str(ROOT/'src'))
STATE=ROOT/'output/research/t5/state'; FACTS=ROOT/'output/research/t5/facts'; TR=ROOT/'output/research/t5/transition'; OUT=ROOT/'output/research/t5/outcome_mapping'; OUT.mkdir(parents=True,exist_ok=True)
H=(1,3,5,10); MIN_PATH_SUPPORT=200; MAX_PATHS=40; BOOT=199; SEED=20260925
METRICS={
 'fwd_ret_1d_log':'mean','fwd_ret_3d_log':'mean','fwd_ret_5d_log':'mean','fwd_ret_10d_log':'mean',
 'fwd_peak_ret_5d_log':'mean','fwd_peak_ret_10d_log':'mean','fwd_mdd_5d_log':'mean','fwd_mdd_10d_log':'mean',
 'fwd_new_high_5d':'rate','fwd_new_high_10d':'rate','fwd_lose_ref20_5d':'rate','fwd_lose_ref20_10d':'rate'}

def ci_event(g,col):
    x=g[["event_id",col]].dropna();
    if x.empty:return (None,None)
    by=x.groupby('event_id')[col].mean(); rng=np.random.default_rng(SEED); a=by.to_numpy(); vals=[]
    for _ in range(BOOT): vals.append(float(np.mean(a[rng.integers(0,len(a),len(a))])))
    return (float(np.quantile(vals,.025)),float(np.quantile(vals,.975)))

def aggregate(d, keys, product):
    rows=[]
    for key,g in d.groupby(keys,dropna=False,sort=True):
        if not isinstance(key,tuple):key=(key,)
        row=dict(zip(keys,key)); row['n_rows']=len(g); row['n_events']=g.event_id.nunique(); row['product']=product
        for c,kind in METRICS.items():
            if c not in g:continue
            v=g[c].dropna(); row[c]=float(v.mean()) if kind=='mean' and len(v) else (float(v.astype(bool).mean()) if kind=='rate' and len(v) else None); row[c+'_n']=len(v)
        lo,hi=ci_event(g,'fwd_ret_5d_log'); row['fwd_ret_5d_log_ci_lo']=lo; row['fwd_ret_5d_log_ci_hi']=hi
        rows.append(row)
    return pd.DataFrame(rows)

def main():
    cs=pd.read_parquet(STATE/'t5_candidate_state_daily.parquet')
    op=pd.read_parquet(TR/'t5_operational_state_daily_v1.parquet',columns=['event_id','delta_day','operational_state_v1'])
    oc=pd.read_parquet(FACTS/'t5_daily_outcome.parquet')
    st=pd.read_parquet(FACTS/'t5_daily_state.parquet',columns=['event_id','delta_day','state_date','termination_reason'])
    base=cs[['event_id','delta_day','final_candidate_state','state_assignable','segment','year_s','exposure_class']].merge(op,on=['event_id','delta_day']).merge(st,on=['event_id','delta_day']).merge(oc,on=['event_id','delta_day'])
    # Explicit frozen outcome-clock contract.
    clock={'contract':'t5_1_individual_valid_observation_clock','horizons_days':list(H),'starts':'after origin close; next valid adjusted-price observations','censor':'complete_h required; incomplete values remain missing','market_excess_used':False,'reason':'T5.2 market calendar clock differed from individual suspended-row clock'}
    (OUT/'t5_4_outcome_clock.json').write_text(json.dumps(clock,indent=2,ensure_ascii=False))
    # Current-state baselines (raw and operational), segmented.
    cur=[]
    for col,prod in [('final_candidate_state','raw_state'),('operational_state_v1','operational_state')]:
        x=aggregate(base.rename(columns={col:'state'}),['segment','state'],prod);cur.append(x)
    pd.concat(cur,ignore_index=True).to_parquet(OUT/'t5_current_state_outcomes.parquet',index=False)
    # Lifecycle remaining and terminal outcome, derived only from frozen state termination.
    last=st.groupby('event_id').delta_day.max(); reason=st.dropna(subset=['termination_reason']).drop_duplicates('event_id').set_index('event_id').termination_reason
    base['remaining_lifecycle_days']=base.event_id.map(last)-base.delta_day; base['termination_reason_event']=base.event_id.map(reason)
    base['year'] = base['year_s']
    haz=[]
    for keys,g in base.groupby(['segment','final_candidate_state'],dropna=False):
        seg,state=keys; l=g[g.termination_reason_event=='LIFECYCLE_END']; haz.append({'segment':seg,'state':state,'n_rows':len(g),'n_events':g.event_id.nunique(),'p_end_1d':float((g.remaining_lifecycle_days<=1).mean()),'p_end_3d':float((g.remaining_lifecycle_days<=3).mean()),'p_end_5d':float((g.remaining_lifecycle_days<=5).mean()),'median_remaining':float(l.remaining_lifecycle_days.median()) if len(l) else None})
    pd.DataFrame(haz).to_parquet(OUT/'t5_current_state_lifecycle.parquet',index=False)
    # One-step transitions: destination labels already explicit in T5.3 edge table.
    e=pd.read_parquet(TR/'t5_transition_edges.parquet'); e=e[e.horizon_k==1][['event_id','delta_day','dest_type','dest_label']]
    tr=base.merge(e,on=['event_id','delta_day'])
    tr['transition']=tr.final_candidate_state.astype(str)+'->'+tr.dest_label.astype(str)
    pd.concat([aggregate(tr,['segment','final_candidate_state','dest_type','dest_label'],'raw_transition'),aggregate(tr,['segment','operational_state_v1','dest_type','dest_label'],'operational_origin_transition')],ignore_index=True).to_parquet(OUT/'t5_transition_outcomes.parquet',index=False)
    # Second-order source-path outcome, fixed from T5.3 operational sequence; no outcome used in discovery.
    seq=base[['event_id','delta_day','segment','operational_state_v1']].sort_values(['event_id','delta_day']).copy(); g=seq.groupby('event_id'); seq['s1']=g.operational_state_v1.shift(-1); seq['s2']=g.operational_state_v1.shift(-2); seq['d1']=g.delta_day.shift(-1); seq['d2']=g.delta_day.shift(-2)
    seq=seq[(seq.d1==seq.delta_day+1)&(seq.d2==seq.delta_day+2)&seq.s1.notna()&seq.s2.notna()]
    dev=seq[seq.segment=='development']; counts=dev.groupby(['operational_state_v1','s1','s2']).size().rename('support').reset_index().sort_values(['support','operational_state_v1','s1','s2'],ascending=[False,True,True,True]); selected=counts[counts.support>=MIN_PATH_SUPPORT].head(MAX_PATHS).copy(); selected['path']=selected.operational_state_v1+'->'+selected.s1+'->'+selected.s2
    selected[['operational_state_v1','s1','s2','support','path']].to_parquet(OUT/'t5_short_path_definition.parquet',index=False)
    ps=seq.merge(selected[['operational_state_v1','s1','s2','path']],on=['operational_state_v1','s1','s2'],how='inner').merge(base,on=['event_id','delta_day','segment'],suffixes=('','_b'))
    aggregate(ps,['segment','path'],'short_path').to_parquet(OUT/'t5_short_path_outcomes.parquet',index=False)
    manifest={'stage':'T5.4_state_transition_outcome_mapping','baseline':'a33c9b5','raw_definition':'read-only T5.2 af2dac7','outcome_clock':clock,'path_discovery':{'segment':'development','minimum_support':MIN_PATH_SUPPORT,'max_paths':MAX_PATHS,'selected_paths':len(selected),'selection_uses_outcome':False},'rows':{'origins':len(base),'transition_edges':len(tr)}}
    (OUT/'t5_4_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False))
    print('done',manifest)
if __name__=='__main__':main()
