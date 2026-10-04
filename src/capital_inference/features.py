#!/usr/bin/env python3
"""R2 §7-11: cost/chip engines + evidence families (E1-E6) PIT snapshot.

snapshot(code, ds, cl, hi, lo, vol, amount, i) uses ONLY bars <= i.
Missing inputs (amount/float/ownership) degrade to MISSING markers, never block.
"""
from __future__ import annotations
def _wq(bins, lo, hi, total, q):
 if total<=0 or hi<=lo: return None
 t=total*q; acc=0.0; w=(hi-lo)/len(bins)
 for b,c in enumerate(bins):
  if c>0 and acc+c>=t: return lo+(b+(t-acc)/c)*w
  acc+=c
 return hi
def snapshot(cl, hi, lo, vol, amount, i, nbin=50):
 if i<120: return None
 c=cl[i]
 win=cl[max(0,i-249):i+1]; v=vol[max(0,i-249):i+1]
 tp=[(hi[k]+lo[k]+cl[k])/3 for k in range(max(0,i-249),i+1)]
 bins=[0.0]*nbin; tot=0.0; tlo=min(tp); thi=max(tp); span=thi-tlo
 if span>0:
  for p,q in zip(tp,v):
   bins[min(nbin-1,int((p-tlo)/span*nbin))]+=q; tot+=q
 p10=_wq(bins,tlo,thi,tot,.10); p25=_wq(bins,tlo,thi,tot,.25); p50=_wq(bins,tlo,thi,tot,.50); p75=_wq(bins,tlo,thi,tot,.75); p90=_wq(bins,tlo,thi,tot,.90)
 width=(p90-p10)/p50 if p50 else None
 # prior band for contraction/migration
 def band_at(j):
  tpj=[(hi[k]+lo[k]+cl[k])/3 for k in range(max(0,j-249),j+1)]; bj=[0.0]*nbin; tj=0.0
  lj=min(tpj); hj=max(tpj); sj=hj-lj
  if sj<=0: return None,None
  for p,q in zip(tpj,vol[max(0,j-249):j+1]): bj[min(nbin-1,int((p-lj)/sj*nbin))]+=q; tj+=q
  w=_wq(bj,lj,hj,tj,.90)-_wq(bj,lj,hj,tj,.10); ctr=_wq(bj,lj,hj,tj,.50)
  return (w/ctr if ctr else None),ctr
 w60,ctr60=band_at(i-60)
 contract=(width/w60-1) if (width is not None and w60) else None
 migrate=((p50-ctr60)/ctr60) if (p50 is not None and ctr60) else None
 # E1 price structure
 hi250=max(win); lo250=min(win); pos=(c-lo250)/(hi250-lo250) if hi250>lo250 else None
 s60=(c/cl[i-60]-1) if cl[i-60]>0 else None
 import statistics
 vola=statistics.pstdev(cl[i-59:i+1])/c if c else None; volb=statistics.pstdev(cl[i-119:i+1])/c if c else None
 conv=(vola/volb) if (vola and volb) else None
 dd1=min(x/max(cl[i-119:i-59] or [c])-1 for x in cl[i-59:i+1])
 dd0=min(x/max(cl[max(0,i-179):i-119] or [c])-1 for x in cl[i-119:i-59]) if i>=180 else None
 shall=(dd1-dd0) if dd0 is not None else None
 # E2 participation
 def vr(a,b):
  x=vol[i-a+1:i+1]; y=vol[max(0,i-b+1):i+1]
  return (sum(x)/len(x))/(sum(y)/len(y)) if (y and sum(y)>0) else None
 ratio20=vr(20,250)
 uv=dv=0.0
 for k in range(max(0,i-19),i+1):
  if cl[k]>cl[k-1]: uv+=vol[k]
  elif cl[k]<cl[k-1]: dv+=vol[k]
 updown=(uv/dv) if dv>0 else None
 med_v=sorted(vol[max(0,i-249):i+1])[len(vol[max(0,i-249):i+1])//2]
 abn=sum(1 for k in range(max(0,i-19),i+1) if vol[k]>3*med_v)
 amt20=None
 if amount and amount[i] is not None:
  a20=[amount[k] for k in range(max(0,i-19),i+1) if amount[k] is not None]
  amt20=sum(a20)/len(a20) if a20 else None
 # chip proxies (E3)
 profit=(c-p50)/p50 if p50 else None
 trapped=(p90-c)/p90 if (p90 and c<p90) else 0.0
 below_p25=(c-p25)/p25 if p25 else None
 lock=0
 if contract is not None and contract<-0.15: lock+=1
 if ratio20 is not None and ratio20<0.9: lock+=1
 if shall is not None and shall>0: lock+=1
 if migrate is not None and migrate>0: lock+=1
 if s60 is not None and s60>0: lock+=1
 locking='HIGH' if lock>=4 else ('MEDIUM' if lock>=2 else 'LOW')
 float_=(c/ (p50 or c)) # placeholder no-op to keep names explicit
 press=0
 if width is not None and width>0.45: press+=1
 if updown is not None and updown<1 and ratio20 and ratio20>1.3: press+=1
 if pos is not None and pos>0.8 and ratio20 and ratio20>1.5: press+=1
 supply='HIGH' if press>=2 else ('MEDIUM' if press==1 else 'LOW')
 return {'pos250':round(pos,4) if pos is not None else None,'ret60':round(s60,4) if s60 is not None else None,'vol_conv':round(conv,4) if conv is not None else None,'dd_shallow':round(shall,4) if shall is not None else None,
  'p10':round(p10,3) if p10 else None,'p25':round(p25,3) if p25 else None,'p50':round(p50,3) if p50 else None,'p75':round(p75,3) if p75 else None,'p90':round(p90,3) if p90 else None,
  'band_width':round(width,4) if width is not None else None,'band_contract60':round(contract,4) if contract is not None else None,'cost_migrate60':round(migrate,4) if migrate is not None else None,
  'profit_vs_cost':round(profit,4) if profit is not None else None,'trapped_below':round(trapped,4),'below_p25':round(below_p25,4) if below_p25 is not None else None,
  'vol_ratio20':round(ratio20,4) if ratio20 is not None else None,'updown_vol20':round(updown,4) if updown is not None else None,'abn_vol_days20':abn,'amt20_avg':amt20,
  'chip_locking':locking,'floating_supply':supply,
  'E4_ownership':'MISSING','E5_public_signals':'MISSING'}
