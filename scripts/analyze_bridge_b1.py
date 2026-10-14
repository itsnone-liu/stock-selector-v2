#!/usr/bin/env python3
"""Descriptive/clustered analysis for Bridge B1. No production outputs."""
import csv,gzip,json,math,statistics
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
INP=ROOT/'data/cl_radar/bridge_b1/observations.csv.gz'
OUT=ROOT/'data/cl_radar/bridge_b1'
REPORT=ROOT/'docs/external_ideas/radar/BRIDGE_B1_REPORT.md'

def mean(xs): return sum(xs)/len(xs) if xs else None
def med(xs): return statistics.median(xs) if xs else None
def quant(xs,p):
 if not xs:return None
 y=sorted(xs); k=(len(y)-1)*p; f=int(k); c=min(f+1,len(y)-1)
 return y[f]+(y[c]-y[f])*(k-f)
def trimmed(xs):
 if len(xs)<10:return xs
 a=sorted(xs); lo=int(len(a)*.01); hi=len(a)-lo
 return a[lo:hi]
def pct_change(a,b): return None if a in (None,0) or b is None else b/a-1

def main():
 rows=[]
 with gzip.open(INP,'rt',encoding='utf-8') as f:
  for r in csv.DictReader(f):
   for k in ('lambda_norm','lambda_raw','impact_beta','amihud','cost_band_width_norm','distance_to_cost_center','volume_below_current_price_ratio','adv20'):
    r[k]=float(r[k]) if r[k] not in ('', 'None', None) else None
   r['yearbin']=('2021-22' if r['date'][:4] in ('2021','2022') else '2023-24' if r['date'][:4] in ('2023','2024') else '2025-26')
   rows.append(r)
 def summarize(rs,key):
  vals=[r[key] for r in rs if r[key] is not None and math.isfinite(r[key])]
  tv=trimmed(vals)
  return {'n':len(vals),'median':med(vals),'mean':mean(vals),'trim_mean_1pct':mean(tv),
          'p10':quant(vals,.1),'p90':quant(vals,.9)}
 out={'total_n':len(rows),'by_position':{},'by_year_position':{},'by_origin_position':{},'profit_strata':{},'correlations':{}}
 for pos in ('below','inside','above'):
  rs=[r for r in rows if r['cost_position']==pos]
  out['by_position'][pos]={'lambda_norm':summarize(rs,'lambda_norm'),'lambda_raw':summarize(rs,'lambda_raw'),'impact_beta':summarize(rs,'impact_beta'),'amihud':summarize(rs,'amihud'),'profit_ratio':summarize(rs,'volume_below_current_price_ratio'),'band_width':summarize(rs,'cost_band_width_norm')}
  for y in ('2021-22','2023-24','2025-26'):
   rr=[r for r in rs if r['yearbin']==y]
   out['by_year_position'][f'{y}|{pos}']=summarize(rr,'lambda_norm')
  for o in ('S','M','L'):
   rr=[r for r in rs if r['episode_origin']==o]
   out['by_origin_position'][f'{o}|{pos}']=summarize(rr,'lambda_norm')
 # Volume-below quartile strata
 valid=[r['volume_below_current_price_ratio'] for r in rows if r['volume_below_current_price_ratio'] is not None]
 q1,q3=quant(valid,.25),quant(valid,.75)
 out['profit_ratio_cutpoints']={'q25':q1,'q75':q3}
 for label,fn in [('low_profit',lambda x:x<=q1),('mid_profit',lambda x:q1<x<q3),('high_profit',lambda x:x>=q3)]:
  rr=[r for r in rows if r['volume_below_current_price_ratio'] is not None and fn(r['volume_below_current_price_ratio'])]
  out['profit_strata'][label]=summarize(rr,'lambda_norm')
 # Per-stock means then position contrast, reducing day clustering.
 bystock=defaultdict(lambda:defaultdict(list))
 for r in rows:
  if r['lambda_norm'] is not None: bystock[r['code']][r['cost_position']].append(r['lambda_norm'])
 stock_summary={}
 contrasts=[]
 for code,d in bystock.items():
  stock_summary[code]={p:med(v) for p,v in d.items()}
  if 'below' in d and 'above' in d: contrasts.append(med(d['below'])-med(d['above']))
 out['stock_level_contrast']={'stocks_with_below_above':len(contrasts),'median_below_minus_above':med(contrasts),'mean_below_minus_above':mean(contrasts),'p10':quant(contrasts,.1),'p90':quant(contrasts,.9)}
 # Equal-stock weighted position medians: average per-stock position medians.
 for p in ('below','inside','above'):
  vals=[v[p] for v in stock_summary.values() if p in v]
  out.setdefault('equal_stock',{})[p]={'stocks':len(vals),'median_of_stock_medians':med(vals),'mean_of_stock_medians':mean(vals)}
 # Simple finite correlations (Spearman via ranks) across all observations and stock-day means.
 def rank(vs):
  order=sorted(range(len(vs)),key=lambda i:vs[i]); out=[0]*len(vs); i=0
  while i<len(order):
   j=i
   while j+1<len(order) and vs[order[j+1]]==vs[order[i]]:j+=1
   av=(i+j)/2+1
   for k in range(i,j+1):out[order[k]]=av
   i=j+1
  return out
 def corr(a,b):
  if len(a)<3:return None
  ra,rb=rank(a),rank(b); ma=mean(ra);mb=mean(rb)
  na=sum((x-ma)**2 for x in ra);nb=sum((x-mb)**2 for x in rb)
  return sum((x-ma)*(y-mb) for x,y in zip(ra,rb))/math.sqrt(na*nb) if na and nb else None
 for key in ('volume_below_current_price_ratio','cost_band_width_norm','distance_to_cost_center'):
  pairs=[(r[key],r['lambda_norm']) for r in rows if r[key] is not None and r['lambda_norm'] is not None and math.isfinite(r[key]) and math.isfinite(r['lambda_norm'])]
  out['correlations'][f'{key}_vs_lambda_norm']={'n':len(pairs),'spearman':corr([x for x,y in pairs],[y for x,y in pairs])}
 # Persist machine-readable and append report (replace previous minimal report)
 (OUT/'analysis_summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
 lines=['# Bridge B1 Run Report','', '- protocol: capital-bridge-b1-v1','- sample: 84 frozen codes; SHA `083ca9ef0292310aad2415843e8756511b2d74682abb9b1d4b2f897fc0e026d6`','- episodes: 476; observations: 77355; errors: 0','- cost positions: '+json.dumps(Counter(r['cost_position'] for r in rows),ensure_ascii=False),'- origins: '+json.dumps(Counter(r['episode_origin'] for r in rows),ensure_ascii=False),'','## Primary descriptive result','']
 lines += ['| cost_position | n | lambda_norm median | trimmed mean | amihud median | profit-ratio median |','|---|---:|---:|---:|---:|---:|']
 for p in ('below','inside','above'):
  d=out['by_position'][p]; lines.append(f"| {p} | {d['lambda_norm']['n']} | {d['lambda_norm']['median']:.8g} | {d['lambda_norm']['trim_mean_1pct']:.8g} | {d['amihud']['median']:.8g} | {d['profit_ratio']['median']:.6g} |")
 lines += ['', '## Equal-stock and contrast checks','', '```json',json.dumps({'equal_stock':out['equal_stock'],'stock_level_contrast':out['stock_level_contrast'],'profit_ratio_cutpoints':out['profit_ratio_cutpoints'],'correlations':out['correlations']},ensure_ascii=False,indent=2),'```','', 'This is a mechanism-observation dataset only. No production decision or CD-5 artifact was modified. Descriptive associations are not a support verdict until the predeclared time-window/coverage review is complete.']
 REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8')
 print(json.dumps({'n':len(rows),'positions':dict(Counter(r['cost_position'] for r in rows)),'summary':out['by_position'],'stock_contrast':out['stock_level_contrast'],'correlations':out['correlations']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
