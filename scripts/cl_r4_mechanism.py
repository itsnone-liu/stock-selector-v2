#!/usr/bin/env python3
"""CL-R4 mechanism: G2 opening replication, G3 episode interaction (A/B/C),
G4 incremental gate vs DailyEffort. Requires ingestion census (per_stock 5m).
Run AFTER cl_r4_ingest_5m.py completes. Pure stdlib (main env)."""
import gzip,json,math,statistics,random
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'; EPS=ROOT/'data/cd/l4_episodes.json.gz'
SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
M5=ROOT/'data/cl_radar/r4_opening/per_stock'; CEN=ROOT/'data/cl_radar/r4_opening/ingestion_census.json'
OUT=ROOT/'data/cl_radar/r4_opening/mechanism.json'; REPORT=ROOT/'docs/external_ideas/radar/CL_R4_MECHANISM_REPORT.md'
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
def fit_boot(rows,ykey,xkeys,nboot=1000,seed=20261014):
 """OLS with columns [1]+xkeys on rows; stock-cluster Gram bootstrap CIs for each coef index."""
 random.seed(seed)
 bys=defaultdict(list)
 for r in rows:bys[r['code']].append(r)
 k=1+len(xkeys)
 def gram(rlist):
  G=[[0.0]*k for _ in range(k)];b=[0.0]*k
  for r in rlist:
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
def main():
 census=json.load(open(CEN))
 if census['g1_verdict']!='SUFFICIENT_SUPPORT':
  print('G1 not passed:',census['g1_verdict']);return
 eps=json.load(gzip.open(EPS,'rt'))['episodes']
 epset=defaultdict(list)
 for e in eps:epset[e['stock']].append((e['start'],e['end']))
 x=json.load(open(SAMPLE));cs=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 rows=[]
 for code in cs:
  six=code.split('.')[1]
  m5=json.load(gzip.open(M5/f'{six}.json.gz','rt'))
  mdates=m5['dates'];mbars=m5['bars'];mpos={d:i for i,d in enumerate(mdates)}
  rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
  ds=rec['dates'];qfq=rec['qfq'];idx={d:i for i,d in enumerate(ds)}
  dret={}
  for j in range(1,len(ds)):
   p=float(qfq[j-1][2])
   if p>0:dret[ds[j]]=float(qfq[j][2])/p-1
  oamts=[]  # opening amounts on supported days, in daily-file order for baseline
  supp={}   # date -> (oamt, c1000, lam_raw) computed lazily below
  for k,d in enumerate(mdates):
   bd=mbars[k]
   oamt=sum(b[6] for b in bd if b[0] in ('0935','0940','0945','0950','0955','1000'))
   c1000=[b[4] for b in bd if b[0]=='1000']
   # lambda 10:00 -> close on 5m closes
   post=[b for b in bd if b[0]>'1000']
   lam_n=lam_d=0.0
   pc=c1000[0] if c1000 else (post[0][5] if post else None)
   if pc is None or pc<=0:continue
   for b in post:
    dc=b[4]-pc
    of=0.0 if abs(b[2]-b[3])<1e-9 and b[2]>0 else b[6]*(1 if dc>0 else -1 if dc<0 else 0)
    lam_n+=of*dc;lam_d+=of*of;pc=b[4]
   lam=lam_n/lam_d if lam_d>0 else None
   supp[d]=(oamt,c1000[0] if c1000 else None,lam)
  # iterate daily dates for baseline context
  hist=[]
  for j,d in enumerate(ds):
   if d in supp and supp[d][1] and supp[d][2] is not None:hist.append((d,supp[d]))
   if j<21 or d not in supp:continue
   oamt,c10,lam=supp[d]
   prev=[h for h in hist[:-1]][-20:]
   if len(prev)<20:continue
   base=statistics.fmean(h[1][0] for h in prev)
   if base<=0 or oamt<=0:continue
   e_open=math.log(oamt/base)
   adv=[float(ext.get(ds[t],{}).get('amount') or 0) for t in range(j-20,j)]
   if any(a<=0 for a in adv):continue
   advv=statistics.fmean(adv)
   rr=[z for z in (dret.get(ds[t2]) for t2 in range(j-20,j)) if z is not None]
   if len(rr)<15:continue
   sd=statistics.pstdev(rr)
   if sd<=0:continue
   lamt=lam*advv/float(qfq[j][2]) if lam is not None else None
   amtT=float(ext.get(d,{}).get('amount') or 0)
   if amtT<=0:continue
   de=math.log(amtT/advv)
   sh_prev=float(ext.get(ds[j-1],{}).get('outstanding_share') or 0)
   cp=float(qfq[j-1][2])
   if sh_prev<=0 or cp<=0:continue
   ctr=[math.log(advv),float(ext.get(ds[j-1],{}).get('turnover_rate') or 0),sd,math.log(max(cp,1e-6)),sum(rr),math.log(max(cp*sh_prev,1.0))]
   ep=1 if any(s<=d<=t for s,t in epset.get(six,())) else 0
   rows.append({'code':code,'date':d,'e_open':e_open,'lamt':lamt,'de':de,'ep':ep,'ctr':ctr})
 nr=[r for r in rows if r['lamt'] is not None]
 ys=sorted(r['lamt'] for r in nr);ylo=ys[int(.01*len(ys))];yhi=ys[int(.99*len(ys))]
 for r in nr:r['y']=max(ylo,min(yhi,r['lamt']))
 for r in rows:r['eox']=r['e_open']*r['ep']
 # materialize ctr columns
 for r in nr:
  for i,c in enumerate(r['ctr']):r[f'x{i+1}']=c
 CTR=[f'x{i+1}' for i in range(6)]
 g2=fit_boot(nr,'y',['e_open']+CTR)
 g3=fit_boot(nr,'y',['e_open']+CTR+['ep','eox'])
 g4=fit_boot(nr,'y',['de','e_open']+CTR+['eox'])
 # correlations
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
 out={'n_rows':len(rows),'n_with_outcome':len(nr),'winsor':[ylo,yhi],
 'corr_eopen_dailyeffort':corr([r['e_open'] for r in nr],[r['de'] for r in nr]),
 'episode_share':sum(1 for r in nr if r['ep']==1)/len(nr),
 'G2':g2,'G3':g3,'G4':g4}
 def ci_ok(res,lbl):return res[lbl]['p05']>0 or res[lbl]['p95']<0
 bE=g2['beta'][1]
 g2_pass=bool(bE<0 and ci_ok(g2,'e_open'))
 bEC=g3['beta'][9];rel=bEC/abs(bE) if bE else None
 g3_pass=bool(ci_ok(g3,'eox') and abs(rel or 0)>=0.20)
 b1=g4['beta'][1];b2=g4['beta'][2];b4=g4['beta'][9]
 g4_pass=bool(ci_ok(g4,'e_open'))
 g4_b4_pass=bool(ci_ok(g4,'eox'))
 out['verdicts']={'G2_pass':g2_pass,'G2_bE':bE,'G2_CI':[g2['e_open']['p05'],g2['e_open']['p95']],
 'G3_pass':g3_pass,'G3_bEC':bEC,'G3_rel':rel,'G3_CI':[g3['eox']['p05'],g3['eox']['p95']],
 'G4_pass':g4_pass,'G4_b1_daily':b1,'G4_b2_opening':b2,'G4_CI':[g4['e_open']['p05'],g4['e_open']['p95']],'G4_b4_interact':b4,'G4_b4_CI':[g4['eox']['p05'],g4['eox']['p95']],'G4_b4_stable':g4_b4_pass,
 'G3_structure_note':'beta_E outside episode = %.4e, inside = %.4e'%(bE,bE+bEC)}
 if not g2_pass:verdict='R4_CLOSE_G2_FAIL'
 elif g2_pass and not g3_pass and not g4_pass:verdict='R4_CLOSE_no_integration_opening_is_early_daily_effort'
 elif g2_pass and g3_pass and not g4_pass:verdict='R4_CLOSE_no_integration_opening_is_early_daily_effort(G3 passed: episode-amplified opening recorded)'
 elif g4_pass and not g3_pass:verdict='R4_PASS_G2_G4_create_OpeningImpactState(no episode amplification)'
 else:verdict='R4_PASS_G2_G3_G4_OpeningImpactState_plus_EpisodeAmplified'
 out['final_verdict']=verdict
 OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(out,ensure_ascii=False,indent=2))
 v=out['verdicts']
 L=['# CL-R4 Opening Mechanism 结果（G2/G3/G4）','',f"- rows: {len(rows)}，outcome 有效 {len(nr)}；episode 占比 {out['episode_share']:.3f}；corr(E_open, DailyEffort)={out['corr_eopen_dailyeffort']:.3f}",f"- Y=λ̃_{{10:00→close}} 缩尾 [{ylo:.3e},{yhi:.3e}]；控制 PIT 至 10:00（ADV20/换手T-1/σ20/log close T-1/ret20/log 市值T-1）",'',f"## G2 复现：β_E = {bE:.4e}，CI [{v['G2_CI'][0]:.4e},{v['G2_CI'][1]:.4e}] → **{'PASS' if g2_pass else 'FAIL'}**（要求 β_E<0 且不跨零）",f"## G3 episode 交互：β_EC = {bEC:.4e}，CI [{v['G3_CI'][0]:.4e},{v['G3_CI'][1]:.4e}]，rel = {rel:+.3f} → **{'PASS' if g3_pass else 'FAIL'}**（A∧B）",f"## G4 增量门：β₂(OpeningEffort|DailyEffort) = {b2:.4e}，CI [{v['G4_CI'][0]:.4e},{v['G4_CI'][1]:.4e}] → **{'PASS' if g4_pass else 'FAIL'}**；β₄(交互) = {b4:.4e}（stable={g4_b4_pass}）",'',f"## 终裁：**{verdict}**",'','判读、结构（判据 C）与停止树执行见对话裁决与后续 closure 文档。']
 REPORT.write_text('\n'.join(L)+'\n',encoding='utf-8');print(json.dumps(out['verdicts'],ensure_ascii=False,indent=2));print('VERDICT:',verdict)
if __name__=='__main__':main()
