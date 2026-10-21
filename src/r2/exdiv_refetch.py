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
# ---------------- TDX 通道（2026-10-21 起默认） ----------------
_tdx_sess=None
def _tdx():
 global _tdx_sess
 if _tdx_sess is None:
  from r2.tdx_client import Session,DEFAULT_HOSTS
  errs=[]
  for ep in DEFAULT_HOSTS:
   h,_,pt=ep.partition(':'); pt=int(pt or 7709)
   try: _tdx_sess=Session(h,pt); break
   except (OSError,ConnectionError,ValueError) as e: errs.append(f'{ep}:{type(e).__name__}')
  if _tdx_sess is None: raise ConnectionError('tdx no host: '+', '.join(errs))
 return _tdx_sess
def _tdx_reset():
 global _tdx_sess
 try:
  if _tdx_sess: _tdx_sess.close()
 except Exception: pass
 _tdx_sess=None
def _rm(a,b):
 """接缝比对：价（open/close/high/low）严格同构，volume 容 ±1 手（末位进位口径差）。"""
 if a[:5]!=b[:5]: return False
 try: return abs(float(a[5])-float(b[5]))<=1.0
 except Exception: return True
def refetch_tdx(code,day):
 """TDX 整段重拉（默认源）。口径与 daily_price_update.py 一致：
 ①unadj 重叠段逐日校验（除权不改未复权）；②尾部 vs 本机镜像防源分叉；
 ③复权按 cat1-affine-c2 重建；④个别事件无法精确复权时退化用现价（老刘口径 2026-10-21）。"""
 p=DAILY/f'{code}.json.gz'
 old=json.loads(gzip.decompress(p.read_bytes()))
 first,last=old['dates'][0],old['dates'][-1]
 mkt=1 if code[0] in '69' else 0
 count=min(12000,len(old['dates'])+60)
 deg=''
 for attempt in (0,1):
  try:
   s=_tdx(); raw=s.daily(mkt,code,count=count)
   try: q=s.qfq_daily(mkt,code,count,day)
   except ValueError as e:
    if 'unverified special category' in str(e): q=None; deg='rawfallback'
    else: raise
   break
  except (OSError,ConnectionError):
   _tdx_reset()
   if attempt==1: return {'code':code,'status':'fetch_fail'}
  except Exception as e:
   return {'code':code,'status':'tdx_err:'+type(e).__name__+':'+str(e)[:80]}
 rb={b['date']:b for b in raw if b['date']<=day}
 if not rb: return {'code':code,'status':'fetch_fail'}
 # 单位自校准：以存量末行 volume 为基准（主板/创业板=手，688 科创板=股）
 sv=0.0
 try: sv=float(old['unadj'][-1][5])
 except Exception: pass
 vh=rb.get(last,rb[sorted(rb)[-1]])['volume_hand']; vol_div=100
 if vh>0:
  if abs(round(vh/100)-sv)<=1: vol_div=100
  elif abs(round(vh)-sv)<=1: vol_div=1
  else: vol_div=100; deg=(deg+'+volguess') if deg else 'volguess'
 def mk(b): return [b['date'],f"{b['open']:.3f}",f"{b['close']:.3f}",f"{b['high']:.3f}",f"{b['low']:.3f}",f"{round(b['volume_hand']/vol_div):.3f}"]
 rawr={d:mk(b) for d,b in rb.items()}
 qfqr=rawr if q is None else {r['date']:mk(r) for r in q['rows'] if r['date']<=day}
 alld=sorted(k for k in (set(rawr)&set(qfqr)) if k>=first)  # 起点下界=原文件首日，不向前扩张历史
 if not alld: return {'code':code,'status':'fetch_fail'}
 oldmap={r[0]:r for r in old['unadj']}
 bad=[k for k in alld if k in oldmap and not _rm(rawr[k],oldmap[k])]
 if bad: return {'code':code,'status':'unadj_mismatch','n':len(bad),'sample':[(k,rawr[k][:6],oldmap[k][:6]) for k in bad[:3]]}
 # 尾部 250 vs 本机镜像：源分叉守卫（同源复制，正常应 0 差；少量差仅告警，大面积差才 fail-closed）
 tc=tdx_closes(code); tail=alld[-250:]; mm=[]
 for k in tail:
  t=tc.get(k.replace('-',''))
  if t is None or abs(t-float(rawr[k][2]))>0.011: mm.append(k)
 if len(mm)>len(tail)*0.2: return {'code':code,'status':'mirror_fork','n':len(mm),'sample':mm[:3]}
 if alld[-1]<last: return {'code':code,'status':'stale','last':alld[-1]}
 if len(alld)<len(old['dates'])-5: return {'code':code,'status':'short_history','old':len(old['dates']),'new':len(alld)}
 newf={'dates':alld,
  'unadj':[rawr[k] for k in alld],
  'qfq':[qfqr[k] for k in alld],
  'adjust_factor_model_derived':[round(float(qfqr[k][2])/float(rawr[k][2]),6) if float(rawr[k][2]) else 1.0 for k in alld],
  'fetched_at':time.strftime('%Y-%m-%dT%H:%M:%SZ')}
 BK.mkdir(parents=True,exist_ok=True)
 (BK/f'{code}.json.gz').write_bytes(gzip.compress(json.dumps(old,ensure_ascii=False).encode()))
 tmp=p.with_suffix('.tmp.gz'); tmp.write_bytes(gzip.compress(json.dumps(newf,ensure_ascii=False).encode())); os.replace(tmp,p)
 oldq={r[0]:r for r in old['qfq']}
 return {'code':code,'status':'ok','source':'tdx','degrade':deg,'bars_old':len(old['dates']),'bars_new':len(alld),
  'last':alld[-1],'mirror_diff':len(mm),
  'qfq_shift_rows':sum(1 for k in alld if k in oldq and qfqr[k][1:5]!=oldq[k][1:5])}
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--codes',default=''); ap.add_argument('--day',required=True)
 ap.add_argument('--source',default='tdx',choices=('tdx','tencent'),
                help='行情源：tdx=通达信通道（默认），tencent=旧腾讯 fqkline 应急回退')
 a=ap.parse_args()
 codes=a.codes.split(',') if a.codes else []
 if not codes:
  import glob
  for p in sorted(glob.glob(str(ROOT/'data/r2/daily_update/update_*.json'))):
   d=json.load(open(p))
   for e in (d.get('tdx_mismatch') or []):
    if ('seam' in e[1] or 'rawfallback' in e[1]) and e[0] not in codes: codes.append(e[0])
 BK.mkdir(parents=True,exist_ok=True)
 fn=refetch_tdx if a.source=='tdx' else refetch
 out=[fn(c,a.day) for c in codes]
 (BK/f'audit_{a.day}.json').write_text(json.dumps(out,ensure_ascii=False,indent=1))
 print(json.dumps(out,ensure_ascii=False))
if __name__=='__main__':main()
