#!/usr/bin/env python3
"""T5.8 Full Lifecycle Strategy Simulation (memory-bounded).

Same contract as the first version; the day loop operates on pre-extracted
compact per-event tuples and daily P&L rows are flushed to parquet
partitions, keeping peak memory low. Contract / clock semantics identical:

  T5.8A  real x0 from T4.6 (strategy x fill; not-filled can never be
        re-opened by T5 ADD; P0 = NON_PARTICIPATION_CONTROL), execution
        clock (close-t signal -> (t, t+1] return), terminal semantics
        (LIFECYCLE_END settlement vs MAX_HORIZON censor), E0/E1.
  T5.8B  frozen 12-cell matrix + static / disable-ADD / disable-REDUCE /
        disable-EXIT counterfactuals.
  T5.8C  layered metrics by segment; censor audit; no ranking, no tuning.
"""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
T7 = ROOT/'output/research/t5/exposure_adjustment'
FACS = ROOT/'output/research/t5/facts'
T46 = ROOT/'output/research/t4/entry_policy'
OUT = ROOT/'output/research/t5/full_lifecycle'; OUT.mkdir(parents=True, exist_ok=True)
DPART = OUT/'daily_parts'; DPART.mkdir(exist_ok=True)

POLICIES = {'P1_conservative': (1/3, 2/3), 'P2_balanced': (1/2, 1/2), 'P3_decisive': (2/3, 1/3)}
ENTRY_STRATS = ['direct_chase', 'staged_entry', 'wait_first_pullback', 'wait_support_hold']
FLUSH_ROWS = 400000
OPS = {'RESOLVED_ADD':'add','RESOLVED_HOLD':'hod','RESOLVED_REDUCE':'red','RESOLVED_EXIT':'ext',
       'CONFLICT_OPPORTUNITY_RISK':'pre','NO_ACTION_EVIDENCE':'pre','UNRESOLVED_UNSEEN_VECTOR':'pre'}
DAY_COLS = ['event_id','segment','strategy','policy_id','delta_day','exposure_prev',
            'ret_1d_log','pnl_log','exposure_after','effective_status','terminal_reason']


def build_inputs():
    st = pd.read_parquet(FACS/'t5_daily_state.parquet',
                         columns=['event_id','code','state_date','delta_day',
                                  'ret_1d_log','termination_reason'])
    tr = pd.read_parquet(T7/'t5_7_exposure_trajectory.parquet',
                         columns=['lifecycle_id','date_delta','segment','resolution_state'])
    tr = tr[tr.resolution_state != 'EPISODE_TERMINAL']
    # the trajectory carries one row per policy; the policy-id column is not
    # loaded, so the three copies are exact duplicates on the loaded schema.
    # De-duplicate to exactly one frozen resolution status per (event, day).
    tr = tr.drop_duplicates(['lifecycle_id','date_delta'])
    seg_map = tr.groupby('lifecycle_id')['segment'].first().to_dict()
    days = st.merge(tr, left_on=['event_id','delta_day'],
                    right_on=['lifecycle_id','date_delta'], how='left')
    days = days.drop(columns=['lifecycle_id','date_delta'])
    ev_days = {}
    for r in days.itertuples(index=False):
        ret = None if (r.ret_1d_log is None or (isinstance(r.ret_1d_log,float) and np.isnan(r.ret_1d_log))) else float(r.ret_1d_log)
        status = r.resolution_state if isinstance(r.resolution_state,str) else None
        ev_days.setdefault(r.event_id, []).append((int(r.delta_day), ret, status, r.termination_reason))
    a46 = pd.read_parquet(T46/'t4_6_assignment.parquet',
                          columns=['code','signal_day','strategy','initial_exposure_weight','fill_status_close'])
    a46['k'] = a46.code.astype(str)+'|'+a46.signal_day.astype(str)
    t0 = st[st.delta_day==0][['event_id','code','state_date']].copy()
    t0['k'] = t0.code.astype(str)+'|'+t0.state_date.astype(str)
    br = t0.merge(a46, on='k', how='inner')
    ev_branch = {}
    for r in br.itertuples(index=False):
        ev_branch.setdefault(r.event_id, []).append(
            (r.strategy, float(r.initial_exposure_weight), r.fill_status_close=='filled'))
    return ev_days, ev_branch, seg_map


