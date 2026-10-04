#!/usr/bin/env python3
"""Append-only prospective outcome ledger for frozen Shadow decisions."""
from __future__ import annotations
import argparse, json
from datetime import date
from pathlib import Path
HORIZONS=(5,20,60)
HORIZON_SEMANTICS='trading_days'
ENTRY_PRICE_DEFINITION='decision-day PRIMARY_ZONE close'
BENCHMARK_DEFINITION='frozen market benchmark as-of decision day'
def load(path): return json.loads(path.read_text()) if path.exists() else []
def append_decisions(path: Path, decisions: list[dict], decision_date: str):
 rows=load(path); known={r['decision_id'] for r in rows}
 for d in decisions:
  did=d.get('decision_id')
  if not did or did in known: continue
  rows.append({'decision_id':did,'episode_id':d.get('episode_id'),'decision_date':decision_date,'horizon_semantics':HORIZON_SEMANTICS,'entry_price_definition':d.get('entry_price_definition',ENTRY_PRICE_DEFINITION),'benchmark_definition':d.get('benchmark_definition',BENCHMARK_DEFINITION),**{f'H{h}':{'status':'PENDING'} for h in HORIZONS}})
 path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n'); return rows
def mature(path: Path, evaluations: list[dict]):
 rows=load(path); by={r['decision_id']:r for r in rows}
 for ev in evaluations:
  did=ev.get('decision_id'); h=ev.get('horizon')
  if did in by and h in HORIZONS and by[did][f'H{h}'].get('status')=='PENDING': by[did][f'H{h}']={'status':'MATURED','matured_at':ev['matured_at'],**{k:ev[k] for k in ('ret_abs','ret_rel','MAE','adverse') if k in ev}}
 path.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n'); return rows
def main():
 p=argparse.ArgumentParser(); p.add_argument('ledger'); p.add_argument('--decisions'); p.add_argument('--date',default=date.today().isoformat()); a=p.parse_args()
 if a.decisions: append_decisions(Path(a.ledger),json.loads(Path(a.decisions).read_text()),a.date)
 print(json.dumps({'ledger':a.ledger,'rows':len(load(Path(a.ledger)))},ensure_ascii=False))
if __name__=='__main__': main()
