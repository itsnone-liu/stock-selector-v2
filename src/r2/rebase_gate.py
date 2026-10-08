#!/usr/bin/env python3
"""R2-9 Structural Rebase (frozen contract 8bb62c3 / docs/r2/R2-9_REBASE_SPEC.md). Single full run."""
from __future__ import annotations
import gzip,json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; D=ROOT/'data/cd/daily_fullmarket'
from support_gate import load,cost_band
H={int(p.stem):{r['code']:r for r in json.load(open(p))['rows']} for p in (ROOT/'data/r2/holders').glob('*.json')}
QEND=sorted(H)
def band_w(cl,hi,lo,vol,j,w=120):
 a=max(0,j-w+1)
 if j-a+1<w: return None
 tp=[(hi[k]+lo[k]+cl[k])/3 for k in range(a,j+1)]; vs=vol[a:j+1]
 mn,mx=min(tp),max(tp)
 if mx<=mn: return None
 nb=100; bw=(mx-mn)/nb; bins=[0.0]*nb
 for t,v in zip(tp,vs): bins[min(nb-1,int((t-mn)/bw))]+=v
 tot=sum(bins); need=tot*0.30; best=None
 for s in range(nb):
  acc=0
  for e in range(s,nb):
   acc+=bins[e]
   if acc>=need:
    span=e-s+1
    if best is None or span<best[0]: best=(span,mn+s*bw,mn+(e+1)*bw)
    break
 return None if not best else (best[1],best[2])
