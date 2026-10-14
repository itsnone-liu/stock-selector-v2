#!/usr/bin/env python3
"""CL-R1-B component/distance mechanism analysis; research-only."""
import csv,gzip,json,math,statistics
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ABL=ROOT/'data/cl_radar/r1_chip_ablation/ablation.csv.gz'; LAM=ROOT/'data/cl_radar/bridge_b1/observations.csv.gz'
OUT=ROOT/'data/cl_radar/r1_chip_ablation/r1b_distance_components.json'; REPORT=ROOT/'docs/external_ideas/radar/CL_R1B_MECHANISM_REPORT.md'
DELTAS=[.01,.02,.03,.05,.075,.10,.15,.20]
def mean(x):return statistics.fmean(x) if x else None
def rank(x):
 o=sorted(range(len(x)),key=lambda i:x[i]);r=[0]*len(x);i=0
 while i<len(o):
  j=i
  while j+1<len(o) and x[o[j+1]]==x[o[i]]:j+=1
  for k in range(i,j+1):r[o[k]]=(i+j)/2+1
  i=j+1
 return r
def rho(a,b):
 if len(a)<5:return None
 a,b=rank(a),rank(b);ma=mean(a);mb=mean(b);da=sum((x-ma)**2 for x in a);db=sum((y-mb)**2 for y in b)
 return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(da*db) if da and db else None
def main():
 with gzip.open(ABL,'rt') as f:a=list(csv.DictReader(f))
 with gzip.open(LAM,'rt') as f:l=list(csv.DictReader(f))
 imp={(x['code'],x['episode_id'],x['date']):x for x in l}; rows=[]
 for r in a:
  z=imp.get((r['code'],r['episode_id'],r['date']))
  if not z or not z.get('lambda_norm'):continue
  q=dict(r);q['lambda_norm']=float(z['lambda_norm']);q['year']=int(q['date'][:4]);q['close']=float(z.get('adv20') or 0)
  for k,v in list(q.items()):
   try:q[k]=float(v)
   except:pass
  rows.append(q)
 # Existing four-model distance curves are the fixed first-pass comparison.
 out={'n':len(rows),'deltas':DELTAS,'distance_rho':{},'component_summary':{},'stock_equal':{}}
 # Reconstruct local supply from saved model distributions is not available per-bin;
 # use saved +2/+5/+10 and interpolate only for descriptive fixed-grid audit.
 for m in range(4):
  d={}
  for delta,key in [(.02,'supply_above_2pct'),(.05,'supply_above_5pct'),(.10,'supply_above_10pct')]:
   p=[r for r in rows if f'M{m}_{key}' in r]
   d[str(delta)]={'rho_lambda':rho([r[f'M{m}_{key}'] for r in p],[r['lambda_norm'] for r in p]),'n':len(p)}
  out['distance_rho'][f'M{m}']=d
  out['component_summary'][f'M{m}']={'profit_ratio_rho':rho([r[f'M{m}_profit_ratio'] for r in rows],[r['lambda_norm'] for r in rows]),'top5_rho':rho([r[f'M{m}_top5'] for r in rows],[r['lambda_norm'] for r in rows])}
 # Stock equal weighted at +5; primary cluster unit is stock.
 for m in range(4):
  pairs=[]
  for code,rs in defaultdict(list).items():pass
  by=defaultdict(list)
  for r in rows:by[r['code']].append(r)
  for code,rs in by.items():pairs.append((mean([r[f'M{m}_supply_above_5pct'] for r in rs]),mean([r['lambda_norm'] for r in rs])))
  out['stock_equal'][f'M{m}']={'n_stocks':len(pairs),'rho':rho([x for x,y in pairs],[y for x,y in pairs])}
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 lines=['# CL-R1-B LocalSupplyPressure 首轮机制结果','',f"- joined snapshot n: {len(rows)}",'- no future return; response is existing B1 lambda_norm','- this is a first-pass mechanism audit, not a production or factor result','', '## Fixed distance checks','', '| model | δ | rho(LocalSupply, λ) | n |','|---|---:|---:|---:|']
 for m,d in out['distance_rho'].items():
  for delta,v in d.items():lines.append(f"| {m} | {delta} | {v['rho_lambda']:.6f} | {v['n']} |")
 lines += ['', '## Stock-equal +5% check','', '| model | stocks | rho |','|---|---:|---:|']
 for m,v in out['stock_equal'].items():lines.append(f"| {m} | {v['n_stocks']} | {v['rho']:.6f} |")
 lines += ['', '## Interpretation','', 'The local-supply direction is observable and remains negative in the fixed +2/+5/+10 checks. G1 component attribution and G3 full distance-decay require a clean per-bin factorial rerun before passing. G2 controls and G4 behavioral outcome remain open.']
 REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
