#!/usr/bin/env python3
"""CL-R3 Support-First census: Effort/Result construction audit.
Census only — no outcome variables computed."""
import gzip,json,math,statistics,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'
SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
OUT=ROOT/'data/cl_radar/r3_effort_result/census.json'; REPORT=ROOT/'docs/external_ideas/radar/CL_R3_EFFORT_RESULT_CENSUS.md'
def med(xs):return statistics.median(xs) if xs else None
def q(xs,p):
 xs=sorted(xs);k=(len(xs)-1)*p;f=int(k);c=min(f+1,len(xs)-1);return xs[f]+(xs[c]-xs[f])*(k-f)
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
def main():
 x=json.load(open(SAMPLE));cs=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 sha=hashlib.sha256(('\n'.join(cs)+'\n').encode()).hexdigest()
 efforts=[];results=[];within=[];n_days=0;amt_missing=0;short_hist=0
 # market conditioner availability: 000985 qfq close vs MA120
 idx=json.load(gzip.open(D/'000985.json.gz','rt'));ic=[float(r[2]) for r in idx['qfq']]
 ma_ok=sum(1 for j in range(120,len(ic)) if ic[j-120]>0)
 for code in cs:
  six=code.split('.')[1]
  rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
  ds=rec['dates'];qfq=rec['qfq']
  amts=[];rets=[]
  es=[];rs=[]
  for j in range(len(ds)):
   a=float(ext.get(ds[j],{}).get('amount') or 0)
   amts.append(a)
   if a<=0:amt_missing+=1
   p=float(qfq[j-1][2]) if j>0 else 0;c2=float(qfq[j][2])
   rets.append(c2/p-1 if p>0 else None)
   if j>=21:
    adv=[amts[k] for k in range(j-20,j) if amts[k]>0]
    rr=[rets[k] for k in range(j-20,j) if rets[k] is not None]
    if a>0 and len(adv)==20 and len(rr)>=15:
     e=math.log(a/statistics.fmean(adv));sd=statistics.pstdev(rr)
     if sd>0:
      r_=abs(rets[j])/sd;es.append(e);rs.append(r_);n_days+=1
     else:short_hist+=1
    else:short_hist+=1
  if len(es)>=50:within.append(corr(es,rs))
  efforts+=es;results+=rs
 pooled=corr(efforts,results)
 e_med=med(efforts);r_med=med(results)
 quad={'EH_RH':0,'EH_RL':0,'EL_RH':0,'EL_RL':0}
 for e,r_ in zip(efforts,results):
  quad['EH_RH' if e>e_med and r_>r_med else 'EH_RL' if e>e_med else 'EL_RH' if r_>r_med else 'EL_RL']+=1
 n=len(efforts)
 out={'sample_n':len(cs),'sample_sha':sha,'days_constructed':n,'amount_missing_days':amt_missing,'insufficient_history_skipped':short_hist,
 'effort':{'median':e_med,'p10':q(efforts,.1),'p90':q(efforts,.9)},
 'result':{'median':r_med,'p10':q(results,.1),'p90':q(results,.9)},
 'degeneracy':{'pooled_spearman':pooled,'within_stock_spearman_median':med(within),'within_stock_spearman_p90_abs':q([abs(z) for z in within],.9),'threshold':0.7,'n_stocks_measured':len(within)},
 'quadrant_share':{k:v/n for k,v in quad.items()},
 'market_conditioner_000985':{'days_with_ma120':ma_ok,'total_days':len(ic)},
 }
 degenerate=abs(pooled)>0.7 or med([abs(z) for z in within] or [0])>0.7
 bal=all(0.15<=v<=0.35 for v in out['quadrant_share'].values())
 out['census_verdict']='SUFFICIENT_SUPPORT' if (not degenerate and bal and n>50000) else 'INSUFFICIENT_SUPPORT_REVIEW'
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 L=['# CL-R3 Effort-Result Support-First 普查（census only）','',f"- days constructed: {n}（84 股，sha {sha[:12]}…）",f"- pooled Spearman(Effort,Result) = {pooled:.4f}；股票内 |ρ| 中位 = {med([abs(z) for z in within] or [0]):.4f}（阈值 0.7）",f"- 象限占比："+"；".join(f"{k}={v:.3f}" for k,v in out['quadrant_share'].items()),f"- market conditioner（000985 MA120 可用日）: {ma_ok}/{len(ic)}",f"- census verdict: **{out['census_verdict']}**",'','判定规则（预注册）：非退化（|ρ|≤0.7 合并与股票内）+ 象限占比 15%–35% + 构造日>5万。未读任何结果变量。']
 REPORT.write_text('\n'.join(L)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
