#!/usr/bin/env python3
"""R2-DU: intraday light scan — live quotes × yesterday's frozen scan.

Heavy layer (cost bands, T1-T3, regime, sector axes) is frozen in the latest
current_scan_<day>.json from the 18:10 daily run. This scan only refreshes
price-dependent quantities (support_state, exit_distance, band test/reclaim,
live RS vs market) from tencent batch quotes. Designed for 11:35 / 13:55 runs.

Usage: intraday_scan.py [--pool all|candidates|confirm]  → data/r2/daily_update/intraday_<ts>.json
Note: BAND_TEST only fires for --pool candidates/all (confirm pool has no ABOVE_SUPPORT
frozen states); RS_VS_INDEX benchmarks the SH composite index, not the pool itself.
"""
from __future__ import annotations
import argparse,json,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SCANS=ROOT/'data/r2/scans'
OUTD=ROOT/'data/r2/daily_update'

import sys as _sys; _sys.path.insert(0,str(ROOT/'src'))
from r2.tdx_quotes import (quotes as _tdx_quotes, index_pct as _tdx_index_pct,
                           split_quotes as _tdx_split, lookup as _tdx_lookup)

def quotes(codes):
 '''实时批量快照。2026-10-21 定案：退役腾讯 qt.gtimg.cn → TDX 通道（字段同名同义）。'''
 return _tdx_quotes(codes)

def idx_pct():
 '''上证综指实时涨幅%（TDX）。'''
 return _tdx_index_pct('sh000001')

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
 want=[c['stock'] for c in cards]
 q=quotes(want)
 mkt_pct=idx_pct()  # FIX: benchmark = SH composite index, not pool average
 # 停牌/无数据口径（2026-10-22 R4/R5 对拍 C-1/C-2/C-3 定案）：
 #   服务器**不返回记录**（missing）才是停牌/无行情信号；绝不能用 price<=0 判停牌
 #   —— 盘前 09:10 全市场请求 5598 只有记录 5576 只，5576/5576 全部
 #   price=0,vol=0,servertime=8:35:00.000。有记录但 price<=0 = 盘前/竞价未撮合，
 #   单列 no_price（不混进 missing，也不上榜）。分桶逻辑在 tdx_quotes.split_quotes。
 _ok,_miss,_noprice=_tdx_split(q,want)
 missing=list(_miss)
 no_price=list(_noprice)
 rows=[]
 for c in cards:
  t=_tdx_lookup(_ok,c['stock'])
  if not t: continue
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
  if t['pct']>mkt_pct+1.0: alerts.append('RS_VS_INDEX')
  rows.append({'stock':c['stock'],'name':t['name'],'tier':c['decision']['decision_tier'],
   'px':px,'pct':t['pct'],'frozen_state':frozen,'live_state':ss,
   'exit_dist':round(px/trig-1,4),'alerts':alerts,'band_pos_live':round(px/cs['cost_band_mid']-1,4),
   'band_low':round(bl,2),'band_high':round(bh,2),'band_mid':round(cs['cost_band_mid'],2),
   'confidence':c.get('confidence')})
 rows.sort(key=lambda r:(len(r['alerts']),r['exit_dist']))
 ts=time.strftime('%Y%m%d_%H%M')
 OUTD.mkdir(parents=True,exist_ok=True)
 (OUTD/f'intraday_{ts}.json').write_text(json.dumps({'ts':ts,'base_scan':base_day,
  'idx_pct':round(mkt_pct,2),'n':len(rows),'n_missing':len(missing),'missing':missing,
  'n_no_price':len(no_price),'no_price':no_price,'rows':rows},ensure_ascii=False,indent=1))
 al=[r for r in rows if r['alerts']]
 print(json.dumps({'ts':ts,'base':base_day,'n':len(rows),'n_missing':len(missing),'missing':missing[:20],
  'n_no_price':len(no_price),'no_price':no_price[:20],'idx_pct':mkt_pct,'alerts':len(al),
  'cross_trigger':[r['stock'] for r in rows if 'CROSS_TRIGGER' in r['alerts']],
  'near_trigger':[r['stock'] for r in rows if 'NEAR_TRIGGER' in r['alerts']],
  'band_test':[r['stock'] for r in rows if 'BAND_TEST' in r['alerts']],
  'band_breakout':[r['stock'] for r in rows if 'BAND_BREAKOUT' in r['alerts']]},ensure_ascii=False))
if __name__=='__main__':main()
