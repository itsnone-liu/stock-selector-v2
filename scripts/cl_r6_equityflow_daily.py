#!/usr/bin/env python3
"""R6 EquityFlow daily collector (Pipeline B, PRE-RESEARCH data collection only).
Collects OFFICIAL exchange data daily; NO analysis, NO joins with outcomes, NO panel.
Sources: SSE ETF shares (fund_etf_scale_sse), SZSE ETF shares (fund_scale_daily_szse),
SSE margin (stock_margin_sse), SZSE margin (stock_margin_szse per-date).
Env: PYTHONPATH=/tmp/aksy (akshare needs its own pandas). Run AFTER ~19:30 CST.
Append-only jsonl.gz per stream; each record carries fetch_date + source + fields."""
import gzip,json,sys,datetime as dt
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/cl_radar/r6_equityflow';OUT.mkdir(parents=True,exist_ok=True)
def append(name,records):
    if not records:return 0
    p=OUT/f'{name}.jsonl.gz'
    with gzip.open(p,'at') as f:
        for r in records:f.write(json.dumps(r,separators=(',',':'),default=str)+'\n')
    return len(records)
def last_dates(name,key):
    p=OUT/f'{name}.jsonl.gz'
    if not p.exists():return set()
    return {json.loads(l)[key] for l in gzip.open(p,'rt')}
def main(target=None):
    import akshare as ak
    today=target or dt.date.today().strftime('%Y%m%d')
    n=0;log=[]
    # 1) SSE ETF shares (per-date query)
    try:
        have=last_dates('etf_sse','date')
        if today not in have:
            df=ak.fund_etf_scale_sse(date=today)
            recs=[{'date':today,'fetch_date':dt.date.today().isoformat(),'source':'SSE official',
                   'code':str(r['基金代码']),'name':r['基金简称'],'etype':r['ETF类型'],'shares':float(r['基金份额'])}
                  for _,r in df.iterrows()]
            n+=append('etf_sse',recs);log.append(f'etf_sse={len(recs)}')
        else:log.append('etf_sse=skip(dup)')
    except Exception as e:log.append(f'etf_sse=FAIL {repr(e)[:80]}')
    # 2) SZSE ETF shares (range query; re-fetch month-to-date, dedup by date+code)
    try:
        mo=f'{today[:6]}01'
        df=ak.fund_scale_daily_szse(start_date=mo,end_date=today,symbol="ETF")
        p=OUT/'etf_szse.jsonl.gz'; have=set()
        if p.exists():
            have={json.loads(l)['date']+'|'+json.loads(l)['code'] for l in gzip.open(p,'rt')}
        recs=[]
        for _,r in df.iterrows():
            date=str(r['日期']); code=str(r['基金代码']); key=date+'|'+code
            if key not in have:
                recs.append({'date':date,'fetch_date':dt.date.today().isoformat(),'source':'SZSE official',
                             'code':code,'shares':float(r['基金份额'])})
        n+=append('etf_szse',recs);log.append(f'etf_szse={len(recs)}')
    except Exception as e:log.append(f'etf_szse=FAIL {repr(e)[:80]}')
    # 3) SSE margin (range, daily rows)
    try:
        y=today[:4];have=last_dates('margin_sse','date')
        df=ak.stock_margin_sse(start_date=f'{y}0101',end_date=today)
        recs=[{'date':str(r['信用交易日期']),'fetch_date':dt.date.today().isoformat(),'source':'SSE official',
               'rzye':float(r['融资余额']),'rzmre':float(r['融资买入额']),'rqye':float(r['融券余量金额']),
               'rzrqye':float(r['融资融券余额'])} for _,r in df.iterrows()
              if str(r['信用交易日期']) not in have]
        n+=append('margin_sse',recs);log.append(f'margin_sse={len(recs)}')
    except Exception as e:log.append(f'margin_sse=FAIL {repr(e)[:80]}')
    # 4) SZSE margin (per-date; only today, cheap)
    try:
        have=last_dates('margin_szse','date')
        if today not in have:
            df=ak.stock_margin_szse(date=today)
            tot=df[['融资买入额','融资余额','融券卖出量','融券余量','融券余额','融资融券余额']].sum(numeric_only=True)
            recs=[{'date':today,'fetch_date':dt.date.today().isoformat(),'source':'SZSE official',
                   **{k:float(v) for k,v in tot.items()}}]
            n+=append('margin_szse',recs);log.append(f'margin_szse=1')
        else:log.append('margin_szse=skip(dup)')
    except Exception as e:log.append(f'margin_szse=FAIL {repr(e)[:80]}')
    print('R6_EQUITYFLOW',today,' '.join(log))
    if all('=FAIL' in x for x in log):sys.exit(1)
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else None)
