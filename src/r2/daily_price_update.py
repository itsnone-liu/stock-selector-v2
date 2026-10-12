#!/usr/bin/env python3
"""R2-DU(A): daily incremental price update for data/cd/daily_fullmarket.

Per stock: append-only extension from tencent fqkline (same source as v3
acquisition), cross-validated against the local TDX mirror (/root/tdx_data).
Fail-closed: any mismatch skips the stock and is reported explicitly.

Usage:
  daily_price_update.py --day 2026-10-08 [--limit 20] [--shard i/n]
Manifest: data/r2/daily_update/update_<day>.json
"""
from __future__ import annotations
import argparse,gzip,json,os,struct,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DAILY=ROOT/'data/cd/daily_fullmarket'; TDX=Path('/root/tdx_data/vipdoc')
OUTD=ROOT/'data/r2/daily_update'
URL='https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get'
UA={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64)'}
try:
 import requests
except ImportError:
 os.system(f'{sys.executable} -m pip install -q requests'); import requests

def tx_full(c):
 return ('sh'+c) if c.startswith(('6','9')) else (('bj'+c) if c.startswith(('4','8')) else 'sz'+c)

def tdx_path(c):
 mkt='sh' if c[0] in '69' else ('bj' if c[0] in '48' else 'sz')
 return TDX/mkt/'lday'/f'{mkt}{c}.day'

_tdx_cache:dict[str,dict]={}
def tdx_closes(c):
 if c in _tdx_cache: return _tdx_cache[c]
 p=tdx_path(c)
 m={}
 if p.exists():
  b=p.read_bytes()
  for i in range(len(b)//32):
   d,o,h,l,cl,amt,vol,_r=struct.unpack('<IIIIIfIf',b[i*32:(i+1)*32])
   m[str(d)]=(cl/100,vol/100)
 _tdx_cache[c]=m
 return m

def fetch(sess,full,last,day):
 """Return {date: (raw_row, qfq_row)} for one small window. end is exclusive (v3 convention)."""
 import datetime as dt
 end=(dt.date.fromisoformat(day)+dt.timedelta(days=1)).isoformat()
 out={}
 for fq in ('','qfq'):
  field='qfqday' if fq else 'day'
  r=None
  for attempt in range(3):
   try:
    resp=sess.get(URL,params={'param':f'{full},day,{last},{end},640,{fq}'},timeout=12,headers=UA)
    j=resp.json()['data'][full]
    r=j.get(field) or j.get('day')
    break
   except Exception:
    if attempt==2: return None
    time.sleep(15)
  if r is None: r=[]
  m={row[0]:row for row in r}
  if fq:
   out['_q']=m
  else:
   out['_r']=m
  time.sleep(0.35)
 return out if '_r' in out and '_q' in out else None

def update_stock(sess,code,day,strict_tdx=True):
 p=DAILY/f'{code}.json.gz'
 d=json.loads(gzip.decompress(p.read_bytes()))
 last=d['dates'][-1]
 if last>=day: return ('current',0)
 seg=fetch(sess,tx_full(code),last,day)
 if seg is None: return ('fetch_fail',0)
 raw,qm=seg['_r'],seg['_q']
 if last not in raw or last not in qm: return ('overlap_missing',0)
 if raw[last][:6]!=d['unadj'][-1][:6]: return ('overlap_raw_mismatch',0)
 if qm[last][:6]!=d['qfq'][-1][:6]: return ('overlap_qfq_mismatch',0)
 nds=sorted(x for x in raw if x>last and x in qm)
 tdx=tdx_closes(code); mism=[]
 for dt_ in nds:
  t=tdx.get(dt_.replace('-',''))
  tc=float(raw[dt_][2])
  if t is None: mism.append((dt_,'no_tdx_bar')); continue
  if abs(t[0]-tc)>0.011: mism.append((dt_,f'close {tc} vs tdx {t[0]}'))
 # bars present in TDX window but not returned by tencent (non-suspension)
 for k in tdx:
  ks=f'{k[:4]}-{k[4:6]}-{k[6:]}'
  if last<ks<=day and ks not in nds: mism.append((ks,'tdx_bar_not_fetched'))
 if mism and strict_tdx: return ('tdx_mismatch',mism)
 if not nds: return ('no_change',0)
 newu=[raw[x][:6] for x in nds]; newq=[qm[x][:6] for x in nds]
 newf=[round(float(qm[x][2])/float(raw[x][2]),6) if float(raw[x][2]) else 1.0 for x in nds]
 d['dates']+=nds; d['unadj']+=newu; d['qfq']+=newq
 d.setdefault('adjust_factor_model_derived',[])
 if len(d['adjust_factor_model_derived'])==len(d['dates'])-len(nds):
  d['adjust_factor_model_derived']+=newf
 d['fetched_at']=time.strftime('%Y-%m-%dT%H:%M:%SZ')
 tmp=p.with_suffix('.tmp.gz')
 tmp.write_bytes(gzip.compress(json.dumps(d,ensure_ascii=False).encode()))
 os.replace(tmp,p)
 return ('updated',len(nds))

def main():
 ap=argparse.ArgumentParser()
 ap.add_argument('--day',required=True); ap.add_argument('--limit',type=int,default=0)
 ap.add_argument('--shard',default='')
 a=ap.parse_args()
 codes=sorted(p.name[:-8] for p in DAILY.glob('*.json.gz'))
 if a.shard: i,n=map(int,a.shard.split('/')); codes=[c for k,c in enumerate(codes) if k%n==i]
 if a.limit: codes=codes[:a.limit]
 day=a.day; sess=requests.Session()
 stats={}; fails=[]; mism=[]; nbars=0
 OUTD.mkdir(parents=True,exist_ok=True)
 t0=time.time()
 for i,code in enumerate(codes):
  st,extra=update_stock(sess,code,day)
  stats[st]=stats.get(st,0)+1
  if st in ('updated','no_change','current'): nbars+= extra if isinstance(extra,int) else 0
  if st not in ('updated','no_change','current','fetch_fail') or st=='fetch_fail': 
   (fails if st=='fetch_fail' else mism).append((code,st,extra if st=='tdx_mismatch' else None))
  if (i+1)%200==0: print(f'{i+1}/{len(codes)} elapsed {time.time()-t0:.0f}s {stats}',flush=True)
  time.sleep(0.15)
 man={'day':day,'n_codes':len(codes),'stats':stats,'new_bars':nbars,'elapsed_s':round(time.time()-t0),
      'fails':fails[:500],'tdx_mismatch':mism[:500],'generated_at':time.strftime('%Y-%m-%dT%H:%M:%SZ')}
 (OUTD/f'update_{day}.json').write_text(json.dumps(man,ensure_ascii=False,indent=1))
 print(json.dumps({k:man[k] for k in ('day','n_codes','stats','new_bars','elapsed_s')},ensure_ascii=False))
if __name__=='__main__': main()
