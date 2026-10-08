#!/usr/bin/env python3
"""R2-5 v0: current per-stock accumulation judgment scan.
Judgments ARE output with evidence matrices regardless of validation status
(charter: no stopping for insufficient proof); every card carries
validation_status=UNVALIDATED_V1 + honest contradict/missing rows.
"""
from __future__ import annotations
import statistics
import gzip,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.capital_inference.features import snapshot as fsnap
from src.capital_inference.state_engine import infer
LVNAME={2:'STRONG_SUPPORT',1:'SUPPORT',0:'NEUTRAL',-1:'CONTRADICT',-2:'STRONG_CONTRADICT',0.0:'MISSING'}

def capital_support(code):
 from support_gate import load,cost_band
 from support_gate import load
 st=load(code)
 if not st: return None
 ds,cl,hi,lo,vol=st; n=len(cl)
 if n<520: return None
 z=cost_band(cl,hi,lo,vol,n-1)
 if not z: return None
 zl,zh=z; zm=(zl+zh)/2; px=cl[-1]
 recent=cl[-10:]
 broken=any(all(cl[k]<zl*0.95 for k in range(b,min(b+5,n))) for b in range(max(0,n-60),n-4))
 lo10=min(lo[-10:])
 if broken: state='BROKEN'
 elif px>zh: state='ABOVE_SUPPORT'
 elif px>=zl: state='IN_SUPPORT'
 elif lo10<zl: state='UNDERCUT_TEST'
 else: state='BROKEN'
 return {'cost_band_low':round(zl,2),'cost_band_mid':round(zm,2),'cost_band_high':round(zh,2),
  'price':round(px,2),'price_to_cost_mid':round(px/zm-1,4),
  'distance_to_band':round(px/zh-1,4) if px>zh else (round(px/zl-1,4) if px<zl else 0.0),
  'support_state':state,'support_quality':'VALID' if not broken else 'INVALID'}


_AX=None
def _axes():
 global _AX
 if _AX is None:
  import gzip as _gz
  l1=json.load(_gz.open(ROOT/'data/cd/sector_axes/l1_market_axes.json.gz','rt'))['rows']
  md=[r['date'].replace('-','') for r in l1]; part={r['date'].replace('-',''):r.get('part') for r in l1}
  rows=json.load(_gz.open(ROOT/'data/cd/sector_axes/l2_four_axes.json.gz','rt'))['rows']
  byl2={}
  for r in rows:
   if 'sector_eq' in r: byl2.setdefault(r['l2'],[]).append(r)
  for v in byl2.values(): v.sort(key=lambda r:r['date'])
  _AX=(md,part,l1,byl2)
 return _AX
def decision_tiers(code,cs):
 from support_gate import load
 md,part,l1,byl2=_axes()
 md=[r['date'].replace('-','') for r in l1]; part={r['date'].replace('-',''):r.get('part') for r in l1}
 from support_gate import load
 st=load(code)
 if not st: return None
 ds,cl=st[0],st[1]
 d=ds[-1].replace('-','')
 i=md.index(d) if d in md else len(md)-1
 pre=[part.get(x) for x in md[max(0,i-20):i] if part.get(x) is not None]
 t1=bool(pre) and part.get(d) is not None and part[d]>statistics.mean(pre)
 l2={m['code']:m['L2'] for m in json.loads((ROOT/'data/cd/sector_seeds/csrc_v1.json').read_text())['members']}.get(code)
 t2=None;t3=None
 if l2:
  v=byl2.get(l2,[])
  j=[k for k,r in enumerate(v) if r['date'].replace('-','')==d]
  if j and j[0]>=20:
   cs20=1;cm=1
   for r in v[j[0]-19:j[0]+1]: cs20*=1+(r['sector_eq'] or 0); cm*=1+(r['mkt_eq'] or 0)
   t2=cs20>cm
   s20=cl[-1]/cl[-21]-1 if len(cl)>21 else None
   t3=(s20 is not None and s20>cs20-1)
 reg=None
 for r in l1:
  if r['date'].replace('-','')==d: reg=r['regime']; break
 if reg is None: reg=l1[-1]['regime']
 bear=reg.startswith(('R_DEPRESSED','R_RISK_OFF')) if reg else False
 ss=cs['support_state'] if cs else 'NA'
 if ss=='BROKEN': tier='EXIT'
 elif ss in('IN_SUPPORT','UNDERCUT_TEST') and t3: tier='CONFIRM_CANDIDATE'
 elif ss in('IN_SUPPORT','UNDERCUT_TEST') and t2 and not bear: tier='BUILD'
 elif ss=='ABOVE_SUPPORT' and t2: tier='WATCH'
 else: tier='NO_BUILD'
 return {'market_tier':t1,'sector_tier':t2,'stock_rs_tier':t3,'regime':reg,'decision_tier':tier}