def replay(dl, base, filled, a_f, r_f, disable=None, static=False, collect_daily=None,
           strategy=None, policy_id=None, segment=None, ev=None):
    x = 1.0 if filled else 0.0
    if base == 0.0: return None
    locked=False
    cum=0.0; peak=-np.inf; trough=0.0; mfe=-np.inf
    n_add=n_red=n_ext=n_cap=n_conf=n_noev=n_lock=0; dust=0; exp_sum=0.0; exp_days=0
    prev_x=x; bh=0.0; term_reason=None; n_days=0
    for (d, ret, status, term) in dl:
        pnl = 0.0 if (d==0 or ret is None) else prev_x*ret
        cum+=pnl; peak=max(peak,cum); trough=min(trough,cum); mfe=max(mfe,pnl)
        if ret is not None: bh+=ret
        n_days+=1
        if not static:
            if locked: x_after=0.0; eff='POST_EXIT_LOCKED'; n_lock+=1
            elif not filled: x_after=0.0; eff='NO_POSITION'
            elif disable is not None and status==disable: x_after=x; eff='DISABLED_'+status
            else:
                op=OPS.get(status,'pre')
                if op=='add':
                    if x>=1.0: x_after=x; eff='ADD_AT_CAP'; n_cap+=1
                    else: x_after=min(x+a_f*(1-x),1.0); eff=status
                    n_add+=1
                elif op=='red': x_after=x*r_f; eff=status; n_red+=1
                elif op=='ext': x_after=0.0; eff=status; n_ext+=1; locked=True
                elif op=='hod': x_after=x; eff=status
                else:
                    x_after=x; eff=status
                    if status=='CONFLICT_OPPORTUNITY_RISK': n_conf+=1
                    if status=='NO_ACTION_EVIDENCE': n_noev+=1
        else: x_after=x; eff='STATIC_HOLD'
        if 0<x_after<0.05: dust+=1
        if x_after>0: exp_sum+=x_after; exp_days+=1
        if collect_daily is not None and filled:
            collect_daily.append((ev,segment,strategy,policy_id,d,prev_x,ret,pnl,x_after,eff,term))
        prev_x=x_after
        x=x_after
        if isinstance(term,str):
            term_reason=term; break
    agg={'ret_ep_log':cum,'bh_ret_ep_log':bh,
         'mdd_ep':trough if trough<0 else 0.0,'mfe_pnl_ep':mfe if mfe>-np.inf else 0.0,
         'mean_exposure':exp_sum/max(n_days,1),'exposure_pos_days':exp_days,
         'dust_days_x_lt_5pct':dust,'n_add':n_add,'n_reduce':n_red,'n_exit':n_ext,
         'n_add_at_cap':n_cap,'n_conflict_preserve':n_conf,'n_no_evidence_preserve':n_noev,
         'n_post_exit_locked':n_lock,'n_days_traded':n_days,'terminal_reason':term_reason}
    return agg


