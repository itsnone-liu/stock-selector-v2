#!/usr/bin/env python3
"""R2-10 Position & Portfolio Policy Study (frozen spec 164d71c). P0-P3 same candidate flow/prices/exits; only position policy differs."""
from __future__ import annotations
import gzip,json,random,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; D=ROOT/'data/cd/daily_fullmarket'
from support_gate import load,cost_band
l1=json.load(gzip.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']
dates=[r['date'].replace('-','') for r in l1]; regs=[r['regime'] for r in l1]
def maj5(k):  # 5-day majority regime at index k
 from collections import Counter
 return Counter(regs[max(0,k-4):k+1]).most_common(1)[0][0]
reg5={dates[k]:maj5(k) for k in range(len(dates))}
def rgrp(g): return 'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','RISK_OFF','R_RISK_OFF')) else 'OTHER')
l2m={m['code']:m['L2'] for m in json.loads((ROOT/'data/cd/sector_seeds/csrc_v1.json').read_text())['members']}
l2rows=json.load(gzip.open(ROOT/'data/cd/sector_axes/l2_four_axes.json.gz','rt'))['rows']
seq={}
for r in l2rows:
 if 'sector_eq' in r: seq.setdefault(r['l2'],{})[r['date'].replace('-','')]=r['sector_eq']
COST=0.0015
def stages(arm,t3,gain,support_ok,regm):
 # returns target fraction of unit position (0..1)
 if arm=='P0': base=1.0
 elif arm=='P1': base=0.30+(0.30 if t3 else 0)+((0.40 if (gain>=0.05 and support_ok) else 0))
 elif arm=='P2':
  base=0.20+(0.20 if t3 else 0)+(0.20 if gain>=0.05 else 0)+(0.20 if gain>=0.10 else 0)+(0.20 if gain>=0.15 else 0)
 else:
  base=stages('P2',t3,gain,support_ok,regm); m={'BULL':1.0,'BEAR':0.5}.get(regm,0.75); base*=m
 return min(1.0,base)
def sim(arm,cl,zl,n,i):
 px0=cl[i]; pos=0.0; turns=0.0; expsum=0.0; days=0; path=[]
 for t in range(i+1,min(i+121,n)):
  r=cl[t]/cl[t-1]-1
  gain=cl[t]/px0-1
  t3=None
  pos*= (1+r)
  # support state daily (frozen band)
  sup=cl[t]>=zl*0.95
  broken=all(cl[x]<zl*0.95 for x in range(t-4,t+1)) if t>=4 else False
  regm=rgrp(reg5.get(__import__('re').sub('-','', '')) if False else 'OTHER')
  path.append((t,pos,r))
  if broken:
   turns+=2*(0.15)  # approx exit turnover
   return pos-1.0,sum(e for e,_ in path and []),days,turns,True,t-i
  days+=1
 return pos-1.0,days,turns,False,t-i
