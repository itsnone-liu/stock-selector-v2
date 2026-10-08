#!/usr/bin/env python3
"""R2-DU: intraday light scan — live quotes × yesterday's frozen scan.

Heavy layer (cost bands, T1-T3, regime, sector axes) is frozen in the latest
current_scan_<day>.json from the 18:10 daily run. This scan only refreshes
price-dependent quantities (support_state, exit_distance, band test/reclaim,
live RS vs market) from tencent batch quotes. Designed for 11:35 / 13:55 runs.

Usage: intraday_scan.py [--pool all|candidates|confirm]  → data/r2/daily_update/intraday_<ts>.json
"""
from __future__ import annotations
import argparse,json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SCANS=ROOT/'data/r2/scans'
OUTD=ROOT/'data/r2/daily_update'

def quotes(codes):
 out={}
 for i in range(0,len(codes),60):
  batch=codes[i:i+60]
  pre=','.join(('sh' if c[0]=='6' else ('bj' if c[0] in '48' else 'sz'))+c for c in batch)
  r=urllib.request.Request('http://qt.gtimg.cn/q='+pre,headers={'User-Agent':'Mozilla/5.0'})
  s=urllib.request.urlopen(r,timeout=15).read().decode('gbk')
  for line in s.split(';'):
   if '~' not in line: continue
   f=line.split('~')
   out[f[2]]={'name':f[1],'price':float(f[3]),'pct':float(f[32]) if f[32] else 0.0,
              'high':float(f[33]) if f[33] else 0.0,'low':float(f[34]) if f[34] else 0.0}
  time.sleep(0.4)
 return out

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--pool',default='candidates')
 ap.add_argument('--push',action='store_true'); a=ap.parse_args()
 snap=sorted(SCANS.glob('current_scan_*.json'))
 if snap:
  latest=snap[-1]; base_day=latest.stem[-10:]; d=json.load(open(latest))
 else:
  latest=ROOT/'data/r2/current_scan_v0.json'; d=json.load(open(latest)); base_day=d.get('asof_ym','v0')
 cards=[c for c in d['cards'] if c.get('capital_support') and c.get('decision')]
 if a.pool=='confirm':
  cards=[c for c in cards if c['decision']['decision_tier']=='CONFIRM_CANDIDATE']
 elif a.pool=='candidates':
  keep={'CONFIRM_CANDIDATE','BUILD','WATCH'}
  cards=[c for c in cards if c['decision']['decision_tier'] in keep or c['capital_support']['support_state'] in ('IN_SUPPORT','UNDERCUT_TEST')]
 q=quotes([c['stock'] for c in cards])
 mkt=[v['pct'] for v in q.values()]; mkt_pct=sum(mkt)/len(mkt) if mkt else 0.0
 rows=[]
 for c in cards:
  t=q.get(c['stock'])
  if not t or t['price']<=0: continue
  cs=c['capital_support']; bl,bh=cs['cost_band_low'],cs['cost_band_high']
  trig=bl*0.95; px=t['price']
  # live support_state vs frozen band
  if px>=bh: ss='ABOVE_SUPPORT(live)'
  elif px>=bl: ss='IN_SUPPORT(live)'
  else: ss='UNDERCUT(live)'
  frozen=cs['support_state']
  alerts=[]
  if px<trig: alerts.append('CROSS_TRIGGER')            # 预警：收盘确认5日才是BROKEN
  elif px/trig-1<0.02: alerts.append('NEAR_TRIGGER')
  if frozen=='ABOVE_SUPPORT' and px<bh: alerts.append('BAND_TEST')      # 回落进带=可BUILD评估
  if frozen in('UNDERCUT_TEST','IN_SUPPORT') and px>bh: alerts.append('BAND_BREAKOUT')
  if t['pct']>mkt_pct+1.0: alerts.append('RS_STRONG')
  rows.append({'stock':c['stock'],'name':t['name'],'tier':c['decision']['decision_tier'],
   'px':px,'pct':t['pct'],'frozen_state':frozen,'live_state':ss,
   'exit_dist':round(px/trig-1,4),'alerts':alerts,'band_pos_live':round(px/cs['cost_band_mid']-1,4)})
 rows.sort(key=lambda r:(len(r['alerts']),r['exit_dist']))
 ts=time.strftime('%Y%m%d_%H%M')
 OUTD.mkdir(parents=True,exist_ok=True)
 (OUTD/f'intraday_{ts}.json').write_text(json.dumps({'ts':ts,'base_scan':base_day,
  'market_avg_pct':round(mkt_pct,2),'n':len(rows),'rows':rows},ensure_ascii=False,indent=1))
 al=[r for r in rows if r['alerts']]
 print(json.dumps({'ts':ts,'base':base_day,'n':len(rows),'alerts':len(al),
  'cross_trigger':[r['stock'] for r in rows if 'CROSS_TRIGGER' in r['alerts']],
  'band_test':[r['stock'] for r in rows if 'BAND_TEST' in r['alerts']][:10],
  'band_breakout':[r['stock'] for r in rows if 'BAND_BREAKOUT' in r['alerts']][:10]},ensure_ascii=False))
if __name__=='__main__':main()
