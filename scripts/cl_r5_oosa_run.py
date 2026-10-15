#!/usr/bin/env python3
"""R5 OOS-A runner: F1-F4 on the frozen 180-stock sample, ZERO definition changes.
Requires: ingestion complete (data/cl_radar/r5_oos/per_stock + census merge done).
Verdicts vs frozen estimates: sign + CI + [0.5,2.0]x band."""
import gzip,json,math,statistics,random,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'; EPS=ROOT/'data/cd/l4_episodes.json.gz'
import os
SM=Path(os.environ['OOSA_SM']) if os.environ.get('OOSA_SM') else ROOT/'data/cl_radar/r5_oos/oosa_sample_frozen.json'
M5=Path(os.environ['OOSA_M5']) if os.environ.get('OOSA_M5') else ROOT/'data/cl_radar/r5_oos/per_stock'
CEN=Path(os.environ['OOSA_CEN']) if os.environ.get('OOSA_CEN') else ROOT/'data/cl_radar/r5_oos/ingestion_census.json'
OUT=Path(os.environ['OOSA_OUT']) if os.environ.get('OOSA_OUT') else ROOT/'data/cl_radar/r5_oos/oosa_results.json'
REPORT=Path(os.environ['OOSA_REP']) if os.environ.get('OOSA_REP') else ROOT/'docs/external_ideas/radar/CL_R5_OOSA_REPORT.md'
FRZ={'F1':-0.193,'F2':-0.524,'F3':-0.03544,'F4':+0.03102}
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
def rank(v):
 o=sorted(range(len(v)),key=lambda i:v[i]);r=[0.]*len(v);i=0
 while i<len(o):
  j=i
  while j+1<len(o) and v[o[j+1]]==v[o[i]]:j+=1
  vv=(i+j)/2+1
  for k2 in range(i,j+1):r[o[k2]]=vv
  i=j+1
 return r
def corr(a,b):
 a,b=rank(a),rank(b);ma=statistics.fmean(a);mb=statistics.fmean(b);da=sum((z-ma)**2 for z in a);db=sum((z-mb)**2 for z in b)
 return sum((u-ma)*(v-mb) for u,v in zip(a,b))/math.sqrt(da*db) if da and db else None
def partial(y,x,ctr):
 ry=rank(y);rx=rank(x);cols=[[1.]+list(c) for c in ctr];k=len(cols[0])
 A=[[sum(r[i]*r[j] for r in cols) for j in range(k)]for i in range(k)]
 sy=[sum(cols[t][i]*ry[t] for t in range(len(ry)))for i in range(k)];sx=[sum(cols[t][i]*rx[t] for t in range(len(rx)))for i in range(k)]
 cy=solve(A,sy);cx=solve(A,sx)
 ey=[ry[t]-sum(cols[t][i]*cy[i]for i in range(k))for t in range(len(ry))];ex=[rx[t]-sum(cols[t][i]*cx[i]for i in range(k))for t in range(len(rx))]
 ma=statistics.fmean(ex);mb=statistics.fmean(ey);da=sum((z-ma)**2 for z in ex);db=sum((z-mb)**2 for z in ey)
 return sum((u-ma)*(v-mb) for u,v in zip(ex,ey))/math.sqrt(da*db) if da and db else None
def fit_boot(rows,ykey,xkeys,nboot=1000,seed=20261015):
 random.seed(seed)
 bys=defaultdict(list)
 for r in rows:bys[r['code']].append(r)
 k=1+len(xkeys)
 def gram(rl):
  G=[[0.0]*k for _ in range(k)];b=[0.0]*k
  for r in rl:
   row=[1.0]+[r[x] for x in xkeys]
   for a in range(k):
    for c in range(a,k):G[a][c]+=row[a]*row[c]
    b[a]+=row[a]*r[ykey]
  for a in range(k):
   for c in range(a):G[a][c]=G[c][a]
  return G,b
 gy={c:gram(rl) for c,rl in bys.items()}
 T=[[sum(gy[c][0][a][cc] for c in gy) for cc in range(k)] for a in range(k)]
 tb=[sum(gy[c][1][a] for c in gy) for a in range(k)]
 beta=solve(T,tb)
 codes=list(gy);CIs={i:[] for i in range(k)}
 for _ in range(nboot):
  G=[[0.0]*k for _ in range(k)];b=[0.0]*k
  for _ in range(len(codes)):
   c=codes[random.randrange(len(codes))];Gs,bs=gy[c]
   for a in range(k):
    b[a]+=bs[a]
    for cc in range(k):G[a][cc]+=Gs[a][cc]
  bt=solve(G,b)
  if bt:
   for i in range(k):CIs[i].append(bt[i])
 out={'beta':beta,'n':len(rows),'n_stocks':len(codes)}
 for i,lbl in enumerate(['const']+xkeys):
  if CIs[i]:out[lbl]={'p05':sorted(CIs[i])[49],'p95':sorted(CIs[i])[949]}
 return out
def pct(v,q):
 v=sorted(v);i=min(len(v)-1,max(0,int(q*len(v))));return v[i]
