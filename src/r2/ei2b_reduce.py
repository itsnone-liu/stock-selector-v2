#!/usr/bin/env python3
"""EI-1 Breadth->P3 (frozen spec docs/external_ideas/EI1_BREADTH_SPEC.md). Inherits R2-11 flow."""
from __future__ import annotations
import gzip,json,random,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; D=ROOT/'data/cd/daily_fullmarket'
from support_gate import load,cost_band
l1=json.load(gzip.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']
dates=[r['date'].replace('-','') for r in l1]; regs=[r['regime'] for r in l1]
def maj5(k):
 from collections import Counter
 return Counter(regs[max(0,k-4):k+1]).most_common(1)[0][0]
reg5={dates[k]:maj5(k) for k in range(len(dates))}
def rgrp(g): return 'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','RISK_OFF','R_RISK_OFF')) else 'OTHER')
l2m={m['code']:m['L2'] for m in json.loads((ROOT/'data/cd/sector_seeds/csrc_v1.json').read_text())['members']}
l2rows=json.load(gzip.open(ROOT/'data/cd/sector_axes/l2_four_axes.json.gz','rt'))['rows']
seq={}
for r in l2rows:
 if 'sector_eq' in r and r.get('mkt_eq') is not None: seq.setdefault(r['l2'],{})[r['date'].replace('-','')]=(r['sector_eq'],r['mkt_eq'])
COST=0.0015
def stages(t3,gain,sup):
 base=0.20+(0.20 if t3 else 0)+(0.20 if gain>=0.05 else 0)+(0.20 if gain>=0.10 else 0)+(0.20 if gain>=0.15 else 0)
 if not sup: base*=0.5
 return min(1.0,base)
