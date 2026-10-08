#!/usr/bin/env python3
"""R2-7c: quarterly ownership change ACROSS breakdown events (the E4 long-window test).
CONTINUED(再跌≥10%) vs STABILIZED(再跌≤3%):
  holders_chg across breakdown (q-2→q+2 quarters), avg_hold_chg, top10_ratio_chg (subset).
Hypothesis: 主力撤退 => holders up / avg_hold down / top10 down before/into continued breakdowns.
"""
from __future__ import annotations
import json,statistics
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; H=ROOT/'data/r2/holders'; I=ROOT/'data/r2/institutional'
def main():
 ev=json.load(open(ROOT/'data/r2/breakdown_aftermath.json'))
 # holders: per code sorted quarterly rows
 qmap={}
 for f in sorted(H.glob('*.json')):
  for r in json.loads(f.read_text())['rows']:
   qmap.setdefault(str(r['code']).zfill(6),[]).append((r['chg_date'],r['holders'],r['avg_hold']))
 for c in qmap: qmap[c].sort()
 imap={}
 for f in sorted(I.glob('*.json')):
  c=f.stem; q=json.loads(f.read_text())['quarters']; imap[c]=sorted(q.items())
 out=[]
 for e in ev:
  c=e['code']; bd=e['ym']  # breakdown month YYYY-MM
  qs=qmap.get(c)
  if not qs: continue
  pre=[q for q in qs if q[0][:7]<=bd][-2:]; post=[q for q in qs if q[0][:7]>bd][:2]
  if len(pre)<2 or len(post)<2: continue
  h0,avg0=pre[-1][1],pre[-1][2]; hp,avgp=post[-1][1],post[-1][2]
  if not(h0 and hp): continue
  row={'code':c,'further':e['further'],'reg':e['reg'],
       'h_chgn':hp/h0-1,'avg_chgn':(avgp/avg0-1) if(avg0 and avgp)else None}
  # window span guard: post[-1] should be within ~3 quarters after breakdown
  q0,q1=pre[-1][0],post[-1][0]
  if q1[:4]==q0[:4] and abs(int(q1[5:7])-int(q0[5:7]))>9: continue
  ii=imap.get(c)
  if ii:
   pr=[x for x in ii if x[0][:7]<=bd][-1:]; po=[x for x in ii if x[0][:7]>bd][:2]
   if pr and po:
    t0=pr[0][1].get('top10_float_ratio'); t1=po[-1][1].get('top10_float_ratio')
    if t0 is not None and t1 is not None: row['top10_chg']=t1-t0
  out.append(row)
 print('events with ownership',len(out),flush=True)
 json.dump(out,open(ROOT/'data/r2/breakdown_owners.json','w'))
 med=statistics.median
 def grp(name,rs):
  if len(rs)<30: print(name,'n',len(rs),'(insufficient)'); return
  h=[r['h_chgn'] for r in rs]; a=[r['avg_chgn'] for r in rs if r['avg_chgn'] is not None]
  t=[r['top10_chg'] for r in rs if 'top10_chg' in r]
  print(f"{name}: n={len(rs)} holders_chg_med={med(h):+.3f} 户均chg_med={med(a):+.3f} top10chg_med={med(t):+.2f}pp(n={len(t)})")
 cont=[r for r in out if r['further']<=-0.10]; stab=[r for r in out if r['further']>=-0.03]
 mid=[r for r in out if -0.10<r['further']<-0.03]
 for g in ('ALL','BULL','BEAR'):
  grp(g+' CONTINUED',[r for r in cont if g=='ALL' or r['reg']==g])
  grp(g+' MID     ',[r for r in mid if g=='ALL' or r['reg']==g])
  grp(g+' STABILIZED',[r for r in stab if g=='ALL' or r['reg']==g])
 grp('21-23 CONT', [r for r in cont if r['code'] and r['further']<=-0.10]) # placeholder era below
if __name__=='__main__':main()
