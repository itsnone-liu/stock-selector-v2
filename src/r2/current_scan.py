#!/usr/bin/env python3
"""R2-5 v0: current per-stock accumulation judgment scan.
Judgments ARE output with evidence matrices regardless of validation status
(charter: no stopping for insufficient proof); every card carries
validation_status=UNVALIDATED_V1 + honest contradict/missing rows.
"""
from __future__ import annotations
import gzip,json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from src.capital_inference.features import snapshot as fsnap
from src.capital_inference.state_engine import infer
LVNAME={2:'STRONG_SUPPORT',1:'SUPPORT',0:'NEUTRAL',-1:'CONTRADICT',-2:'STRONG_CONTRADICT',0.0:'MISSING'}
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
  cards.append({'stock':code,'state':st['state'],'confidence':st['confidence'],'validation_status':'UNVALIDATED_V1',
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
