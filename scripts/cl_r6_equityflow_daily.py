#!/usr/bin/env python3
"""R6 EquityFlow daily collector (Pipeline B, PRE-RESEARCH data collection only).
Collects OFFICIAL exchange data daily; NO analysis, NO joins with outcomes, NO panel.
Sources: SSE ETF shares (fund_etf_scale_sse), SZSE ETF shares (fund_scale_daily_szse),
SSE margin (stock_margin_sse), SZSE margin (stock_margin_szse per-date).
Env: PYTHONPATH=/tmp/aksy (akshare needs its own pandas). Run AFTER ~19:30 CST.
Append-only jsonl.gz per stream; each record carries fetch_date + source + fields.

2026-10-19 revision (per-date streams auto-backfill):
- etf_sse / margin_szse previously queried ONLY "today"; when the exchange had not
  published same-day data by run time the query raised (empty payload -> akshare
  KeyError/ValueError) and the missed date was never retried -> permanent hole
  (2026-10-16 was backfilled manually via the target-arg).
- Now: every missing CONFIRMED trading day in a <=10-calendar-day window is queried.
  The trading calendar is derived from the SSE margin range stream (official dates,
  fetched first); when that fetch fails, a Mon-Fri fallback is used.
- "Not yet published" (empty payload) for TODAY logs pending(...) and is NOT a
  failure — the next run heals it. Empty payload for a confirmed trading day OLDER
  than today IS a failure (source-side break, e.g. page redesign). Transport errors
  fail the stream (the pipeline entry retries the whole script once, dedup-safe)."""
import gzip,json,sys,datetime as dt
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/cl_radar/r6_equityflow';OUT.mkdir(parents=True,exist_ok=True)
EMPTY_EXC=(KeyError,ValueError)  # akshare empty-payload signature = date not published yet

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

def candidates(have,today,trade_days,lookback=10):
    """Missing per-date query targets: dates in [today-lookback, today] not already
    stored, restricted to confirmed trading days (calendar from SSE margin range).
    TODAY is always attempted; without a calendar (margin fetch failed) fall back
    to Mon-Fri so one broken stream cannot stall the other's backfill."""
    t=dt.datetime.strptime(today,'%Y%m%d').date()
    out=[];d=t-dt.timedelta(days=lookback)
    while d<=t:
        s=d.strftime('%Y%m%d')
        if s not in have and (s==today or s in trade_days or (not trade_days and d.weekday()<5)):
            out.append(s)
        d+=dt.timedelta(days=1)
    return out

def main(target=None):
    import akshare as ak
    today=target or dt.date.today().strftime('%Y%m%d')
    n=0;log=[];fails=[]
    # 0) SSE margin (range) FIRST — its official trade dates double as the
    #    A-share trading calendar for the per-date streams below.
    trade_days=set();mlog=''
    try:
        y=today[:4];have=last_dates('margin_sse','date')
        df=ak.stock_margin_sse(start_date=f'{y}0101',end_date=today)
        trade_days={str(d).replace('-','') for d in df['信用交易日期']}
        recs=[{'date':str(r['信用交易日期']).replace('-',''),'fetch_date':dt.date.today().isoformat(),'source':'SSE official',
               'rzye':float(r['融资余额']),'rzmre':float(r['融资买入额']),'rqye':float(r['融券余量金额']),
               'rzrqye':float(r['融资融券余额'])} for _,r in df.iterrows()
              if str(r['信用交易日期']).replace('-','') not in have]
        n+=append('margin_sse',recs);mlog=f'margin_sse={len(recs)}'
    except Exception as e:
        mlog=f'margin_sse=FAIL {repr(e)[:80]}';fails.append(mlog)
    # 1) SSE ETF shares (per-date; auto-backfill missing trading days)
    try:
        have=last_dates('etf_sse','date')
        todo=candidates(have,today,trade_days)
        wrote=0;pend=[];nodata=[];sfail=None
        for d in todo:
            try:
                df=ak.fund_etf_scale_sse(date=d)
                recs=[{'date':d,'fetch_date':dt.date.today().isoformat(),'source':'SSE official',
                       'code':str(r['基金代码']),'name':r['基金简称'],'etype':r['ETF类型'],'shares':float(r['基金份额'])}
                      for _,r in df.iterrows()]
                if not recs:nodata.append(d)     # served 0 rows (endpoint keeps ~6 recent trade days)
                wrote+=append('etf_sse',recs)
            except EMPTY_EXC:
                if d==today:pend.append(d)      # race with publication — next run heals
                else:sfail=f'etf_sse=FAIL empty(published trade day {d})';break
            except Exception as e:
                sfail=f'etf_sse=FAIL {repr(e)[:60]}';break
        if sfail:log.append(sfail);fails.append(sfail)
        elif not todo:log.append('etf_sse=skip(dup)')
        else:log.append(f'etf_sse={wrote}'
                        +(f' pending=({",".join(pend)})' if pend else '')
                        +(f' empty=({",".join(nodata)})' if nodata else ''))
    except Exception as e:
        log.append(f'etf_sse=FAIL {repr(e)[:80]}');fails.append(log[-1])
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
                             'code':code,'name':str(r.get('基金简称','')),'shares':float(r['基金份额'])})
        n+=append('etf_szse',recs);log.append(f'etf_szse={len(recs)}')
    except Exception as e:log.append(f'etf_szse=FAIL {repr(e)[:80]}');fails.append(log[-1])
    # 3) append the margin_sse log entry in canonical stream order
    log.append(mlog)
    # 4) SZSE margin (per-date; auto-backfill missing trading days)
    try:
        have=last_dates('margin_szse','date')
        todo=candidates(have,today,trade_days)
        wrote=0;pend=[];nodata=[];sfail=None
        for d in todo:
            try:
                df=ak.stock_margin_szse(date=d)
                tot=df[['融资买入额','融资余额','融券卖出量','融券余量','融券余额','融资融券余额']].sum(numeric_only=True)
                if df.empty:nodata.append(d)
                wrote+=append('margin_szse',[{'date':d,'fetch_date':dt.date.today().isoformat(),'source':'SZSE official',
                    **{k:float(v) for k,v in tot.items()}}])
            except EMPTY_EXC:
                if d==today:pend.append(d)
                else:sfail=f'margin_szse=FAIL empty(published trade day {d})';break
            except Exception as e:
                sfail=f'margin_szse=FAIL {repr(e)[:60]}';break
        if sfail:log.append(sfail);fails.append(sfail)
        elif not todo:log.append('margin_szse=skip(dup)')
        else:log.append(f'margin_szse={wrote}'+(' row(s)' if wrote else '')
                        +(f' pending=({",".join(pend)})' if pend else '')
                        +(f' empty=({",".join(nodata)})' if nodata else ''))
    except Exception as e:
        log.append(f'margin_szse=FAIL {repr(e)[:80]}');fails.append(log[-1])
    print('R6_EQUITYFLOW',today,' '.join(log))
    # Any required stream failing must fail the pipeline: the old `all('=FAIL' in x ...)`
    # only tripped when ALL FOUR streams failed, so 3/4 failing still exited 0 and
    # daily_pipelines.sh recorded RC_B=0 (silent data hole).
    if fails:
        print('R6_EQUITYFLOW_FAILED',' | '.join(f for f in fails if '=FAIL' in f),file=sys.stderr)
        sys.exit(1)
if __name__=='__main__':main(sys.argv[1] if len(sys.argv)>1 else None)
