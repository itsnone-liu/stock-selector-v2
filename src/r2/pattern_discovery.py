#!/usr/bin/env python3
"""R2 §15-18: pattern discovery vs matched controls, path census, probability lift."""
from __future__ import annotations
import argparse,json
from collections import defaultdict,Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
LABELS={'M60_50':('f60',0.50),'M120_100':('f120',1.00),'M250_200':('f250',2.00)}
def load(path):
 rows=[]
 with open(path) as f:
  for line in f: rows.append(json.loads(line))
 return rows
def era(ym): return '2021-2023' if ym<'2024-01' else '2024-2026'
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--panel',default=str(ROOT/'data/r2/panel_monthly.jsonl'));ap.add_argument('--out',default=str(ROOT/'data/r2/discovery_v1.json'));a=ap.parse_args()
 rows=load(a.panel)
 for r in rows: r['era']=era(r['ym'])
 out={'stage':'R2-3/R2-4 v1','evidence_families_available':['E1','E2','E3'],'pending':['E4 ownership','E5 public signals','E6 sector context']}
 # 1) base rates & lift by state
 for lname,(fk,thr) in LABELS.items():
  for e in ('2021-2023','2024-2026'):
   seg=[r for r in rows if r['era']==e and r.get(fk) is not None]
   base=sum(r[fk]>=thr for r in seg)/len(seg) if seg else None
   by=defaultdict(list)
   for r in seg: by[r['state']].append(r[fk]>=thr)
   out.setdefault('lift_by_state',{})[f'{lname}|{e}']={'base':round(base,5) if base is not None else None,
    'states':{s:{'n':len(v),'p':round(sum(v)/len(v),4),'lift':round((sum(v)/len(v))/base,2) if base else None} for s,v in sorted(by.items())}}
 # 2) matched controls: same era+ym, pos250 within .15, vol_ratio20 within .4, control label=0
 feats=['band_contract60','cost_migrate60','dd_shallow','updown_vol20','vol_conv','profit_vs_cost','band_width']
 fk,thr=LABELS['M120_100']
 cases=[r for r in rows if r.get(fk) is not None and r[fk]>=thr]
 buckets=defaultdict(list)
 for r in rows:
  if r.get(fk) is None: continue
  buckets[(r['era'],r['ym'],round((r.get('pos250') or 0)/0.15))].append(r)
 diffs={f:[] for f in feats}; lockdiff=[]; supdiff=[]
 used=0
 for cse in cases:
  cand=buckets.get((cse['era'],cse['ym'],round((cse.get('pos250') or 0)/0.15)),[])
  ctr=[x for x in cand if x[fk]<thr and abs((x.get('vol_ratio20') or 1)-(cse.get('vol_ratio20') or 1))<0.4][:3]
  if not ctr: continue
  used+=1
  for f in feats:
   cv=cse.get(f); tv=sum(x.get(f) or 0 for x in ctr)/len(ctr)
   if cv is not None: diffs[f].append(cv-tv)
  lockdiff.append((cse.get('chip_locking') in('MEDIUM','HIGH'))-sum(x.get('chip_locking') in('MEDIUM','HIGH') for x in ctr)/len(ctr))
  supdiff.append(cse['support_score']-sum(x['support_score'] for x in ctr)/len(ctr))
 out['matched_control']={'label':'M120_100','cases_matched':used,
  'case_minus_control_mean':{f:(round(sum(v)/len(v),4) if v else None) for f,v in diffs.items()},
  'locking_high_excess':round(sum(lockdiff)/len(lockdiff),4) if lockdiff else None,
  'support_score_excess':round(sum(supdiff)/len(supdiff),4) if supdiff else None}
 # 3) path census (§16): compressed state sequences per stock ending in markup vs not
 seq_hit=Counter(); seq_all=Counter(); trans=Counter(); acc_before_markup=[]
 bystock=defaultdict(list)
 for r in rows: bystock[r['stock']].append(r)
 for s,rs in bystock.items():
  rs.sort(key=lambda x:x['ym'])
  seq=[r['state'] for r in rs]
  comp=[]
  for st in seq:
   if not comp or comp[-1]!=st: comp.append(st)
  if len(comp)>=2: seq_all['->'.join(comp[-3:])]+=1
  hit=any(r.get('f120') is not None and r['f120']>=1.0 for r in rs)
  if hit and len(comp)>=2: seq_hit['->'.join(comp[-3:])]+=1
  for x,y in zip(comp,comp[1:]): trans[(x,y)]+=1
  if hit:
   run=0
   for st in reversed(seq):
    if st in('ACCUMULATION','ACCUMULATION_MATURE'): run+=1
    else: break
   acc_before_markup.append(run)
 out['path_census']={'top_sequences_overall':seq_all.most_common(10),
  'top_sequences_leading_to_markup_120d':seq_hit.most_common(10),
  'median_months_accumulation_before_markup':sorted(acc_before_markup)[len(acc_before_markup)//2] if acc_before_markup else None,
  'transition_counts_top':[(f'{k[0]}->{k[1]}',v) for k,v in trans.most_common(15)]}
 # 4) score-bucket calibration (rule engine v1, §18 substitute)
 fk,thr=LABELS['M120_100']
 for e in ('2021-2023','2024-2026'):
  seg=[r for r in rows if r['era']==e and r.get(fk) is not None]
  base=sum(r[fk]>=thr for r in seg)/len(seg) if seg else None
  by=defaultdict(list)
  for r in seg: by[r['support_score']].append(r[fk]>=thr)
  out.setdefault('calibration_by_support_score',{})[e]={'base':round(base,5) if base else None,
   'buckets':{str(k):{'n':len(v),'p':round(sum(v)/len(v),4),'lift':round((sum(v)/len(v))/base,2) if base else None} for k,v in sorted(by.items())}}
 Path(a.out).write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'out':a.out,'cases_M120_100':len(cases),'matched':out['matched_control']['cases_matched'],'median_acc_months':out['path_census']['median_months_accumulation_before_markup']},ensure_ascii=False))
if __name__=='__main__':main()