def main():
 cen=json.load(open(CEN))
 if cen.get('g1_verdict')!='SUFFICIENT_SUPPORT':print('G1:',cen.get('g1_verdict'));sys.exit(2)
 cs=json.load(open(SM))['stocks']
 eps=json.load(gzip.open(EPS,'rt'))['episodes']
 epset=defaultdict(list)
 for e in eps:epset[e['stock']].append((e['start'],e['end']))
 drows=[];orows=[]
 for code in cs:
  six=code.split('.')[1]
  rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
  ds=rec['dates'];qfq=rec['qfq'];un=rec['unadj'];n=len(ds)
  amt=[float(ext.get(d,{}).get('amount') or 0) for d in ds]
  dret={}
  for j in range(1,n):
   p=float(qfq[j-1][2])
   if p>0:dret[ds[j]]=float(qfq[j][2])/p-1
  his=[float(r[3]) or 0 for r in qfq];los=[float(r[5]) or 0 for r in qfq]
  # daily rows (R3 construction) + opening rows (R4 construction)
  m5p=M5/f'{six}.json.gz'
  m5=json.load(gzip.open(m5p,'rt')) if m5p.exists() else {'dates':[],'bars':[]}
  mpos={d:i for i,d in enumerate(m5['dates'])}
  oam_hist=[]
  for j in range(21,n-20):
   adv=[amt[t] for t in range(j-20,j)]
   rr=[dret.get(ds[t]) for t in range(j-20,j)]
   if amt[j]<=0 or any(a<=0 for a in adv):continue
   rr=[z for z in rr if z is not None]
   if len(rr)<15:continue
   sd=statistics.pstdev(rr)
   if sd<=0:continue
   advv=statistics.fmean(adv);de=math.log(amt[j]/advv)
   sh=float(ext.get(ds[j-1],{}).get('outstanding_share') or 0);cu=float(un[j-1][2])
   if sh<=0 or cu<=0:continue
   ctr=[math.log(advv),float(ext.get(ds[j-1],{}).get('turnover_rate') or 0),sd,math.log(max(cu,1e-6)),sum(rr),math.log(max(cu*sh,1.0))]
   ln=ld=0.0
   for k2 in range(j+1,j+21):
    dc=float(qfq[k2][2])-float(qfq[k2-1][2])
    of=0.0 if(his[k2]==los[k2] and his[k2]>0) else amt[k2]*(1 if dc>0 else -1 if dc<0 else 0)
    ln+=of*dc;ld+=of*of
   if ld<=0:continue
   ep=1 if any(s<=ds[j]<=t for s,t in epset.get(six,())) else 0
   drows.append({'code':code,'date':ds[j],'de':de,'lam':ln/ld,'ctr':ctr,'ep':ep,'deox':de*ep,'advv':advv})
   # opening side
   d=ds[j]
   if d in mpos:
    bd=m5['bars'][mpos[d]]
    oam=sum(b[6] for b in bd if '0935'<=b[0]<='1000')
    prev=[h for h in oam_hist if h>0][-20:]
    if len(prev)==20 and oam>0 and prev:
     base=statistics.fmean(prev);c10=[b[4] for b in bd if b[0]=='1000']
     if base>0 and c10:
      pc=c10[0];n2=d2=0.0
      for b in bd:
       if b[0]<='1000':continue
       dc=b[4]-pc
       of=0.0 if(abs(b[2]-b[3])<1e-9 and b[2]>0) else b[6]*(1 if dc>0 else -1 if dc<0 else 0)
       n2+=of*dc;d2+=of*of;pc=b[4]
      if d2>0:
       lamt=(n2/d2)*advv/float(qfq[j][2])
       orows.append({'code':code,'date':d,'e_open':math.log(oam/base),'lamt':lamt,'de':de,'ep':ep,'eox':math.log(oam/base)*ep,'ctr':ctr})
    oam_hist.append(oam)
 ys=sorted(r['lam'] for r in drows)
 # F1: controlled rank partial + stock bootstrap of per-stock partials is heavy; use pooled partial + stock-mean corr bootstrap (R3 pattern)
 f1_pooled=partial([r['lam'] for r in drows],[r['de'] for r in drows],[r['ctr'] for r in drows])
 bys=defaultdict(list)
 for r in drows:bys[r['code']].append(r)
 codes=list(bys);random.seed(20261015);ests=[]
 for _ in range(1000):
  smp=[codes[random.randrange(len(codes))]for _ in codes]
  xx=[];yy=[]
  for c in smp:
   g=bys[c]
   xx.append(statistics.fmean(r['de'] for r in g));yy.append(statistics.fmean(r['lam'] for r in g))
  e=corr(xx,yy)
  if e is not None:ests.append(e)
 f1_boot_med=statistics.median(ests) if ests else None
 # F2: daily OLS interaction (R3-B model) A/B on |rel|>=0.20
 ys2=sorted(r['lam'] for r in drows);ylo=ys2[int(.01*len(ys2))];yhi=ys2[int(.99*len(ys2))]
 for r in drows:r['y']=max(ylo,min(yhi,r['lam']))
 for r in drows:
  for i,c in enumerate(r['ctr']):r[f'x{i+1}']=c
 # (columns materialized after first use guard)
 f2=fit_boot(drows,'y',['de','x1','x2','x3','x4','x5','x6','ep','deox'])
 bE_f2=f2['beta'][1];bEC=f2['beta'][9];rel=bEC/abs(bE_f2) if bE_f2 else None
 # F3/F4 opening (R4 model), winsor on lamt
 ys3=sorted(r['lamt'] for r in orows);lo3=ys3[int(.01*len(ys3))];hi3=ys3[int(.99*len(ys3))]
 for r in orows:
  r['y']=max(lo3,min(hi3,r['lamt']))
  for i,c in enumerate(r['ctr']):r[f'x{i+1}']=c
 CTR=[f'x{i}' for i in range(1,7)]
 f3=fit_boot(orows,'y',['e_open']+CTR)
 f4=fit_boot(orows,'y',['de','e_open']+CTR+['eox'])
 f3_b=f3['beta'][1];f4_b2=f4['beta'][2]
 def verdict(est,ci,frozen):
  if ci[0]>0 or ci[1]<0:
   sgn=1 if est>0 else -1;fsgn=1 if frozen>0 else -1
   if sgn!=fsgn:return 'FAIL'
   if 0.5*abs(frozen)<=abs(est)<=2.0*abs(frozen):return 'PASS'
   return 'PARTIAL'
  return 'FAIL'
 res={'F1':{'pooled_partial':f1_pooled,'boot_med':f1_boot_med,'frozen':FRZ['F1'],'verdict':verdict(f1_pooled,(pct(ests,.05),pct(ests,.95)),FRZ['F1']) if f1_pooled is not None and ests else 'FAIL',
  'note':'F1 verdict on controlled partial (R3 pattern: pooled partial sign + CI via stock-mean bootstrap)'},
 'F2':{'bE':bE_f2,'bEC':bEC,'rel':rel,'ci':[f2['deox']['p05'],f2['deox']['p95']] if f2.get('deox') else None,'frozen_rel':FRZ['F2'],
  'verdict':('PASS' if (f2['deox']['p05']>0 or f2['deox']['p95']<0) and abs(rel or 0)>=0.20 and rel<0 else ('PARTIAL' if (f2['deox']['p05']>0 or f2['deox']['p95']<0) and rel<0 else 'FAIL'))},
 'F3':{'bE':f3_b,'ci':[f3['e_open']['p05'],f3['e_open']['p95']],'frozen':FRZ['F3'],'verdict':verdict(f3_b,(f3['e_open']['p05'],f3['e_open']['p95']),FRZ['F3']) if f3.get('e_open') else 'FAIL'},
 'F4':{'b2':f4_b2,'ci':[f4['e_open']['p05'],f4['e_open']['p95']],'frozen':FRZ['F4'],'verdict':verdict(f4_b2,(f4['e_open']['p05'],f4['e_open']['p95']),FRZ['F4']) if f4.get('e_open') else 'FAIL'},
 'n_daily_rows':len(drows),'n_opening_rows':len(orows),'n_stocks':len(codes)}
 allp=all(res[k]['verdict']=='PASS' for k in ('F1','F2','F3','F4'))
 anyf=any(res[k]['verdict']=='FAIL' for k in ('F1','F2','F3','F4'))
 res['overall']='OOSA_VERIFIED_FORWARD_PENDING' if allp else ('MIXED_PARTIAL' if not anyf else 'FAILED_RECORD_HONESTLY')
 OUT.write_text(json.dumps(res,ensure_ascii=False,indent=2))
 L=['# CL-R5 OOS-A 报告（180 股 untouched，零定义改动）','',f"- daily rows {res['n_daily_rows']}；opening rows {res['n_opening_rows']}；股票 {res['n_stocks']}",'','| fact | 估计 | CI | 冻结值 | 判定 |','|---|---:|---|---:|---|']
 for k in ('F1','F2','F3','F4'):
  r=res[k];est=r.get('pooled_partial') or r.get('bEC') or r.get('bE') or r.get('b2');ci=r.get('ci')
  L.append(f"| {k} | {est if isinstance(est,float) else r.get('rel')} | {ci} | {r.get('frozen',r.get('frozen_rel'))} | **{r['verdict']}** |")
 L+=['',f"## 总裁决：**{res['overall']}**",'','OOS-A 无论结果：OpeningImpactState 保持 SHADOW；晋升讨论至少等 OOS-B 首个 60 日闭包（用户裁决）。']
 REPORT.write_text('\n'.join(L)+'\n',encoding='utf-8');print(json.dumps(res,ensure_ascii=False,indent=2) if not os.environ.get('OOSA_QUIET') else 'DRYRUN_OK daily=%d opening=%d stocks=%d'%(res['n_daily_rows'],res['n_opening_rows'],res['n_stocks']))
if __name__=='__main__':
 main()
 if os.environ.get('OOSA_QUIET'):print('DRYRUN_OK rows only: daily/results suppressed')

