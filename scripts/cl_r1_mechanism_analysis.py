#!/usr/bin/env python3
"""CL-R1 mechanism-only analysis: model proxies vs existing B1 price impact."""
import csv,gzip,json,math,statistics
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ABL=ROOT/'data/cl_radar/r1_chip_ablation/ablation.csv.gz'
LAM=ROOT/'data/cl_radar/bridge_b1/observations.csv.gz'
OUT=ROOT/'data/cl_radar/r1_chip_ablation/mechanism_summary.json'
REPORT=ROOT/'docs/external_ideas/radar/CL_R1_MECHANISM_REPORT.md'
def mean(x): return statistics.fmean(x) if x else None
def med(x): return statistics.median(x) if x else None
def rank(x):
 o=sorted(range(len(x)),key=lambda i:x[i]); r=[0]*len(x); i=0
 while i<len(o):
  j=i
  while j+1<len(o) and x[o[j+1]]==x[o[i]]: j+=1
  a=(i+j)/2+1
  for k in range(i,j+1):r[o[k]]=a
  i=j+1
 return r
def corr(a,b):
 if len(a)<5:return None
 a,b=rank(a),rank(b); ma=mean(a);mb=mean(b); da=sum((x-ma)**2 for x in a);db=sum((y-mb)**2 for y in b)
 return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(da*db) if da and db else None
def summary(rs,k):
 x=[r[k] for r in rs if r.get(k) not in ('',None) and math.isfinite(float(r[k]))];x=[float(z) for z in x]
 return {'n':len(x),'median':med(x),'mean':mean(x)}
def main():
 a=[]
 with gzip.open(ABL,'rt') as f:a=list(csv.DictReader(f))
 l=[]
 with gzip.open(LAM,'rt') as f:l=list(csv.DictReader(f))
 impact={(r['code'],r['episode_id'],r['date']):r for r in l}
 rows=[]
 for r in a:
  z=impact.get((r['code'],r['episode_id'],r['date']))
  if not z:continue
  q=dict(r)
  for k,v in q.items():
   try:q[k]=float(v)
   except:pass
  for k in ('lambda_norm','lambda_raw','amihud'):
   q[k]=float(z[k]) if z.get(k) not in ('',None) else None
  rows.append(q)
 out={'n_joined':len(rows),'models':{},'by_model':{},'paired_deltas':{}}
 for m in range(4):
  ks=['profit_ratio','top5','below_1pct','near_2pct','supply_above_2pct','supply_above_5pct','supply_above_10pct','overhead_total','avg_cost']
  out['by_model'][f'M{m}']={}
  for k in ks:
   pairs=[(r[f'M{m}_{k}'],r['lambda_norm']) for r in rows if r[f'M{m}_{k}'] is not None and r['lambda_norm'] is not None]
   out['by_model'][f'M{m}'][k]={'n':len(pairs),'spearman_lambda_norm':corr([x for x,y in pairs],[y for x,y in pairs])}
  out['models'][f'M{m}']={'lambda_norm':summary(rows,'lambda_norm'),'amihud':summary(rows,'amihud')}
 for k in ('profit_ratio','top5','below_1pct','near_2pct','avg_cost'):
  vals=[]
  for r in rows:
   if r[f'M0_{k}']!='' and r[f'M3_{k}']!='': vals.append(float(r[f'M3_{k}'])-float(r[f'M0_{k}']))
  out['paired_deltas'][k]={'n':len(vals),'median_M3_minus_M0':med(vals),'mean_M3_minus_M0':mean(vals)}
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 lines=['# CL-R1 机制层报告（不含收益回测）','',f"- joined snapshots with B1 impact: {len(rows)}",'- response: existing 20d normalized lambda / Amihud only','- interpretation: associations with observable price impact; no actor or causal claim','', '## Model vs PriceImpact Spearman', '', '| model | proxy | rho(lambda_norm) | n |','|---|---|---:|---:|']
 for m,d in out['by_model'].items():
  for k,v in d.items():lines.append(f"| {m} | {k} | {v['spearman_lambda_norm']:.6f} | {v['n']} |" if v['spearman_lambda_norm'] is not None else f"| {m} | {k} | null | {v['n']} |")
 lines += ['', '## Ablation deltas (M3−M0)', '','```json',json.dumps(out['paired_deltas'],ensure_ascii=False,indent=2),'```','', 'This does not validate a trading factor. Any next-stage decision requires stronger stock/episode clustered tests and predeclared supply-pressure outcomes.']
 REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
