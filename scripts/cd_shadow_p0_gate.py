#!/usr/bin/env python3
import argparse,json
from pathlib import Path
def main():
 p=argparse.ArgumentParser();p.add_argument('package');a=p.parse_args();r=Path(a.package); expected=json.loads((r/'expected_event.json').read_text()); actual=json.loads((r/'actual_event.json').read_text()); checks={
 'nonempty_anchors':bool(expected),'event_identity_preserved':len({x.get('trade_id') for x in expected})==len(expected),'expected_actual_identity':[{x.get('trade_id') for x in expected}=={x.get('trade_id') for x in actual}][0],
 'actual_position_after_zero':all(x.get('position_after')==0 for x in actual),'actual_independent_producer':all(x.get('actual_producer')=='independent_accounting_replay' for x in actual),
 'reduce_decision':all(x.get('decision')=='REDUCE' for x in expected),'position_before_positive':all(x.get('position_before',0)>0 for x in expected),'position_after_zero':all(x.get('remaining_position')==0 for x in expected),'exactly_one_close':all(x.get('terminal_reason')=='REDUCED_OUT' for x in expected),'ordering':all(x.get('ordering')==['close_record_created','position_discarded'] for x in expected),'conservation':json.loads((r/'accounting_proof.json').read_text()).get('position_conservation') is True,'no_silent_disappearance':len(expected)==len(actual)}
 out={'gate':'G-SHADOW-AUTHORITY-P0-REGRESSION','status':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'n_anchors':len(expected)};print(json.dumps(out,ensure_ascii=False,indent=2));raise SystemExit(0 if out['status']=='PASS' else 2)
if __name__=='__main__':main()
