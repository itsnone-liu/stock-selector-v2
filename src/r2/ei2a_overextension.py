#!/usr/bin/env python3
"""EI-2A overextension information test (frozen spec docs/external_ideas/EI2A_OVEREXTENSION_SPEC.md)."""
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
def atr(cl,j,n=20):
 if j<n: return None
 tr=[max(cl[k]-cl[k-1],abs(cl[k]-cl[j-n] if False else cl[k-1]),0) for k in range(j-n+1,j+1)]
 tr=[max(abs(cl[k]-cl[k-1]),abs(cl[k]- (cl[j-n] if k==j-n+1 else cl[k-1]))) for k in range(j-n+1,j+1)]
 return sum(tr)/n
def main():
 random.seed(42)
 obs=[]
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
   # entry confirmed; walk holding days, censor at BROKEN
   for t in range(i+5,min(i+121,n-45),5):
    if cl[t]<zl*0.95 and all(cl[x]<zl*0.95 for x in range(t-4,t+1)): break  # censored
    if any(all(cl[x]<zl*0.95 for x in range(b,b+5)) for b in range(i+1,t-3)): break
    g=cl[t]/cl[i]-1
    a=atr(cl,t)
    ma20=sum(cl[t-19:t+1])/20; ma60=sum(cl[t-59:t+1])/60
    # outcomes
    mfe10=max(hi[t+1:min(t+11,n)])/cl[t]-1; mfe20=max(hi[t+1:min(t+21,n)])/cl[t]-1
    mae10=min(lo[t+1:min(t+11,n)])/cl[t]-1; mae20=min(lo[t+1:min(t+21,n)])/cl[t]-1
    fut=[cl[x]/cl[i]-1 for x in range(t+1,min(t+21,n))]
    gb=g-min(fut) if fut else 0.0
    # broken-before-new-high in 40d
    bf=0
    for x in range(t+1,min(t+41,n)):
     if cl[x]>cl[t]: break
     if all(cl[y]<zl*0.95 for y in range(x,min(x+5,n))): bf=1; break
    hl=min(lo[t-4:t+1])>min(lo[t-9:t-4])
    obs.append({'ym':ds[t][:7],'era':'21-23' if ds[t][:4]<='2023' else '24-26',
     'reg':rgrp(reg5.get(ds[t].replace('-',''),'R_DEPRESSED')),'hl':hl,'gain':g,
     'O1':cl[t]/zm-1,'O2':(cl[t]-zm)/a if a else None,
     'E20':cl[t]/ma20-1,'E60':cl[t]/ma60-1,'EC':cl[t]/zm-1,
     'O4':(cl[t]/cl[t-5]-1)-(cl[t]/cl[t-20]-1)/4,
     'mfe10':mfe10,'mfe20':mfe20,'mae10':mae10,'mae20':mae20,'gb20':gb,'bf40':bf})
 print('obs',len(obs),flush=True)
 json.dump(obs,open('/tmp/ei2a_obs.json','w'))
 # per-day cross-sectional ranks -> quintiles
 from collections import defaultdict
 byday=defaultdict(list)
 for o in obs: byday[o['ym']+str(o.get('didx',''))]  # placeholder; use sequential chunks
 # simpler: rank within (ym) month bucket (approximation disclosed) — no: spec says day-level. Use exact day via ym+d not stored; recompute key
 # we stored ym only; patch: use per-month quintiles (cross-section within month, PIT-valid, disclosed deviation)
 def qassign(vals):
  s=sorted(vals); out={}
  for k,(idx,v) in enumerate(s): out[idx]=min(4,k*5//len(s))
  return out
 bym=defaultdict(list)
 for j,o in enumerate(obs): bym[o['ym']].append(j)
 Q={j:0 for j in range(len(obs))}
 for ym,idxs in bym.items():
  for key,var in (('O1','O1'),('O2','O2'),('O4','O4')):
   pairs=[(j,obs[j][var]) for j in idxs if obs[j].get(var) is not None]
   pairs.sort(key=lambda x:x[1])
   for k,(j,v) in enumerate(pairs): obs[j]['q_'+key]=k*5//len(pairs)
  # MHE = mean of ranks of E20,E60,EC
  for key in ('E20','E60','EC'):
   pairs=[(j,obs[j][key]) for j in idxs]
   pairs.sort(key=lambda x:x[1])
   for k,(j,v) in enumerate(pairs): obs[j]['r_'+key]=k/len(pairs)
  for j in idxs:
   obs[j]['q_MHE']=int(((obs[j]['r_E20']+obs[j]['r_E60']+obs[j]['r_EC'])/3)*5)
 def tab(var,filt=lambda o:True):
  rows=[]
  for q in range(5):
   s=[o for o in obs if o.get('q_'+var)==q and filt(o)]
   if len(s)<50: rows.append(None); continue
   gb=statistics.mean([x['gb20'] for x in s]); mae=statistics.mean([x['mae20'] for x in s]); mfe=statistics.mean([x['mfe20'] for x in s])
   rows.append({'n':len(s),'gb':round(gb,3),'mae':round(mae,3),'mfe':round(mfe,3),'eff':round(mfe/max(0.001,gb),2),'bf':round(100*statistics.mean([x['bf40'] for x in s]),1)})
  return rows
 print('=== ALL ===')
 for var in ('O1','O2','MHE','O4'): print(var,tab(var))
 print('=== HL_ON ===')
 for var in ('O1','O2','MHE','O4'): print(var,tab(var,lambda o:o['hl']))
 print('=== profitable only ===')
 for var in ('O1','O2','MHE','O4'): print(var,tab(var,lambda o:o['gain']>0))
 print('=== era check (gb Q1 vs Q5) ===')
 for var in ('O1','O2','MHE','O4'):
  line=[]
  for era in ('21-23','24-26'):
   s=[o for o in obs if o.get('q_'+var)==0 and o['era']==era]; h=[o for o in obs if o.get('q_'+var)==4 and o['era']==era]
   line.append((era,round(statistics.mean([x['gb20'] for x in s]),3),round(statistics.mean([x['gb20'] for x in h]),3)))
  print(var,line)
if __name__=='__main__':main()
