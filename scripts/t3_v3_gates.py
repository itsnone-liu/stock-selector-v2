#!/usr/bin/env python3
"""T3 V3 five gates + deterministic/invariant/PIT evidence."""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path('/root/project/workspace/stock-selector-v2'); OUT=ROOT/'output/research/t3_v3'
sys.path.insert(0,str(ROOT/'src'))
from stock_selector.research import t3_v2 as v2
from stock_selector.research import t3_v3 as v3


def trunc(sd, cutoff):
    ks={d for d in sd.dates if d<=cutoff}
    return v2.StockData(sd.code_pfx, sorted(ks), None,
      {d:x for d,x in sd.h.items() if d in ks},{d:x for d,x in sd.l.items() if d in ks},
      {d:x for d,x in sd.c.items() if d in ks},{d:x for d,x in sd.vol.items() if d in ks},
      {d:x for d,x in sd.amt.items() if d in ks},{d:x for d,x in sd.turn.items() if d in ks},
      {},{}, {d:x for d,x in sd.F.items() if d in ks},
      [d for d in sd.valid if d in ks],{d for d in sd.vpos if d in ks})

def eq(a,b):
    if pd.isna(a) and pd.isna(b): return True
    if isinstance(a,(float,np.floating)) and isinstance(b,(float,np.floating)):
        return bool(np.isclose(a,b,rtol=1e-12,atol=1e-12,equal_nan=True))
    return a==b

