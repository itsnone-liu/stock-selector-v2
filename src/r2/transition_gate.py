#!/usr/bin/env python3
"""R2-7 Support->Markup Transition Gate. Spec: docs/r2/R2-7_TRANSITION_SPEC.md"""
from __future__ import annotations
import gzip,json,statistics
from collections import defaultdict
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]; D=ROOT/'data/cd/daily_fullmarket'
sys.path.insert(0,str(Path(__file__).resolve().parent))
from support_gate import load,cost_band
_reg={}; _eq={}
for _r in json.load(gzip.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']:
 _d=_r['date'].replace('-',''); _reg[_d]=_r['regime']; _eq[_d]=_r['eq_ret']
def rclass(d):
 g=_reg.get(d,'')
 return 'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','R_RISK_OFF')) else 'OTHER')
def main():
 # market axes
 l1=json.load(gzip.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']
 mdates=[r['date'].replace('-','') for r in l1]; mpart={r['date'].replace('-',''):r.get('part') for r in l1}
 def mkt_part_impr(d):
  if d not in mpart: return False
  i=mdates.index(d); pre=[mpart[x] for x in mdates[max(0,i-20):i] if mpart.get(x) is not None]
  return bool(pre) and mpart[d] is not None and mpart[d]>statistics.mean(pre)
 # sector axes: per l2 daily series
 l2rows=json.load(gzip.open(ROOT/'data/cd/sector_axes/l2_four_axes.json.gz','rt'))['rows']
 seq=defaultdict(list)
 for r in l2rows:
  if 'sector_eq' in r and 'mkt_eq' in r: seq[r['l2']].append((r['date'].replace('-',''),r['sector_eq'],r['mkt_eq']))
 for k in seq: seq[k].sort()
 sidx={k:{d:i for i,(d,_,_) in enumerate(v)} for k,v in seq.items()}
 def lead20(l2,d):
  v=seq.get(l2); i=sidx.get(l2,{}).get(d)
  if v is None or i is None or i<20: return None
  cs=cm=1
  for _,se,me in v[i-19:i+1]:
   cs*=1+(se or 0); cm*=1+(me or 0)
  return cs>cm
 L2m={m['code']:m['L2'] for m in json.loads((ROOT/'data/cd/sector_seeds/csrc_v1.json').read_text())['members']}
 out=[]; done=0
 for p in sorted(D.glob('*.json.gz')):
  c=p.name[:-8]; s=load(c)
  if not s: continue
  ds,cl,hi,lo,vol=s; n=len(cl)
  if n<560: continue
  l2=L2m.get(c); 
  mends=[k for k in range(1,n) if ds[k][:7]!=ds[k-1][:7]]
  for i in [k for k in mends if 520<=k<=n-61]:
   d=ds[i].replace('-','')
   z=cost_band(cl,hi,lo,vol,i-1)
   if not z: continue
   zl,zh=z
   broken_pre=any(all(cl[t]<zl*0.95 for t in range(b,min(b+5,i))) for b in range(max(0,i-60),i-4))
   if broken_pre: continue  # cohort: valid support only
   ret20=cl[i]/cl[i-20]-1
   # outcomes
   fh=max(hi[i:min(i+60,n)]); conv=fh/cl[i]-1>=0.30
   brk=any(all(cl[t]<zl*0.95 for t in range(b,min(b+5,n))) for b in range(i,min(i+56,n)))
   mimp=mkt_part_impr(d)
   led=lead20(l2,d) if l2 else None
   s20=cl[i]/cl[i-20]-1
   l2r=None
   if l2 and led is not None:
    v=seq[l2]; j=sidx[l2].get(d)
    if j is not None and j>=20:
     cs=1
     for _,se,_ in v[j-19:j+1]: cs*=1+(se or 0)
     l2r=cs-1
   rs=(s20>l2r) if l2r is not None else None
   act=(cl[i]>=max(cl[i-9:i+1])) and (-0.10<=ret20<=0.05)
   tiers={'T0':True,'T1':mimp,'T2':(mimp and led),'T3':(mimp and led and rs),'T4':(mimp and led and rs and act)}
   row={'ym':ds[i][:7],'era':'21-23' if ds[i][:4]<='2023' else '24-26','reg':rclass(d),
        'led':led,'conv':int(conv),'brk':int(brk)}
   for t,f in tiers.items(): row[t]=bool(f)
   out.append(row)
  done+=1
  if done%1500==0: print('stocks',done,'events',len(out),flush=True)
 print('events',len(out),flush=True)
 json.dump(out,open(ROOT/'data/r2/transition_gate_events.json','w'))
 # funnel report
 def rep(rows):
  r={'n':len(rows)}
  for t in ('T0','T1','T2','T3','T4'):
   x=[q for q in rows if q[t]]
   r[t]={'n':len(x),'conv':round(sum(q['conv'] for q in x)/max(1,len(x)),4),'brk':round(sum(q['brk'] for q in x)/max(1,len(x)),4)} if x else None
  return r
 report={'ALL':rep(out)}
 for g in ('BULL','BEAR'): report[g]=rep([q for q in out if q['reg']==g])
 for e in ('21-23','24-26'): report[e]=rep([q for q in out if q['era']==e])
 report['SECTOR_LEADING']=rep([q for q in out if q['led']]); report['SECTOR_LAGGING']=rep([q for q in out if q['led'] is False])
 json.dump(report,open(ROOT/'data/r2/transition_gate_result.json','w'),ensure_ascii=False,indent=1)
 for k,v in report.items():
  print(k,{t:(f"{x['n']} conv {x['conv']} brk {x['brk']}" if x else 'None') for t,x in v.items() if t!='n'} if v else 'None')
if __name__=='__main__':main()
