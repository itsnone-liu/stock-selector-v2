#!/usr/bin/env python3
"""R2-6 H-support gate. Frozen spec: docs/r2/R2-6_SUPPORT_PERSISTENCE_SPEC.md"""
from __future__ import annotations
import gzip,json,random,statistics
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
D=ROOT/'data/cd/daily_fullmarket'
def load(c):
 p=D/f'{c}.json.gz'
 if not p.exists(): return None
 r=json.load(gzip.open(p,'rt')); q=r['qfq']; u=r['unadj']
 return r['dates'],[float(x[2]) for x in q],[float(x[3]) for x in q],[float(x[4]) for x in q],[float(x[5]) for x in u]
def cost_band(cl,hi,lo,vol,j):
 a=max(0,j-499); tp=[(hi[k]+lo[k]+cl[k])/3 for k in range(a,j+1)]; vs=vol[a:j+1]
 mn,mx=min(tp),max(tp)
 if mx<=mn: return None
 nb=100; w=(mx-mn)/nb; bins=[0.0]*nb
 for t,v in zip(tp,vs): bins[min(nb-1,int((t-mn)/w))]+=v
 tot=sum(bins); need=tot*0.30; best=None
 for s in range(nb):
  acc=0
  for e in range(s,nb):
   acc+=bins[e]
   if acc>=need:
    span=(e-s+1)
    if best is None or span<best[0]: best=(span,mn+s*w,mn+(e+1)*w)
    break
 if not best: return None
 return best[1],best[2]
def evaluate(zl,zh,cl,hi,lo,i,n):
 zmid=(zl+zh)/2; w=range(i,min(i+60,n))
 lows=[lo[k] for k in w][:20]
 pen=(zl-min(lows))/zmid if zl>min(lows) else 0.0
 rec={h:1 if any(cl[k]>zh for k in range(i,min(i+h,n))) else 0 for h in (5,10,20)}
 tb=sum(1 for k in w if cl[k]<zl)/max(1,len(list(w)))
 brk=any(all(cl[k]<zl*0.95 for k in range(b,min(b+5,n))) for b in range(i,min(i+56,n)))
 r60=cl[min(i+59,n-1)]/zmid-1
 return pen,rec,tb,int(brk),r60
def main():
 reg={}; mkt=[]; eq={}
 for r in json.load(gzip.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']:
  d=r['date'].replace('-',''); reg[d]=r['regime']; eq[d]=r['eq_ret']; mkt.append(d)
 mkt.sort(); midx={d:k for k,d in enumerate(mkt)}
 def rclass(d):
  g=reg.get(d.replace('-',''),'')
  return 'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','R_RISK_OFF')) else 'OTHER')
 def mktdd(i0,w=60):
  if i0 is None or i0>=len(eq): return None
  seq=[eq[mkt[k]] for k in range(i0,min(i0+w,len(mkt))) if mkt[k] in eq]
  c=1; peak=1; dd=0
  for x in seq:
   c*=(1+x); peak=max(peak,c); dd=min(dd,c/peak-1)
  return dd
 random.seed(42)
 res=defaultdict(list); touch_count=defaultdict(int)
 files=sorted(D.glob('*.json.gz')); done=0
 for p in files:
  c=p.name[:-8]; s=load(c)
  if not s: continue
  ds,cl,hi,lo,vol=s; n=len(cl)
  if n<600: continue
  arms={}
  mends=[k for k in range(1,n) if ds[k][:7]!=ds[k-1][:7]]
  for i in [k for k in mends if 520<=k<=n-61]:
   d=ds[i]; ym=d[:7]
   za=cost_band(cl,hi,lo,vol,i-1)
   ma=statistics.mean(cl[max(0,i-250):i])
   zb=(ma*0.98,ma*1.02)
   pl=min(lo[max(0,i-250):i]); zc=(pl*0.98,pl*1.02)
   mn500=min(lo[max(0,i-500):i]); mx500=max(hi[max(0,i-500):i])
   zr=None
   for _ in range(20):
    q=random.uniform(0.15,0.85); mid=mn500+(mx500-mn500)*q; cand=(mid*0.99,mid*1.01)
    if za and not (cand[1]>za[0] and cand[0]<za[1]): zr=cand; break
   if not zr: zr=(zb[0]*0.5+mx500*0.5,zb[1]*0.5+mx500*0.5)
   arms={'A':za,'B':zb,'C':zc,'D':zr}
   for k,(nm,z) in enumerate(arms.items()):
    zl,zh=z
    if zh<=zl or zh<=0: continue
    prev_above=all(cl[t]>zh for t in range(max(0,i-20),i))
    touch = lo[i]<=zh and prev_above
    if not (za and touch and nm=='A') and not (touch and nm!='A'): continue
    pen,rec,tb,brk,r60=evaluate(zl,zh,cl,hi,lo,i,n)
    tc=touch_count[(c,nm,ym[:4])]+1; touch_count[(c,nm,ym[:4])]=tc
    mi=midx.get(ds[i].replace('-','')); md=mktdd(mi)
    stk_dd=None
    if mi is not None:
     seq=[cl[k] for k in range(i,min(i+60,n))]; peak=max(seq[:1]); dd=0
     for x in seq:
      peak=max(peak,x); dd=min(dd,x/peak-1)
     stk_dd=dd
    resi={'ym':ym,'ord':min(tc,3),'era':'21-23' if ym[:4]<='2023' else '24-26','reg':rclass(ds[i]),
          'pen':pen,'r5':rec[5],'r10':rec[10],'r20':rec[20],'tb':tb,'brk':brk,'r60':r60,
          'resil':(stk_dd-md) if (stk_dd is not None and md is not None and md<0) else None}
    touch_count[(c,nm,ym[:4])]+=1
    res[nm].append(resi)
  done+=1
  if done%800==0: print('stocks',done,'A',len(res['A']),flush=True)
 def agg(rows,key=lambda r:r):
  out={'n':len(rows)}
  for f in ('pen','tb','r60','resil'):
   v=[r[f] for r in rows if r[f] is not None]
   out[f]=round(statistics.mean(v),4) if len(v)>=50 else None
  out['brk_ord']={o:round(sum(r['brk'] for r in rows if r['ord']==o)/max(1,sum(1 for r in rows if r['ord']==o)),4) for o in (1,2,3)}
  for f in ('r5','r10','r20','brk'):
   v=[r[f] for r in rows]
   out[f]=round(sum(v)/len(v),4) if len(v)>=50 else None
  return out
 rep={}
 for nm in 'ABCD':
  rep[nm]={'ALL':agg(res[nm])}
  for g in ('BULL','BEAR'): rep[nm][g]=agg([r for r in res[nm] if r['reg']==g])
  for e in ('21-23','24-26'): rep[nm][e]=agg([r for r in res[nm] if r['era']==e])
 json.dump(rep,open(ROOT/'data/r2/support_gate_result.json','w'),ensure_ascii=False,indent=1)
 for nm in 'ABCD': print(nm,'n',rep[nm]['ALL']['n'],'pen',rep[nm]['ALL']['pen'],'r10',rep[nm]['ALL']['r10'],'tb',rep[nm]['ALL']['tb'],'brk',rep[nm]['ALL']['brk'],'r60',rep[nm]['ALL']['r60'])
if __name__=='__main__':main()
