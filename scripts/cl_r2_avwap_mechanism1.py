#!/usr/bin/env python3
"""CL-R2 first mechanism pass: gap vs pre-registered behavior family.
Unadjusted price space; main set (factor max dev <=2%) vs sensitivity set (>2%).
No parameter search; fixed windows/levels were preregistered."""
import csv,gzip,json,math,statistics,random
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'
EPS=ROOT/'data/cd/l4_episodes.json.gz'; SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
LAM=ROOT/'data/cl_radar/bridge_b1/observations.csv.gz'
OUT=ROOT/'data/cl_radar/r2_avwap/mechanism1.json'; REPORT=ROOT/'docs/external_ideas/radar/CL_R2_AVWAP_MECHANISM1.md'
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
 def solve(A,b):
  n=len(b);A=[row[:]+[b[i]] for i,row in enumerate(A)]
  for k in range(n):
   p=max(range(k,n),key=lambda i:abs(A[i][k]));A[k],A[p]=A[p],A[k]
   if abs(A[k][k])<1e-12:return[0.]*n
   z=A[k][k];A[k]=[v/z for v in A[k]]
   for i in range(n):
    if i!=k:
     z=A[i][k];A[i]=[A[i][j]-z*A[k][j] for j in range(n+1)]
  return[A[i][-1] for i in range(n)]
 cols=[[1.]+list(v) for v in controls];k=len(cols[0])
 A=[[sum(r[i]*r[j] for r in cols) for j in range(k)] for i in range(k)]
 by=[sum(cols[t][i]*y[t] for t in range(len(y)))for i in range(k)];bx=[sum(cols[t][i]*x[t] for t in range(len(y)))for i in range(k)]
 cy=solve(A,by);cx=solve(A,bx)
 ry=[y[t]-sum(cols[t][i]*cy[i] for i in range(k))for t in range(len(y))];rx=[x[t]-sum(cols[t][i]*cx[i] for i in range(k))for t in range(len(y))]
 return corr(rx,ry)
