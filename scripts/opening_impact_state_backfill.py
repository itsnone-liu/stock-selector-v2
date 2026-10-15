#!/usr/bin/env python3
"""OpeningImpactState shadow backfill (84 stocks, full sample period).
Pure stdlib. Append-only semantics: rerun regenerates backfill identically;
forward appends handled by the same script with --append in future runs."""
import gzip,json,math,statistics,sys
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
D=ROOT/'data/cd/daily_fullmarket'; AMT=ROOT/'data/r2/market_ext'; EPS=ROOT/'data/cd/l4_episodes.json.gz'
SAMPLE=ROOT/'output/research/csr/08_pilot_cases/phase_a/sample_selection.json'
M5=ROOT/'data/cl_radar/r4_opening/per_stock'
OUT=ROOT/'data/cl_radar/opening_impact_state/shadow_daily.jsonl.gz'
R4FREEZE='2026-10-14'
def lam5(bars,lo,hi,prev_close=None):
 """lambda over 5m bars with time in (lo,hi]; returns (lam, first_close)"""
 seg=[b for b in bars if lo<b[0]<=hi]
 if not seg:return None,None
 pc=prev_close if prev_close is not None else seg[0][4]
 if pc is None or pc<=0:return None,None
 n=d_=0.0
 for b in seg:
  dc=b[4]-pc
  of=0.0 if (abs(b[2]-b[3])<1e-9 and b[2]>0) else b[6]*(1 if dc>0 else -1 if dc<0 else 0)
  n+=of*dc;d_+=of*of;pc=b[4]
 return (n/d_ if d_>0 else None),seg[0][4]
def main():
 eps=json.load(gzip.open(EPS,'rt'))['episodes']
 epset=defaultdict(list)
 for e in eps:epset[e['stock']].append((e['start'],e['end']))
 x=json.load(open(SAMPLE));cs=[r['code'] for g in x['groups'].values() for r in g['chosen']]
 n_rows=0;OUT.parent.mkdir(parents=True,exist_ok=True)
 with gzip.open(OUT,'wt') as fo:
  for code in cs:
   six=code.split('.')[1]
   m5=json.load(gzip.open(M5/f'{six}.json.gz','rt'))
   mpos={d:i for i,d in enumerate(m5['dates'])}
   rec=json.load(gzip.open(D/f'{six}.json.gz','rt'));ext={r['date']:r for r in json.load(open(AMT/f'{six}.json'))['rows']}
   ds=rec['dates'];qfq=rec['qfq'];un=rec['unadj'];idx={d:i for i,d in enumerate(ds)}
   # daily lambda series (R3 definition) for lambda_next_5/20
   amt={d:(float(ext.get(d,{}).get('amount') or 0)) for d in ds}
   dlam={}
   for j in range(1,len(ds)-20):
    ln=ld=0.0
    for k in range(j+1,j+21):
     dc=float(qfq[k][2])-float(qfq[k-1][2])
     of=0.0 if (float(qfq[k][3])==float(qfq[k][4]) and float(qfq[k][3])>0) else amt[ds[k]]*(1 if dc>0 else -1 if dc<0 else 0)
     ln+=of*dc;ld+=of*of
    if ld>0:dlam[ds[j]]=ln/ld
   dlam5={}
   for j in range(1,len(ds)-5):
    ln=ld=0.0
    for k in range(j+1,j+6):
     dc=float(qfq[k][2])-float(qfq[k-1][2])
     of=0.0 if (float(qfq[k][3])==float(qfq[k][4]) and float(qfq[k][3])>0) else amt[ds[k]]*(1 if dc>0 else -1 if dc<0 else 0)
     ln+=of*dc;ld+=of*of
    if ld>0:dlam5[ds[j]]=ln/ld
   hist=[]  # (date, opening_amount)
   for j,d in enumerate(ds):
    if d not in mpos:
     continue
    bd=m5['bars'][mpos[d]]
    oam=sum(b[6] for b in bd if '0935'<=b[0]<='1000')
    lam_o,first_close=lam5(bd,'0930','1000',prev_close=float(un[j-1][2]) if j>0 else None)
    lam_post,_=lam5(bd,'1000','1500',prev_close=None)
    c1000=[b[4] for b in bd if b[0]=='1000']
    # path efficiency on opening window closes
    oc=[b[4] for b in bd if '0935'<=b[0]<='1000']
    pe=None
    if len(oc)>=2:
     net=abs(oc[-1]-oc[0]);path=sum(abs(oc[i+1]-oc[i]) for i in range(len(oc)-1))
     pe=net/path if path>0 else None
    if lam_o is None or lam_post is None or not c1000 or j<21:hist.append((d,oam));continue
    prev20=[h for h in hist if h[1]>0][-20:]
    if len(prev20)<20:hist.append((d,oam));continue
    base=statistics.fmean(h[1] for h in prev20)
    adv=[amt[ds[t]] for t in range(j-20,j)]
    if base<=0 or oam<=0 or any(a<=0 for a in adv):hist.append((d,oam));continue
    advv=statistics.fmean(adv)
    cp=float(un[j-1][2]);cq=float(qfq[j-1][2])
    if cp<=0 or cq<=0:hist.append((d,oam));continue
    sh=float(ext.get(ds[j-1],{}).get('outstanding_share') or 0)
    ep=1 if any(s<=d<=t for s,t in epset.get(six,())) else 0
    damt=amt[d]
    row={'code':code,'date':d,'in_model_period':d<=R4FREEZE,
     'opening_amount':oam,'expected_opening_amount':base,'expected_daily_amount_adv20':advv,
     'e_open':math.log(oam/base),'share_open_pit':oam/advv,
     'opening_return':c1000[0]/cp-1,'opening_path_efficiency':pe,
     'lambda_open':lam_o,'lambda_open_dim':lam_o*advv/cq,'episode_state':ep,
     'daily_amount':damt if damt>0 else None,'daily_effort':math.log(damt/advv) if damt>0 else None,
     'opening_share_actual':oam/damt if damt>0 else None,
     'post_open_lambda':lam_post,'post_open_lambda_dim':lam_post*advv/float(qfq[j][2]) if lam_post else None,
     'close_retention':float(un[j][2])/c1000[0]-1,
     'lambda_next_5':dlam5.get(d),'lambda_next_20':dlam.get(d)}
    fo.write(json.dumps(row,separators=(',',':'))+'\n');n_rows+=1
    hist.append((d,oam))
 print('rows written:',n_rows,'->',OUT)
if __name__=='__main__':main()
