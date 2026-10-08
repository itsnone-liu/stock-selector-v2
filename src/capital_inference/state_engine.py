#!/usr/bin/env python3
"""R2 §9-11: latent capital state inference + evidence scoring (rule v1)."""
from __future__ import annotations
LV={'STRONG_SUPPORT':2,'SUPPORT':1,'NEUTRAL':0,'CONTRADICT':-1,'STRONG_CONTRADICT':-2,'MISSING':0}
def infer(f):
 """f = features.snapshot(...) dict. Returns state, confidence, family scores."""
 fam={}
 pos=f.get('pos250'); r60=f.get('ret60'); conv=f.get('vol_conv'); shall=f.get('dd_shallow')
 e1=0
 if pos is not None:
  if pos<0.35: e1+=1
  if pos<0.2: e1+=1
  if pos>0.85: e1-=1
 if conv is not None and conv<0.8: e1+=1
 if shall is not None and shall>0.05: e1+=1
 if r60 is not None and r60>0.2: e1+=1
 if r60 is not None and r60<-0.2: e1-=1
 fam['E1_price']=max(-2,min(2,e1))
 vr=f.get('vol_ratio20'); ud=f.get('updown_vol20'); abn=f.get('abn_vol_days20')
 e2=0
 if vr is not None:
  if vr<0.85: e2+=1
  if vr>1.6: e2-=0
 if ud is not None:
  if ud>1.5: e2+=1
  if ud<0.7: e2-=1
 if abn is not None and abn>=2: e2+=1
 fam['E2_participation']=max(-2,min(2,int(e2)))
 bw=f.get('band_width'); bc=f.get('band_contract60'); cm=f.get('cost_migrate60'); pr=f.get('profit_vs_cost'); lock=f.get('chip_locking'); sup=f.get('floating_supply')
 e3=0
 if bc is not None and bc<-0.2: e3+=2
 elif bc is not None and bc<0: e3+=1
 if bw is not None and bw<0.3: e3+=1
 if cm is not None and cm>0.02: e3+=1
 if lock=='HIGH': e3+=1
 if sup=='HIGH': e3-=1
 if pr is not None and pr>0.5: e3-=1
 fam['E3_chip']=max(-2,min(2,int(e3)))
 hc=f.get('holders_chg_pct'); hc2=f.get('holders_chg2_pct')
 e4=0
 if hc is not None:
  if hc<-10: e4+=2
  elif hc<-5: e4+=1
  elif hc>10: e4-=1
 if hc2 is not None and hc2<-5: e4+=1
 if hc2 is not None and hc2>5: e4-=1
 fam['E4_ownership']=max(-2,min(2,e4))
 mc=f.get('margin_chg20'); li=f.get('lhb_inst_net60'); le=f.get('lhb_events60')
 e5s=0
 if mc is not None:
  if mc>0.15: e5s+=1
  elif mc<-0.15: e5s-=1
 if li is not None:
  if li>0.3: e5s+=1
  elif li<-0.3: e5s-=1
 fam['E5_public']=max(-2,min(2,e5s)) if (mc is not None or li is not None) else 'MISSING'
 fam['E6_context']='MISSING'
 scores=[v for v in fam.values() if isinstance(v,int)]
 cov_adj=fam['E4_ownership']!='MISSING'
 sup=sum(v for v in scores if v>0); con=sum(-v for v in scores if v<0); cov=len([v for v in fam.values() if v!='MISSING'])/6
 conf=round(min(0.9,0.3+0.1*sup+0.35*cov),2)
 # state rules v1 (price/chip driven; ownership pending -> confidence cap)
 if con>=2: state='CONFLICTED'
 elif sup>=4 and (pos is not None and pos<0.45) and (f.get('holders_chg_pct') is None or f.get('holders_chg_pct')<5) and (r60 is not None and r60<0.25) and (bc is not None and bc<0): state='ACCUMULATION_MATURE' if sup>=5 else 'ACCUMULATION'
 elif (r60 is not None and r60>0.25) and (cm is not None and cm>0.03) and sup>=3: state='MARKUP_ACTIVE'
 elif sup>=3 and (cm is not None and cm>=0) and lock in ('MEDIUM','HIGH'): state='MARKUP_READY'
 elif (pos is not None and pos>0.8) and (sup=='HIGH' or (pr is not None and pr>0.6)): state='DISTRIBUTION_RISK'
 elif (r60 is not None and r60<-0.2) or (pos is not None and pos<0.3 and sup<2): state='DECLINE'
 else: state='ACCUMULATION' if sup>=2 else 'NEUTRAL'
 if cov<0.5: conf=round(min(conf,0.5),2)
 return {'state':state,'confidence':conf,'support_score':sup,'contradiction_score':con,'coverage':round(cov,2),'evidence_family_scores':{k:(v if isinstance(v,int) else v) for k,v in fam.items()}}