def main():
 with gzip.open(LAM,'rt') as f:lam={(x['code'],x['episode_id'],x['date']):x for x in csv.DictReader(f)}
 x=json.load(open(SAMPLE));cs=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 eps=json.load(gzip.open(EPS,'rt'))['episodes']
 by=defaultdict(list)
 for e in eps:
  if e['stock'] in {c.split('.')[1] for c in cs}:by[e['stock']].append(e)
 rows=[]
 for code in cs:
  six=code.split('.')[1]
  rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
  ds=rec['dates'];idx={d:i for i,d in enumerate(ds)};qfq=rec['qfq'];un=rec['unadj']
  facs=[(float(qfq[j][2])/float(un[j][2])) if float(un[j][2])>0 and float(qfq[j][2])>0 else None for j in range(len(ds))]
  for e in by[six]:
   s,t=e['start'],e['end']
   if s not in idx or t not in idx:continue
   i0,i1=idx[s],idx[t];inds=[i for i in range(i0,i1+1)]
   if len(inds)<6:continue
   fs=[facs[j] for j in inds if facs[j]]
   fmax=max((abs(f/fs[0]-1) for f in fs),default=1.0) if fs else 1.0
   subset='main' if fmax<=0.02 else 'sensitivity'
   picks=sorted(set(inds[min(len(inds)-1,max(0,int(len(inds)*p)))] for p in (0,.25,.5,.75,.999)))
   for i in picks:
    if i<=i0:continue
    a=cumv=0.0
    for j in range(i0,i+1):
     a+=float(ext.get(ds[j],{}).get('amount') or 0);cumv+=float(un[j][5] or 0)*100.0
    if a<=0 or cumv<=0:continue
    avwap=a/cumv;cu=float(un[i][2]);gap=cu/avwap-1
    # controls at T (PIT)
    advs=[float(ext.get(ds[j],{}).get('amount') or 0) for j in range(max(0,i-19),i+1)]
    rets=[]
    for j in range(max(1,i-19),i+1):
     p=float(qfq[j-1][2]);c2=float(qfq[j][2])
     if p>0:rets.append(c2/p-1)
    sh=float(ext.get(ds[i],{}).get('outstanding_share') or 0)
    ctr=[math.log(max(statistics.fmean(advs),1.0)),float(ext.get(ds[i],{}).get('turnover_rate') or 0),statistics.pstdev(rets) if len(rets)>1 else 0,math.log(max(cu,1e-6)),sum(rets),math.log(max(cu*sh,1.0))]
    # preregistered fixed outcomes (unadjusted space, frozen anchor value)
    fwin=inds[-1]
    n10=[j for j in range(i+1,min(len(ds),i+11))]
    n20=[j for j in range(i+1,min(len(ds),i+21))]
    minc=min((float(un[j][2]) for j in n10),default=None)
    retention=None if minc is None or not n10 else (1 if minc>avwap else 0)
    touch=None;tj=None
    for j in n20:
     if float(un[j][2])<=avwap:touch=1;tj=j;break
    if touch is None and len(n20)==20:touch=0
    bounce=None
    if tj is not None and tj+5<len(ds):bounce=1 if float(un[tj+5][2])>avwap else 0
    drift=None
    if n10:drift=statistics.fmean(float(un[j][2]) for j in n10)/avwap-1
    z=lam.get((code,e['episode_id'],ds[i]))
    rows.append({'code':code,'episode_id':e['episode_id'],'date':ds[i],'subset':subset,'gap':gap,'avwap':avwap,'controls':ctr,'retention':retention,'touch':touch,'bounce':bounce,'drift10':drift,'lambda_norm':float(z['lambda_norm']) if z and z.get('lambda_norm') else None})
 random.seed(20261014)
 out={'n_snapshots':len(rows),'n_main':sum(1 for r in rows if r['subset']=='main'),'n_sensitivity':sum(1 for r in rows if r['subset']=='sensitivity'),'subsets':{}}
 for sub in ('main','sensitivity'):
  rs=[r for r in rows if r['subset']==sub]
  if not rs:continue
  S={'n':len(rs),'gap':{'median':statistics.median(r['gap'] for r in rs),'p10':sorted(r['gap'] for r in rs)[len(rs)//10],'p90':sorted(r['gap'] for r in rs)[9*len(rs)//10]}}
  # C: lambda association raw/controlled
  lr=[r for r in rs if r['lambda_norm'] is not None]
  if len(lr)>=50:
   S['lambda']={'n':len(lr),'raw_rho':corr([r['gap'] for r in lr],[r['lambda_norm'] for r in lr]),'controlled_partial':partial([r['lambda_norm'] for r in lr],[r['gap'] for r in lr],[r['controls'] for r in lr])}
   byst=defaultdict(list)
   for r in lr:byst[r['code']].append(r)
   codes=list(byst);ests=[]
   for _ in range(1000):
    samp=[codes[random.randrange(len(codes))]for _ in codes]
    xx=[statistics.fmean(r['gap'] for r in byst[c])for c in samp];yy=[statistics.fmean(r['lambda_norm'] for r in byst[c])for c in samp]
    ests.append(corr(xx,yy))
   S['lambda']['stock_bootstrap_median']=statistics.median(ests);S['lambda']['stock_bootstrap_p05']=sorted(ests)[49];S['lambda']['stock_bootstrap_p95']=sorted(ests)[949]
  # behavior family by gap tercile among gap>0 (above anchor)
  ab=[r for r in rs if r['gap']>0]
  if len(ab)>=60:
   gs=sorted(r['gap'] for r in ab);t1=gs[len(gs)//3];t2=gs[2*len(gs)//3]
   ter=lambda g:0 if g<=t1 else (1 if g<=t2 else 2)
   S['above_anchor_terciles']={'cut1':t1,'cut2':t2}
   for k in (0,1,2):
    g=[r for r in ab if ter(r['gap'])==k]
    ret=[r['retention'] for r in g if r['retention'] is not None];tch=[r['touch'] for r in g if r['touch'] is not None];bnc=[r['bounce'] for r in g if r['bounce'] is not None]
    S['above_anchor_terciles'][f't{k}']={'n':len(g),'retention10_rate':statistics.fmean(ret) if ret else None,'touch20_rate':statistics.fmean(tch) if tch else None,'bounce5_given_touch':statistics.fmean(bnc) if bnc else None,'drift10_median':statistics.median([r['drift10'] for r in g]) if g and all(r['drift10'] is not None for r in g) else None}
   # drift association
   dd=[r for r in ab if r['drift10'] is not None]
   if len(dd)>=50:S['drift10_vs_gap']={'n':len(dd),'raw_rho':corr([r['gap'] for r in dd],[r['drift10'] for r in dd]),'controlled_partial':partial([r['drift10'] for r in dd],[r['gap'] for r in dd],[r['controls'] for r in dd])}
  out['subsets'][sub]=S
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 L=['# CL-R2 AVWAP 首轮机制结果（预注册行为族，未复权空间）','',f"- snapshots: {out['n_snapshots']}（main {out['n_main']} / sensitivity {out['n_sensitivity']}）",'- 固定窗口：retention=10日内最低收盘>冻结AVWAP；touch=20日内收盘回落至AVWAP；bounce=触及后5日收回上方；drift=后10日均价/AVWAP−1','- 无参数搜索；λ 为 B1 复用','']
 for sub,S in out['subsets'].items():
  L+=[f'## {sub}（n={S["n"]}）',f"- gap 中位 {S['gap']['median']:.4f}（P10 {S['gap']['p10']:.4f}，P90 {S['gap']['p90']:.4f}）"]
  if 'lambda' in S:
   z=S['lambda'];L+=["",f"- gap×λ：raw ρ={z['raw_rho']:.4f}，控制后 partial={z['controlled_partial']:.4f}，股票 bootstrap 中位={z['stock_bootstrap_median']:.4f}（P05 {z['stock_bootstrap_p05']:.4f}，P95 {z['stock_bootstrap_p95']:.4f}，n={z['n']}）"]
  if 'above_anchor_terciles' in S:
   T=S['above_anchor_terciles'];L+=['',f"### 锚上方 gap 三分位（cut {T['cut1']:.3f}/{T['cut2']:.3f}）",'','| tercile | n | retention@10d | touch@20d | bounce@5d|touch | drift10 中位 |','|---|---:|---:|---:|---:|---:|']
   for k in (0,1,2):
    v=T[f't{k}']
    f_=lambda x:'—' if x is None else f"{x:.3f}"
    L.append(f"| t{k} | {v['n']} | {f_(v['retention10_rate'])} | {f_(v['touch20_rate'])} | {f_(v['bounce5_given_touch'])} | {f_(v['drift10_median'])} |")
  if 'drift10_vs_gap' in S:
   z=S['drift10_vs_gap'];L+=['',f"- gap×drift10：raw ρ={z['raw_rho']:.4f}，控制后 partial={z['controlled_partial']:.4f}（n={z['n']}）"]
  L+=['']
 L+=['## 解释边界','', 'AVWAP 是事件锚定成交重心，非"主力成本"；gap 不识别持仓者意图；全部为机制关联描述，非因果、非交易信号；sensitivity 子集含 episode 内真实除权，跨除权日的价格比较受机械除权影响，仅作对照。']
 REPORT.write_text('\n'.join(L)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
