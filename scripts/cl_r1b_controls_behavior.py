#!/usr/bin/env python3
"""CL-R1-B controls and behavioral outcome audit; no trading backtest."""
import csv,gzip,json,math,statistics
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ABL=ROOT/'data/cl_radar/r1_chip_ablation/ablation.csv.gz'; LAM=ROOT/'data/cl_radar/bridge_b1/observations.csv.gz'; D=ROOT/'data/cd/daily_fullmarket'; EXT=ROOT/'data/r2/market_ext'
OUT=ROOT/'data/cl_radar/r1_chip_ablation/r1b_controls_behavior.json'; REPORT=ROOT/'docs/external_ideas/radar/CL_R1B_CONTROLS_BEHAVIOR_REPORT.md'
def rank(x):
 o=sorted(range(len(x)),key=lambda i:x[i]);r=[0.]*len(x);i=0
 while i<len(o):
  j=i
  while j+1<len(o) and x[o[j+1]]==x[o[i]]:j+=1
  v=(i+j)/2+1
  for k in range(i,j+1):r[o[k]]=v
  i=j+1
 return r
def corr(a,b):
 if len(a)<10:return None
 a,b=rank(a),rank(b);ma=statistics.fmean(a);mb=statistics.fmean(b);da=sum((x-ma)**2 for x in a);db=sum((y-mb)**2 for y in b)
 return sum((x-ma)*(y-mb) for x,y in zip(a,b))/math.sqrt(da*db) if da and db else None
def partial(y,x,controls):
 # rank residualization with intercept; deterministic small-matrix OLS via normal equations.
 def solve(A,b):
  n=len(b); A=[row[:] + [b[i]] for i,row in enumerate(A)]
  for k in range(n):
   p=max(range(k,n),key=lambda i:abs(A[i][k])); A[k],A[p]=A[p],A[k]
   if abs(A[k][k])<1e-12:return [0.]*n
   z=A[k][k];A[k]=[v/z for v in A[k]]
   for i in range(n):
    if i!=k:
     z=A[i][k];A[i]=[A[i][j]-z*A[k][j] for j in range(n+1)]
  return [A[i][-1] for i in range(n)]
 cols=[[1.]+list(v) for v in controls]
 A=[[sum(row[i]*row[j] for row in cols) for j in range(len(cols[0]))] for i in range(len(cols[0]))]
 by=[sum(cols[j][i]*y[j] for j in range(len(y))) for i in range(len(cols[0]))]
 cy=solve(A,by); bx=[sum(cols[j][i]*x[j] for j in range(len(y))) for i in range(len(cols[0]))]
 cx=solve(A,bx); ry=[y[j]-sum(cols[j][i]*cy[i] for i in range(len(cols[0]))) for j in range(len(y))];rx=[x[j]-sum(cols[j][i]*cx[i] for i in range(len(cols[0]))) for j in range(len(y))]
 return corr(rx,ry)
