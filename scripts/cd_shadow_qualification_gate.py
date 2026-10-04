#!/usr/bin/env python3
"""G-SHADOW-ACTION-QUALIFICATION: accumulate coverage over REAL qualification days only.

Drill days are machinery validation and never count. Historical semantic parity is
permanently EVIDENCE_UNAVAILABLE (ROUND1_ACTION_SEMANTIC_EVIDENCE_GAP); this gate
substitutes prospective evidence, it does not rewrite history.
"""
import argparse,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; QUAL=ROOT/'data/cd/shadow_qualification'
REQUIRED={'lifecycle':{'STRENGTHENING','HOLDING','DECAYING','TERMINAL_RELEVANT'},'primary_zone':{True,False},'decision':{'ENTER','NO_ACTION','REDUCE','EXIT'}}
# REDUCE/EXIT accrue only after a real ENTER opens positions on a genuine qualification day.

def scan():
 days=[]
 if QUAL.exists():
  for d in sorted(QUAL.iterdir()):
   snap=d/'qualification_snapshot.json'; aud=d/'independent_audit.json'
   if not snap.exists(): continue
   s=json.loads(snap.read_text()); entry={'day':d.name,'mode':s.get('mode'),'forever_non_evidence':s.get('forever_non_evidence') is True}
   if aud.exists():
    a=json.loads(aud.read_text()); entry.update({'audited':True,'all_exact_match':a.get('all_exact_match'),'n_anchors':a.get('n_anchors'),'coverage':a.get('coverage')})
   else: entry['audited']=False
   days.append(entry)
 return days

def main():
 days=scan(); real=[d for d in days if d['mode']=='real' and d.get('audited') and d.get('all_exact_match') is True and d['forever_non_evidence']]
 drills=[d for d in days if d['mode']=='drill']
 cov={'lifecycle_states':set(),'primary_zone':set(),'decisions':set()}
 for d in real:
  c=d.get('coverage') or {}
  cov['lifecycle_states']|=set(c.get('lifecycle_states') or []); cov['primary_zone']|=set(c.get('primary_zone') or []); cov['decisions']|=set(c.get('decisions') or [])
 missing={
  'lifecycle':sorted(REQUIRED['lifecycle']-cov['lifecycle_states']),
  'primary_zone':sorted({True,False}-cov['primary_zone'],key=str),
  'decision':sorted(REQUIRED['decision']-cov['decisions'])}
 complete=not any(missing.values())
 result={'gate':'G-SHADOW-ACTION-QUALIFICATION','status':'PASS' if complete and real else 'PENDING','real_qualification_days':len(real),'drill_days':[d['day'] for d in drills],'coverage':{'lifecycle_states':sorted(cov['lifecycle_states']),'primary_zone':sorted(cov['primary_zone'],key=str),'decisions':sorted(cov['decisions'])},'missing':missing,'historical_note':'Historical Level-B semantic parity is permanently EVIDENCE_UNAVAILABLE and is not part of this gate.'}
 print(json.dumps(result,ensure_ascii=False,indent=2)); raise SystemExit(0 if result['status']=='PASS' else 2)
if __name__=='__main__':main()