def main():
    ev_days, ev_branch, seg_map = build_inputs()
    contract = {
        'baseline': '8c4a992',
        'execution_clock': 'signal at close t -> target exposure effective for the (t, t+1] return; pnl_d = x_{d-1} * ret_1d_log_d; day-0 return not traded (entry fills at close)',
        'real_x0': {'rule': 'x_0 = actual_initial_exposure / base_risk_budget', 'filled(close)': 1.0, 'not_filled': 0.0, 't5_7_x0_eq_1_assumption': 'REVOKED'},
        'p0': 'NON_PARTICIPATION_CONTROL: base=0 branches recorded as control, excluded from dynamic exposure stats',
        'not_filled': 'NO_POSITION for the entire lifecycle; T5 ADD can never create a position (hard invariant)',
        'terminal': {'LIFECYCLE_END': 'episode settlement (natural end)', 'MAX_HORIZON': 'right-censored episode, reported separately'},
        'execution_semantics': {'E0_exact': 'primary: any x>0 remains a position', 'E1_dust': 'sensitivity only: x<0.05 counted as dust-days, threshold NOT frozen, not converted to EXIT'},
        'matrix': {'entry_strategies': ENTRY_STRATS, 'policies': list(POLICIES),
                   'counterfactuals': ['static_no_T5 (per strategy)', 'no_ADD/no_REDUCE/no_EXIT (P2 attribution)']},
        'suspension': 'ret NaN days contribute zero pnl; exposure carried frozen'}
    (OUT/'t5_8_simulation_contract.json').write_text(json.dumps(contract, indent=2, ensure_ascii=False))
    (OUT/'t5_8_execution_clock.json').write_text(json.dumps(
        {'rule': contract['execution_clock'], 'fill_basis': 'fill_status_close',
         'return_source': 't5_daily_state.ret_1d_log (T5.4 outcome clock, suspension-skipped)'}, indent=2, ensure_ascii=False))

    ep_rows=[]; attr_rows=[]; daily=[]; part=0; n_daily=0
    def flush():
        nonlocal daily, part, n_daily
        if daily:
            pd.DataFrame(daily, columns=DAY_COLS).to_parquet(DPART/f'part{part:04d}.parquet', index=False)
            n_daily+=len(daily); part+=1; daily=[]
    for ev, branches in ev_branch.items():
        dl = ev_days.get(ev)
        if dl is None: continue
        segment = seg_map.get(ev)
        for (strategy, base, filled) in branches:
            if base == 0.0:
                ep_rows.append({'event_id':ev,'segment':segment,'strategy':strategy,'policy_id':'CONTROL',
                                'branch':'NON_PARTICIPATION_CONTROL','filled':bool(filled),'base':0.0,
                                'ret_ep_log':0.0,'bh_ret_ep_log':0.0,'terminal_reason':None})
                continue
            for pid,(a_f,r_f) in POLICIES.items():
                agg = replay(dl, base, filled, a_f, r_f, collect_daily=daily if filled else None,
                             strategy=strategy, policy_id=pid, segment=segment, ev=ev)
                ep_rows.append({'event_id':ev,'segment':segment,'strategy':strategy,'policy_id':pid,
                                'branch':f'{strategy}|{pid}','filled':bool(filled),'base':base,**agg})
            agg = replay(dl, base, filled, 0.0, 1.0, static=True)
            attr_rows.append({'event_id':ev,'segment':segment,'strategy':strategy,
                              'variant':'static_no_T5','policy_id':'STATIC',**agg})
            if filled:
                for disable in ('RESOLVED_ADD','RESOLVED_REDUCE','RESOLVED_EXIT'):
                    agg = replay(dl, base, filled, 0.5, 0.5, disable=disable)
                    attr_rows.append({'event_id':ev,'segment':segment,'strategy':strategy,
                                      'variant':'disable_'+disable.split('_')[1].lower(),
                                      'policy_id':'P2_balanced',**agg})
        if len(daily) >= FLUSH_ROWS:
            flush()
    flush()

    ep = pd.DataFrame(ep_rows)
    ep['portfolio_contribution'] = ep.base*ep.ret_ep_log
    ep['censored'] = ep.terminal_reason=='MAX_HORIZON'
    ep.to_parquet(OUT/'t5_8_episode_results.parquet', index=False)
    pd.concat([pd.read_parquet(f) for f in sorted(DPART.glob('part*.parquet'))]).to_parquet(
        OUT/'t5_8_daily_exposure_pnl.parquet', index=False)
    for f in sorted(DPART.glob('part*.parquet')): f.unlink()
    DPART.rmdir()
    pd.DataFrame(attr_rows).to_parquet(OUT/'t5_8_counterfactual_attribution.parquet', index=False)

    act = ep[ep.policy_id!='CONTROL']
    cells = (act.groupby(['strategy','policy_id'])
             .agg(n_episodes=('event_id','size'), filled_rate=('filled','mean'),
                  mean_ret_ep=('ret_ep_log','mean'), median_ret_ep=('ret_ep_log','median'),
                  mean_contrib=('portfolio_contribution','mean'), mean_mdd=('mdd_ep','mean'),
                  p95_loss=('ret_ep_log', lambda s: s.quantile(0.05)),
                  mean_exposure=('mean_exposure','mean'),
                  mean_n_reduce=('n_reduce','mean'), mean_n_add=('n_add','mean'),
                  mean_dust_days=('dust_days_x_lt_5pct','mean'), censored_rate=('censored','mean')).reset_index())
    cells.to_parquet(OUT/'t5_8_strategy_matrix.parquet', index=False)
    spm = (act.groupby(['segment','strategy','policy_id'])
           .agg(n=('event_id','size'), mean_ret_ep=('ret_ep_log','mean'),
                median_ret_ep=('ret_ep_log','median'), mean_mdd=('mdd_ep','mean'),
                mean_exposure=('mean_exposure','mean'),
                mean_conflict_days=('n_conflict_preserve','mean'),
                mean_noev_days=('n_no_evidence_preserve','mean'),
                censored_rate=('censored','mean')).reset_index())
    spm.to_parquet(OUT/'t5_8_split_metrics.parquet', index=False)
    (act.groupby(['segment','terminal_reason']).agg(n=('event_id','size')).reset_index()
        ).to_parquet(OUT/'t5_8_censor_terminal_audit.parquet', index=False)

    man = {'stage':'T5.8_full_lifecycle','baseline':'8c4a992',
           'episodes': {'total_rows': len(ep), 'control_p0': int((ep.policy_id=='CONTROL').sum()),
                        'active_12cell': int(len(act)),
                        'not_filled_no_position': int(((ep.policy_id!='CONTROL')&(~ep.filled)).sum()),
                        'censored_max_horizon': int(ep.censored.sum())},
           'daily_rows': int(n_daily), 'attribution_rows': len(attr_rows),
           'pnl_computed': True, 'champion_ranking': False, 'parameter_tuning': False}
    (OUT/'t5_8_manifest.json').write_text(json.dumps(man, indent=2, ensure_ascii=False))
    print(json.dumps(man, indent=2))
    print(cells.round(4).to_string(index=False))

if __name__ == '__main__':
    main()
