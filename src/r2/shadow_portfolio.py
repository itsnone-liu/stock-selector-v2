#!/usr/bin/env python3
"""Shadow Portfolio (prospective validation, frozen policy): 每日封存，不可重算。
读 data/r2/scans/current_scan_<day>.json → CONFIRM/BUILD/RISK_HOLD 清单 + P3 目标仓位 + 当日封存哈希。
用法（每晚 F 之后）：shadow_portfolio.py --day YYYY-MM-DD"""
from __future__ import annotations
import argparse,hashlib,json,gzip
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SCANS=ROOT/'data/r2/scans'; OUT=ROOT/'data/r2/shadow'
def p3_target(tier,hl,reg,support_state):
 if tier in('EXIT','WATCH','NO_BUILD'): return 0.0
 base={'CONFIRM_CANDIDATE':0.5,'RISK_HOLD':0.25,'BUILD':0.2}.get(tier,0.0)
 m={'BULL':1.0,'BEAR':0.5}.get(reg,0.75)           # regime 乘数（R2-10/11 验证：base*=m）
 t=base*m
 if support_state=='UNDERCUT_TEST': t*=0.5         # 状态修正（验证模拟 if not sup: st*=0.5）
 return round(t,4)
def breadth50():
 # EI-1 v1 frozen: fraction of stocks with close>MA50 (EOD compute, next-session use)
 D=ROOT/'data/cd/daily_fullmarket'; a=t=0
 for pth in D.glob('*.json.gz'):
  try: d=json.loads(gzip.decompress(pth.read_bytes()))
  except Exception: continue
  cl=d.get('qfq_close') or d.get('close')
  if not cl or len(cl)<50: continue
  t+=1
  if cl[-1]>sum(cl[-50:])/50: a+=1
 return round(a/t,4) if t else 0.5

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--day',required=True); ap.add_argument('--out',default=None); a=ap.parse_args()
 snap=SCANS/f'current_scan_{a.day}.json'
 d=json.load(open(snap)); cards=d['cards']
 B50=breadth50(); B50M=0.75 if B50<0.50 else 1.0
 reg=cards[0]['decision']['regime'] if cards and 'decision' in cards[0] else 'NA'
 grp=lambda g:'BULL' if g.startswith('R_RISK_ON') else ('BEAR' if g.startswith(('R_DEPRESSED','R_RISK_OFF')) else 'OTHER')
 rg=grp(reg)
 rows=[]
 for c in cards:
  de=c.get('decision'); cs=c.get('capital_support')
  if not de or not cs: continue
  tier=de['decision_tier']; hl=de.get('higher_low',False)
  raw=p3_target(tier,hl,rg,cs['support_state'])
  tgt=round(raw*B50M,4) if raw else 0.0   # EI-1 v1 frozen: x0.75 if breadth50<0.50
  if tgt<=0: continue
  rows.append({'stock':c['stock'],'name':c.get('name',''),'tier':tier,'higher_low':hl,'p3_raw':raw,
   'support_state':cs['support_state'],'px_close':cs.get('price'),'band_low':round(cs['cost_band_low'],2),
   'band_high':round(cs['cost_band_high'],2),'p3_target':tgt,
   'exit_distance':round(de.get('exit_distance') if 'exit_distance' in de else (cs.get('price',0)/(cs['cost_band_low']*0.95)-1),4)})
 rows.sort(key=lambda r:-r['p3_target'])
 exits=sorted([c for c in cards if c.get('decision',{}).get('decision_tier')=='EXIT'],
  key=lambda c:c['capital_support'].get('price',0)/(c['capital_support']['cost_band_low']*0.95)-1)[:30]
 OUTD2=Path(a.out) if a.out else OUT; OUTD2.mkdir(parents=True,exist_ok=True)
 payload={'day':a.day,'regime_5d':reg,'regime_grp':rg,'breadth50':B50,'breadth50_gate':'ON' if B50M<1 else 'OFF','n':len(rows),
  'confirm':sum(1 for r in rows if r['tier']=='CONFIRM_CANDIDATE'),'build':sum(1 for r in rows if r['tier']=='BUILD'),
  'risk_hold':sum(1 for r in rows if r['tier']=='RISK_HOLD'),'rows':rows,
  'exit_watchlist':[{'stock':c['stock'],'name':c.get('name',''),
    'exit_distance':round(c['capital_support'].get('price',0)/(c['capital_support']['cost_band_low']*0.95)-1,4)} for c in exits]}
 body=json.dumps(payload,ensure_ascii=False,sort_keys=True)
 payload['sealed_sha256']=hashlib.sha256(body.encode()).hexdigest()[:16]
 (OUTD2/f'shadow_{a.day}.json').write_text(json.dumps(payload,ensure_ascii=False,indent=1))
 if not a.out:
  with open(OUT/'breadth_history.jsonl','a') as f: f.write(json.dumps({'day':a.day,'breadth50':B50,'gate':'ON' if B50M<1 else 'OFF'})+'\n')
 print(json.dumps({k:payload[k] for k in ('day','regime_grp','breadth50','breadth50_gate','n','confirm','build','risk_hold','sealed_sha256')}))
if __name__=='__main__':main()
