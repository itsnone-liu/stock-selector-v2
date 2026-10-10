#!/usr/bin/env python3
"""除权票整段重拉（runbook §4.3 自动化版）：腾讯全量 unadj+qfq 分页回拉到旧文件起点，
校验 unadj 与旧文件逐日一致（除权不改未复权）+ 尾部 unadj==TDX，然后整段替换 qfq。
备份到 data/r2/exdiv_backup/<code>.json.gz；审计写 data/r2/exdiv_backup/audit_<day>.json。"""
from __future__ import annotations
import argparse,gzip,json,os,struct,sys,time
from pathlib import Path
import requests
ROOT=Path(__file__).resolve().parents[2]
DAILY=ROOT/'data/cd/daily_fullmarket'; BK=ROOT/'data/r2/exdiv_backup'
TDX=Path('/root/tdx_data/vipdoc'); UA={'User-Agent':'Mozilla/5.0'}
URLS=['https://web.ifzq.gtimg.cn/appstock/app/fqkline/get','https://ifzq.gtimg.cn/appstock/app/fqkline/get','https://proxy.finance.qq.com/ifzqgtimg/appstock/app/fqkline/get']
def tx_full(c): return ('sh'+c) if c.startswith(('6','9')) else (('bj'+c) if c.startswith(('4','8')) else 'sz'+c)
def tdx_closes(c):
 mkt='sh' if c[0] in '69' else ('bj' if c[0] in '48' else 'sz')
 p=TDX/mkt/'lday'/f'{mkt}{c}.day'; m={}
 if p.exists():
  b=p.read_bytes()
  for i in range(len(b)//32):
   d,o,h,l,cl,amt,vol,_r=struct.unpack('<IIIIIfIf',b[i*32:(i+1)*32]); m[str(d)]=cl/100
 return m
def win(sess,full,start,end):
 out={}
 for fq in ('','qfq'):
  field='qfqday' if fq else 'day'; r=None
  r=None
  for attempt in range(8):
   try:
    j=sess.get(URLS[attempt%3],params={'param':f'{full},day,{start},{end},640,{fq}'},timeout=12,headers=UA).json()
    if j.get('code')!=0 or not isinstance(j.get('data'),dict): raise RuntimeError(j.get('msg'))
    j=j['data'][full]; r=j.get(field) or j.get('day'); break
   except Exception:
    if attempt==7: return None
    time.sleep(4)
  out[fq]= {row[0]:row for row in (r or [])}
  time.sleep(0.35)
 return out if out[''] and out['qfq'] else out
def refetch(code,day):
 p=DAILY/f'{code}.json.gz'
 old=json.loads(gzip.decompress(p.read_bytes()))
 first,last=old['dates'][0],old['dates'][-1]
 sess=requests.Session()
 raw={};qfq={}
 end=(time.strftime('%Y-%m-%d',time.localtime(time.time()+86400)))
 for _ in range(40):
  w=win(sess,tx_full(code),first,end)
  if w is None: return {'code':code,'status':'fetch_fail'}
  nr=w['']; nq=w['qfq']
  newk=[k for k in nr if k not in raw]
  for k in newk: raw[k]=nr[k]
  for k in nq:
   if k not in qfq: qfq[k]=nq[k]
  if not newk: break
  end=min(newk)
  if end<=first: break
 common=sorted(set(raw)&set(qfq)&set(old['dates']))
 # check1: unadj identical on overlap (除权不改未复权)
 bad=[k for k in common if raw[k][:6]!= [r for r in old['unadj'] if r[0]==k][0][:6]]
 if bad: return {'code':code,'status':'unadj_mismatch','n':len(bad),'sample':bad[:3]}
 # check2: 尾部250 unadj vs TDX
 tc=tdx_closes(code); tail=common[-250:]; mm=[]
 for k in tail:
  t=tc.get(k.replace('-',''))
  if t is None or abs(t-float(raw[k][2]))>0.011: mm.append(k)
 if mm: return {'code':code,'status':'tdx_mismatch','n':len(mm),'sample':mm[:3]}
 alld=sorted(set(raw)&set(qfq))
 if alld[-1]<last: return {'code':code,'status':'stale', 'last':alld[-1]}
 newf={'dates':alld,
  'unadj':[raw[k][:6] for k in alld],
  'qfq':[qfq[k][:6] for k in alld],
  'adjust_factor_model_derived':[round(float(qfq[k][2])/float(raw[k][2]),6) if float(raw[k][2]) else 1.0 for k in alld],
  'fetched_at':time.strftime('%Y-%m-%dT%H:%M:%SZ')}
 if len(alld)<len(old['dates'])-5: return {'code':code,'status':'short_history','old':len(old['dates']),'new':len(alld)}
 BK.mkdir(parents=True,exist_ok=True)
 (BK/f'{code}.json.gz').write_bytes(gzip.compress(json.dumps(old,ensure_ascii=False).encode()))
 tmp=p.with_suffix('.tmp.gz'); tmp.write_bytes(gzip.compress(json.dumps(newf,ensure_ascii=False).encode())); os.replace(tmp,p)
 return {'code':code,'status':'ok','bars_old':len(old['dates']),'bars_new':len(alld),'last':alld[-1],
  'qfq_shift_rows':sum(1 for k in common if qfq[k][:6]!=[r for r in old['qfq'] if r[0]==k][0][:6])}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--codes',default=''); ap.add_argument('--day',required=True)
 a=ap.parse_args()
 codes=a.codes.split(',') if a.codes else []
 if not codes:
  import glob
  for p in sorted(glob.glob(str(ROOT/'data/r2/daily_update/update_*.json'))):
   d=json.load(open(p))
   for e in (d.get('tdx_mismatch') or []):
    if e[1]=='overlap_qfq_mismatch' and e[0] not in codes: codes.append(e[0])
 BK.mkdir(parents=True,exist_ok=True)
 out=[refetch(c,a.day) for c in codes]
 (BK/f'audit_{a.day}.json').write_text(json.dumps(out,ensure_ascii=False,indent=1))
 print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()
