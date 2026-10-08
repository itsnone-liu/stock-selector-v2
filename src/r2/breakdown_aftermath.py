#!/usr/bin/env python3
"""R2-7b: post-breakdown continuation + capital-withdrawal covariates.
Q1: after close < band_low*0.95, how much further downside (by tier)?
Q2: do CONTINUED breakdowns show margin retreat / LHB inst selling / holders dispersal?
"""
from __future__ import annotations
import gzip,json,sqlite3,statistics
from collections import defaultdict
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]; D=ROOT/'data/cd/daily_fullmarket'
sys.path.insert(0,str(Path(__file__).resolve().parent))
from support_gate import load,cost_band
l1=json.load(gzip.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']
reg={r['date'].replace('-',''):r['regime'] for r in l1}
def rclass(d):
 g=reg.get(d,'')
 return 'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','R_RISK_OFF')) else 'OTHER')
E5=sqlite3.connect(str(ROOT/'data/r2/e5/e5.db'))
def mchg(code,d1,d0):
 a=E5.execute('SELECT rzye FROM margin WHERE code=? AND date<=? AND rzye IS NOT NULL ORDER BY date DESC LIMIT 1',(code,d1)).fetchone()
 b=E5.execute('SELECT rzye FROM margin WHERE code=? AND date<=? AND rzye IS NOT NULL ORDER BY date DESC LIMIT 1',(code,d0)).fetchone()
 return (a[0]/b[0]-1) if a and b and b[0] else None
def lhb(code,d1,d0):
 v=E5.execute('SELECT SUM(inst_net) FROM lhb WHERE code=? AND date BETWEEN ? AND ?',(code,d0,d1)).fetchone()[0]
 return v
def main():
 rows=[]
 for p in sorted(D.glob('*.json.gz')):
  c=p.name[:-8]; s=load(c)
  if not s: continue
  ds,cl,hi,lo,vol=s; n=len(cl)
  if n<560: continue
  mends=[k for k in range(1,n) if ds[k][:7]!=ds[k-1][:7]]
  for i in [k for k in mends if 520<=k<=n-121]:
   z=cost_band(cl,hi,lo,vol,i-1)
   if not z: continue
   zl,zh=z
   if any(all(cl[t]<zl*0.95 for t in range(b,min(b+5,i))) for b in range(max(0,i-60),i-4)): continue
   # first breakdown bar within +60
   b=None
   for t in range(i,min(i+60,n)):
    if t+4<n and all(cl[x]<zl*0.95 for x in range(t,t+5)): b=t; break
   if b is None: continue
   d0=ds[b].replace('-',''); dpre=ds[max(0,b-20)].replace('-','')
   trough=min(lo[b:min(b+60,n)]); bd=cl[b]
   further=trough/bd-1
   rec10=1 if any(cl[x]>zl*0.95 for x in range(b,min(b+10,n))) else 0
   r20=cl[min(b+20,n-1)]/bd-1; r60=cl[min(b+59,n-1)]/bd-1
   rows.append({'code':c,'ym':ds[b][:7],'reg':rclass(d0),'further':round(further,4),
    'rec10':rec10,'r20':round(r20,4),'r60':round(r60,4),
    'mchg_pre':mchg(c,d0,ds[max(0,b-20)].replace('-','')) if b>=20 else None,
    'mchg_post':mchg(c,ds[min(b+20,n-1)].replace('-',''),d0),
    'lhb_net':(lhb(c,ds[min(b+10,n-1)].replace('-',''),ds[max(0,b-10)].replace('-','')) or 0)/1e8})
 print('breakdowns',len(rows),flush=True)
 json.dump(rows,open(ROOT/'data/r2/breakdown_aftermath.json','w'))
 def grp(name,rs):
  if not rs: print(name,'n=0'); return
  f=[r['further'] for r in rs]; med=statistics.median
  cont=[r for r in rs if r['further']<=-0.10]; stab=[r for r in rs if r['further']>=-0.03]
  print(f"{name}: n={len(rs)} further_med={med(f):+.3f} p25={sorted(f)[len(f)//4]:+.3f} p10={sorted(f)[len(f)//10]:+.3f} rec10={sum(r['rec10'] for r in rs)/len(rs):.3f} r20_med={med([r['r20'] for r in rs]):+.3f} r60_med={med([r['r60'] for r in rs]):+.3f}")
  def cap(g,lab):
   if len(g)<50: return
   mp=[r['mchg_pre'] for r in g if r['mchg_pre'] is not None]; mq=[r['mchg_post'] for r in g if r['mchg_post'] is not None]
   ln=[r['lhb_net'] for r in g]
   print(f"   {lab}: n={len(g)} mchg_pre_med={med(mp):+.3f} mchg_post_med={med(mq):+.3f} lhb_net_med={med(ln):+.2f}亿")
  cap(cont,'CONTINUED(再跌≥10%)'); cap(stab,'STABILIZED(再跌≤3%)')
 for g in ('ALL','BULL','BEAR'):
  grp(g,[r for r in rows if g=='ALL' or r['reg']==g])
 grp('21-23',[r for r in rows if r['ym'][:4]<='2023']); grp('24-26',[r for r in rows if r['ym'][:4]>='2024'])
if __name__=='__main__':main()
