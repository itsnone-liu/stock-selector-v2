#!/usr/bin/env python3
"""CL-R2 census refinement: volume unit check + adjustment-factor change magnitude.
Census only — no outcome variables."""
import gzip,json,statistics,hashlib
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'
EPS=ROOT/'data/cd/l4_episodes.json.gz'; SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
OUT=ROOT/'data/cl_radar/r2_avwap/census2.json'
def med(xs):return statistics.median(xs) if xs else None
def q(xs,p):
 xs=sorted(xs);k=(len(xs)-1)*p;f=int(k);c=min(f+1,len(xs)-1);return xs[f]+(xs[c]-xs[f])*(k-f)
def main():
 x=json.load(open(SAMPLE));cs=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 eps=json.load(gzip.open(EPS,'rt'))['episodes']
 by=defaultdict(list)
 for e in eps:
  if e['stock'] in {c.split('.')[1] for c in cs}:by[e['stock']].append(e)
 # A. unit check on raw days: ratio (amount/volume)/ohlc4 across ALL days of 84 stocks
 ratios=[];n_days=0
 # B. per-episode max |Δfactor| (factor=close_qfq/close_unadj, day-over-day ratio)
 maxch=[];ch_from_start=[];n_ep=0;stable=0;small=0;real=0
 avw_dev=[]
 for code in cs:
  six=code.split('.')[1]
  rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
  ds=rec['dates'];idx={d:i for i,d in enumerate(ds)};qfq=rec['qfq'];un=rec['unadj']
  # unit ratio on a subsample of days (every 5th) to bound cost
  for j in range(0,len(ds),5):
   d=ds[j];a=float(ext.get(d,{}).get('amount') or 0);v=float(un[j][5] or 0)
   o,h,l,c=(float(un[j][k]) for k in (1,2,3,4))
   if a>0 and v>0 and o>0:ratios.append((a/v)/((o+h+l+c)/4));n_days+=1
  facs=[]
  for j in range(len(ds)):
   u=float(un[j][2]);qq=float(qfq[j][2]);facs.append(qq/u if u>0 and qq>0 else None)
  for e in by[six]:
   s,t=e['start'],e['end']
   if s not in idx or t not in idx:continue
   i0,i1=idx[s],idx[t];n_ep+=1
   fs=[facs[j] for j in range(i0,i1+1) if facs[j]]
   if len(fs)<2:continue
   base=fs[0]
   devs=[abs(f/base-1) for f in fs]
   mx=max(devs);maxch.append(mx);ch_from_start.append(statistics.fmean(devs))
   if mx<0.005:stable+=1
   elif mx<0.02:small+=1
   else:real+=1
   # corrected AVWAP vs unadj OHLC4 within episode
   dv=[]
   for j in range(i0,i1+1):
    d=ds[j];a=float(ext.get(d,{}).get('amount') or 0);v=float(un[j][5] or 0)*100.0
    o,h,l,c=(float(un[j][k]) for k in (1,2,3,4))
    if a>0 and v>0 and o>0:dv.append(abs((a/v)/((o+h+l+c)/4)-1))
   if dv:avw_dev.append(statistics.fmean(dv))
 out={'unit_check':{'n_days_sampled':n_days,'ratio_amount_per_lotvolume_over_ohlc4':{'median':med(ratios),'p10':q(ratios,.1),'p90':q(ratios,.9)},'conclusion':'volume unit = 手(lots of 100); AVWAP must divide by volume*100'},
 'episodes_audited':n_ep,
 'factor_change_from_episode_start':{'max_dev_median':med(maxch),'max_dev_p90':q(maxch,.9),'mean_dev_median':med(ch_from_start)},
 'factor_stability_classes':{'stable_lt_0.5pct':stable,'small_0.5_2pct':small,'real_break_gt_2pct':real,'real_break_frac':real/n_ep},
 'corrected_avwap_vs_unadj_ohlc4_dev':{'median':med(avw_dev),'p90':q(avw_dev,.9),'n_episodes':len(avw_dev)}}
 ok=((out['corrected_avwap_vs_unadj_ohlc4_dev']['median'] or 1)<0.02 and out['factor_stability_classes']['real_break_frac']<=0.10)
 out['census_verdict']='SUFFICIENT_SUPPORT' if ok else 'INSUFFICIENT_SUPPORT_REVIEW'
 OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