def main():
 random.seed(42)
 # ---- collect events (shared flow) ----
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
   if not (zl*0.95<=cl[i]<=zh): continue      # IN_SUPPORT or UNDERCUT_TEST
   # T2 at t0
   accs=1.0;accm=1.0;ok=True
   for k in range(i-20,i):
    v=sq.get(ds[k].replace('-',''))
    if v is None: ok=False;break
    accs*=1+(v or 0);accm*=1+(1.0)  # mkt not in these rows: use flat-market proxy? no -> use l1 eq
   if not ok: continue
   # market cum from l1: l1 rows carry eq? fallback: use mean of sector eq as mkt proxy is wrong; use regime gate instead: T2 proxied by sector20>0 (frozen simplification, disclosed)
   if accs-1<=0: continue
   events.append({'c':c,'i':i,'ym':ds[i][:7],'l2':l2})
  if len(events)>400000: break
 # dedupe per (c,ym) keep first; cap 150/month
 from collections import defaultdict
 bym=defaultdict(list)
 seen=set()
 for e in events:
  k=(e['c'],e['ym'])
  if k in seen: continue
  seen.add(k); bym[e['ym']].append(e)
 flow=[]
 for ym in sorted(bym):
  evs=bym[ym]
  if len(evs)>150: evs=random.sample(evs,150)
  flow.extend(evs)
 print('flow events',len(flow),flush=True)
 # ---- simulate each arm on same events ----
 cache={}
 def get(c):
  if c not in cache:
   s=load(c); cache[c]=s if s else None
  return cache[c]
 res={a:[] for a in ('P0','P1','P2','P3')}
 for e in flow:
  s=get(e['c'])
  if not s: continue
  ds,cl,hi,lo,vol=s; n=len(cl); i=e['i']
  z=cost_band(cl,hi,lo,vol,i-1)
  if not z: continue
  zl=z[0]; sq=seq.get(e['l2'],{})
  t3_at={}; # rolling t3 by day index
  # precompute stock cum and sector cum arrays lazily
  def t3f(t):
   if t<i or t<20: return False
   a=cl[t]/cl[t-20]-1; b=1.0; ok=True
   for k in range(t-20,t):
    v=sq.get(ds[k].replace('-',''))
    if v is None: ok=False;break
    b*=1+(v or 0)
   return ok and a>b-1
  for arm in ('P0','P1','P2','P3'):
   px0=cl[i]; val=1.0; exp_days=[]; turns=1.0; exit_ret=None; broken=False; hold=0
   t3c=None
   for t in range(i+1,min(i+121,n)):
    r=cl[t]/cl[t-1]-1
    val*= (1+r*( val/val if False else 1))*0+val*(1+r)  # value grows with full ret scaled below
    # stage decision at close t (applies next day); approximate: apply to today's ret with stage decided at t-1
    pass
   # --- clean recompute ---
   val=1.0; pos=0.0; prev_stage=0.0; entries=[]
   for t in range(i+1,min(i+121,n)):
    r=cl[t]/cl[t-1]-1
    val*=1+r*pos
    turns+=abs(pos-prev_stage)*0.5  # one-side approx
    prev_stage=pos
    gain=cl[t]/px0-1
    sup=cl[t]>=zl*0.95
    brk=all(cl[x]<zl*0.95 for x in range(t-4,t+1)) and t-4>i-4
    rg=rgrp(reg5.get(ds[t].replace('-',''),'R_DEPRESSED'))
    t3=t3f(t)
    if brk:
     turns+=pos*0.15; broken=True; hold=t-i; break
    st=stages(arm,t3,gain,sup,rg)
    if not sup: st*=0.5
    pos=st
    exp_days.append(pos); hold=t-i
   exit_ret=val-1.0-turns*COST
   res[arm].append({'ret':exit_ret,'exp':statistics.mean(exp_days) if exp_days else 0,'broken':broken,'hold':hold,'ym':e['ym'],'l2':e['l2']})
 # ---- report ----
 print(json.dumps({'n':len(res['P0'])}))
 out={}
 for arm in ('P0','P1','P2','P3'):
  rs=res[arm]; rets=[x['ret'] for x in rs]
  # portfolio equity: compound monthly mean
  months=sorted({x['ym'] for x in rs}); eq=1.0; peak=1.0; mdd=0.0
  for m in months:
   mr=statistics.mean([x['ret'] for x in rs if x['ym']==m]); eq*=1+mr
   peak=max(peak,eq); mdd=min(mdd,eq/peak-1)
  yrs=len(months)/12
  brk=[x['ret'] for x in rs if x['broken']]
  srt=sorted(rets); tail=srt[max(0,int(0.05*len(srt)))]
  out[arm]={'totret':round(eq-1,3),'cagr':round(eq**(1/yrs)-1,3) if yrs>0 else None,'maxDD':round(mdd,3),
   'MAR':round((eq**(1/yrs)-1)/abs(mdd),2) if mdd<0 else None,'hit':round(100*sum(1 for r in rets if r>0)/len(rets),1),
   'avg_exp':round(statistics.mean([x['exp'] for x in rs]),2),'cap_eff':round((eq-1)/max(0.01,statistics.mean([x['exp'] for x in rs])),2),
   'tail5pct':round(tail,3),'broken_n':len(brk),'broken_mean':round(statistics.mean(brk),3) if brk else None}
  print(arm,out[arm],flush=True)
 json.dump(out,open(ROOT/'data/r2/position_policy_result.json','w'))
 # sector concentration descriptor
 from collections import Counter
 cc=Counter(x['l2'] for x in res['P1'])
 print('sector top3:',cc.most_common(3))
if __name__=='__main__':main()
