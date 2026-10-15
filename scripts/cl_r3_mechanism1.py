#!/usr/bin/env python3
"""CL-R3 first mechanism pass: State -> lambda_next + conditional structure.
Frozen quadrants from census (effort_med=-0.14689, result_med=0.60454).
Outcomes: lambda_next (B1-style, one-price days OF=0), vol_ratio, maxDD20.
No outcome switching; no absorption/distribution naming before gates."""
import gzip,json,math,statistics,random
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'; EPS=ROOT/'data/cd/l4_episodes.json.gz'
SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
OUT=ROOT/'data/cl_radar/r3_effort_result/mechanism1.json'; REPORT=ROOT/'docs/external_ideas/radar/CL_R3_EFFORT_RESULT_MECHANISM1.md'
E_MED=-0.14689450827608783;R_MED=0.6045422731351255
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
 # rank-based residual partial correlation via normal equations on ranks
 ry=rank(y);rx=rank(x);cols=[[1.]+list(c) for c in controls];k=len(cols[0])
 A=[[sum(r[i]*r[j] for r in cols) for j in range(k)]for i in range(k)]
 sy=[sum(cols[t][i]*ry[t] for t in range(len(ry)))for i in range(k)];sx=[sum(cols[t][i]*rx[t] for t in range(len(rx)))for i in range(k)]
 def solve(M,b):
  n=len(b);M=[row[:]+[b[i]]for i,row in enumerate(M)]
  for kk in range(n):
   p=max(range(kk,n),key=lambda i:abs(M[i][kk]));M[kk],M[p]=M[p],M[kk]
   if abs(M[kk][kk])<1e-12:return[0.]*n
   z=M[kk][kk];M[kk]=[v/z for v in M[kk]]
   for i in range(n):
    if i!=kk:
     z=M[i][kk];M[i]=[M[i][j]-z*M[kk][j]for j in range(n+1)]
  return[M[i][-1]for i in range(n)]
 cy=solve(A,sy);cx=solve(A,sx)
 ey=[ry[t]-sum(cols[t][i]*cy[i]for i in range(k))for t in range(len(ry))];ex=[rx[t]-sum(cols[t][i]*cx[i]for i in range(k))for t in range(len(rx))]
 ma=statistics.fmean(ex);mb=statistics.fmean(ey);da=sum((v-ma)**2 for v in ex);db=sum((v-mb)**2 for v in ey)
 return sum((u-ma)*(v-mb) for u,v in zip(ex,ey))/math.sqrt(da*db) if da and db else None
