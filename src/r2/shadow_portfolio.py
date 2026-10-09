#!/usr/bin/env python3
"""Shadow Portfolio (prospective validation, frozen policy): 每日封存，不可重算。
读 data/r2/scans/current_scan_<day>.json → CONFIRM/BUILD/RISK_HOLD 清单 + P3 目标仓位 + 当日封存哈希。
用法（每晚 F 之后）：shadow_portfolio.py --day YYYY-MM-DD"""
from __future__ import annotations
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SCANS=ROOT/'data/r2/scans'; OUT=ROOT/'data/r2/shadow'
def p3_target(tier,hl,reg):
 if tier=='EXIT': return 0.0
 if tier=='CONFIRM_CANDIDATE': base=0.5          # T3 跳档后（P3 生产规则：基座0.2+T3 0.3）
 elif tier=='RISK_HOLD': return 0.25
 elif tier=='BUILD': return 0.2
 elif tier=='WATCH': return 0.0
 else: return 0.0
 m={'BULL':1.0,'BEAR':0.5}.get(reg,0.75)
 return round(base*m,3)
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--day',required=True); a=ap.parse_args()
 snap=SCANS/f'current_scan_{a.day}.json'
 d=json.load(open(snap)); cards=d['cards']
 reg=cards[0]['decision']['regime'] if cards and 'decision' in cards[0] else 'NA'
 grp=lambda g:'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','R_RISK_OFF')) else 'OTHER')
 rg=grp(reg)
 rows=[]
 for c in cards:
  de=c.get('decision'); cs=c.get('capital_support')
  if not de or not cs: continue
  tier=de['decision_tier']; hl=de.get('higher_low',False)
  tgt=p3_target(tier,hl,rg)
  if tgt<=0: continue
  rows.append({'stock':c['stock'],'name':c.get('name',''),'tier':tier,'higher_low':hl,
   'support_state':cs['support_state'],'px_close':cs.get('price'),'band_low':round(cs['cost_band_low'],2),
   'band_high':round(cs['cost_band_high'],2),'p3_target':tgt,
   'exit_distance':round(de.get('exit_distance') if 'exit_distance' in de else (cs.get('price',0)/(cs['cost_band_low']*0.95)-1),4)})
 rows.sort(key=lambda r:-r['p3_target'])
 exits=sorted([c for c in cards if c.get('decision',{}).get('decision_tier')=='EXIT'],
  key=lambda c:c['capital_support'].get('price',0)/(c['capital_support']['cost_band_low']*0.95)-1)[:30]
 OUT.mkdir(parents=True,exist_ok=True)
 payload={'day':a.day,'regime_5d':reg,'regime_grp':rg,'n':len(rows),
  'confirm':sum(1 for r in rows if r['tier']=='CONFIRM_CANDIDATE'),'build':sum(1 for r in rows if r['tier']=='BUILD'),
  'risk_hold':sum(1 for r in rows if r['tier']=='RISK_HOLD'),'rows':rows,
  'exit_watchlist':[{'stock':c['stock'],'name':c.get('name',''),
    'exit_distance':round(c['capital_support'].get('price',0)/(c['capital_support']['cost_band_low']*0.95)-1,4)} for c in exits]}
 body=json.dumps(payload,ensure_ascii=False,sort_keys=True)
 payload['sealed_sha256']=hashlib.sha256(body.encode()).hexdigest()[:16]
 (OUT/f'shadow_{a.day}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=1))
 print(json.dumps({k:payload[k] for k in ('day','regime_grp','n','confirm','build','risk_hold','sealed_sha256')}))
if __name__=='__main__':main()