def main():
 margin={}
 mf=ROOT/'data/r2/margin/ratio_pa_20260930.json'
 if mf.exists():
  margin={r['code']:r for r in json.loads(mf.read_text())['rows']}
 inst={}
 for f in (ROOT/'data/r2/institutional').glob('*.json'):
  q=json.loads(f.read_text())['quarters']
  if q: inst[f.stem]=q[sorted(q)[-1]]
 last={}
 with open(ROOT/'data/r2/panel_monthly.jsonl') as f:
  for line in f:
   r=json.loads(line); last[r['stock']]=r
 D=ROOT/'data/cd/daily_fullmarket'; cards=[]
 for p in sorted(D.glob('*.json.gz')):
  code=p.name[:-8]; row=last.get(code)
  if not row or row['state'] not in ('ACCUMULATION_MATURE','MARKUP_READY','ACCUMULATION'): continue
  try: rec=json.load(gzip.open(p,'rt'))
  except Exception: continue
  ds=rec['dates']
  if len(ds)<260: continue
  cl=[float(x[2]) for x in rec['qfq']]; hi=[float(x[3]) for x in rec['qfq']]; lo=[float(x[4]) for x in rec['qfq']]; vol=[float(x[5]) for x in rec['unadj']]
  f_=fsnap(cl,hi,lo,vol,None,len(ds)-1)
  if f_ is None: continue
  st=infer(f_); c=cl[-1]
  mg=margin.get(code); iq=inst.get(code)
  fund_ratio=(iq['by_type'].get('FUND',{}).get('ratio',0)+iq['by_type'].get('INSURANCE',{}).get('ratio',0)) if iq else None
  cs=capital_support(code)
  dt=decision_tiers(code,cs) if cs else None
  #dup-removed
  cards.append({'stock':code,'state':st['state'],'confidence':st['confidence'],'validation_status':'UNVALIDATED_V1',
   **({'capital_support':cs} if cs else {}),
   **({'decision':dt} if dt else {}),
   'close':c,'cost_band':[f_['p25'],f_['p50'],f_['p75']],'dist_to_cost':round(c/f_['p50']-1,4) if f_['p50'] else None,
   'evidence':{'E1_price':st['evidence_family_scores']['E1_price'],'E2_participation':st['evidence_family_scores']['E2_participation'],'E3_chip':st['evidence_family_scores']['E3_chip'],'E4_ownership':st['evidence_family_scores'].get('E4_ownership','MISSING'),'E5_margin':(1 if (mg and mg.get('rz_ratio') is not None and 0<mg['rz_ratio']<0.15) else 0) if mg else 'MISSING','E6_context':'MISSING'},
   'chip_locking':f_['chip_locking'],'floating_supply':f_['floating_supply'],'band_width':f_['band_width'],
   'holders_chg_pct':row.get('holders_chg_pct'),'margin_ratio':(mg or {}).get('rz_ratio'),'fund_ins_ratio':fund_ratio,
   'contradictions':[k for k,v in st['evidence_family_scores'].items() if isinstance(v,int) and v<0]+(['价格已高于成本带75%线'] if f_['p75'] and c>f_['p75']*1.05 else [])+(['距成本过远(>30%)'] if f_['p50'] and c/f_['p50']>1.3 else [])+(['浮筹压力HIGH'] if f_['floating_supply']=='HIGH' else []),
   'missing':[k for k,v in st['evidence_family_scores'].items() if v=='MISSING']})
 cards.sort(key=lambda x:(x['state']!='ACCUMULATION_MATURE',-(x['confidence'])))
 out=ROOT/'data/r2/current_scan_v0.json'; out.write_text(json.dumps({'generated':'2026-10-05','asof_ym':max(r['ym'] for r in last.values()),'n_judged':len(cards),'cards':cards},ensure_ascii=False,indent=1))
 top=[x for x in cards if x['state']=='ACCUMULATION_MATURE'][:15] or cards[:15]
 md=['# R2-5 当前吸筹判断扫描 v0（'+max(r['ym'] for r in last.values())+'）','','> validation_status=UNVALIDATED_V1：历史验证(E1-E4月度)未发现吸筹签名，以下为章程允许的低置信概率判断，非已验证信号。','','| 股票 | 状态 | 置信 | 成本带(P25/50/75) | 距成本 | 锁定 | 户数变动 | 融资比例 | 反证 |','|---|---|---|---|---|---|---|---|---|']
 for x in top:
  cb='/'.join(str(v) for v in x['cost_band'])
  md.append(f"| {x['stock']} | {x['state']} | {x['confidence']} | {cb} | {x['dist_to_cost']} | {x['chip_locking']} | {x['holders_chg_pct']} | {x['margin_ratio']} | {';'.join(map(str,x['contradictions'])) or '无'} |")
 md.append('')
 md.append(f"共 {len(cards)} 只进入判断池（ACCUMULATION/MATURE/READY）。完整证据矩阵: data/r2/current_scan_v0.json")
 (ROOT/'docs/r2/R2-5_SCAN_v0.md').write_text('\n'.join(md)+'\n')
 print(json.dumps({'judged':len(cards),'mature':sum(1 for x in cards if x['state']=='ACCUMULATION_MATURE'),'top15':[x['stock'] for x in top[:5]]},ensure_ascii=False))
if __name__=='__main__':main()