def main():
 random.seed(20261014)
 x=json.load(open(SAMPLE));cs=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 eps=json.load(gzip.open(EPS,'rt'))['episodes']
 ep_days=defaultdict(dict)
 for e in eps:
  for d in range(0,1):pass
 idx=json.load(gzip.open(D/'000985.json.gz','rt'));ids=idx['dates'];ic=[float(r[2]) for r in idx['qfq']];ipos={d:i for i,d in enumerate(ids)}
 market={}
 for j in range(120,len(ids)):
  ma=statistics.fmean(ic[j-120:j])
  if ma>0:market[ids[j]]=ic[j]/ma-1
 epset=defaultdict(set)
 for e in eps:
  s,t=e['start'],e['end']
  for d in range(0,1):pass
  epset[e['stock']].add((s,t))
 def in_episode(six,d):
  for s,t in epset.get(six,()):
   if s<=d<=t:return True
  return False
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
  los=[float(r[5]) or 0 for r in qfq];his=[float(r[3]) or 0 for r in qfq];cls=[float(r[2]) or 0 for r in qfq];uns=[float(r[2]) or 0 for r in un]
  for j in range(21,n-20):
   adv=[amt[k] for k in range(j-20,j)]
   rr=[ret[k] for k in range(j-20,j)]
   if amt[j]<=0 or any(a<=0 for a in adv) or any(z is None for z in rr):continue
   sd=statistics.pstdev(rr)
   if sd<=0:continue
   e=math.log(amt[j]/statistics.fmean(adv));r_=abs(ret[j])/sd
   q='EH_RH' if e>E_MED and r_>R_MED else 'EH_RL' if e>E_MED else 'EL_RH' if r_>R_MED else 'EL_RL'
   # forward outcomes T+1..T+20 (full window only)
   lam_num=lam_den=0.0;frets=[]
   for k2 in range(j+1,j+21):
     dc=float(qfq[k2][2])-float(qfq[k2-1][2])
     of=0.0 if his[k2]==los[k2] and his[k2]>0 else amt[k2]*(1 if dc>0 else -1 if dc<0 else 0)
     lam_num+=of*dc;lam_den+=of*of
     p=float(qfq[k2-1][2]);rets2=float(qfq[k2][2])/p-1 if p>0 else 0.0;frets.append(rets2)
   lam=lam_num/lam_den if lam_den>0 else None
   vr=statistics.pstdev(frets)/sd
   peak=-1e18;mdd=0.0
   for k2 in range(j+1,j+21):
    c2=float(qfq[k2][2]);peak=max(peak,c2);mdd=max(mdd,(peak-c2)/peak if peak>0 else 0)
   lo60=min(uns[k2] for k2 in range(j-59,j+1));hi60=max(uns[k2] for k2 in range(j-59,j+1))
   pos=(uns[j]-lo60)/(hi60-lo60) if hi60>lo60 else .5
   sh=float(ext.get(ds[j],{}).get('outstanding_share') or 0)
   ctr=[math.log(statistics.fmean(adv)),float(ext.get(ds[j],{}).get('turnover_rate') or 0),sd,math.log(max(uns[j],1e-6)),sum(rr),math.log(max(uns[j]*sh,1.0))]
   rows.append({'code':code,'date':ds[j],'q':q,'e':e,'r':r_,'sgn':1 if ret[j]>0 else -1,'lam':lam,'vr':vr,'mdd':mdd,'pos':pos,'ep':1 if in_episode(six,ds[j]) else 0,'mkt':market.get(ds[j]),'ctr':ctr})
 # ---- G2: state -> lambda_next
 lr=[r for r in rows if r['lam'] is not None]
 quads=['EH_RH','EH_RL','EL_RH','EL_RL']
 med_by={qq:statistics.median(r['lam'] for r in lr if r['q']==qq) for qq in quads}
 n_by={qq:sum(1 for r in lr if r['q']==qq) for qq in quads}
 # continuous raw/controlled
 xs=[r['e'] for r in lr];xr=[r['r'] for r in lr];ys=[r['lam'] for r in lr]
 e_rho=corr(xs,ys);e_part=partial(ys,xs,[r['ctr'] for r in lr])
 r_rho=corr(xr,ys);r_part=partial(ys,xr,[r['ctr'] for r in lr])
 # contrast EH_RL vs EL_RL (same low result, effort differs) stock bootstrap
 bys=defaultdict(lambda:{'a':[],'b':[]})
 for r in lr:
  if r['q']=='EH_RL':bys[r['code']]['a'].append(r['lam'])
  elif r['q']=='EL_RL':bys[r['code']]['b'].append(r['lam'])
 st=[(statistics.fmean(v['a']),statistics.fmean(v['b']))for v in bys.values() if v['a'] and v['b']]
 diffs=[a-b for a,b in st];ests=[]
 for _ in range(1000):
  smp=[st[random.randrange(len(st))]for _ in st];ests.append(statistics.median([a-b for a,b in smp]))
 boot={'n_stocks':len(st),'median_diff_EHRL_minus_ELRL':statistics.median(diffs),'p05':sorted(ests)[49],'p95':sorted(ests)[949]}
 # secondary outcomes by quadrant
 sec={qq:{'vr':statistics.median(r['vr'] for r in rows if r['q']==qq),'mdd':statistics.median(r['mdd'] for r in rows if r['q']==qq)}for qq in quads}
 # ---- G3: conditional structure (lambda_next by quadrant x conditioner)
 g3={}
 for name,key,fn in [('price_pos_tercile','pos',lambda v:'low' if v<=1/3 else ('mid' if v<=2/3 else 'high')),('episode','ep',lambda v:'in' if v==1 else 'out'),('market','mkt',lambda v:'weak' if v is None or v<=0 else 'strong')]:
  cells={}
  for qq in quads:
   for lev in ('low','mid','high') if name=='price_pos_tercile' else (('in','out') if name=='episode' else ('weak','strong')):
    vals=[r['lam'] for r in lr if r['q']==qq and fn(r[key])==lev]
    if len(vals)>=50:cells[f'{qq}|{lev}']={'n':len(vals),'med':statistics.median(vals)}
  g3[name]=cells
 out={'n_rows':len(rows),'n_with_lambda':len(lr),'quadrant_n':n_by,'lambda_median_by_quadrant':med_by,
 'continuous':{'effort_vs_lambda':{'raw':e_rho,'controlled':e_part},'result_vs_lambda':{'raw':r_rho,'controlled':r_part}},
 'contrast_EHRL_vs_ELRL_bootstrap':boot,'secondary_by_quadrant':sec,'g3_conditional':g3}
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 L=['# CL-R3 Effort-Result 首轮机制结果','','预注册冻结象限（census 中位数分割）。主结果 λ_next（B1 式，一字板 OF=0）。未命名任何象限。','',f"- rows: {len(rows)}；λ_next 有效 {len(lr)}",'', '## λ_next 象限中位（G2）','','| quadrant | n | λ_next 中位 |','|---|---:|---:|']
 for qq in quads:L.append(f"| {qq} | {n_by[qq]} | {med_by[qq]:.6f} |")
 L+=['',f"- 连续 Effort×λ_next：raw {e_rho:.4f} / 控制 {e_part:.4f}；Result×λ_next：raw {r_rho:.4f} / 控制 {r_part:.4f}",f"- 对比 EH_RL−EL_RL（同低结果、努力不同）：股票 bootstrap 中位差 {boot['median_diff_EHRL_minus_ELRL']:.6f}，P05 {boot['p05']:.6f}，P95 {boot['p95']:.6f}（{boot['n_stocks']} 股）",'', '## 次结果（象限中位）','','| quadrant | vol_ratio | maxDD20 |','|---|---:|---:|']
 for qq in quads:L.append(f"| {qq} | {sec[qq]['vr']:.4f} | {sec[qq]['mdd']:.4f} |")
 L+=['', '## 条件结构（G3，λ_next 中位）','']
 for name,cells in g3.items():
  L.append('### '+name);L+=['','| cell | n | λ_next 中位 |','|---|---:|---:|']
  for k2,v in cells.items():L.append(f"| {k2} | {v['n']} | {v['med']:.6f} |")
  L.append('')
 L+=['## 判读原则','', '- G2：连续与对比检验须在控制+bootstrap 下方向稳定；','- G3：同一象限在不同条件层的 λ_next 排序是否分化；','- Gate 未过前，EH_RL/EL_RH 等仅为构造标签，无资金语义。']
 REPORT.write_text('\n'.join(L)+'\n',encoding='utf-8');print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
