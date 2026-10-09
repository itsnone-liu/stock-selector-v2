#!/usr/bin/env python3
"""EI-4 frozen spec: VWAP proxy vs Full Cost Band agreement + risk-ranking retention."""
import json,random,statistics
from pathlib import Path
import sys; sys.path.insert(0,str(Path(__file__).parent))
from support_gate import load,cost_band
ROOT=Path(__file__).resolve().parents[2]; D=ROOT/'data/cd/daily_fullmarket'
random.seed(42)
files=sorted(D.glob('*.json.gz')); sample=random.sample(files,800)
pairs=[]; full_brk={}; proxy_st={}
for pth in sample:
 s=load(pth.name[:-8])
 if not s: continue
 ds,cl,hi,lo,vol=s; n=len(cl)
 if n<620: continue
 mends=[k for k in range(1,n) if ds[k][:7]!=ds[k-1][:7]][-24:]
 for t in mends:
  z=cost_band(cl,hi,lo,vol,t)
  if not z: continue
  zl,zh=z; zm=(zl+zh)/2
  if not vol[t-249:t+1] or sum(vol[t-249:t+1])==0: continue
  typ=[(hi[k]+lo[k]+cl[k])/3 for k in range(t-249,t+1)]; vv=vol[t-249:t+1]
  v250=sum(a*b for a,b in zip(typ,vv))/sum(vv)
  typ1=typ[-120:]; vv1=vv[-120:]
  v120=sum(a*b for a,b in zip(typ1,vv1))/sum(vv1)
  pl=min(v120,v250)*0.95; ph=max(v120,v250)*1.05; pm=(v120+v250)/2
  c=cl[t]
  fs='IN' if zl*0.95<=c<=zh else ('UNDERCUT' if c>=zl*0.95 else 'BELOW')
  ps='IN' if pl<=c<=ph else ('UNDERCUT' if c>=pl*0.95 else 'BELOW')
  bw=all(cl[x]<zl*0.95 for x in range(t-4,t+1)) if t>=4 else False
  pw=all(cl[x]<pl*0.95 for x in range(t-4,t+1)) if t>=4 else False
  f60=any(all(cl[y]<zl*0.95 for y in range(x,min(x+5,n))) for x in range(t+1,min(t+61,n-4)))
  pairs.append({'fs':fs,'ps':ps,'bw':bw,'pw':pw,'f60':f60,
   'dtc_f':c/zm-1,'dtc_p':c/pm-1})
n=len(pairs)
agree=sum(1 for x in pairs if x['fs']==x['ps'])/n
warn_agree=sum(1 for x in pairs if x['bw']==x['pw'])/n
import math
xs=[x['dtc_f'] for x in pairs]; ys=[x['dtc_p'] for x in pairs]
mx=sum(xs)/n; my=sum(ys)/n
corr=sum((a-mx)*(b-my) for a,b in zip(xs,ys))/math.sqrt(sum((a-mx)**2 for a in xs)*sum((b-my)**2 for b in ys))
def grp(st):
 g={}
 for s2 in ('IN','UNDERCUT','BELOW'):
  q=[x for x in pairs if x['ps']==s2]
  g[s2]={'n':len(q),'f60':round(100*sum(1 for x in q if x['f60'])/len(q),1) if q else None}
 return g
print(json.dumps({'n':n,'state_agree':round(agree,3),'breakwarn_agree':round(warn_agree,3),
 'dtc_corr':round(corr,3),'proxy_state_vs_real60d_broken':grp(None)},ensure_ascii=False))
json.dump({'n':n,'agree':agree,'corr':corr},open(ROOT/'data/r2/ei4_result.json','w'))