def main():
 with gzip.open(ABL,'rt') as f: a=list(csv.DictReader(f))
 with gzip.open(LAM,'rt') as f: l=list(csv.DictReader(f))
 imp={(x['code'],x['episode_id'],x['date']):x for x in l}; rows=[]; cache={}
 for r in a:
  z=imp.get((r['code'],r['episode_id'],r['date']))
  if not z or not z.get('lambda_norm'):continue
  code=r['code']; six=code.split('.')[1]
  if code not in cache:
   rec=json.load(gzip.open(D/f'{six}.json.gz','rt')); ext={x['date']:x for x in json.load(open(EXT/f'{six}.json'))['rows']}; cache[code]=(rec,ext)
  rec,ext=cache[code]; ds=rec['dates']; i=ds.index(r['date']); q=rec['qfq']; ur=rec['unadj'];
  close=float(q[i][2]); prev=float(q[i-1][2]) if i else 0; rets=[]
  for j in range(max(1,i-19),i+1):
   p=float(q[j-1][2]);c=float(q[j][2]);
   if p>0:rets.append(c/p-1)
  amt=float(ext.get(r['date'],{}).get('amount') or 0);tr=float(ext.get(r['date'],{}).get('turnover_rate') or 0);adv=[]
  for j in range(max(0,i-19),i+1):
   v=float(ext.get(ds[j],{}).get('amount') or 0)
   if v>0:adv.append(v)
  # Future breakout behavior, fixed x and H; censoring explicit.
  fut=[]
  for x in (.05,.10):
   for H in (20,40):
    target=close*(1+x); hit=None; cum_amt=0.;cum_turn=0.
    end=min(len(ds)-1,i+H)
    for j in range(i+1,end+1):
     cum_amt+=float(ext.get(ds[j],{}).get('amount') or 0);cum_turn+=float(ext.get(ds[j],{}).get('turnover_rate') or 0)
     if float(q[j][2])>=target:hit=j-i;break
    fut += [(f'break_{int(x*100)}_{H}_hit',1 if hit is not None else 0),(f'break_{int(x*100)}_{H}_time',hit if hit is not None else None),(f'break_{int(x*100)}_{H}_amt',cum_amt if hit is not None else None),(f'break_{int(x*100)}_{H}_turn',cum_turn if hit is not None else None)]
  d=dict(r);d['lambda_norm']=float(z['lambda_norm']);d['controls']=[math.log(max(statistics.fmean(adv),1.0)),tr,statistics.pstdev(rets) if len(rets)>1 else 0,close,math.log(max(close,1e-6)),sum(rets)];
  for k,v in fut:d[k]=v
  for k,v in list(d.items()):
   if k not in ('code','episode_id','date','controls'):
    try:d[k]=float(v)
    except:pass
  rows.append(d)
 out={'n':len(rows),'market_cap_control':'unavailable in local R1 assets; not imputed','controls':['log_ADV20','turnover_T','vol20','close','log_close','ret20'],'results':{}}
 for m in range(4):
  for key in ('supply_above_2pct','supply_above_5pct','supply_above_10pct','overhead_total'):
   rr=[r for r in rows if r.get(f'M{m}_{key}') is not None];x=[r[f'M{m}_{key}'] for r in rr];y=[r['lambda_norm'] for r in rr];
   out['results'][f'M{m}|{key}']={'n':len(rr),'raw_rho':corr(x,y),'controlled_partial_rank':partial(y,x,[r['controls'] for r in rr])}
 # behavior association: +5 supply against fixed breakout hit and time-to-hit where uncensored.
 for m in range(4):
  for target in ('break_5_20_hit','break_5_40_hit','break_10_20_hit','break_10_40_hit'):
   rr=[r for r in rows if r.get(target) is not None];x=[r[f'M{m}_supply_above_5pct'] for r in rr];y=[r[target] for r in rr];out['results'][f'M{m}|{target}']={'n':len(rr),'rho':corr(x,y)}
 (OUT).parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 lines=['# CL-R1-B 控制与行为结果','',f"- valid joined observations: {len(rows)}",'- market-cap control: unavailable; no imputation','- behavior outcome: PIT-safe fixed breakout difficulty, not a trading return test','', '| model/metric | n | raw rho | controlled partial rank |','|---|---:|---:|---:|']
 for k,v in out['results'].items():
  if 'break_' not in k:lines.append(f"| {k} | {v['n']} | {v.get('raw_rho',v.get('rho')):.6f} | {v.get('controlled_partial_rank','—') if v.get('controlled_partial_rank') is not None else '—'} |")
 lines += ['', '## Breakout outcome', '', '| model/outcome | n | rho(local +5%, hit) |','|---|---:|---:|']
 for k,v in out['results'].items():
  if 'break_' in k:lines.append(f"| {k} | {v['n']} | {v['rho']:.6f} |")
 lines += ['', 'Market cap and market-regime controls remain an explicit data gap. Results are mechanism associations, not causal or investment conclusions.']
 REPORT.write_text('\n'.join(lines)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
