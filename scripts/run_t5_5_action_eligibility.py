#!/usr/bin/env python3
"""T5.5 Action Evidence Layer and multi-label eligibility.

Only frozen T5.4 aggregate products are read. Thresholds and hierarchy are
constructed from development rows, then applied unchanged to validation and
confirmation. No state/path/outcome definitions are rewritten; no position
size or action priority is produced.
"""
from __future__ import annotations
import json, hashlib
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path('/root/project/workspace/stock-selector-v2'); SRC=ROOT/'output/research/t5/outcome_mapping'; OUT=ROOT/'output/research/t5/action_eligibility'; OUT.mkdir(parents=True,exist_ok=True)
MET=['fwd_ret_5d_log','fwd_peak_ret_5d_log','fwd_mdd_5d_log','fwd_new_high_5d','fwd_lose_ref20_5d']

def norm_frame(df, level, source_key):
    df=df.copy(); df['source_level']=level; df['source_key']=df[source_key].astype(str)
    if level=='current': df['source_state']=df[source_key].astype(str)
    elif level=='transition': df['source_state']=df[source_key].astype(str)
    else: df['source_state']=df[source_key].astype(str)
    return df

def main():
    cur=pd.read_parquet(SRC/'t5_current_state_outcomes.parquet')
    tr=pd.read_parquet(SRC/'t5_transition_outcomes.parquet')
    pa=pd.read_parquet(SRC/'t5_short_path_outcomes.parquet')
    # T5.4 has two current products; use raw_state as base and retain operational
    # as an auditable parallel source, not as a replacement.
    c=cur[cur['product']=='raw_state'].copy(); c['source_level']='current'; c['source_key']=c['state'].astype(str); c['source_state']=c['state'].astype(str)
    t=tr[tr['product']=='raw_transition'].copy(); t['source_level']='transition'; t['source_key']=t.final_candidate_state.astype(str)+'->'+t.dest_label.astype(str); t['source_state']=t.final_candidate_state.astype(str)
    p=pa.copy(); p['source_level']='short_path'; p['source_key']=p.path.astype(str); p['source_state']=p.path.str.split('->').str[0]
    allx=pd.concat([c,t,p],ignore_index=True,sort=False)
    # Evidence axes are descriptive transformations of frozen outcome aggregates.
    allx['continuation_evidence']=allx['fwd_new_high_5d']
    allx['upside_opportunity']=allx['fwd_peak_ret_5d_log']
    allx['downside_risk']=allx['fwd_mdd_5d_log']
    allx['failure_risk']=allx['fwd_lose_ref20_5d']
    allx['terminal_risk']=np.nan
    allx['recovery_evidence']=allx['fwd_ret_3d_log']
    allx['support']=allx['n_rows']; allx['event_support']=allx['n_events']
    allx['coverage']=allx['fwd_ret_5d_log_n']/allx['n_rows'].replace(0,np.nan)
    allx['censor_missing_rate']=1-allx['coverage']
    # lifecycle terminal evidence is available only from current raw product through
    # its separate T5.4 table; merge exact segment/state values.
    life=pd.read_parquet(SRC/'t5_current_state_lifecycle.parquet'); life['source_key']=life.state.astype(str); life['terminal_risk']=life.p_end_5d
    allx=allx.drop(columns=['terminal_risk']).merge(life[['segment','source_key','p_end_5d']],on=['segment','source_key'],how='left').rename(columns={'p_end_5d':'terminal_risk'})
    # Development-only thresholds. Missing terminal risk for transition/path is
    # explicitly conservative: it cannot create EXIT evidence.
    dev=allx[allx.segment=='development']
    q={}
    for col in ['continuation_evidence','upside_opportunity','recovery_evidence']:
        q[col]={'q25':float(dev[col].quantile(.25)),'q50':float(dev[col].quantile(.50)),'q75':float(dev[col].quantile(.75))}
    for col in ['downside_risk','failure_risk','terminal_risk']:
        q[col]={'q50':float(dev[col].quantile(.50)),'q75':float(dev[col].quantile(.75)),'q90':float(dev[col].quantile(.90))}
    q['reliability']={'min_support':200,'min_events':30,'min_coverage':.85,'sparse_support':500}
    # Evidence reliability is not an outcome score.
    allx['reliability_class']=np.select([
        (allx.event_support>=100)&(allx.coverage>=.9),
        (allx.event_support>=30)&(allx.coverage>=.75),
    ],['high','medium'],default='low')
    allx['sparse_evidence']=(allx.event_support<30)|(allx.support<200)
    # Positive, independent evidence definitions; no priority is assigned.
    allx['continuation_positive']=allx.continuation_evidence>=q['continuation_evidence']['q50']
    allx['upside_positive']=allx.upside_opportunity>=q['upside_opportunity']['q50']
    allx['downside_positive']=allx.downside_risk>=q['downside_risk']['q75']
    allx['failure_positive']=allx.failure_risk>=q['failure_risk']['q75']
    allx['terminal_positive']=allx.terminal_risk>=q['terminal_risk']['q75']
    allx['recovery_positive']=allx.recovery_evidence>=q['recovery_evidence']['q50']
    reliable=allx.reliability_class.isin(['high','medium']) & ~allx.sparse_evidence
    allx['ADD_ELIGIBLE']=allx.continuation_positive & allx.upside_positive & ~allx.downside_positive & ~allx.terminal_positive & reliable
    allx['HOLD_ELIGIBLE']=(allx.continuation_positive|allx.recovery_positive) & ~allx.downside_positive & ~allx.failure_positive & ~allx.terminal_positive & reliable
    allx['REDUCE_ELIGIBLE']=(allx.downside_positive|allx.failure_positive|allx.terminal_positive) & reliable
    # EXIT has an independent conjunction, not REDUCE escalation; missing terminal
    # evidence can never qualify.
    allx['EXIT_ELIGIBLE']=allx.terminal_positive & allx.failure_positive & (allx.reliability_class=='high') & ~allx.sparse_evidence
    # hierarchy: only development support and dev incremental evidence decide source.
    # Higher level is retained only when it has adequate support and its 5d return
    # differs from its lower-level parent by a fixed practical margin.
    state_ret=dev[dev.source_level=='current'].set_index('source_state')['fwd_ret_5d_log'].to_dict()
    trans_dev=dev[dev.source_level=='transition'].copy(); path_dev=dev[dev.source_level=='short_path'].copy()
    allx['hierarchy_selected']='current'; allx['backoff_reason']='default_current'
    for idx,r in allx.iterrows():
        if r.source_level=='transition' and r.event_support>=30 and r.source_state in state_ret and pd.notna(r.fwd_ret_5d_log) and abs(r.fwd_ret_5d_log-state_ret[r.source_state])>=.005:
            allx.at[idx,'hierarchy_selected']='transition'; allx.at[idx,'backoff_reason']='dev_increment>=0.5pp'
        elif r.source_level=='short_path' and r.event_support>=30 and r.source_state in state_ret and pd.notna(r.fwd_ret_5d_log) and abs(r.fwd_ret_5d_log-state_ret[r.source_state])>=.005:
            allx.at[idx,'hierarchy_selected']='short_path'; allx.at[idx,'backoff_reason']='dev_increment>=0.5pp'
        elif r.source_level!='current': allx.at[idx,'backoff_reason']='no_stable_dev_increment_or_support'
    evidence_cols=['segment','source_level','source_key','source_state','n_rows','n_events','support','event_support','coverage','censor_missing_rate','reliability_class','sparse_evidence']+[x for x in ['continuation_evidence','upside_opportunity','downside_risk','failure_risk','terminal_risk','recovery_evidence','fwd_ret_5d_log','fwd_mdd_5d_log','fwd_new_high_5d','fwd_lose_ref20_5d'] if x in allx]
    allx[evidence_cols].to_parquet(OUT/'t5_action_evidence.parquet',index=False)
    allx[['segment','source_level','source_key','hierarchy_selected','backoff_reason','n_rows','n_events']].to_parquet(OUT/'t5_hierarchy_increment.parquet',index=False)
    flags=['ADD_ELIGIBLE','HOLD_ELIGIBLE','REDUCE_ELIGIBLE','EXIT_ELIGIBLE']
    allx[['segment','source_level','source_key','source_state','hierarchy_selected','backoff_reason']+evidence_cols[4:]+flags].to_parquet(OUT/'t5_action_eligibility.parquet',index=False)
    # Stability is a reportable split-level product, not a retuned rule.
    stab=[]
    for (lev,key),g in allx.groupby(['source_level','source_key']):
      for seg,sg in g.groupby('segment'):
       stab.append({'source_level':lev,'source_key':key,'segment':seg,'n_rows':int(sg.n_rows.sum()),'n_events':int(sg.n_events.sum()),'coverage':float(np.average(sg.coverage,weights=sg.n_rows)),'reliability_high_medium_rate':float(sg.reliability_class.isin(['high','medium']).mean()),**{f'{f}_rate':float(sg[f].mean()) for f in flags}})
    pd.DataFrame(stab).to_parquet(OUT/'t5_eligibility_split_stability.parquet',index=False)
    definition={'baseline':'ebfc490','threshold_source':'development only; fixed quantiles/practical increment; no validation refit','evidence_axes':['continuation','upside','downside','failure','terminal','recovery','reliability'],'thresholds':q,'eligibility_semantics':{'ADD':'continuation + upside, no elevated downside/terminal, reliable','HOLD':'continuation or recovery, no elevated downside/failure/terminal, reliable','REDUCE':'elevated downside/failure/terminal, reliable; independent of EXIT','EXIT':'elevated terminal + failure and high reliability; independent conjunction'},'hierarchy':'short_path -> transition -> current; unsupported/nonincremental levels back off','priority_defined':False,'position_size_defined':False}
    (OUT/'t5_5_evidence_definition.json').write_text(json.dumps(definition,indent=2,ensure_ascii=False))
    man={'stage':'T5.5_action_eligibility','baseline':'ebfc490','source_products':['t5_current_state_outcomes','t5_transition_outcomes','t5_short_path_outcomes'],'development_thresholds_only':True,'n_evidence_rows':len(allx),'levels':allx.source_level.value_counts().to_dict(),'eligibility_rates':{f:float(allx[f].mean()) for f in flags}}
    (OUT/'t5_5_manifest.json').write_text(json.dumps(man,indent=2,ensure_ascii=False))
    print(json.dumps(man,indent=2))
if __name__=='__main__':main()
