#!/usr/bin/env python3
import json
from csr8_batch_h_orchestrator import (snapshot_transcript,
    reviewer_id_novelty_spot_check, complete_batch)

def sample(run='run-new', session='session-new', prefix='executor prior transcript'):
    return {'reviewer_operation':'ANNOTATION','reviewer_run_id':run,
            'reviewer_session_id':session,
            'pre_spawn_snapshot':snapshot_transcript(prefix, 42)}

def rejects(fn):
    try: fn()
    except ValueError: return
    raise AssertionError('negative control accepted')

def main():
    ok=reviewer_id_novelty_spot_check(7, ['old'], [sample()])
    assert ok['evidence'][0]['premature_run_id_found'] is False
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [sample(prefix='x run-new')]))
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [sample(prefix='x session-new')]))
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [dict(sample(), pre_spawn_snapshot={})]))
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [sample(run='same',session='same')]))
    rejects(lambda: reviewer_id_novelty_spot_check(7, [], [sample(run='',session='s')]))
    evidence=[sample(run=f'r{i}',session=f's{i}') for i in range(2)]
    done=complete_batch(7, list(range(7,15)), evidence)
    assert done['status']=='BATCH_COMPLETE' and done['batch_end']==14
    print(json.dumps({'status':'PASS','legal_prefix':'PASS',
      'premature_run_id':'PASS','premature_session_id':'PASS',
      'missing_transcript':'PASS','duplicate_empty':'PASS',
      'hard_batch_completion':'PASS'},separators=(',',':')))
if __name__=='__main__': main()
