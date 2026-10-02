#!/usr/bin/env python3
import hashlib, json, tempfile
from pathlib import Path
from csr8_batch_h_orchestrator import (canon, snapshot_transcript,
    reviewer_id_novelty_spot_check, complete_batch)

def ledger_file(run='run-real', session='session-real', ordinal=7, op='ANNOTATION'):
    body={'campaign_id':'test','created_at':'x','input_commitment_sha256':'0'*64,
          'operation':op,'ordinal':ordinal,'prev_review_hash':'0'*64,
          'reviewer_run_id':run,'reviewer_session_id':session,'sequence':0,
          'state':'APPROVE'}
    body['review_hash']=hashlib.sha256(canon(body).encode()).hexdigest()
    p=Path(tempfile.mktemp())
    p.write_text(canon(body)+'\n')
    return p, body

def sample(body, snap):
    return {'ordinal':body['ordinal'],'reviewer_operation':body['operation'],
      'ledger_sequence':body['sequence'],'review_hash':body['review_hash'],
      'reviewer_run_id':body['reviewer_run_id'],
      'reviewer_session_id':body['reviewer_session_id'],
      'pre_spawn_snapshot':snap}

def rejects(fn):
    try: fn()
    except ValueError: return
    raise AssertionError('negative control accepted')

def main():
    path, body=ledger_file()
    snap=snapshot_transcript('executor prior transcript', 42)
    ok=reviewer_id_novelty_spot_check(7, ['old'], [sample(body,snap)], str(path))
    assert ok['evidence'][0]['pre_spawn_sequence_cutoff']==42
    fake=sample(body,snap); fake['reviewer_run_id']='fake-run'
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [fake], str(path)))
    fake=sample(body,snap); fake['review_hash']='f'*64
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [fake], str(path)))
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [sample(body,{**snap,'pre_spawn_sequence_cutoff':None})], str(path)))
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [sample(body,{**snap,'pre_spawn_transcript_length':999})], str(path)))
    rejects(lambda: reviewer_id_novelty_spot_check(7, [body['reviewer_run_id']], [sample(body,snap)], str(path)))
    done=complete_batch(7, list(range(7,15)), [sample(body,snap)], str(path))
    assert done['status']=='BATCH_COMPLETE' and done['batch_end']==14
    print(json.dumps({'status':'PASS','fake_id':'PASS','ledger_mismatch':'PASS',
      'missing_cutoff':'PASS','length_mismatch':'PASS','previous_overlap':'PASS',
      'hard_batch_completion':'PASS'},separators=(',',':')))
if __name__=='__main__': main()