def own_group(code,tB_ds,tF_ds):
 q0=[q for q in QEND if q<=int(tB_ds.replace('-',''))]; 
 if len(q0)<1: return None,None
 q0=q0[-1]; q1=[q for q in QEND if q>q0]
 if not q1: return None,None
 q1=q1[0]
 r0=H[q0].get(code); r1=H[q1].get(code)
 if not r0 or not r1 or not r0.get('holders'): return None,None
 chg=(r1['holders']-r0['holders'])/r0['holders']*100
 g='CONC' if chg<-3 else ('DISP' if chg>3 else 'FLAT')
 avail=int(str(q1)[4:6] in('03','06','09','12') and q1) # q1m end
 pit=True  # availability check vs decision time done below
 return g,{'q0':q0,'q1':q1,'chg':round(chg,1),
   'tradable': (q1//10000*10000 + ((q1%10000)//100)*100) and (int(str(q1)[:4])+ (1 if q1%10000>1000 else 0))>0 and True}
def main():
 out=[]
 for p in sorted(D.glob('*.json.gz')):
  c=p.name[:-8]; s=load(c)
  if not s: continue
  ds,cl,hi,lo,vol=s; n=len(cl)
  if n<620: continue
  last_ev=-999
  for j in range(540,n-5):
   if j-last_ev<60: continue
   z=cost_band(cl,hi,lo,vol,j-1)
   if not z: continue
   zl=z[0]
   if all(cl[t]<zl*0.95 for t in range(j,j+5)):
    tB=j+4; last_ev=tB
    # R9-2 formation
    tF=None
    for k in range(tB+40,min(tB+250,n-65)+1):
     b=band_w(cl,hi,lo,vol,k); b2=band_w(cl,hi,lo,vol,k-20)
     if not b or not b2: continue
     nl,nh=b; w1=(nh-nl)/((nl+nh)/2); w0=(b2[1]-b2[0])/((b2[0]+b2[1])/2)
     if not(w1<w0): continue
     if not(nl<=cl[k]<=nh): continue
     if any(cl[t]<nl*0.95 for t in range(k-19,k+1)): continue
     tF=k; newlo,newhi=nl,nh; break
    ev={'code':c,'tB':ds[tB],'rebase':tF is not None}
    if tF is None:
     out.append({**ev,'verdict':'NO_REBASE'}); continue
    ev['speed']=tF-tB
    # R9-3 first retest vs frozen new band
    tR=None
    for t in range(tF+1,min(tF+120,n)):
     if cl[t]<newlo: tR=t; break
    if tR is None:
     out.append({**ev,'verdict':'BAND_UNRETESTED'}); continue
    ev['tR']=ds[tR]
    pen=min(cl[tR:min(tR+10,n)])/newlo-1
    rec10=cl[tR+10]/cl[tR]-1 if tR+10<n else None
    tb=sum(1 for t in range(tR,min(tR+20,n)) if cl[t]<newlo)
    brk60=any(all(cl[x]<newlo*0.95 for x in range(b,b+5)) for b in range(tR,min(tR+60,n-4)))
    r60=cl[tR+60]/cl[tR]-1 if tR+60<n else None
    surv=(not brk60) and rec10 is not None and rec10>=0
    ev.update({'pen':round(pen,3),'rec10':round(rec10,3) if rec10 is not None else None,'tbelow':tb,'brk60':int(brk60),'r60':round(r60,3) if r60 is not None else None,'surv':surv,'verdict':'SURVIVED' if surv else 'FAILED'})
    # ownership descriptor (explanatory; tradable flag separately)
    g=None
    q0=[q for q in QEND if q<=int(ds[tB].replace('-',''))]
    q1=[q for q in QEND if q>int(ds[tB].replace('-',''))]
    if q0 and q1:
     r0=H[q0[-1]].get(c); r1=H[q1[0]].get(c)
     if r0 and r1 and r0.get('holders'):
      chg=(r1['holders']-r0['holders'])/r0['holders']*100
      g='CONC' if chg<-3 else ('DISP' if chg>3 else 'FLAT')
      q1d=q1[0]; avail_ok=q1d+4500<=int(ds[tF].replace('-',''))  # qend+45d (approx as YYYYMMDD +4500)
      ev['own']=g; ev['own_chg']=round(chg,1); ev['own_tradable']=avail_ok
    out.append(ev)
 print('events',len(out),flush=True)
 json.dump(out,open(ROOT/'data/r2/rebase_gate_events.json','w'))
 from collections import Counter
 vc=Counter(e['verdict'] for e in out); print('verdict:',dict(vc))
 form=[e for e in out if e['rebase']]
 print(f'formation: {len(form)}/{len(out)} ({100*len(form)/len(out):.1f}%) | speed med {statistics.median([e["speed"] for e in form]):.0f} bars')
 ret=[e for e in form if 'surv' in e]
 print(f'retested {len(ret)} | SURVIVED {100*sum(e["surv"] for e in ret)/len(ret):.1f}% | brk60 {100*sum(e["brk60"] for e in ret)/len(ret):.1f}% | rec10 med {statistics.median([e["rec10"] for e in ret if e["rec10"] is not None]):.3f} | pen med {statistics.median([e["pen"] for e in ret]):.3f}')
 byera=Counter()
 for e in ret:
  byera[e['tR'][:4]<='2023']+=0
 for lab,f in (('21-23',lambda e:e['tR'][:4]<='2023'),('24-26',lambda e:e['tR'][:4]>'2023')):
  s=[e for e in ret if f(e)]
  if s: print(f'  {lab}: n{len(s)} surv {100*sum(e["surv"] for e in s)/len(s):.1f}% brk {100*sum(e["brk60"] for e in s)/len(s):.1f}%')
 for g in ('CONC','FLAT','DISP'):
  s=[e for e in ret if e.get('own')==g]
  f_=[e for e in form if e.get('own')==g]
  if s: print(f'  own {g}: n {len(s)} surv {100*sum(e["surv"] for e in s)/len(s):.1f}% brk {100*sum(e["brk60"] for e in s)/len(s):.1f}% | speed med {statistics.median([e["speed"] for e in f_]):.0f}')
 trad=[e for e in ret if e.get('own_tradable')]
 if trad: print(f'  tradable-layer own events: {len(trad)} ({100*sum(e["surv"] for e in trad)/len(trad):.1f}% surv)')
if __name__=='__main__':main()
