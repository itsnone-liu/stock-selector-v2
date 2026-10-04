#!/usr/bin/env python3
"""Independent bounded semantic audit for a qualification day.

Second implementation path: rules are re-written explicitly here from the frozen
written contracts. This module does NOT import cd_shadow_runtime, adapters,
materializers, or CD-7 engines. It reads the trace file only to select entity ids;
all expected values are re-derived from frozen raw inputs.
"""
from __future__ import annotations
import argparse,gzip,json,math
from collections import defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data/cd'
def loadg(p): return json.loads(gzip.decompress(Path(p).read_bytes()))

def quantile_from_hist(counts, lo, hi, q):
 """Independent weighted-quantile: single cumulative scan, proportionally interpolated."""
 total=sum(counts)
 if total<=0 or hi<=lo: return hi
 target=total*q; cum=0.0; width=(hi-lo)/len(counts)
 for idx,c in enumerate(counts):
  if c<=0: continue
  if cum+c>=target:
   frac=(target-cum)/c; return lo+(idx+frac)*width
  cum+=c
 return hi

def bands_of(value, lo, hi):
 if value is None: return None
 return 'LOW' if value<lo else ('HIGH' if value>=hi else 'MID')

def derive(entity_day, stock_file, members_l2, bands, mkt20, sec20, regime):
 """Re-derive lifecycle/zone for one (episode, asof) from raw bars."""
 ep,start,end_id=entity_day['episode'],entity_day['start'],entity_day['end']
 rec=loadg(stock_file); dates=rec['dates']
 qfq=rec['qfq']; unadj=rec['unadj']
 closes=[float(r[2]) for r in qfq]; highs=[float(r[3]) for r in qfq]; lows=[float(r[4]) for r in qfq]; vols=[float(r[5]) for r in unadj]
 s=next(i for i,d in enumerate(dates) if d>=start)
 end=max(i for i,d in enumerate(dates) if d<=entity_day['day'])
 vols_prefix=[0.0]
 for v in vols: vols_prefix.append(vols_prefix[-1]+v)
 base_window=vols_prefix[s]-vols_prefix[max(0,s-20)]; base_days=max(1,min(20,s)); baseline=base_window/base_days if s>=1 else None
 counts=[0]*50; lo_tp=hi_tp=None; ever=False; first_trigger=None; state='HOLDING'; prev='HOLDING'; snap=None
 for i in range(s,end+1):
  c,h,l,v=closes[i],highs[i],lows[i],vols[i]
  if not(c>0 and h>0 and l>0): continue
  typical=(h+l+c)/3.0
  lo_tp=typical if lo_tp is None else min(lo_tp,typical); hi_tp=typical if hi_tp is None else max(hi_tp,typical)
  span=hi_tp-lo_tp; idx=0 if span<=0 else min(49,int((typical-lo_tp)/span*50)); counts[idx]+=v
  p25=quantile_from_hist(counts,lo_tp,hi_tp,0.25); centre=quantile_from_hist(counts,lo_tp,hi_tp,0.5)
  rps=rpm=None
  if i>=20 and closes[i-20]>0:
   own=c/closes[i-20]-1
   sv=sec20.get((members_l2,dates[i])); mv=mkt20.get(dates[i])
   # frozen contract: missing benchmark series value falls back to 0 (producer: `or 0`)
   rps=own-(sv if sv is not None else 0.0); rpm=own-(mv if mv is not None else 0.0)
  v20=(vols_prefix[i+1]-vols_prefix[max(0,i-19)])/max(1,min(20,i+1))
  part=(v20/baseline) if (baseline and baseline>0) else None
  b_rps=bands_of(rps,*bands['rps']); b_rpm=bands_of(rpm,*bands['rpm']); b_part=bands_of(part,*bands['part'])
  prev=state
  decay=(b_rps=='LOW' and b_rpm=='LOW' and (c<p25 or b_part=='LOW'))
  strengthen=((b_rps=='HIGH' or b_rpm=='HIGH') and b_part!='LOW')
  state='DECAYING' if decay else ('STRENGTHENING' if strengthen else 'HOLDING')
  if state=='STRENGTHENING': ever=True
  eligible=((i-s+1)>=10 and ever and state in ('HOLDING','STRENGTHENING'))
  zone=(eligible and p25<=c<=centre*1.05 and b_part!='LOW' and regime not in ('R_DEPRESSED','R_RISK_OFF'))
  if zone and first_trigger is None: first_trigger=dates[i]
  snap={'date':dates[i],'prev':prev,'state':state,'b_rps':b_rps,'b_rpm':b_rpm,'b_part':b_part,'p25':p25,'centre':centre,'eligible':eligible,'zone':zone,'close':c}
 return {'episode_id':ep,'snap':snap,'first_trigger':first_trigger,'state':state}

