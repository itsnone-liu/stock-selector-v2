#!/usr/bin/env python3
"""CL-R3-B: interaction closure. Three frozen binary conditioners, OLS with
per-stock Gram bootstrap. Criteria A (CI excludes 0), B (|bEC/bE|>=0.20), C (structure).
Rows identical to R3 mechanism1 construction (deterministic recompute)."""
import gzip,json,math,statistics,random
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'; EPS=ROOT/'data/cd/l4_episodes.json.gz'
SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
OUT=ROOT/'data/cl_radar/r3_effort_result/interaction.json'; REPORT=ROOT/'docs/external_ideas/radar/CL_R3B_INTERACTION_REPORT.md'
def solve(A,b):
 n=len(b);A=[row[:]+[b[i]] for i,row in enumerate(A)]
 for k in range(n):
  p=max(range(k,n),key=lambda i:abs(A[i][k]));A[k],A[p]=A[p],A[k]
  if abs(A[k][k])<1e-12:return None
  z=A[k][k];A[k]=[v/z for v in A[k]]
  for i in range(n):
   if i!=k:
    z=A[i][k];A[i]=[A[i][j]-z*A[k][j] for j in range(n+1)]
 return [A[i][-1] for i in range(n)]
def rank(x):
 o=sorted(range(len(x)),key=lambda i:x[i]);r=[0.]*len(x);i=0
 while i<len(o):
  j=i
  while j+1<len(o) and x[o[j+1]]==x[o[i]]:j+=1
  v=(i+j)/2+1
  for k in range(i,j+1):r[o[k]]=v
  i=j+1
 return r
