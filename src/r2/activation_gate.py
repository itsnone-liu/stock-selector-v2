#!/usr/bin/env python3
"""R2-8 activation gate (frozen spec docs/r2/R2-8_ACTIVATION_SPEC.md).
T3 cohort x {ER_TURN, RS_TURN, PB_SHRINK, HL_RAISE, VOL_THRUST, COMBO} -> conv/brk vs T3 base.
"""
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
 if 'sector_eq' in r: seq.setdefault(r['l2'],{})[r['date'].replace('-','')]=r['sector_eq']
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
  l2=l2m.get(c); sq=seq.get(l2,{}) if l2 else {}
  mends=[k for k in range(1,n) if ds[k][:7]!=ds[k-1][:7]]
  for i in [k for k in mends if 540<=k<=n-61]:
   d0=ds[i].replace('-','')
   z=cost_band(cl,hi,lo,vol,i-1)
   if not z: continue
   zl=z[0]
   if any(all(cl[t]<zl*0.95 for t in range(b,min(b+5,i))) for b in range(max(0,i-60),i-4)): continue
   # T3 at t0: stock 20d cum > sector 20d cum
   if not l2: continue
   s20=cl[i]/cl[i-20]-1 if i>=20 else None
   q20=None
   if s20 is not None:
    d10=ds[i-20].replace('-',''); acc=1.0; ok=True
    for k in range(i-20,i):
     dd=ds[k].replace('-','')
     v=sq.get(dd)
     if v is None: ok=False; break
     acc*=1+(v or 0)
    if ok: q20=acc-1
   if s20 is None or q20 is None or s20<=q20: continue
   # ---- features (t0=i) ----
   def er(a,b):  # ER10 at bar a using window ending a
    net=abs(cl[a]-cl[a-10]) if a>=10 else None
    if net is None: return None
    path=sum(abs(cl[j]-cl[j-1]) for j in range(a-9,a+1))
    return net/path if path>0 else None
   e0=er(i,i); em=er(i-10,i-10)
   ER=e0 is not None and em is not None and e0>em
   # RS_TURN: rs(t0) - rs(t0-10) > 0, rs=stock20-sector20
   rs0=s20-q20
   rs1=None
   if i>=30:
    s20b=cl[i-10]/cl[i-30]-1
    d10b=ds[i-30].replace('-',''); acc=1.0; ok=True
    for k in range(i-30,i-10):
     v=sq.get(ds[k].replace('-',''))
     if v is None: ok=False; break
     acc*=1+(v or 0)
    if ok: rs1=s20b-(acc-1)
   RS=rs1 is not None and rs0>rs1
   def dd(a,b):
    mn=1e9; pk=-1e9
    for j in range(a,b+1):
     mn=min(mn,cl[j]); pk=max(pk,cl[j])
    return 0.0 if pk<=0 else (pk-mn)/pk
   PB=dd(i-9,i)<dd(i-19,i-10)
   HL=min(lo[i-4:i+1])>min(lo[i-9:i-4])
   def vt(a):
    r=abs(cl[a]/cl[a-5]-1) if a>=5 else None
    vr=(sum(vol[a-4:a+1])/5)/(sum(vol[a-24:a-4])/20+1e-9)
    return r/(vr+1e-9) if r is not None else None
   v0=vt(i); v1=vt(i-5)
   VT=v0 is not None and v1 is not None and v0>v1
   # outcome
   conv=0; brk=0
   hh=max(hi[i:min(i+60,n)])
   if hh/cl[i]-1>=0.30: conv=1
   for b in range(i,min(i+60,n-4)):
    if all(cl[x]<zl*0.95 for x in range(b,b+5)): brk=1; break
   out.append({'code':c,'ym':ds[i][:7],'reg':rclass(d0),'era':'21-23' if ds[i][:4]<='2023' else '24-26',
    'F':{'ER':ER,'RS':RS,'PB':PB,'HL':HL,'VT':VT,'COMBO':RS and ER},'conv':conv,'brk':brk})
 print('T3 events',len(out),flush=True)
 json.dump(out,open(ROOT/'data/r2/activation_gate_events.json','w'))
 def agg(rows): return (round(100*statistics.mean([r['conv'] for r in rows]),1),round(100*statistics.mean([r['brk'] for r in rows]),1),len(rows))
 print('BASE T3:',agg(out))
 for g in ('ALL','BULL','BEAR','21-23','24-26'):
  sub=[r for r in out if g=='ALL' or r['reg']==g or r['era']==g]
  if g not in('ALL',) and not (g in('BULL','BEAR') or g in('21-23','24-26')): continue
  b=agg(sub)
  line=f'{g}: base {b[0]}/{b[1]} (n{b[2]})'
  for f in ('ER','RS','PB','HL','VT','COMBO'):
   on=[r for r in sub if r['F'][f]]; off=[r for r in sub if not r['F'][f]]
   if len(on)>=100:
    a1=agg(on); a0=agg(off)
    line+=f' | {f} on {a1[0]}/{a1[1]}(n{a1[2]}) off {a0[0]}/{a0[1]}'
  print(line,flush=True)
if __name__=='__main__':main()
