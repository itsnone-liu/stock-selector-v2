#!/usr/bin/env python3
"""R2-0 market daily extension: amount / turnover_rate / free-float history.

**TDX 通道（2026-10-21 起默认）**：`Session.daily()` 裸价 OHLC + amount(元) +
volume(股) + `Session.capital_batch()` 流通股本 → turnover_rate(比值口径，与旧
sina 一致：volume/outstanding_share)。

⚠️ 口径说明（老刘 2026-10-21）：`outstanding_share` 取 **TDX 股本快照（当前值）**，
非历史值。股权发生过变动（定增/解禁）的票，其早期 turnover_rate 为近似值 —— 按
"个别算不准就用现值 + 人工判断" 口径接受，meta 里显式标注 `turnover_basis`。

`--source akshare` 保留旧链路（akshare/sina）作应急回退。

Append-only, resumable, provenance-meta per file.
"""
from __future__ import annotations
import argparse,json,sys,time,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; OUT=ROOT/'data/r2/market_ext'
sys.path.insert(0,str(ROOT/'src'))


def fetch_akshare(code:str,start:str,end:str):
 """旧链路（akshare stock_zh_a_daily/sina）。仅 --source akshare 时调用。"""
 import akshare as ak
 sym=('sh' if code.startswith('6') else 'sz')+code
 df=ak.stock_zh_a_daily(symbol=sym,start_date=start,end_date=end)
 rows=[]
 for _,r in df.iterrows():
  def g(k):
   v=r[k] if k in r else None
   return None if v is None or v!=v else float(v)
  rows.append({'date':str(r['date'])[:10],'open':g('open'),'close':g('close'),'high':g('high'),'low':g('low'),'volume':g('volume'),'amount':g('amount'),'outstanding_share':g('outstanding_share'),'turnover_rate':g('turnover')})
 return rows


_tdx_sess=None
def _tdx():
 global _tdx_sess
 if _tdx_sess is None:
  from r2.tdx_client import Session,DEFAULT_HOSTS
  errs=[]
  for ep in DEFAULT_HOSTS:
   h,_,pt=ep.partition(':'); pt=int(pt or 7709)
   try:
    _tdx_sess=Session(h,pt); break
   except (OSError,ConnectionError,ValueError) as e:
    errs.append(f'{ep}:{type(e).__name__}')
  if _tdx_sess is None: raise ConnectionError('tdx no host: '+', '.join(errs))
 return _tdx_sess


def _need_count(start:str,end:str)->int:
 d0=datetime.date(int(start[:4]),int(start[4:6]),int(start[6:8]))
 d1=datetime.date(int(end[:4]),int(end[4:6]),int(end[6:8]))
 return min(12000,int((d1-d0).days*5/7)+80)


def fetch_tdx(code:str,start:str,end:str):
 """TDX 通道：日线裸价 + amount(元) + volume(股) + 当前流通股本。"""
 mkt=1 if code[0] in '69' else 0
 s=_tdx()
 raw=s.daily(mkt,code,count=_need_count(start,end))
 fs=None
 try:
  cap=s.capital_batch([(mkt,code)])
  if cap and cap[0].get('float_shares'): fs=float(cap[0]['float_shares'])
 except (ValueError,OSError,ConnectionError):
  fs=None
 rows=[]
 for b in raw:
  d=b['date']
  if not (start<=d<=end): continue
  v=b['volume_hand']; amt=b['amount']
  rows.append({'date':d,'open':b['open'],'close':b['close'],'high':b['high'],'low':b['low'],
               'volume':v,'amount':amt,'outstanding_share':fs,
               'turnover_rate':(v/fs) if (fs and v is not None) else None})
 return rows,fs


def fetch(code:str,start:str,end:str,source='tdx'):
 if source=='tdx':
  rows,fs=fetch_tdx(code,start,end)
  return rows,fs
 return fetch_akshare(code,start,end),None


def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--limit',type=int,default=0);ap.add_argument('--shard',default='')
 ap.add_argument('--start',default='20210101');ap.add_argument('--end',default='')
 ap.add_argument('--source',default='tdx',choices=('tdx','akshare'))
 ap.add_argument('--out',default='');ap.add_argument('--sleep',type=float,default=-1)
 ap.add_argument('--update',action='store_true',
                 help='对已存在文件只追加新交易日（保留旧源行不动，meta 记 update_source）')
 a=ap.parse_args()
 end=a.end or datetime.date.today().strftime('%Y%m%d')
 out=Path(a.out) if a.out else OUT
 allc=sorted(p.name[:-8] for p in (ROOT/'data/cd/daily_fullmarket').glob('*.json.gz'))
 codes=allc if a.limit==0 else allc[:a.limit]
 if a.shard:
  i,n=map(int,a.shard.split('/')); codes=[c for k,c in enumerate(codes) if k%n==i]
 out.mkdir(parents=True,exist_ok=True); ok=0; fails=[]
 slp=a.sleep if a.sleep>=0 else (0.0 if a.source=='tdx' else 0.4)
 for i,code in enumerate(codes):
  dst=out/f'{code}.json'
  if dst.exists() and not a.update: ok+=1; continue
  try:
   if dst.exists() and a.update:
    old=json.loads(dst.read_text()); lastd=old['rows'][-1]['date'] if old['rows'] else ''
    start2=max(a.start,lastd.replace('-','') if lastd else a.start)
    rows,_fs=fetch(code,start2,end,a.source)
    newr=[r for r in rows if r['date']>lastd]
    napp=0
    if newr:
     old['rows'].extend(newr); napp=len(newr)
     old['meta']['n']=len(old['rows'])
     old['meta']['update_source']=('tdx' if a.source=='tdx' else a.source)
     old['meta']['update_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ'); old['meta']['update_end']=end
    tmp=dst.with_suffix('.tmp'); tmp.write_text(json.dumps(old,ensure_ascii=False)); tmp.replace(dst)
    ok+=1
    if i%5==0: print(f'{i+1}/{len(codes)} {code} +{napp} rows (last {lastd}→{end})',flush=True)
    time.sleep(slp); continue
   rows,fs=fetch(code,a.start,end,a.source)
   if a.source=='tdx':
    meta={'code':code,'source':'tdx:Session.daily+capital_batch','fetched_at':time.strftime('%Y-%m-%dT%H:%M:%SZ'),'start':a.start,'end':end,'n':len(rows),'turnover_basis':'current_float_shares (近似；股本变动票早段 turnover 近似)'}
   else:
    meta={'code':code,'source':'akshare:stock_zh_a_daily(sina)','fetched_at':time.strftime('%Y-%m-%dT%H:%M:%SZ'),'start':a.start,'end':end,'n':len(rows)}
   dst.write_text(json.dumps({'meta':meta,'rows':rows},ensure_ascii=False)); ok+=1
   if i%5==0: print(f'{i+1}/{len(codes)} {code} {len(rows)} rows fs={fs}',flush=True)
  except Exception as e:
   fails.append({'code':code,'error':str(e)[:200]})
  time.sleep(slp)
 print(json.dumps({'ok':ok,'fails':len(fails),'fail_sample':fails[:5],'source':a.source,'end':end},ensure_ascii=False))
if __name__=='__main__':main()