#!/usr/bin/env python3
"""CL-R1 fixed-sample M0-M3 chip-distribution ablation (research only)."""
import csv,gzip,json,math,statistics,hashlib
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'
EPS=ROOT/'data/cd/l4_episodes.json.gz'; SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
OUT=ROOT/'data/cl_radar/r1_chip_ablation'; REPORT=ROOT/'docs/external_ideas/radar/CL_R1_ABLATION_REPORT.md'
def sf(x):
 try:
  x=float(x); return x if math.isfinite(x) else 0.
 except: return 0.
def q(x,p):
 x=sorted(x); k=(len(x)-1)*p; f=int(k); c=min(f+1,len(x)-1); return x[f]+(x[c]-x[f])*(k-f)
def codes():
 x=json.load(open(SAMPLE)); c=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 return c,hashlib.sha256(('\n'.join(c)+'\n').encode()).hexdigest()
def rows(code):
 s=code.split('.')[-1]; rec=json.load(gzip.open(D/f'{s}.json.gz','rt')); ext={r['date']:r for r in json.load(open(AMT/f'{s}.json'))['rows']}; out=[]
 for qr,ur in zip(rec['qfq'],rec['unadj']):
  d=qr[0]; e=ext.get(d,{}); h,l,c,o=sf(qr[3]),sf(qr[4]),sf(qr[2]),sf(qr[1]); v=sf(ur[5]); a=sf(e.get('amount')); tr=sf(e.get('turnover_rate'))*100
  out.append({'date':d,'open':o,'high':h,'low':l,'close':c,'volume':v,'amount':a,'turnover':tr})
 return out
def center(r,vwap=False):
 if vwap and r['amount']>0 and r['volume']>0:return max(r['low'],min(r['high'],r['amount']/r['volume']))
 return max(r['low'],min(r['high'],(r['high']+r['low']+r['close'])/3))
def summarize(dist,lo,hi,close,bins):
 total=sum(dist)
 if total<=0:return None
 span=max(hi-lo, max(hi*.001,1e-9)); w=span/bins; items=[(lo+(i+.5)*w,z/total) for i,z in enumerate(dist)]
 return {'avg_cost':sum(p*x for p,x in items),'profit_ratio':sum(x for p,x in items if p<=close),'top5':sum(x for p,x in sorted(items,key=lambda z:z[1],reverse=True)[:5]),'below_1pct':sum(x for p,x in items if p<close*1.01),'near_2pct':sum(x for p,x in items if abs(p/close-1)<=.02),'supply_above_2pct':sum(x for p,x in items if p>close and p<=close*1.02),'supply_above_5pct':sum(x for p,x in items if p>close and p<=close*1.05),'supply_above_10pct':sum(x for p,x in items if p>close and p<=close*1.10),'overhead_total':sum(x for p,x in items if p>close),'width':w,'mn':lo,'mx':hi}
def cd5_or_m1(hist,decay=False):
 lo=hi=None; dist=[0.]*50
 for r in hist:
  if not (r['high']>0 and r['low']>0 and r['close']>0 and r['volume']>=0):continue
  if decay:
   rem=1-max(0,min(.98,r['turnover']/100)); dist=[z*rem for z in dist]
  tp=(r['high']+r['low']+r['close'])/3
  if lo is None:lo=hi=tp
  lo=min(lo,tp);hi=max(hi,tp); span=hi-lo; b=0 if span<=0 else min(49,int((tp-lo)/span*50)); dist[b]+=r['volume']
 return summarize(dist,lo,hi,hist[-1]['close'],50) if lo is not None else None
def global_model(hist,bins,decay=False,gauss=False,vwap=False):
 valid=[r for r in hist if r['high']>0 and r['low']>0 and r['volume']>0]
 if not valid:return None
 lo=min(r['low'] for r in valid);hi=max(r['high'] for r in valid);dist=[0.]*bins;w=max((hi-lo)/bins,1e-9)
 for r in valid:
  if decay:
   rem=1-max(0,min(.98,r['turnover']/100));dist=[z*rem for z in dist]
  c=center(r,vwap)
  if not gauss:
   dist[min(bins-1,max(0,int((c-lo)/w)))]+=r['volume'];continue
  sig=max((r['high']-r['low'])/4,w/2); weights=[];tw=0
  for i in range(bins):
   blo=lo+i*w;bhi=blo+w;z=0 if bhi<r['low'] or blo>r['high'] else math.exp(-.5*((lo+(i+.5)*w-c)/sig)**2);weights.append(z);tw+=z
  if tw:
   for i,z in enumerate(weights):dist[i]+=r['volume']*z/tw
 return summarize(dist,lo,hi,hist[-1]['close'],bins)
def main():
 OUT.mkdir(parents=True,exist_ok=True);cs,sha=codes();eps=json.load(gzip.open(EPS,'rt'))['episodes'];by=defaultdict(list)
 for e in eps:
  if e['stock'] in {c.split('.')[1] for c in cs}:by[e['stock']].append(e)
 out=[]
 for ni,code in enumerate(cs,1):
  rr=rows(code);six=code.split('.')[1]
  for ep in by[six]:
   start_i=next((i for i,r in enumerate(rr) if r['date']>=ep['start']),None); inds=[i for i,r in enumerate(rr) if ep['start']<=r['date']<=ep['end'] and i>=20]
   if start_i is None or not inds:continue
   for i in sorted(set(inds[min(len(inds)-1,max(0,int(len(inds)*p)))] for p in (0,.25,.5,.75,.999))):
    h=rr[start_i:i+1]; vals=[cd5_or_m1(h,False),cd5_or_m1(h,True),global_model(h,50,True,True,False),global_model(h,80,True,True,True)]
    if any(v is None for v in vals):continue
    rec={'code':code,'episode_id':ep['episode_id'],'date':rr[i]['date']}
    for j,v in enumerate(vals):
     for k,x in v.items():rec[f'M{j}_{k}']=x
    out.append(rec)
  print(f'{ni}/{len(cs)} {code}',flush=True)
 fields=sorted({k for r in out for k in r})
 with gzip.open(OUT/'ablation.csv.gz','wt',newline='') as f:
  w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(out)
 summary={'sample_n':len(cs),'sample_sha':sha,'snapshot_n':len(out),'models':{'M0':'CD5 exact running 50-bin point HLC/3','M1':'M0 + turnover decay','M2':'M1-like decay + Gaussian [L,H] HLC/3 + 50 global PIT grid','M3':'a-stock decay + Gaussian + VWAP center + 80 bins'},'metrics':{}}
 for k in ('avg_cost','profit_ratio','top5','below_1pct','near_2pct','supply_above_2pct','supply_above_5pct','supply_above_10pct','overhead_total','width'):
  summary['metrics'][k]={}
  for m in range(4):
   x=[r[f'M{m}_{k}'] for r in out];summary['metrics'][k][f'M{m}']={'median':statistics.median(x),'mean':statistics.fmean(x),'p10':q(x,.1),'p90':q(x,.9)}
 (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2));REPORT.write_text('# CL-R1 M0-M3 消融对照\n\n'+json.dumps(summary,ensure_ascii=False,indent=2)+'\n\n只比较成本分布与供应代理，不使用未来收益。\n',encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
