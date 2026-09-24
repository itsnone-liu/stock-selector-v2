#!/usr/bin/env python3
"""T5.7 Exposure Adjustment Mapping (no P&L).

Read-only over T5.1–T5.6 frozen products plus T4.6 entry_policy assignment.
Exposure is normalized to the T4.6 per-event base risk budget
(initial_exposure_weight): x = actual/base, 0<=x<=1. x_0 = 1.0 by contract
(budget fully available from T0; staged fills belong to T5.8 joint
simulation). Six operators; only RESOLVED_EXIT may drive exposure to exact
zero, and after EXIT exposure is locked (POST_EXIT_LOCKED) until episode
end. Terminal rows are not traded: episode_terminal=true, exposure_after=NA.
Policies P1/P2/P3 are fixed a priori; no outcome data is read anywhere.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
SRC = ROOT/'output/research/t5/action_resolution'
STATE = ROOT/'output/research/t5/state'
TR = ROOT/'output/research/t5/transition'
FACS = ROOT/'output/research/t5/facts'
T46 = ROOT/'output/research/t4/entry_policy'
OUT = ROOT/'output/research/t5/exposure_adjustment'; OUT.mkdir(parents=True, exist_ok=True)

POLICIES = {'P1_conservative': (1/3, 2/3), 'P2_balanced': (1/2, 1/2), 'P3_decisive': (2/3, 1/3)}
PRESETS = {
    'RESOLVED_ADD': ('ADD', 'ADD_TOWARD_CAP'),
    'RESOLVED_HOLD': ('HOLD', 'HOLD_IDENTITY'),
    'RESOLVED_REDUCE': ('REDUCE', 'REDUCE_RETAIN_FRACTION'),
    'RESOLVED_EXIT': ('EXIT', 'EXIT_EXACT_ZERO'),
    'CONFLICT_OPPORTUNITY_RISK': ('PRESERVE', 'PRESERVE_EXPOSURE_UNDER_CONFLICT'),
    'NO_ACTION_EVIDENCE': ('PRESERVE', 'PRESERVE_EXPOSURE_NO_EVIDENCE'),
    'UNRESOLVED_UNSEEN_VECTOR': ('PRESERVE', 'PRESERVE_EXPOSURE_UNSEEN_VECTOR'),
}


def effective_resolution(day, res_idx, hier_idx):
    """Hierarchy fallback: short_path -> transition -> current (T5.5 frozen)."""
    for level, key in (('short_path', day['path_key']),
                       ('transition', day['trans_key'])):
        if key is None:
            continue
        r = res_idx.get((day['segment'], level, key))
        h = hier_idx.get((day['segment'], level, key))
        if r is not None and h == level:
            return r, level, key
    r = res_idx.get((day['segment'], 'current', day['cur_key']))
    return (r, 'current', day['cur_key']) if r else (None, 'current', day['cur_key'])


def main():
    # --- inputs ---
    res = pd.read_parquet(SRC/'t5_6b_resolution.parquet')
    h = pd.read_parquet(SRC.parent/'action_eligibility'/'t5_hierarchy_increment.parquet',
                        columns=['segment','source_level','source_key','hierarchy_selected'])
    cs = pd.read_parquet(STATE/'t5_candidate_state_daily.parquet',
                         columns=['event_id','delta_day','final_candidate_state','segment'])
    op = pd.read_parquet(TR/'t5_operational_state_daily_v1.parquet',
                         columns=['event_id','delta_day','operational_state_v1'])
    edges = pd.read_parquet(TR/'t5_transition_edges.parquet',
                            columns=['event_id','delta_day','horizon_k','dest_type','dest_label'])
    st = pd.read_parquet(FACS/'t5_daily_state.parquet',
                         columns=['event_id','code','delta_day','termination_reason','participation_policy'])
    a46 = pd.read_parquet(T46/'t4_6_assignment.parquet')
    pol46 = st.drop_duplicates('event_id')[['event_id','participation_policy']]
    budget_map = (a46.drop_duplicates('participation_policy')
                  .set_index('participation_policy')['initial_exposure_weight'].to_dict())

    res_idx = {(r.segment, r.source_level, r.source_key): r for r in res.itertuples(index=False)}
    hier_idx = {(r.segment, r.source_level, r.source_key): r.hierarchy_selected for r in h.itertuples(index=False)}

    # --- per-day table ---
    d = cs.merge(op, on=['event_id','delta_day']).merge(
        st[['event_id','delta_day','termination_reason']], on=['event_id','delta_day'])
    d = d.sort_values(['event_id','delta_day']).reset_index(drop=True)
    g = d.groupby('event_id')
    d['s1'] = g.operational_state_v1.shift(-1); d['s2'] = g.operational_state_v1.shift(-2)
    e1 = edges[edges.horizon_k==1][['event_id','delta_day','dest_label']]
    d = d.merge(e1, on=['event_id','delta_day'], how='left')
    d['cur_key'] = d.final_candidate_state.astype(str)
    d['trans_key'] = d.final_candidate_state.astype(str)+'->'+d.dest_label.astype(str)
    d['path_key'] = np.where(d.s1.notna() & d.s2.notna(),
                             d.operational_state_v1.astype(str)+'->'+d.s1.astype(str)+'->'+d.s2.astype(str), None)
    d['is_terminal_row'] = d.termination_reason.notna()

    # --- exposure contract ---
    contract = {
        'unit': 'x_t = actual_exposure_t / base_risk_budget',
        'base_risk_budget': 'T4.6 initial_exposure_weight per participation_policy (P0=0, P1=0.25, P2=0.5, P3=1.0)',
        'x0': '1.0 by contract for base>0 events (budget fully available from T0); staged fills are a T5.8 concern',
        'bounds': '0 <= x_t <= 1',
        'zero_budget_events': 'P0 events recorded with ZERO_BUDGET trajectory; excluded from operator usage statistics',
        'terminal': 'episode_terminal rows are not traded; exposure_after_terminal = NA',
        'post_exit': 'after RESOLVED_EXIT, exposure locked at 0 until episode end (POST_EXIT_LOCKED)'}
    (OUT/'t5_7_exposure_contract.json').write_text(json.dumps(contract, indent=2, ensure_ascii=False))

    # --- replay ---
    rows = []
    day_cols = ['event_id','delta_day','segment','cur_key','trans_key','path_key','is_terminal_row']
    for ev, gd in d.groupby('event_id', sort=False):
        pol = pol46.loc[pol46.event_id==ev,'participation_policy'].iloc[0]
        base = float(budget_map.get(pol, np.nan))
        days = gd[day_cols].to_dict('records')
        for pid,(a_frac,r_frac) in POLICIES.items():
            x = 1.0 if base and base>0 else 0.0
            locked = False
            for day in days:
                term = bool(day['is_terminal_row'])
                if base is None or (isinstance(base,float) and np.isnan(base)) or base==0:
                    status, level, key, rule = 'ZERO_BUDGET','current',day['cur_key'],'P0_no_participation'
                elif term:
                    status, level, key = 'EPISODE_TERMINAL','current',day['cur_key']; rule='terminal_not_traded'
                else:
                    r, level, key = effective_resolution(day, res_idx, hier_idx)
                    if r is None:
                        status, rule = 'PRESERVE','NO_RESOLUTION_ROW'
                    else:
                        status, rule = r.resolution_status, r.resolution_rule
                    if locked:
                        status, rule = 'POST_EXIT_LOCKED','exit_lock'
                x_before = x
                reason = None
                if status=='EPISODE_TERMINAL':
                    x_after = None; reason='EPISODE_TERMINAL_NOT_TRADED'
                elif status=='ZERO_BUDGET':
                    x_after = 0.0; reason='ZERO_BUDGET_P0'
                elif status=='POST_EXIT_LOCKED':
                    x_after = 0.0; reason='POST_EXIT_LOCKED'
                elif status=='RESOLVED_ADD':
                    if x>=1.0: x_after=x; reason='ADD_AT_CAP'
                    else: x_after = min(x + a_frac*(1-x), 1.0); reason='ADD_TOWARD_CAP'
                elif status=='RESOLVED_HOLD': x_after=x; reason='HOLD_IDENTITY'
                elif status=='RESOLVED_REDUCE': x_after = x*r_frac; reason='REDUCE_RETAIN_FRACTION'
                elif status=='RESOLVED_EXIT': x_after=0.0; locked=True; reason='EXIT_EXACT_ZERO'
                else:
                    x_after = x
                    reason = {'CONFLICT_OPPORTUNITY_RISK':'PRESERVE_EXPOSURE_UNDER_CONFLICT',
                              'NO_ACTION_EVIDENCE':'PRESERVE_EXPOSURE_NO_EVIDENCE',
                              'UNRESOLVED_UNSEEN_VECTOR':'PRESERVE_EXPOSURE_UNSEEN_VECTOR'}.get(status,'PRESERVE_NO_RESOLUTION_ROW')
                if x_after is not None: x = x_after
                rows.append({'lifecycle_id':ev,'date_delta':int(day['delta_day']),'segment':day['segment'],
                    'resolution_state':status,'source_level':level,'source_key':key,
                    'exposure_before':x_before,'operator':PRESETS.get(status,(status,'n/a'))[0],
                    'policy_id':pid,'operator_parameter':json.dumps({'a':a_frac,'r':r_frac}),
                    'exposure_after':x_after,'base_risk_budget':base,
                    'actual_target_exposure':None if x_after is None else x_after*base,
                    'reason_code':reason,'source_resolution_rule':rule})
    traj = pd.DataFrame(rows)
    traj.to_parquet(OUT/'t5_7_exposure_trajectory.parquet', index=False)

    # --- operator usage ---
    nz = traj[~traj.resolution_state.isin(['ZERO_BUDGET','EPISODE_TERMINAL']) & traj.exposure_after.notna()]
    usage = (nz.groupby(['policy_id','resolution_state'])
             .agg(n_days=('exposure_after','size'), mean_exposure_after=('exposure_after','mean'),
                  add_at_cap_days=('reason_code', lambda s:(s=='ADD_AT_CAP').sum()))
             .reset_index())
    usage.to_parquet(OUT/'t5_7_operator_usage.parquet', index=False)

    # --- split diagnostics (structure only, no P&L) ---
    diag = (nz.groupby(['policy_id','segment'])
            .agg(n_days=('exposure_after','size'),
                 mean_exposure=('exposure_after','mean'),
                 median_exposure=('exposure_after','median'),
                 p_at_cap=('exposure_after', lambda s:(s>=1.0).mean()),
                 p_near_zero_not_exit=('exposure_after', lambda s:((s<0.05)&(s>0)).mean()),
                 n_add_at_cap=('reason_code', lambda s:(s=='ADD_AT_CAP').sum()),
                 n_reduce=('resolution_state', lambda s:(s=='RESOLVED_REDUCE').sum()),
                 n_conflict_preserve=('resolution_state', lambda s:(s=='CONFLICT_OPPORTUNITY_RISK').sum()),
                 n_no_evidence_preserve=('resolution_state', lambda s:(s=='NO_ACTION_EVIDENCE').sum()),
                 n_post_exit_locked=('resolution_state', lambda s:(s=='POST_EXIT_LOCKED').sum()),
                 n_terminal=('resolution_state', lambda s:(s=='EPISODE_TERMINAL').sum()))
            .reset_index())
    diag['exposure_unit_turnover'] = diag.n_reduce/np.maximum(diag.n_days,1)
    diag.to_parquet(OUT/'t5_7_split_diagnostics.parquet', index=False)

    # --- operator definition + policy family ---
    opdef = {'operators':{
        'RESOLVED_ADD': {'x_after':'x + a*(1-x), capped at 1','at_cap':'exposure unchanged, reason=ADD_AT_CAP (still an ADD decision)'},
        'RESOLVED_HOLD': {'x_after':'x (identity, evidence-supported)'},
        'RESOLVED_REDUCE': {'x_after':'r*x, 0<r<1; a single REDUCE never reaches zero'},
        'RESOLVED_EXIT': {'x_after':'0 (the ONLY action-driven exact zero)','post':'locked POST_EXIT_LOCKED until episode end'},
        'CONFLICT_OPPORTUNITY_RISK': {'x_after':'x','reason':'PRESERVE_EXPOSURE_UNDER_CONFLICT (never HOLD)'},
        'NO_ACTION_EVIDENCE': {'x_after':'x','reason':'PRESERVE_EXPOSURE_NO_EVIDENCE (never HOLD)'},
        'UNRESOLVED_UNSEEN_VECTOR': {'x_after':'x','reason':'PRESERVE_EXPOSURE_UNSEEN_VECTOR'}},
        'invariants':['x in [0,1]','only EXIT -> exact zero via action','all preserves keep x unchanged with distinct reason codes'],
        'exit_lock':'once EXIT, exposure stays 0 (no re-entry inside the lifecycle)'}
    (OUT/'t5_7_operator_definition.json').write_text(json.dumps(opdef, indent=2, ensure_ascii=False))
    fam = {'note':'fixed a priori, not tuned by outcome; T4.6 has no dynamic tranche unit to reuse',
           'policies':{k:{'add_fraction_of_headroom':v[0],'reduce_retain_fraction':v[1]} for k,v in POLICIES.items()},
           'selection':'deferred to T5.8; T5.7 reports structure only'}
    (OUT/'t5_7_policy_family.json').write_text(json.dumps(fam, indent=2, ensure_ascii=False))

    man = {'stage':'T5.7_exposure_adjustment','baseline':'ad7fd2c',
           't46_inputs':'t4_6_assignment initial_exposure_weight (participation policy budget)',
           'rows':{'trajectory_rows':len(traj),'operable_days':len(nz),'policies':len(POLICIES)},
           'pnl_computed':False,'outcome_data_read':False,
           'coverage':{'resolved':float(nz.resolution_state.str.startswith('RESOLVED').mean()),
                       'conflict_preserve':float((nz.resolution_state=='CONFLICT_OPPORTUNITY_RISK').mean()),
                       'no_evidence_preserve':float((nz.resolution_state=='NO_ACTION_EVIDENCE').mean())}}
    (OUT/'t5_7_manifest.json').write_text(json.dumps(man, indent=2, ensure_ascii=False))
    print(json.dumps(man, indent=2))
    print(diag.to_string(index=False))

if __name__=='__main__':
    main()