def main():
 p=argparse.ArgumentParser();p.add_argument('--day',required=True);p.add_argument('--snapshot',default=None);p.add_argument('--per-stratum',type=int,default=8);a=p.parse_args()
 qdir=Path(a.snapshot) if a.snapshot else ROOT/'data/cd/shadow_qualification'/a.day
 traces=json.loads(gzip.decompress((qdir/'traces.json.gz').read_bytes()))
 strat=defaultdict(list)
 for t in traces['lifecycle']:
  zt=next((z for z in traces['primary_zone'] if z['episode_id']==t['episode_id']),None)
  dt=next((d for d in traces['decision'] if d['episode_id']==t['episode_id']),None)
  key=(t['next_state'],bool(zt['first_trigger_today']) if zt else False)
  strat[key].append((t,zt,dt))
 chosen=[]
 for key,items in strat.items():
  step=max(1,len(items)//a.per_stratum)
  chosen+=items[::step][:a.per_stratum]
 eps={e['episode_id']:e for e in loadg(DATA/'l4_episodes.json.gz')['episodes']}
 members={m['code']:m.get('L2') for m in json.load(open(DATA/'sector_seeds/csrc_v1.json'))['members']}
 bands=json.load(open(ROOT/'docs/cd/cd5bd_results.json'))['frozen_bands']
 axes=loadg(DATA/'sector_axes/l2_four_axes.json.gz')['rows']
 byday_m=defaultdict(list); byday_s=defaultdict(dict)
 for r in axes:
  if r.get('status')=='OK':
   if r.get('mkt_eq') is not None: byday_m[r['date']].append(r['mkt_eq'])
   if r.get('sector_eq') is not None: byday_s[r['l2']][r['date']]=r['sector_eq']
 def roll20(series):
  ordered=sorted(series); out={}; cum=1.0; hist=[]
  for d in ordered:
   cum*=1+series[d]; hist.append((d,cum))
  for j in range(20,len(hist)): out[hist[j][0]]=hist[j][1]/hist[j-20][1]-1
  return out
 mkt20=roll20({d:(sum(v)/len(v)) for d,v in byday_m.items()})
 sec20={}
 for l2,m in byday_s.items(): sec20.update({(l2,d):v for d,v in roll20(m).items()})
 regime=next(r['regime'] for r in loadg(DATA/'sector_axes/l1_market_axes.json.gz')['rows'] if r['date']==a.day)
 anchors=[]; mismatches=[]
 for t,zt,dt in chosen:
  ep=eps[t['episode_id']]; stock=ep['stock']; f=DATA/'daily_fullmarket'/f'{stock}.json.gz'
  if not f.exists(): continue
  got=derive({'episode':t['episode_id'],'start':ep['start'],'end':ep['end'],'day':a.day},f,members.get(stock),bands,mkt20,sec20,regime)
  exp={'lifecycle_state':t['next_state'],'primary_zone_today':zt['primary_zone_today'],'first_trigger_today':zt['first_trigger_today'],'b_rps':t['predicates']['rps_band'],'b_rpm':t['predicates']['rpm_band'],'b_part':t['predicates']['part_band'],'p25_delta':abs((got['snap']['p25'] or 0)-(t['inputs']['p25'] or 0))}
  act={'lifecycle_state':got['state'],'primary_zone_today':got['snap']['zone'],'first_trigger_today':got['first_trigger']==a.day,'b_rps':got['snap']['b_rps'],'b_rpm':got['snap']['b_rpm'],'b_part':got['snap']['b_part'],'p25_delta':exp['p25_delta']}
  categorical_ok=all(exp[k]==act[k] for k in ('lifecycle_state','primary_zone_today','first_trigger_today','b_rps','b_rpm','b_part')) and exp['p25_delta']<1e-3
  decision_expected='ENTER' if act['first_trigger_today'] else 'NO_ACTION'
  decision_actual=dt['decision'] if dt else 'NOT_TRACED'
  decision_ok=(decision_actual=='NOT_TRACED') or (decision_expected==decision_actual)
  anchors.append({'episode_id':t['episode_id'],'asof':a.day,'expected':exp,'actual':act,'decision_expected':decision_expected,'decision_actual':decision_actual,'exact_match':categorical_ok and decision_ok,'oracle':'independent_semantic_audit','uses_runtime_code':False})
  if not categorical_ok or not decision_ok: mismatches.append(t['episode_id'])
 coverage={'lifecycle_states':sorted({a['actual']['lifecycle_state'] for a in anchors if a['actual']['lifecycle_state']}),'primary_zone':sorted({a['actual']['primary_zone_today'] for a in anchors if a['actual']['primary_zone_today'] is not None},key=str),'decisions':sorted({a['decision_actual'] for a in anchors if a['decision_actual']})}
 result={'gate':'G-SHADOW-ACTION-QUALIFICATION','day':a.day,'oracle':'independent','n_anchors':len(anchors),'all_exact_match':not mismatches,'mismatches':mismatches,'coverage':coverage,'anchors':anchors}
 out=qdir/'independent_audit.json'; out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(result,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