def main():
 # ---- PASS 1: breadth series (stream all stocks once) ----
 above={d:0 for d in dates}; tot={d:0 for d in dates}; nh={d:0 for d in dates}; nl={d:0 for d in dates}
 pos_sum={d:0.0 for d in dates}; rets={d:[] for d in dates}
 for p in sorted(D.glob('*.json.gz')):
  s=load(p.name[:-8])
  if not s: continue
  ds,cl=s[0],s[1]; n=len(cl)
  if n<300: continue
  for k in range(max(250,n-1450),n):
   d=ds[k].replace('-','')
   if d not in tot: continue
   tot[d]+=1
   ma50=sum(cl[k-49:k+1])/50
   if cl[k]>ma50: above[d]+=1
   w=cl[max(0,k-19):k+1]
   if cl[k]>=max(w): nh[d]+=1
   if cl[k]<=min(w): nl[d]+=1
   r=cl[k]/cl[k-1]-1 if k>0 and cl[k-1]>0 else 0.0
   if r>0: rets[d].append(r)
 print('breadth pass done',flush=True)
 B50={d:above[d]/tot[d] if tot[d] else 0.5 for d in dates}
 NHNL={d:(nh[d]-nl[d])/tot[d] if tot[d] else 0.0 for d in dates}
 for d in dates:
  rs=sorted(rets[d],reverse=True); pos_sum[d]=sum(rs)
 LC={d:(sum(sorted(rets[d],reverse=True)[:20])/pos_sum[d] if pos_sum[d]>0 else 0.0) for d in dates}
 SB={}
 for d in dates:
  pos=0;cnt=0
  for l2 in seq:
   q=seq[l2]
   # 20d cum approx via last 20 entries ending d: too slow -> use point eq sign of (eq_d - eq_{d-20}) unavailable; approximate by eq momentum sign from stored series index
   cnt+=1  # replaced below
  SB[d]=0.5
 # SB from sector_eq deltas: precompute per l2 sorted dates
 allq=sorted({d for l2 in seq for d in seq[l2]})
 for d in dates:
  pos=0;cnt=0
  for l2,sq in seq.items():
   ks=sorted(sq)
   import bisect
   i=bisect.bisect_right(ks,d)-1
   if i<20: continue
   v0=sq[ks[i]][0]; v1=sq[ks[i-20]][0]
   cnt+=1
   if v0>v1: pos+=1
  SB[d]=pos/cnt if cnt else 0.5
 print('breadth vars built',flush=True)
 json.dump({'B50':B50,'NHNL':NHNL,'LC':LC,'SB':SB},open('/tmp/ei1_breadth.json','w'))
 # ---- PASS 2: R2-11 flow (identical) ----
 random.seed(42)
 events=[]
 for p in sorted(D.glob('*.json.gz')):
  c=p.name[:-8]; s=load(c)
  if not s: continue
  ds,cl,hi,lo,vol=s; n=len(cl)
  if n<620: continue
  l2=l2m.get(c); sq=seq.get(l2) if l2 else None
  if not sq: continue
  mends=[k for k in range(1,n) if ds[k][:7]!=ds[k-1][:7]]
  for i in [k for k in mends if 560<=k<=n-125]:
   z=cost_band(cl,hi,lo,vol,i-1)
   if not z: continue
   zl,zh=z
   if not (zl*0.95<=cl[i]<=zh): continue
   accs=1.0;accm=1.0;ok=True
   for k in range(i-20,i):
    v=sq.get(ds[k].replace('-',''))
    if v is None: ok=False;break
    accs*=1+(v[0] or 0); accm*=1+(v[1] or 0)
   if not ok: continue
   s20=cl[i]/cl[i-20]-1
   if not(accs-1>accm-1 and s20>accs-1): continue
   if rgrp(reg5.get(ds[i].replace('-',''),'R_DEPRESSED'))=='BEAR':
    if not (min(lo[i-4:i+1])>min(lo[i-9:i-4])): continue
   events.append({'c':c,'i':i,'ym':ds[i][:7],'l2':l2})
 from collections import defaultdict,Counter
 bym=defaultdict(list); seen=set()
 for e in events:
  k=(e['c'],e['ym'])
  if k in seen: continue
  seen.add(k); bym[e['ym']].append(e)
 flow=[]
 for ym in sorted(bym):
  evs=bym[ym]
  if len(evs)>150: evs=random.sample(evs,150)
  cntL2=Counter(); cntI={}; kept=[]
  for e in evs:
   if len(kept)>=150: break
   ind=e['l2'][:3]
   if cntL2[e['l2']]>=30 or cntI.get(ind,0)>=53: continue
   cntL2[e['l2']]+=1; cntI[ind]=cntI.get(ind,0)+1; kept.append(e)
  flow.extend(kept)
 print('flow',len(flow),flush=True)
 import bisect
 obs2=json.load(open('/tmp/ei2a_obs.json'))
 from collections import defaultdict
 bym2=defaultdict(list)
 for o in obs2: bym2[o['ym']].append(o['O1'])
 Q5THR={ym:(sorted(v)[int(0.8*len(v))] if len(v)>=25 else 1e9) for ym,v in bym2.items()}
 weak={}; arms=['R0','R1','R2']
 res={a:[] for a in arms}
 cache={}
 for e in flow:
  c=e['c']
  if c not in cache: cache[c]=load(c)
  s=cache[c]
  if not s: continue
  ds,cl,hi,lo,vol=s; n=len(cl); i=e['i']
  z=cost_band(cl,hi,lo,vol,i-1)
  if not z: continue
  zl=z[0]; zh0=z[1]; sq=seq.get(e['l2'],{})
  def t3f(t):
   if t<20: return False
   a=cl[t]/cl[t-20]-1; b=1.0; ok=True
   for k in range(t-20,t):
    v=sq.get(ds[k].replace('-',''))
    if v is None: ok=False;break
    b*=1+(v[0] or 0)
   return ok and a>b-1
  mult={'R0':1.0}
  for arm in arms:
   m=1.0; px0=cl[i]; val=1.0; pos=0.0; prev=0.0; turns=0.0; broken=False; exp=[]; peak=1.0
   for t in range(i+1,min(i+121,n)):
    r=cl[t]/cl[t-1]-1
    val*=1+r*pos
    turns+=abs(pos-prev)*0.5; prev=pos
    gain=cl[t]/px0-1; sup=cl[t]>=zl*0.95
    brk=all(cl[x]<zl*0.95 for x in range(t-4,t+1)) and t-4>i-4
    rg=rgrp(reg5.get(ds[t].replace('-',''),'R_DEPRESSED'))
    if brk:
     turns+=pos*0.15; broken=True; break
    st=stages(t3f(t),gain,sup)*({'BULL':1.0,'BEAR':0.5}.get(rg,0.75))*m
    if arm!='R0':
     o1=cl[t]/((zl+zh0)/2)-1
     if o1>=Q5THR.get(ds[t][:7],1e9): st*= (0.75 if arm=='R1' else 0.50)
    pos=st; exp.append(pos); peak=max(peak,val)
   res[arm].append({'ret':val-1.0-turns*COST,'exp':statistics.mean(exp) if exp else 0,'broken':broken,'ym':e['ym'],'peak':peak-1.0,'turns':turns})
 out={}
 base_ret=sorted([x['ret'] for x in res['R0']],reverse=True)
 top5=[r for r in base_ret[:max(1,len(base_ret)//20)]]
 for arm in arms:
  rs=res[arm]; months=sorted({x['ym'] for x in rs}); eq=1.0; peak=1.0; mdd=0.0
  for m in months:
   eq*=1+statistics.mean([x['ret'] for x in rs if x['ym']==m]); peak=max(peak,eq); mdd=min(mdd,eq/peak-1)
  yrs=len(months)/12; rets_=[x['ret'] for x in rs]
  brk=[x['ret'] for x in rs if x['broken']]; srt=sorted(rets_)
  # era split
  def erasub(pre):
   s2=[x for x in rs if (x['ym'][:4]<='2023')==pre]; return s2
  e1,e2=erasub(True),erasub(False)
  def mar_of(rr):
   m2=sorted({x['ym'] for x in rr}); q=1.0;pk=1.0;dd=0.0
   for mm in m2:
    q*=1+statistics.mean([x['ret'] for x in rr if x['ym']==mm]);pk=max(pk,q);dd=min(dd,q/pk-1)
   return dd
  out[arm]={'totret':round(eq-1,3),'cagr':round(eq**(1/yrs)-1,3),'maxDD':round(mdd,3),
   'MAR':round((eq**(1/yrs)-1)/abs(mdd),2),'hit':round(100*sum(1 for r in rets_ if r>0)/len(rets_),1),
   'avg_exp':round(statistics.mean([x['exp'] for x in rs]),2),'cap_eff':round((eq-1)/max(0.01,statistics.mean([x['exp'] for x in rs])),2),
   'tail':round(srt[max(0,int(0.05*len(srt)))],3),'brk_mean':round(statistics.mean(brk),3) if brk else None,
   'era_dd':[round(mar_of(e1),3),round(mar_of(e2),3)],
   'retained':round(sum(x['ret'] for x in rs)/max(0.001,sum(x['peak'] for x in rs if x['peak']>0)),3),
   'turnover':round(statistics.mean([x['turns'] for x in rs]),2)}
  rr=sorted(res[arm],key=lambda x:0,reverse=False)
  print(arm,out[arm],flush=True)
 # winner capture: R0 top5% events -> same-index returns per arm
 n=len(res['R0']); k=max(1,n//20)
 idx=sorted(range(n),key=lambda j:res['R0'][j]['ret'],reverse=True)[:k]
 wc={a:round(statistics.mean([res[a][j]['ret'] for j in idx]),3) for a in arms}
 out['winner_capture_top5pct']=wc; print('winner capture R0-top5% mean ret:',wc,flush=True)
 json.dump(out,open(ROOT/'data/r2/ei2b_result.json','w'))
 # regime overlap descriptors
 import math
 bs=[(B50[d],NHNL[d],SB[d],LC[d],1 if rgrp(reg5.get(d,''))=='BEAR' else 0) for d in dates[-1400:]]
 def corr(xs,ys):
  n=len(xs); mx=sum(xs)/n; my=sum(ys)/n
  cov=sum((a-mx)*(b-my) for a,b in zip(xs,ys))
  vx=sum((a-mx)**2 for a in xs); vy=sum((b-my)**2 for b in ys)
  return round(cov/math.sqrt(vx*vy),2) if vx>0 and vy>0 else 0
 print('corr with BEAR: B50',corr([b[0] for b in bs],[b[4] for b in bs]),'NHNL',corr([b[1] for b in bs],[b[4] for b in bs]),'SB',corr([b[2] for b in bs],[b[4] for b in bs]),'LC',corr([b[3] for b in bs],[b[4] for b in bs]),flush=True)
if __name__=='__main__':main()
