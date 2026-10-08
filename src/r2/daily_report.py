#!/usr/bin/env python3
"""R2-DU(F): daily report — tier migration diff + fixed-slice cross stats +
BROKEN critical queue. Reads current_scan_{day}.json + local TDX mirror.
Suspended stocks are excluded from cross stats (pct from TDX needs 2 bars).
Output: data/r2/daily_update/report_{day}.json (+append to crossval_history.jsonl)
"""
from __future__ import annotations
import argparse,gzip,json,struct
from collections import Counter,defaultdict
from pathlib import Path
import statistics as st
ROOT=Path(__file__).resolve().parents[2]
TDX=Path('/root/tdx_data/vipdoc'); SCANS=ROOT/'data/r2/scans'
OUTD=ROOT/'data/r2/daily_update'

def day_pct(code,day):
 """pct chg on `day` from TDX raw bars; None if suspended (no bar) or file missing."""
 mkt='sh' if code[0] in '69' else ('bj' if code[0] in '48' else 'sz')
 p=TDX/mkt/'lday'/f'{mkt}{code}.day'
 if not p.exists(): return None
 b=p.read_bytes(); rows=[struct.unpack('<IIIIIfIf',b[i*32:(i+1)*32]) for i in range(len(b)//32)]
 dk=day.replace('-','')
 for i,r in enumerate(rows):
  if str(r[0])==dk:
   if i==0: return None
   return r[4]/rows[i-1][4]-1
 return None  # no bar that day => suspended

def slices(c):
 cs=c.get('capital_support',{}); dt=c.get('decision',{}); e=c.get('evidence',{})
 pm=cs.get('price_to_cost_mid')
 band='带中区±5%' if pm is not None and -0.05<=pm<0.05 else ('带下区<-5%' if pm is not None and pm<-0.05 else ('带上区+5~20%' if pm is not None and pm<0.2 else '带上沿>20%'))
 return {'band_pos':band,'support_state':cs.get('support_state'),
  'T2':dt.get('sector_tier'),'T3':dt.get('stock_rs_tier'),
  'E3':e.get('E3_chip'),'state':c.get('state'),'conf':('0.85+' if c.get('confidence',0)>=0.85 else '0.75-0.85' if c.get('confidence',0)>=0.75 else '<0.75')}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--day',required=True); a=ap.parse_args()
 day=a.day; cur=json.load(open(SCANS/f'current_scan_{day}.json'))
 cards=cur['cards']
 prevs=[p for p in sorted(SCANS.glob('current_scan_*.json')) if p.stem[-10:]!=day]
 prev=json.load(open(prevs[-1])) if prevs else None
 mig=[]
 if prev:
  pt={c['stock']:c.get('decision',{}).get('decision_tier') for c in prev['cards']}
  for c in cards:
   t0=pt.get(c['stock']); t1=c.get('decision',{}).get('decision_tier')
   if t0 and t1 and t0!=t1: mig.append({'stock':c['stock'],'from':t0,'to':t1})
 # cross stats (exclude suspended)
 rows=[]
 for c in cards:
  p=day_pct(c['stock'],day)
  if p is None: continue
  r={'pct':p}; r.update(slices(c)); r['stock']=c['stock']; rows.append(r)
 cross={}
 for k in ('band_pos','support_state','state','conf','E3','T2','T3'):
  g=defaultdict(list)
  for r in rows: g[str(r[k])].append(r['pct'])
  cross[k]={kk:{'n':len(v),'mean':round(st.mean(v),4),'median':round(st.median(v),4),'up_ratio':round(sum(1 for x in v if x>0)/len(v),3)} for kk,v in g.items() if len(v)>=8}
 # BROKEN critical queue: exit_distance = close(day)/trigger - 1, trigger=band_low*0.95
 q=[]
 for c in cards:
  cs=c.get('capital_support',{})
  if not cs or cs.get('support_state')=='BROKEN': continue
  mkt='sh' if c['stock'][0] in '69' else ('bj' if c['stock'][0] in '48' else 'sz')
  p=TDX/mkt/'lday'/f'{mkt}{c["stock"]}.day'
  if not p.exists(): continue
  b=p.read_bytes(); last=struct.unpack('<IIIIIfIf',b[-32:])
  if str(last[0])!=day.replace('-',''): continue
  trig=cs['cost_band_low']*0.95; px=last[4]/100
  q.append({'stock':c['stock'],'name':c.get('name',''),'px':round(px,2),'trigger':round(trig,2),
   'exit_distance':round(px/trig-1,4),'tier':c.get('decision',{}).get('decision_tier')})
 q.sort(key=lambda x:x['exit_distance'])
 susp=[c['stock'] for c in cards if day_pct(c['stock'],day) is None]
 rep={'day':day,'n_cards':len(cards),'n_traded':len(rows),'n_suspended':len(susp),'suspended':susp[:50],
  'tier_hist':dict(Counter(c.get('decision',{}).get('decision_tier','NA') for c in cards)),
  'migrations':mig,'cross':cross,'broken_queue':q[:30],'pool_stats':{'mean_pct':round(st.mean([r['pct'] for r in rows]),4) if rows else None,
  'up_ratio':round(sum(1 for r in rows if r['pct']>0)/len(rows),3) if rows else None}}
 OUTD.mkdir(parents=True,exist_ok=True)
 (OUTD/f'report_{day}.json').write_text(json.dumps(rep,ensure_ascii=False,indent=1))
 with open(OUTD/'crossval_history.jsonl','a') as f: f.write(json.dumps({'day':day,**{k:cross.get(k,{})for k in('band_pos','E3','state')},'pool':rep['pool_stats']},ensure_ascii=False)+'\n')
 print(json.dumps({'day':day,'traded':len(rows),'susp':len(susp),'migrations':len(mig),'pool':rep['pool_stats']},ensure_ascii=False))
if __name__=='__main__':main()
