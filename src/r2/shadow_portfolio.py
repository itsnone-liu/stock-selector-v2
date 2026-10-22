#!/usr/bin/env python3
"""Shadow Portfolio 三账户封存 (frozen EI-1 v1 + EI-2 v1, 2026-10-09 裁定)
A=P3 raw | B=P3 x B50(0.75 if breadth50<0.50) | C=B x Q5_REDUCE(0.75 if DTC in top20% 当日横截面)
Q5 口径继承 EI-2A PIT 横截面法：当日可见可行动池(CONFIRM/RISK_HOLD/BUILD, p3_raw>0)按 DTC 排序前 20%；禁止事后校准绝对阈值。
BROKEN/EXIT → 0 最高优先。每晚封存，不可重算。用法（每晚 F 之后）：shadow_portfolio.py --day YYYY-MM-DD"""
from __future__ import annotations
import argparse,hashlib,json,gzip,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SCANS=ROOT/'data/r2/scans'; OUT=ROOT/'data/r2/shadow'
def p3_target(tier,hl,reg,support_state):
 if tier in('EXIT','WATCH','NO_BUILD'): return 0.0
 base={'CONFIRM_CANDIDATE':0.5,'RISK_HOLD':0.25,'BUILD':0.2}.get(tier,0.0)
 m={'BULL':1.0,'BEAR':0.5}.get(reg,0.75)           # regime 乘数（R2-10/11 验证）
 t=base*m
 if support_state=='UNDERCUT_TEST': t*=0.5         # 状态修正
 return round(t,4)
def breadth50():
 # EI-1 v1 frozen: fraction of stocks with close>MA50 (EOD compute, next-session use)
 D=ROOT/'data/cd/daily_fullmarket'; a=t=0
 for pth in D.glob('*.json.gz'):
  try: d=json.loads(gzip.decompress(pth.read_bytes()))
  except Exception: continue
  # 2026-10-22 fix: CD 全市场文件 schema 为 {'dates','qfq','unadj'}，无 qfq_close/close 键，
  # 旧写法 `d.get('qfq_close') or d.get('close')` 恒为 None → 每只票 continue → t=0
  # → 兜底 0.5 → B50 闸门永远 OFF（breadth_history.jsonl 全 14 条均 0.5 取证）。
  cl=d.get('qfq_close') or d.get('close') or [float(r[2]) for r in (d.get('qfq') or [])]
  if not cl or len(cl)<50: continue
  t+=1
  if cl[-1]>sum(cl[-50:])/50: a+=1
 return round(a/t,4) if t else 0.5
def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--day',required=True); ap.add_argument('--out',default=None); a=ap.parse_args()
 snap=SCANS/f'current_scan_{a.day}.json'
 d=json.load(open(snap)); cards=d['cards']
 B50=breadth50(); B50M=0.75 if B50<0.50 else 1.0
 reg=d.get('regime_5d') or (cards[0].get('decision',{}).get('regime','') if cards else '')
 rg='BULL' if str(reg).startswith('R_RISK_ON') else ('BEAR' if str(reg).startswith(('R_DEPRESSED','RISK_OFF','R_RISK_OFF')) else 'OTHER')
 rows=[]
 for c in cards:
  t=c.get('decision',{}); tier=t.get('decision_tier','NO_BUILD'); hl=t.get('higher_low',False)
  cs=c.get('capital_support')
  if not cs: continue
  px=cs.get('price',0); bl=cs.get('cost_band_low'); bh=cs.get('cost_band_high')
  if not bl or not bh: continue
  zm=(bl+bh)/2; dtc=px/zm-1
  raw=p3_target(tier,hl,rg,cs.get('support_state',''))
  rows.append({'stock':c['stock'],'name':c.get('name',''),'tier':tier,'higher_low':hl,
   'support_state':cs.get('support_state',''),'px':px,'band':[bl,bh],'dtc':round(dtc,4),'p3_raw':raw})
 act=[r for r in rows if r['p3_raw']>0]
 thr=sorted(r['dtc'] for r in act)[int(0.8*len(act))] if act else None
 for r in rows:
  r['p3_b50']=round(r['p3_raw']*B50M,4)
  r['q5']=bool(thr is not None and r['p3_raw']>0 and r['dtc']>=thr)
  r['p3_final']=round(r['p3_b50']*(0.75 if r['q5'] else 1.0),4)
 exits=sorted([c for c in cards if c.get('decision',{}).get('decision_tier')=='EXIT'],
  key=lambda c:c['capital_support'].get('price',0)/(c['capital_support']['cost_band_low']*0.95)-1)[:30]
 payload={'day':a.day,'regime_5d':reg,'regime_grp':rg,'breadth50':B50,'breadth50_gate':'ON' if B50M<1 else 'OFF',
  'n':len(rows),'q5_threshold':round(thr,4) if thr is not None else None,
  'counts':{'confirm':sum(1 for r in rows if r['tier']=='CONFIRM_CANDIDATE'),'build':sum(1 for r in rows if r['tier']=='BUILD'),
   'risk_hold':sum(1 for r in rows if r['tier']=='RISK_HOLD'),'q5_reduce':sum(1 for r in rows if r['q5'])},
  'exp_sums':{'A':round(sum(r['p3_raw'] for r in rows),2),'B':round(sum(r['p3_b50'] for r in rows),2),'C':round(sum(r['p3_final'] for r in rows),2)},
  'rows':rows,'exit_watchlist':[{'stock':c['stock'],'name':c.get('name',''),
   'exit_distance':round(c['capital_support'].get('price',0)/(c['capital_support']['cost_band_low']*0.95)-1,4)} for c in exits]}
 body=json.dumps(payload,sort_keys=True,ensure_ascii=False)
 payload['sealed_sha256']=hashlib.sha256(body.encode()).hexdigest()[:16]
 OUTD=Path(a.out) if a.out else OUT; OUTD.mkdir(parents=True,exist_ok=True)
 # 原子落盘：先写 .tmp 再 os.replace。封存文件"不可重算"，不能被中途 kill/磁盘满
 # 截断成半截 JSON（下游 export_r2_list/export_190_md/fetch_names 直读该文件）。
 _tmp=OUTD/f'.shadow_{a.day}.json.tmp'
 _tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=1))
 os.replace(_tmp,OUTD/f'shadow_{a.day}.json')
 if not a.out:
  with open(OUT/'breadth_history.jsonl','a') as f:
   f.write(json.dumps({'day':a.day,'breadth50':B50,'gate':'ON' if B50M<1 else 'OFF'})+'\n')
 print(json.dumps({k:payload[k] for k in ('day','regime_grp','breadth50','breadth50_gate','n','counts','exp_sums','q5_threshold','sealed_sha256')}))
if __name__=='__main__':main()
