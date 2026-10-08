#!/usr/bin/env python3
"""R2-3 FINAL GRANULARITY FALSIFICATION GATE. Frozen spec: docs/r2/R2-3_EPISODE_GATE_SPEC.md"""
from __future__ import annotations
import gzip,json,random,sqlite3,statistics
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
D=ROOT/'data/cd/daily_fullmarket'; E5=sqlite3.connect(str(ROOT/'data/r2/e5/e5.db'))
def load_stock(c):
 p=D/f'{c}.json.gz'
 if not p.exists(): return None
 r=json.load(gzip.open(p,'rt')); q=r['qfq']; u=r['unadj']
 return r['dates'],[float(x[2]) for x in q],[float(x[3]) for x in q],[float(x[4]) for x in q],[float(x[5]) for x in u]
def msl(code,d1,d0):
 a=E5.execute('SELECT rzye FROM margin WHERE code=? AND date<=? AND rzye IS NOT NULL ORDER BY date DESC LIMIT 1',(code,d1)).fetchone()
 b=E5.execute('SELECT rzye FROM margin WHERE code=? AND date<=? AND rzye IS NOT NULL ORDER BY date DESC LIMIT 1',(code,d0)).fetchone()
 return (a[0]/b[0]-1) if a and b and b[0] else None
