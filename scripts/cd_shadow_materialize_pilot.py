#!/usr/bin/env python3
"""Frozen Round-1 authority producer with optional deterministic traces.

Historical migration producer for lifecycle / PRIMARY_ZONE / decision projection.
Trace collection is observability instrumentation only: enabling it must not change
any computed value or payload byte. Qualified by byte-identity against promoted
authority artifacts after every instrumentation change.
"""
from __future__ import annotations
import bisect,gzip,json,hashlib,argparse
from collections import defaultdict,Counter
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; DATA=ROOT/'data'/'cd'; N=50
DATES=('2021-07-30','2022-04-29','2023-03-31','2024-06-28','2025-12-31','2026-09-30')
def loadg(p): return json.loads(gzip.decompress(Path(p).read_bytes()))
def canon(x): return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def sha(b): return hashlib.sha256(b).hexdigest()
def wq(h,lo,hi,total,q):
 t=total*q; acc=0.; span=hi-lo
 for b in range(N):
  if h[b]>0 and acc+h[b]>=t:return lo+(b+(t-acc)/h[b])/N*span
  acc+=h[b]
 return hi

def materialize_day(day, out, collect_trace=False, no_action_trace_cap=25):
 eps=loadg(DATA/'l4_episodes.json.gz')['episodes']; by=defaultdict(list)
 for e in eps: by[e['stock']].append(e)
 members={m['code']:m.get('L2') for m in json.load(open(DATA/'sector_seeds/csrc_v1.json'))['members']}
 bands=json.load(open(ROOT/'docs/cd/cd5bd_results.json'))['frozen_bands']
 ax=loadg(DATA/'sector_axes/l2_four_axes.json.gz')['rows']; l1=loadg(DATA/'sector_axes/l1_market_axes.json.gz')['rows']; l1map={r['date']:r for r in l1}
 if day not in l1map: raise SystemExit('missing L1 asof')
 mkt=defaultdict(list); sec=defaultdict(dict)
 for r in ax:
  if r.get('status')=='OK':
   if r.get('mkt_eq') is not None:mkt[r['date']].append(r['mkt_eq'])
   if r.get('sector_eq') is not None:sec[r['l2']][r['date']]=r['sector_eq']
 mh=[];c=1.
 for d in sorted(mkt): c*=1+sum(mkt[d])/len(mkt[d]);mh.append((d,c))
 mr={mh[i][0]:mh[i][1]/mh[i-20][1]-1 for i in range(20,len(mh))}
 sr={}
 for l2, vals in sec.items():
  h=[];c=1.
  for d in sorted(vals):c*=1+vals[d];h.append((d,c))
  for i in range(20,len(h)):sr[(l2,h[i][0])]=h[i][1]/h[i-20][1]-1
 reg=l1map[day].get('regime'); reg_rows=sorted(l1map); mode=Counter(l1map[d]['regime'] for d in reg_rows[max(0,reg_rows.index(day)-19):reg_rows.index(day)+1]).most_common(1)[0][0] if day in reg_rows else reg
 lifecycle=[]; zones=[]; decisions=[]; traces={'lifecycle':[],'primary_zone':[],'decision':[]}; no_action_seen=0
 for code, elist in by.items():
  f=DATA/'daily_fullmarket'/f'{code}.json.gz'
  if not f.exists():continue
  rec=loadg(f); ds=rec['dates']; cl=[float(r[2]) for r in rec['qfq']]; hi=[float(r[3]) for r in rec['qfq']]; lo=[float(r[4]) for r in rec['qfq']]; vol=[float(r[5]) for r in rec['unadj']]; n=len(ds);vs=[0.]*(n+1)
  for i in range(n):vs[i+1]=vs[i]+vol[i]
  l2=members.get(code)
  for e in elist:
   if e['start']>day or e['end']<day:continue
   s=bisect.bisect_left(ds,e['start']); end=bisect.bisect_right(ds,day)-1
   if s>=n or end<s:continue
   hist=[0.]*N; total=0.;tlo=thi=None;baseline=(vs[s]-vs[max(0,s-20)])/max(1,min(20,s)) if s>=1 else None; ever=False; trigger=None; state='HOLDING'
   snap=None; prev_state='HOLDING'
   for i in range(s,end+1):
    if not(cl[i]>0 and hi[i]>0 and lo[i]>0):continue
    tp=(hi[i]+lo[i]+cl[i])/3;v=vol[i]
    if tlo is None:tlo=thi=tp
    tlo=min(tlo,tp);thi=max(thi,tp);span=thi-tlo;b=0 if span<=0 else min(N-1,int((tp-tlo)/span*N));hist[b]+=v;total+=v
    p25=wq(hist,tlo,thi,total,.25);p75=wq(hist,tlo,thi,total,.75);center=wq(hist,tlo,thi,total,.5)
    rps=rpm=None
    if i>=20 and cl[i-20]>0:
     r=cl[i]/cl[i-20]-1;rps=r-(sr.get((l2,ds[i])) or 0);rpm=r-(mr.get(ds[i]) or 0)
    v20=(vs[i+1]-vs[max(0,i-19)])/max(1,min(20,i+1));part=v20/baseline if baseline and baseline>0 else None
    band=lambda k,x: None if x is None else ('LOW' if x<bands[k][0] else 'HIGH' if x>=bands[k][1] else 'MID')
    bs, bm, bp=band('rps',rps),band('rpm',rpm),band('part',part)
    prev_state=state
    if bs=='LOW' and bm=='LOW' and (cl[i]<p25 or bp=='LOW'):state='DECAYING'
    elif (bs=='HIGH' or bm=='HIGH') and bp!='LOW':state='STRENGTHENING'
    else:state='HOLDING'
    if state=='STRENGTHENING':ever=True
    eligible=(i-s+1)>=10 and ever and state in ('HOLDING','STRENGTHENING')
    zone=eligible and p25<=cl[i]<=center*1.05 and bp!='LOW' and reg not in ('R_DEPRESSED','R_RISK_OFF')
    if zone and trigger is None:trigger=ds[i]
    snap={'i':i,'date':ds[i],'prev_state':prev_state,'state':state,'rps':rps,'rpm':rpm,'part':part,'close':cl[i],'p25':p25,'center':center,'bs':bs,'bm':bm,'bp':bp,'eligible':eligible,'zone':zone,'ever':ever}
   ep=e['episode_id']; lifecycle.append({'episode_id':ep,'stock':code,'asof':day,'state':state,'terminal':e['terminal'],'end':e['end']}); zones.append({'episode_id':ep,'stock':code,'asof':day,'primary_zone':trigger==day,'trigger_date':trigger})
   if trigger==day:decisions.append({'decision_id':f'{ep}@{day}','episode_id':ep,'stock':code,'decision':'ENTER','entry_mode':'PRIMARY_ZONE','data_asof':day,'market_permission':reg,'lifecycle_state':state})
   if collect_trace and snap is not None:
    rd=lambda x: None if x is None else round(x,6)
    traces['lifecycle'].append({'episode_id':ep,'stock':code,'asof':day,'last_bar':snap['date'],'rule_id':'L4_STATE_V1','inputs':{'rps':rd(snap['rps']),'rpm':rd(snap['rpm']),'part':rd(snap['part']),'close':snap['close'],'p25':rd(snap['p25'])},'predicates':{'rps_band':snap['bs'],'rpm_band':snap['bm'],'part_band':snap['bp'],'close_below_p25':snap['close']<snap['p25']},'previous_state':snap['prev_state'],'next_state':snap['state']})
    traces['primary_zone'].append({'episode_id':ep,'stock':code,'asof':day,'last_bar':snap['date'],'rule_id':'PZ_V1','inputs':{'close':snap['close'],'p25':rd(snap['p25']),'center_x1.05':rd(snap['center']*1.05),'part_band':snap['bp'],'regime':reg,'days_since_start':snap['i']-s+1,'ever_strengthening':snap['ever']},'predicates':{'eligible':snap['eligible'],'price_in_band':snap['p25']<=snap['close']<=snap['center']*1.05,'part_not_low':snap['bp']!='LOW','regime_ok':reg not in ('R_DEPRESSED','R_RISK_OFF')},'primary_zone_today':snap['zone'],'first_trigger_today':trigger==day})
    if trigger==day:
     traces['decision'].append({'episode_id':ep,'stock':code,'asof':day,'rule_id':'DEC_ENTER_V1','market_permission':reg,'position_before':0,'position_after':1,'decision':'ENTER','position_transition':'OPEN_PRIMARY_ZONE','lifecycle_state':state})
    elif no_action_seen<no_action_trace_cap:
     no_action_seen+=1
     traces['decision'].append({'episode_id':ep,'stock':code,'asof':day,'rule_id':'DEC_NO_ACTION_V1','market_permission':reg,'position_before':0,'position_after':0,'decision':'NO_ACTION','position_transition':'NONE','lifecycle_state':state})
 out=Path(out); inputs={'l1':str(DATA/'sector_axes/l1_market_axes.json.gz'),'l2':str(DATA/'sector_axes/l2_four_axes.json.gz'),'bands':str(ROOT/'docs/cd/cd5bd_results.json'),'episodes':str(DATA/'l4_episodes.json.gz')}
 payloads={'lifecycle':lifecycle,'primary_zone':zones,'decisions':{'data_asof':day,'decisions':decisions,'positions':[],'terminals':[],'p0_regression_checked':False}}
 for kind,payload in payloads.items():
  raw=canon(payload)+b'\n';content=gzip.compress(raw,mtime=0);path=out/kind/f'{day}.json.gz';path.parent.mkdir(parents=True,exist_ok=True)
  if path.exists() and path.read_bytes()!=content:raise RuntimeError(f'overwrite forbidden {path}')
  if not path.exists():path.write_bytes(content)
  meta={'asof':day,'artifact_type':kind,'authority_status':'ROUND1_FROZEN','producer_commit':'2105cc3','freeze_version':'round1-freeze-v1','input_artifacts':inputs,'input_sha256':{k:sha(Path(v).read_bytes()) for k,v in inputs.items()},'producer_code_sha256':sha(Path(__file__).read_bytes()),'output_sha256':sha(content),'materialized_at':datetime.now(timezone.utc).isoformat(),'policy_mutation':False}
  path.with_suffix('.manifest.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2)+'\n')
 summary={'day':day,'status':'AUTHORITY_MATERIALIZED','counts':{k:(len(v) if isinstance(v,list) else len(v['decisions'])) for k,v in payloads.items()}}
 return summary,traces

def main():
 p=argparse.ArgumentParser();p.add_argument('--day',required=True);p.add_argument('--out',default=str(DATA/'shadow_authority'));p.add_argument('--trace-out');a=p.parse_args()
 summary,traces=materialize_day(a.day,a.out,collect_trace=bool(a.trace_out))
 if a.trace_out:
  tp=Path(a.trace_out);tp.parent.mkdir(parents=True,exist_ok=True);tp.write_bytes(gzip.compress(canon(traces)+b'\n',mtime=0))
 print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
