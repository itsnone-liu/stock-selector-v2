#!/usr/bin/env python3
"""R2-8B final activation round (frozen spec docs/r2/R2-8B_EARLY_TRANSITION_SPEC.md)."""
from __future__ import annotations
import gzip,json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; D=ROOT/'data/cd/daily_fullmarket'
from support_gate import load,cost_band
l1=json.load(gzip.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']
reg={r['date'].replace('-',''):r['regime'] for r in l1}
l2m={m['code']:m['L2'] for m in json.loads((ROOT/'data/cd/sector_seeds/csrc_v1.json').read_text())['members']}
l2rows=json.load(gzip.open(ROOT/'data/cd/sector_axes/l2_four_axes.json.gz','rt'))['rows']
seq={}
for r in l2rows:
 if 'sector_eq' in r and r.get('mkt_eq') is not None:
  seq.setdefault(r['l2'],{})[r['date'].replace('-','')]=(r['sector_eq'],r['mkt_eq'])
def rclass(d):
 g=reg.get(d,'')
 return 'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','R_RISK_OFF')) else 'OTHER')
def main():
 out=[]
 for p in sorted(D.glob('*.json.gz')):
  c=p.name[:-8]; s=load(c)
  if not s: continue
  ds,cl,hi,lo,vol=s; n=len(cl)
  if n<560: continue
  l2=l2m.get(c); sq=seq.get(l2) if l2 else None
  if not sq: continue
  mends=[k for k in range(1,n) if ds[k][:7]!=ds[k-1][:7]]
  for i in [k for k in mends if 540<=k<=n-61]:
   d0=ds[i].replace('-','')
   z=cost_band(cl,hi,lo,vol,i-1)
   if not z: continue
   zl,zh=z; zm=(zl+zh)/2
   if any(all(cl[t]<zl*0.95 for t in range(b,min(b+5,i))) for b in range(max(0,i-60),i-4)): continue
   accs=1.0; accm=1.0; ok=True
   for k in range(i-20,i):
    t=sq.get(ds[k].replace('-',''))
    if t is None: ok=False; break
    accs*=1+(t[0] or 0); accm*=1+(t[1] or 0)
   if not ok: continue
   s20=cl[i]/cl[i-20]-1
   if not (accs-1>accm-1 and s20>accs-1): continue   # nested T2 ∧ T3
   # M1: reclaimed midpoint
   M1=(min(cl[max(0,i-14):i+1])<zm) and all(x>=zm for x in cl[i-2:i+1])
   # M2: downside pressure exhaustion
   def dpe(a,b):
    lr=sum(max(0,cl[j-1]-cl[j]) for j in range(a,b+1))
    lv=sum(vol[j] for j in range(a,b+1) if cl[j]<cl[j-1])
    return lr/(lv+1e-9)
   M2=dpe(i-9,i)<dpe(i-19,i-10)
   # M3: rebound efficiency > decline efficiency
   hw=range(max(0,i-19),i+1)
   hd=max(hw,key=lambda j:cl[j]); lo_=min(range(hd,i+1),key=lambda j:cl[j])
   def eff(a,b):
    if b<=a: return 0.0
    return abs(cl[b]-cl[a])/(sum(abs(cl[j]-cl[j-1]) for j in range(a+1,b+1))+1e-9)
   M3=(i>lo_) and eff(lo_,i)>eff(hd,lo_)
   # M4: volume phase shift
   def dv(a,b):
    return sum(vol[j] for j in range(a,b+1) if cl[j]<cl[j-1])/(sum(vol[a:b+1])+1e-9)
   def uv(a,b):
    u=[vol[j] for j in range(a,b+1) if cl[j]>cl[j-1]]
    return sum(u)/len(u) if u else 0
   M4=dv(i-9,i)<dv(i-19,i-10) and uv(i-9,i)>uv(i-19,i-10)
   conv=0; brk=0
   if max(hi[i:min(i+60,n)])/cl[i]-1>=0.30: conv=1
   for b in range(i,min(i+60,n-4)):
    if all(cl[x]<zl*0.95 for x in range(b,b+5)): brk=1; break
   out.append({'code':c,'ym':ds[i][:7],'reg':rclass(d0),'era':'21-23' if ds[i][:4]<='2023' else '24-26',
    'F':{'M1':M1,'M2':M2,'M3':M3,'M4':M4},'conv':conv,'brk':brk})
 print('nested T2∧T3 events',len(out),flush=True)
 json.dump(out,open(ROOT/'data/r2/transition_micro_events.json','w'))
 def agg(rs): return (round(100*statistics.mean([r['conv'] for r in rs]),1),round(100*statistics.mean([r['brk'] for r in rs]),1),len(rs))
 for g in ('ALL','BULL','BEAR','21-23','24-26'):
  sub=[r for r in out if g=='ALL' or r['reg']==g or r['era']==g]
  b=agg(sub); line=f'{g}: base {b[0]}/{b[1]} (n{b[2]})'
  for f in ('M1','M2','M3','M4'):
   on=[r for r in sub if r['F'][f]]; off=[r for r in sub if not r['F'][f]]
   if len(on)>=100:
    a1=agg(on); a0=agg(off); line+=f' | {f} on {a1[0]}/{a1[1]}(n{a1[2]}) off {a0[0]}/{a0[1]}'
  print(line,flush=True)
if __name__=='__main__':main()