def feats(c,ds,cl,hi,lo,vol,i):
 n=len(cl)
 if i<270 or i+1>=n: return None
 medv=statistics.median(vol[i-270:i+1]); medw=statistics.median(vol[i-20:i+1])
 ret20=cl[i]/cl[i-20]-1
 relv=sum(vol[i-20:i+1])/(medv*20+1e-9)
 hold=cl[i]/(sum(cl[i-20:i+1])/21)-1
 def width(j):
  a=j-249; vs=sorted(((hi[k]+lo[k]+cl[k])/3,vol[k]) for k in range(a,j+1))
  tot=sum(v for _,v in vs); cum=0; p10=p90=None
  for tv,v in vs:
   cum+=v
   if p10 is None and cum>=tot*0.10: p10=tv
   if p90 is None and cum>=tot*0.90: p90=tv
  return (p90-p10)/(vs[len(vs)//2][0]+1e-9)
 w=width(i-5)/(width(i-20)+1e-9)-1
 def over(j):
  a=j-249; base=cl[j]; s=t=0
  for k in range(a,j+1):
   t+=vol[k]
   if (hi[k]+lo[k]+cl[k])/3>1.05*base: s+=vol[k]
  return s/(t+1e-9)
 o=over(i-20)-over(i-5)
 def recon(j):
  a=j-59; base=cl[j]; s=t=0
  for k in range(a,j+1):
   t+=vol[k]
   if abs((hi[k]+lo[k]+cl[k])/3/base-1)<0.05: s+=vol[k]
  return s/(t+1e-9)
 cr=recon(i)-recon(i-20)
 def eff(half,side):
  vals=[]
  for k in range(i-20,i+1):
   if (i-k>10 and half==0)or(i-k<=10 and half==1):
    ret=cl[k]/cl[k-1]-1
    if (side=='u' and ret>0)or(side=='d' and ret<0):
     vals.append(ret/(vol[k]/(medw+1e-9)))
  return statistics.mean(vals) if vals else 0.0
 se=eff(0,'d')-eff(1,'d'); be=eff(1,'u')-eff(0,'u')
 ms=msl(c,ds[i],ds[i-20])
 return {'T1_margin':ms,'T2_width':w,'T3_over':o,'T4_recon':cr,'T5_sell':se,'T6_buy':be,'T7_relv':relv,'T7_hold':hold,'T8_ret20':ret20}
def main():
 eps=[json.loads(l) for l in open(ROOT/'data/r2/markup_episodes.jsonl')]
 reg={r['date'].replace('-',''):r['regime'] for r in json.load(gzip.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']}
 L2={}
 for m in json.loads((ROOT/'data/cd/sector_seeds/csrc_v1.json').read_text())['members']:
  L2[m['code']]=m['L2']
 def rclass(d):
  g=reg.get(d.replace('-',''),'')
  return 'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','R_RISK_OFF')) else 'OTHER')
 epi=defaultdict(list)
 for e in eps: epi[e['stock']].append(e['i'])
 cases=[]; ctrl_pool=defaultdict(list); done=0
 for c,anchors in epi.items():
  s=load_stock(c)
  if not s: continue
  ds,cl,hi,lo,vol=s
  for i in anchors:
   f=feats(c,ds,cl,hi,lo,vol,i)
   if f: cases.append({'stock':c,'ym':ds[i][:6],'reg':rclass(ds[i]),'f':f})
  banned=set()
  for a in anchors:
   banned.update(range(a-120,a+121))
  l2=L2.get(c,'?')
  for k in range(270,len(cl)-121):
   if k in banned: continue
   if k+1>=len(cl) or k==len(cl)-1: continue
   if ds[k+1][:6]!=ds[k][:6]:  # month-end bar
    if cl[k+120]/cl[k]-1<1.0:
     ctrl_pool[(l2,rclass(ds[k]))].append((c,k,ds[k][:6]))
  done+=1
  if done%500==0: print('stocks',done,'cases',len(cases),flush=True)
 print('cases',len(cases),'pool',sum(len(v) for v in ctrl_pool.values()),flush=True)
 random.seed(42); controls=[]; bycase=defaultdict(list)
 for case in cases:
  l2=L2.get(case['stock'],'?'); want=case['reg']
  pool=ctrl_pool.get((l2,want)) or ctrl_pool.get((l2,'OTHER')) or []
  if not pool: continue
  cy,cm=int(case['ym'][:4]),int(case['ym'][4:])
  cands=[x for x in pool if x[0]!=case['stock'] and abs((int(x[2][:4])-cy)*12+int(x[2][4:])-cm)<=2]
  random.shuffle(cands)
  for x in cands[:3]: bycase[(x[0],x[1])].append(case)
 for (c,k),cs in bycase.items():
  s=load_stock(c)
  if not s: continue
  ds,cl,hi,lo,vol=s
  f=feats(c,ds,cl,hi,lo,vol,k)
  if f: controls.append({'ym':ds[k][:6],'reg':cs[0]['reg'],'f':f})
 print('controls',len(controls),flush=True)
 FKS=['T1_margin','T2_width','T3_over','T4_recon','T5_sell','T6_buy','T7_relv','T7_hold','T8_ret20']
 def summ(rows):
  o={}
  for k in FKS:
   v=[r['f'][k] for r in rows if r['f'][k] is not None]
   if len(v)>=30: o[k]={'n':len(v),'mean':round(statistics.mean(v),5),'sem':round(statistics.pstdev(v)/len(v)**.5,5)}
  return o
 def diff(a,b):
  return {k:{'diff':round(a[k]['mean']-b[k]['mean'],5),
             'z':round((a[k]['mean']-b[k]['mean'])/(a[k]['sem']**2+b[k]['sem']**2)**.5,2)}
           for k in FKS if k in a and k in b}
 rep={'n_cases':len(cases),'n_controls':len(controls),'regimes':{},'eras':{}}
 for g in ('ALL','BULL','BEAR'):
  A=[x for x in cases if g=='ALL' or x['reg']==g]; B=[x for x in controls if g=='ALL' or x['reg']==g]
  sA,sB=summ(A),summ(B); rep['regimes'][g]={'case':sA,'ctrl':sB,'diff':diff(sA,sB)}
 for er,lo_,hi_ in (('21-23','2021','2023'),('24-26','2024','2026')):
  A=[x for x in cases if lo_<=x['ym'][:4]<=hi_]; B=[x for x in controls if lo_<=x['ym'][:4]<=hi_]
  sA,sB=summ(A),summ(B); rep['eras'][er]={'case':sA,'ctrl':sB,'diff':diff(sA,sB)}
 json.dump(rep,open(ROOT/'data/r2/episode_gate_result.json','w'),ensure_ascii=False,indent=1)
 print('written')
if __name__=='__main__':main()
