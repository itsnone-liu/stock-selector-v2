#!/usr/bin/env python3
"""Build T3 V3 event x market-calendar tau trajectory facts.

No event_labels import/join. Daily rows are as-of-tau only; summary and
checkpoints are derived from daily parquet after construction.
"""
from __future__ import annotations
import hashlib, json, sys, time
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path('/root/project/workspace/stock-selector-v2')
sys.path.insert(0, str(ROOT/'src'))
from stock_selector.research import t3_v2 as v2
from stock_selector.research import t3_v3 as v3

OUT = ROOT/'output/research/t3_v3'

def sha(p):
    h=hashlib.sha256()
    with open(p,'rb') as f:
        for b in iter(lambda:f.read(1<<20),b''): h.update(b)
    return h.hexdigest()

def same(a,b):
    if pd.isna(a) and pd.isna(b): return True
    return a == b

def main():
    t0=time.time(); OUT.mkdir(parents=True, exist_ok=True)
    v2out=ROOT/'output/research/t3_v2'
    factors=v2.load_factor_cache(v2out)
    ev=v2.load_events()
    mdates,mclose=v2.market_calendar_and_close(); mpos={d:i for i,d in enumerate(mdates)}
    by_code={}
    for r in ev.itertuples(index=False): by_code.setdefault(r.code,[]).append(r._asdict())
    daily_parts=[]; missing_codes=[]
    for ci,code in enumerate(sorted(by_code)):
        pref=v3.stock_prefix(code)
        fp=ROOT/f'data/adjustment_baostock/per_stock/{pref}.json.gz'
        if not fp.exists(): missing_codes.append(code); continue
        sd=v2.load_stock_data(pref,factors)
        for row in by_code[code]:
            d=v3.build_event_daily(sd,row,mdates,mclose,mpos)
            daily_parts.append(d)
        if ci%250==249: print(f'[v3] {ci+1}/{len(by_code)} codes {time.time()-t0:.0f}s',flush=True)
    daily=pd.concat(daily_parts,ignore_index=True).sort_values(['breakout_event_id','tau']).reset_index(drop=True)
    summary=pd.DataFrame([v3.summarize_event(g) for _,g in daily.groupby('breakout_event_id',sort=False)])
    summary=summary.sort_values('breakout_event_id').reset_index(drop=True)
    checkpoints=daily[daily.tau.isin(v3.CHECKPOINTS)].copy().reset_index(drop=True)
    daily.to_parquet(OUT/'event_path_daily.parquet',index=False,compression='snappy')
    checkpoints.to_parquet(OUT/'event_path_checkpoints.parquet',index=False,compression='snappy')
    summary.to_parquet(OUT/'event_path_summary.parquet',index=False,compression='snappy')
    # Field coverage is descriptive, not a model/selection result.
    cov=[]
    for c in daily.columns:
        n=int(daily[c].notna().sum()); miss=len(daily)-n
        cov.append({'field':c,'n_valid':n,'n_missing':miss,'coverage_pct':round(100*n/len(daily),4),
                    'source':'calendar/date or as-of tau fact'})
    pd.DataFrame(cov).to_csv(OUT/'trajectory_field_coverage.csv',index=False)
    report={'task':'T3_V3_event_evolution','baseline_commit':'a7cfbb9',
            'events':len(ev),'daily_rows':len(daily),'expected_daily_rows':len(ev)*41,
            'checkpoint_rows':len(checkpoints),'summary_rows':len(summary),
            'calendar_range':[mdates[0],mdates[-1]],'dataset_end':v2.DATASET_END,
            'missing_codes':missing_codes,
            'products':{},'elapsed_sec':round(time.time()-t0,2)}
    for n in ('event_path_daily','event_path_checkpoints','event_path_summary'):
        p=OUT/f'{n}.parquet'; report['products'][n]={'rows':len(pd.read_parquet(p)),'sha256':sha(p)}
    (OUT/'trajectory_field_coverage.csv').resolve()
    (OUT/'trajectory_integrity_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
