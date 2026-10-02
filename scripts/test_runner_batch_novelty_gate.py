#!/usr/bin/env python3
import hashlib,json,tempfile
from pathlib import Path
from csr8_batch_h_orchestrator import canon,capture_pre_spawn_snapshot,reviewer_id_novelty_spot_check,complete_batch

def ledger_file():
 body={'campaign_id':'test','created_at':'x','input_commitment_sha256':'0'*64,'operation':'ANNOTATION','ordinal':7,'prev_review_hash':'0'*64,'reviewer_run_id':'run-real','reviewer_session_id':'session-real','sequence':0,'state':'APPROVE'};body['review_hash']=hashlib.sha256(canon(body).encode()).hexdigest();p=Path(tempfile.mktemp());p.write_text(canon(body)+'\n');return p,body

def fixture(body, source_text='executor prior transcript'):
 d=Path(tempfile.mkdtemp());src=d/'executor.transcript';src.write_text(source_text);snap,anchor=capture_pre_spawn_snapshot(src,'executor-session',d/'snapshot.json',d/'anchor.json',len(source_text.encode()));return snap,d/'anchor.json'

def sample(body,snap,anchor):
 return {'ordinal':7,'reviewer_operation':'ANNOTATION','ledger_sequence':0,'review_hash':body['review_hash'],'reviewer_run_id':body['reviewer_run_id'],'reviewer_session_id':body['reviewer_session_id'],'executor_session_id':'executor-session','pre_spawn_snapshot':snap,'snapshot_anchor_path':str(anchor)}
def rejects(fn):
 try:fn()
 except ValueError:return
 raise AssertionError('negative control accepted')
def main():
 p,b=ledger_file();snap,a=fixture(b);ok=reviewer_id_novelty_spot_check(7,['old'],[sample(b,snap,a)],str(p));assert ok['evidence'][0]['source_prefix_bytes']==len('executor prior transcript'.encode())
 x=sample(b,snap,a);x['reviewer_run_id']='fake';rejects(lambda:reviewer_id_novelty_spot_check(7,[],[x],str(p)))
 x=sample(b,snap,a);x['review_hash']='f'*64;rejects(lambda:reviewer_id_novelty_spot_check(7,[],[x],str(p)))
 bad=dict(snap);bad['pre_spawn_sequence_cutoff']=None;rejects(lambda:reviewer_id_novelty_spot_check(7,[],[dict(sample(b,snap,a),pre_spawn_snapshot=bad)],str(p)))
 bad=dict(snap);bad['pre_spawn_transcript_length']=999;rejects(lambda:reviewer_id_novelty_spot_check(7,[],[dict(sample(b,snap,a),pre_spawn_snapshot=bad)],str(p)))
 rejects(lambda:reviewer_id_novelty_spot_check(7,['run-real'],[sample(b,snap,a)],str(p)))
 done=complete_batch(7,list(range(7,15)),[sample(b,snap,a)],str(p));assert done['status']=='BATCH_COMPLETE'
 print(json.dumps({'status':'PASS','source_capture':'PASS','fake_id':'PASS','ledger_mismatch':'PASS','cutoff_length':'PASS','previous_overlap':'PASS','hard_batch_completion':'PASS'},separators=(',',':')))
if __name__=='__main__':main()
