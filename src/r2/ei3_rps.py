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

 # ---- EI-3 descriptor ----
 from collections import defaultdict
 random.seed(42)
 ev=[]
 for p in sorted(D.glob('*.json.gz')):
  c=p.name[:-8]; s2=load(c)
  if not s2: continue
  ds,cl,hi,lo,vol=s2; n=len(cl)
  if n<620: continue
  l2=l2m.get(c); sq=seq.get(l2) if l2 else None
  if not sq: continue
  mends=[k for k in range(1,n) if ds[k][:7]!=ds[k-1][:7]]
  for i in [k for k in mends if 560<=k<=n-125]:
   z=cost_band(cl,hi,lo,vol,i-1)
   if not z: continue
   zl,zh=z; zm=(zl+zh)/2
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
   r120=cl[i]/cl[i-120]-1 if i>=120 else None
   r250=cl[i]/cl[i-250]-1 if i>=250 else None
   f20=cl[min(i+20,n-1)]/cl[i]-1; f60=cl[min(i+60,n-1)]/cl[i]-1
   brk=None
   for x in range(i+1,min(i+61,n-4)):
    if all(cl[y]<zl*0.95 for y in range(x,x+5)): brk=(cl[x+4]/cl[i]-1); break
   ev.append({'ym':ds[i][:7],'era':'21-23' if ds[i][:4]<='2023' else '24-26',
    'reg':rgrp(reg5.get(ds[i].replace('-',''),'R_DEPRESSED')),
    'RPS_S':s20,'RPS_M':r120,'RPS_L':r250,'RS_SN':s20-(accs-1),
    'f20':f20,'f60':f60,'brk':brk,'dtc':cl[i]/zm-1})
 bym=defaultdict(list)
 for j,e in enumerate(ev): bym[e['ym']].append(j)
 for key in ('RPS_S','RPS_M','RPS_L','RS_SN'):
  for ym,idxs in bym.items():
   pr=[(j,ev[j][key]) for j in idxs if ev[j][key] is not None]
   pr.sort(key=lambda x:x[1])
   for k,(j,v) in enumerate(pr): ev[j]['q_'+key]=k*5//len(pr)
 def tab(key,filt=lambda e:True):
  out=[]
  for q in range(5):
   s3=[e for e in ev if e.get('q_'+key)==q and filt(e)]
   if len(s3)<50: out.append(None); continue
   f20=[x['f20'] for x in s3]; brks=[x for x in s3 if x['brk'] is not None]
   out.append({'n':len(s3),'fwd':round(statistics.mean(f20),4),'conv':round(100*sum(1 for r in f20 if r>0)/len(f20),1),
    'p90':round(sorted(f20)[int(0.9*len(f20))],3),'brk':round(100*len(brks)/len(s3),1),
    'brkl':round(statistics.mean([b['brk'] for b in brks]),3) if brks else None,
    'dtc':round(statistics.mean([x['dtc'] for x in s3]),3),'q5dtc':round(100*sum(1 for x in s3 if x['dtc']>0.05)/len(s3),1)})
  return out
 print('ev',len(ev),flush=True)
 for key in ('RS_SN','RPS_S','RPS_M','RPS_L'):
  print('ALL',key,tab(key),flush=True)
 print('=== SN era ===')
 for era in ('21-23','24-26'):
  s3=[e for e in ev if e.get('q_RS_SN') in(0,4) and e['era']==era]
  lo=[e for e in s3 if e['q_RS_SN']==0]; hh=[e for e in s3 if e['q_RS_SN']==4]
  print(era,'Q1fwd',round(statistics.mean([x['f20'] for x in lo]),4),'Q5fwd',round(statistics.mean([x['f20'] for x in hh]),4),
   'Q1q5dtc',round(100*sum(1 for x in lo if x['dtc']>0.05)/len(lo),1),'Q5q5dtc',round(100*sum(1 for x in hh if x['dtc']>0.05)/len(hh),1),flush=True)
 json.dump({'n':len(ev)},open(ROOT/'data/r2/ei3_result.json','w'))
if __name__=="__main__":main()