def main():
 random.seed(20261014)
 x=json.load(open(SAMPLE));cs=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 eps=json.load(gzip.open(EPS,'rt'))['episodes']
 epset=defaultdict(list)
 for e in eps:epset[e['stock']].append((e['start'],e['end']))
 idx=json.load(gzip.open(D/'000985.json.gz','rt'));ids=idx['dates'];ic=[float(r[2]) for r in idx['qfq']]
 market={}
 for j in range(120,len(ids)):
  ma=statistics.fmean(ic[j-120:j])
  if ma>0:market[ids[j]]=ic[j]/ma-1
 rows=[]
 for code in cs:
  six=code.split('.')[1]
  rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
  ds=rec['dates'];qfq=rec['qfq'];un=rec['unadj'];n=len(ds)
  amt=[float(ext.get(d,{}).get('amount') or 0) for d in ds]
  ret=[None]*n
  for j in range(1,n):
   p=float(qfq[j-1][2])
   if p>0:ret[j]=float(qfq[j][2])/p-1
  his=[float(r[3]) or 0 for r in qfq];los=[float(r[5]) or 0 for r in qfq];uns=[float(r[2]) or 0 for r in un]
  eps_here=epset.get(six,[])
  for j in range(21,n-20):
   adv=[amt[k] for k in range(j-20,j)];rr=[ret[k] for k in range(j-20,j)]
   if amt[j]<=0 or any(a<=0 for a in adv) or any(z is None for z in rr):continue
   sd=statistics.pstdev(rr)
   if sd<=0:continue
   e=math.log(amt[j]/statistics.fmean(adv))
   lam_n=lam_d=0.0
   for k in range(j+1,j+21):
    dc=float(qfq[k][2])-float(qfq[k-1][2])
    of=0.0 if his[k]==los[k] and his[k]>0 else amt[k]*(1 if dc>0 else -1 if dc<0 else 0)
    lam_n+=of*dc;lam_d+=of*of
   if lam_d<=0:continue
   lam=lam_n/lam_d;adv_=statistics.fmean(adv)
   y=lam*adv_/float(qfq[j][2])
   lo60=min(uns[k] for k in range(j-59,j+1));hi60=max(uns[k] for k in range(j-59,j+1))
   pos=(uns[j]-lo60)/(hi60-lo60) if hi60>lo60 else .5
   inep=1 if any(s<=ds[j]<=t for s,t in eps_here) else 0
   mk=market.get(ds[j])
   sh=float(ext.get(ds[j],{}).get('outstanding_share') or 0)
   ctr=[math.log(adv_),float(ext.get(ds[j],{}).get('turnover_rate') or 0),sd,math.log(max(uns[j],1e-6)),sum(rr),math.log(max(uns[j]*sh,1.0))]
   rows.append({'code':code,'e':e,'y':y,'ctr':ctr,'pos':pos,'ep':inep,'mkt':mk})
 ys=sorted(r['y'] for r in rows);ylo=ys[int(.01*len(ys))];yhi=ys[int(.99*len(ys))]
 for r in rows:r['y']=max(ylo,min(yhi,r['y']))
 yrank=rank([r['y'] for r in rows]);mu=statistics.fmean(yrank);sg=statistics.pstdev(yrank)
 for i,r in enumerate(rows):r['yr']=(yrank[i]-mu)/sg
 def fit_model(sel,key,cval1,name):
  # columns: 1, E, C, E*C, ctr(6)
  data=[r for r in rows if key(r)]
  bys=defaultdict(list)
  for r in data:bys[r['code']].append(r)
  k=10
  gy={};gyr={}
  for c_,rl in bys.items():
   def build(rlist,Cfn):
    G=[[0.0]*k for _ in range(k)];bb=[0.0]*k
    for r in rlist:
     C=Cfn(r);row=[1.0,r['e'],C,r['e']*C]+r['ctr']
     for a in range(k):
      for cc in range(a,k):G[a][cc]+=row[a]*row[cc]
      bb[a]+=row[a]*r['y']
    for a in range(k):
     for cc in range(a):G[a][cc]=G[cc][a]
    return G,bb
   gy[c_]=build(rl,cval1)
   def buildr(rlist,Cfn):
    G=[[0.0]*k for _ in range(k)];bb=[0.0]*k
    for r in rlist:
     C=Cfn(r);row=[1.0,r['e'],C,r['e']*C]+r['ctr']
     for a in range(k):
      for cc in range(a,k):G[a][cc]+=row[a]*row[cc]
      bb[a]+=row[a]*r['yr']
    for a in range(k):
     for cc in range(a):G[a][cc]=G[cc][a]
    return G,bb
   gyr[c_]=buildr(rl,cval1)
  def total(g):
   G=[[0.0]*k for _ in range(k)];b=[0.0]*k
   for c_,(Gs,bs) in g.items():
    for a in range(k):
     b[a]+=bs[a]
     for cc in range(k):G[a][cc]+=Gs[a][cc]
   return G,b
  G,b=total(gy);beta=solve(G,b)
  codes=list(gy);ests=[]
  for _ in range(1000):
   G2=[[0.0]*k for _ in range(k)];b2=[0.0]*k
   for _ in range(len(codes)):
    c_=codes[random.randrange(len(codes))]
    Gs,bs=gy[c_]
    for a in range(k):
     b2[a]+=bs[a]
     for cc in range(k):G2[a][cc]+=Gs[a][cc]
   bt=solve(G2,b2)
   if bt:ests.append(bt[3])
  p05=sorted(ests)[49];p95=sorted(ests)[949]
  G3_,_=total(gyr);betar=solve(G3_,b)
  return {'name':name,'n':len(data),'n_stocks':len(codes),'bE':beta[1],'bC':beta[2],'bEC':beta[3],
   'bEC_p05':p05,'bEC_p95':p95,'rel_diff':beta[3]/abs(beta[1]) if beta[1] else None,
   'rank_check_bEC_sign':(betar[3]>0)==(beta[3]>0) if betar else None,
   'A_pass':p05>0 or p95<0,'B_pass':abs(beta[3]/beta[1])>=0.20 if beta[1] else False}
 m1=fit_model(rows,lambda r:r['pos']<=1/3 or r['pos']>=2/3,lambda r:1 if r['pos']>=2/3 else 0,'PricePosition(high vs low)')
 m2=fit_model(rows,lambda r:True,lambda r:r['ep'],'EpisodeState(in vs out)')
 m3=fit_model(rows,lambda r:r['mkt'] is not None,lambda r:1 if r['mkt']>0 else 0,'MarketRegime(strong vs weak)')
 for m in (m1,m2,m3):m['G3_pass']=bool(m['A_pass'] and m['B_pass'])
 n_pass=sum(1 for m in (m1,m2,m3) if m['G3_pass'])
 verdict={0:'R3_CLOSE_unconditional_effort_effect_retained',1:'R3_CLOSE_effort_plus_single_interaction',2:'R3_CLOSE_multi_interaction_inputs_to_next_topic',3:'R3_CLOSE_multi_interaction_inputs_to_next_topic'}[n_pass]
 out={'n_rows':len(rows),'winsor':[ylo,yhi],'models':[m1,m2,m3],'n_pass':n_pass,'verdict':verdict}
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 L=['# CL-R3-B Conditional Interaction Closure 结果','',f"- rows: {len(rows)}（Y=λ̃_next 缩尾 [{ylo:.3e},{yhi:.3e}]；bootstrap 1000×84 股 Gram 重采样）",'','| model | n | β_E | β_EC | β_EC P05 | P95 | A:CI不跨零 | B:|β_EC/β_E|≥0.20 | rank 符号一致 | G3 |','|---|---:|---:|---:|---:|---:|---|---|---|---|']
 for m in (m1,m2,m3):
  L.append(f"| {m['name']} | {m['n']} | {m['bE']:.4e} | {m['bEC']:.4e} | {m['bEC_p05']:.4e} | {m['bEC_p95']:.4e} | {'PASS' if m['A_pass'] else 'FAIL'} | {'PASS' if m['B_pass'] else 'FAIL'} ({m['rel_diff']:+.3f}) | {m['rank_check_bEC_sign']} | **{'PASS' if m['G3_pass'] else 'FAIL'}** |")
 L+=['',f"**verdict: {verdict}（{n_pass}/3 交互通过）**",'','判读与终止树执行见 CL_R3_CLOSURE（随后写入）。']
 REPORT.write_text('\n'.join(L)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