def main():
    daily=pd.read_parquet(OUT/'event_path_daily.parquet')
    ev=v2.load_events(); mdates,mclose=v2.market_calendar_and_close(); mpos={d:i for i,d in enumerate(mdates)}
    factors=v2.load_factor_cache(ROOT/'output/research/t3_v2')
    byid={r.breakout_event_id:r._asdict() for r in ev.itertuples(index=False)}
    bycode={c:[] for c in ev.code.unique()}
    for r in ev.itertuples(index=False): bycode[r.code].append(r._asdict())
    # Calendar Gate
    counts=daily.groupby('breakout_event_id').size()
    cal=(len(daily)==len(ev)*41 and counts.eq(41).all() and
         daily.groupby('breakout_event_id').tau.apply(lambda x: tuple(x)==tuple(range(41))).all())
    # T0 Anchor Gate: V2 overlap primitives, no future labels.
    a1=pd.read_parquet(ROOT/'output/research/t3_v2/event_features_a1.parquet').set_index('breakout_event_id')
    b1=pd.read_parquet(ROOT/'output/research/t3_v2/event_features_b1.parquet').set_index('breakout_event_id')
    chip=pd.read_parquet(ROOT/'output/research/t3_v2/event_features_chip.parquet').set_index('breakout_event_id')
    d0=daily[daily.tau==0].set_index('breakout_event_id')
    anchor_checks=0; anchor_bad=[]
    for eid in d0.index:
        checks=[('ref60',d0.at[eid,'distance_to_ref60'],a1.at[eid,'a1_ref60_close_margin']),
                ('vol20',d0.at[eid,'volume_ratio_pre20'],b1.at[eid,'b1_vol_ratio_20']),
                ('vwap5',d0.at[eid,'price_to_rolling_vwap5'],chip.at[eid,'chip_price_to_vwap_5d'])]
        for name,x,y in checks:
            anchor_checks+=1
            if not eq(x,y):
                anchor_bad.append({'id':eid,'field':name,'v3':x,'v2':y})
                if len(anchor_bad)>=20: break
        if len(anchor_bad)>=20: break
    # Invariants, including tau0 and cumulative monotonic relations.
    inv_bad=[]
    for eid,g in daily.groupby('breakout_event_id',sort=False):
        g=g.sort_values('tau')
        for _,r in g.iterrows():
            if r.running_peak_return is not None and pd.notna(r.running_peak_return) and r.close_rel_t0_log is not None and pd.notna(r.close_rel_t0_log) and r.running_peak_return+1e-12 < r.close_rel_t0_log: inv_bad.append((eid,int(r.tau),'peak'))
        for c in ('new_high_count_to_tau','days_above_t0_to_tau','max_drawdown_to_tau'):
            x=g[c].dropna().to_numpy()
            if len(x)>1 and np.any(np.diff(x)<-1e-12): inv_bad.append((eid,c,'decrease'))
        z=g.iloc[0]
        for c,want in [('close_rel_t0_log',0.0),('days_above_t0_to_tau',0),('new_high_count_to_tau',0)]:
            if pd.notna(z[c]) and abs(float(z[c])-want)>1e-12: inv_bad.append((eid,'tau0',c))
    # PIT samples: deterministic category-first selection, tau set fixed.
    ids=list(daily.breakout_event_id.drop_duplicates())
    groups=[]
    # ordinary
    groups.append(('ordinary',ids[0]))
    # factor unavailable
    nofactor=daily.loc[~daily.adj_factor_available,'breakout_event_id']
    if len(nofactor): groups.append(('adj_factor_missing',nofactor.iloc[0]))
    # sample end
    se=daily.loc[(daily.tau==40)&(~daily.calendar_in_dataset),'breakout_event_id']
    if len(se): groups.append(('sample_end',se.iloc[0]))
    # post-T0 turnover missing
    tm=daily.loc[(daily.tau>0)&(~daily.turnover_ratio_pre20.notna()),'breakout_event_id']
    if len(tm): groups.append(('turnover_missing_candidate',tm.iloc[0]))
    groups += [('weekday_'+str(pd.Timestamp(byid[e]['breakout_day']).dayofweek),e) for e in ids[:5]]
    pit_bad=[]; pit_checked=0
    for label,eid in groups:
        row=byid[eid]; pref=v3.stock_prefix(row['code']); sd=v2.load_stock_data(pref,factors)
        full=v3.build_event_daily(sd,row,mdates,mclose,mpos)
        for tau in (0,1,5,10,20,40):
            if mpos[row['breakout_day']]+tau>=len(mdates): continue
            cutoff=mdates[mpos[row['breakout_day']]+tau]
            got=v3.build_event_daily(trunc(sd,cutoff),row,mdates,mclose,mpos).iloc[tau]
            expected=full.iloc[tau]; pit_checked+=1
            for c in full.columns:
                if c in ('breakout_event_id','code','breakout_day','tau'): continue
                if not eq(got[c],expected[c]):
                    pit_bad.append({'category':label,'id':eid,'tau':tau,'field':c,'full':repr(expected[c]),'trunc':repr(got[c])})
                    break
    # Missing/no fill: dates remain calendar dates and no values are filled across missing row.
    nofill = bool((daily.loc[~daily.row_present & daily.calendar_in_dataset].isna().any(axis=1)).all())
    # source_date causality
    source_ok=bool(((daily.source_date.isna()) | (daily.source_date<=daily.observation_date)).all())
    gates={'calendar':{'verdict':'PASS' if cal else 'FAIL','rows':len(daily),'expected':len(ev)*41},
      't0_anchor':{'verdict':'PASS' if not anchor_bad else 'FAIL','checked':anchor_checks,'bad':anchor_bad},
      'path_pit':{'verdict':'PASS' if not pit_bad else 'FAIL','checked':pit_checked,'bad':pit_bad},
      'path_invariant':{'verdict':'PASS' if not inv_bad else 'FAIL','bad_count':len(inv_bad),'sample':inv_bad[:20]},
      'missing_censor':{'verdict':'PASS' if nofill and source_ok else 'FAIL','no_fill_check':nofill,'source_date_causal':source_ok,'no_row_valid':int((~daily.row_present).sum())},
      'determinism_note':'run builder twice and compare product hashes'}
    (OUT/'trajectory_pit_audit.json').write_text(json.dumps(gates['path_pit'],ensure_ascii=False,indent=2,default=str))
    (OUT/'trajectory_integrity_gates.json').write_text(json.dumps(gates,ensure_ascii=False,indent=2,default=str))
    print(json.dumps(gates,ensure_ascii=False,indent=2,default=str))
    return 0 if all(g.get('verdict')=='PASS' for g in gates.values() if isinstance(g,dict)) else 1
if __name__=='__main__': raise SystemExit(main())
