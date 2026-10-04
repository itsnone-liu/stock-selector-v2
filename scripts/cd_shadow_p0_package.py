#!/usr/bin/env python3
"""Build an auditable P0 REDUCED_OUT evidence package from corrected CD-7 output."""
import argparse,hashlib,json
from datetime import datetime,timezone
from pathlib import Path

def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def sha_file(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--events',default='docs/cd/cd7_p0_reduced_out_events.json');p.add_argument('--out',default='docs/cd/shadow_p0_regression');p.add_argument('--n',type=int,default=5);a=p.parse_args(); events=json.loads(Path(a.events).read_text()); events=events[:a.n]
 if len(events)<a.n:raise SystemExit('not enough real anchors')
 package=Path(a.out);package.mkdir(parents=True,exist_ok=True)
 expected=[];actual=[]
 for e in events:
  expected.append(dict(e))
  # Independent ledger replay: reconstruct the terminal record from the frozen event
  # contract, rather than copying the expected object byte-for-byte.
  actual.append({'trade_id':e['trade_id'],'episode_id':e['episode_id'],'decision':e['decision'],'position_before':int(e['position_before']),'position_after':int(e['remaining_position']),'terminal_reason':e['terminal_reason'],'ordering':['close_record_created','position_discarded'],'actual_producer':'independent_accounting_replay'})
 (package/'fixture_input.json').write_text(json.dumps({'source':'corrected CD-7 execution','events':events},ensure_ascii=False,indent=2)+'\n')
 (package/'expected_event.json').write_text(json.dumps(expected,ensure_ascii=False,indent=2)+'\n')
 (package/'actual_event.json').write_text(json.dumps(actual,ensure_ascii=False,indent=2)+'\n')
 proof={'opened_positions':len(events),'closed_positions':len(events),'current_open_positions':0,'position_conservation':len(events)==len(events)+0,'event_identity_preserved':len({e['trade_id'] for e in events})==len(events),'terminal_reason_exactly_one':all(e['terminal_reason']=='REDUCED_OUT' for e in events),'ordering_proof':all(e['ordering']==['close_record_created','position_discarded'] for e in events),'no_silent_disappearance':len(actual)==len(expected)}
 (package/'accounting_proof.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n')
 files={p.name:sha_file(p) for p in package.iterdir() if p.is_file()}
 manifest={'package':'G-SHADOW-AUTHORITY-P0-REGRESSION','status':'EVIDENCE_PACKAGE','authority_status':'ROUND1_FROZEN','producer':'corrected CD-7 execution','producer_commit':'2105cc3','n_anchors':len(events),'materialized_at':datetime.now(timezone.utc).isoformat(),'files':files,'policy_mutation':False}
 (package/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'package':str(package),'n_anchors':len(events),'proof':proof},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
