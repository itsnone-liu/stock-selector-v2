#!/usr/bin/env python3
"""Mandatory Batch-H reviewer novelty boundary with source-bound evidence."""
import argparse, hashlib, json, os, stat
from pathlib import Path
BATCH_SIZE = 8
SNAPSHOT_VERSION = 'csr8-reviewer-novelty-snapshot-v3'
ANCHOR_VERSION = 'csr8-reviewer-novelty-anchor-v1'

def canon(obj): return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
def digest(raw): return hashlib.sha256(raw).hexdigest()
def batch_boundary(batch_start, completed_count=BATCH_SIZE):
    if batch_start < 1 or completed_count != BATCH_SIZE: raise ValueError('batch must contain exactly eight ordinals')
    return batch_start + completed_count - 1

def capture_pre_spawn_snapshot(transcript_path, executor_session_id, snapshot_path, anchor_path, sequence_cutoff=None):
    """Capture source bytes and anchor them before reviewer spawn; fail closed."""
    src=Path(transcript_path); out=Path(snapshot_path); anchor=Path(anchor_path)
    if not executor_session_id or not src.is_file(): raise ValueError('real transcript source required')
    st=os.stat(src); raw=src.read_bytes()
    if sequence_cutoff is None: sequence_cutoff=len(raw)
    if not isinstance(sequence_cutoff,int) or sequence_cutoff<0 or sequence_cutoff>len(raw): raise ValueError('invalid source cutoff')
    prefix=raw[:sequence_cutoff]; out.parent.mkdir(parents=True,exist_ok=True); anchor.parent.mkdir(parents=True,exist_ok=True)
    snap={'snapshot_version':SNAPSHOT_VERSION,'executor_session_id':executor_session_id,
          'source_path':str(src.resolve()),'source_device':st.st_dev,'source_inode':st.st_ino,
          'source_prefix_bytes':sequence_cutoff,'transcript_prefix':prefix.decode('utf-8'),
          'pre_spawn_transcript_sha256':digest(prefix),'pre_spawn_transcript_length':len(prefix),
          'pre_spawn_sequence_cutoff':sequence_cutoff}
    data=canon(snap).encode(); fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try: os.write(fd,data); os.fsync(fd)
    finally: os.close(fd)
    os.chmod(out,0o400)
    afd=os.open(anchor,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    anch={'anchor_version':ANCHOR_VERSION,'executor_session_id':executor_session_id,
          'source_path':str(src.resolve()),'source_device':st.st_dev,'source_inode':st.st_ino,
          'pre_spawn_sequence_cutoff':sequence_cutoff,'snapshot_sha256':digest(data)}
    try: os.write(afd,canon(anch).encode()); os.fsync(afd)
    finally: os.close(afd)
    os.chmod(anchor,0o400)
    for p in (out.parent,anchor.parent):
        d=os.open(p,os.O_RDONLY); os.fsync(d); os.close(d)
    return snap, anch

def snapshot_transcript(prefix, sequence_cutoff=None, path=None):
    """Legacy test constructor; production evidence must use source capture."""
    if path is not None: raise ValueError('use capture_pre_spawn_snapshot for persisted evidence')
    if not isinstance(prefix,str) or not prefix: raise ValueError('missing transcript')
    if not isinstance(sequence_cutoff,int) or sequence_cutoff<0: raise ValueError('cutoff required')
    raw=prefix.encode(); return {'snapshot_version':SNAPSHOT_VERSION,'executor_session_id':'TEST_ONLY',
      'source_path':'TEST_ONLY','source_device':0,'source_inode':0,'source_prefix_bytes':len(raw),
      'transcript_prefix':prefix,'pre_spawn_transcript_sha256':digest(raw),
      'pre_spawn_transcript_length':len(raw),'pre_spawn_sequence_cutoff':sequence_cutoff}

def load_ledger(path):
    rows=[json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    if not rows: raise ValueError('review ledger empty')
    for i,row in enumerate(rows):
        if row.get('sequence')!=i or not row.get('review_hash'): raise ValueError('ledger sequence drift')
        h=row['review_hash']; body=dict(row); body.pop('review_hash')
        if digest(canon(body).encode())!=h: raise ValueError('ledger hash mismatch')
        if i and row.get('prev_review_hash')!=rows[i-1].get('review_hash'): raise ValueError('ledger chain break')
    return rows

def _read_snapshot(snap, anchor_path=None):
    if isinstance(snap,(str,Path)): snap=json.loads(Path(snap).read_text())
    if not isinstance(snap,dict) or snap.get('snapshot_version')!=SNAPSHOT_VERSION: raise ValueError('invalid snapshot')
    p=snap.get('transcript_prefix'); cutoff=snap.get('pre_spawn_sequence_cutoff')
    if not isinstance(p,str) or not p or not isinstance(cutoff,int) or cutoff<0: raise ValueError('missing source cutoff')
    raw=p.encode()
    if snap.get('source_prefix_bytes')!=len(raw) or snap.get('pre_spawn_transcript_length')!=len(raw): raise ValueError('source length mismatch')
    if snap.get('pre_spawn_transcript_sha256')!=digest(raw): raise ValueError('snapshot hash mismatch')
    if anchor_path is not None:
        a=json.loads(Path(anchor_path).read_text()); data=canon(snap).encode()
        if a.get('anchor_version')!=ANCHOR_VERSION or a.get('snapshot_sha256')!=digest(data): raise ValueError('anchor mismatch')
        for k in ('executor_session_id','source_path','source_device','source_inode','pre_spawn_sequence_cutoff'):
            if a.get(k)!=snap.get(k): raise ValueError('anchor provenance mismatch')
    return snap,p

def reviewer_id_novelty_spot_check(batch_start, previous_ids, samples, ledger_path, completed_count=BATCH_SIZE):
    end=batch_boundary(batch_start,completed_count)
    if not samples: raise ValueError('novelty evidence required')
    rows=load_ledger(ledger_path); ids=[]; evidence=[]
    for s in samples:
        req=('ordinal','reviewer_operation','ledger_sequence','review_hash','reviewer_run_id','reviewer_session_id','pre_spawn_snapshot','snapshot_anchor_path')
        if any(k not in s for k in req): raise ValueError('incomplete source-bound evidence')
        seq=s['ledger_sequence']
        if not isinstance(seq,int) or seq<0 or seq>=len(rows): raise ValueError('ledger sequence range')
        row=rows[seq]
        if (s['ordinal'],s['reviewer_operation'],s['review_hash'])!=(row.get('ordinal'),row.get('operation'),row.get('review_hash')): raise ValueError('ledger row mismatch')
        if (s['reviewer_run_id'],s['reviewer_session_id'])!=(row.get('reviewer_run_id'),row.get('reviewer_session_id')): raise ValueError('ledger ID mismatch')
        snap,p=_read_snapshot(s['pre_spawn_snapshot'],s['snapshot_anchor_path'])
        if s.get('executor_session_id')!=snap.get('executor_session_id'): raise ValueError('executor session mismatch')
        pr,ps=row['reviewer_run_id'] in p,row['reviewer_session_id'] in p
        if pr or ps: raise ValueError('premature reviewer ID')
        ids += [row['reviewer_run_id'],row['reviewer_session_id']]
        evidence.append({'ordinal':s['ordinal'],'reviewer_operation':s['reviewer_operation'],'ledger_sequence':seq,'review_hash':row['review_hash'],'reviewer_run_id':row['reviewer_run_id'],'reviewer_session_id':row['reviewer_session_id'],'executor_session_id':snap['executor_session_id'],'source_path':snap['source_path'],'source_prefix_bytes':snap['source_prefix_bytes'],'pre_spawn_transcript_sha256':snap['pre_spawn_transcript_sha256'],'pre_spawn_transcript_length':snap['pre_spawn_transcript_length'],'pre_spawn_sequence_cutoff':snap['pre_spawn_sequence_cutoff'],'snapshot_anchor_path':s['snapshot_anchor_path'],'premature_run_id_found':False,'premature_session_id_found':False})
    if len(ids)!=len(set(ids)) or set(previous_ids)&set(ids): raise ValueError('reviewer duplicate/previous overlap')
    return {'status':'PASS','batch_start':batch_start,'batch_end':end,'batch_size':completed_count,'checked_samples':len(samples),'novelty':True,'evidence':evidence,'attestation_level':'PLATFORM_OPAQUE_SUBAGENT'}

def complete_batch(batch_start,completed_ordinals,novelty_evidence,ledger_path,previous_ids=()):
    end=batch_boundary(batch_start,len(completed_ordinals))
    if list(completed_ordinals)!=list(range(batch_start,end+1)): raise ValueError('non-contiguous batch')
    return {'status':'BATCH_COMPLETE','batch_start':batch_start,'batch_end':end,'novelty_gate':reviewer_id_novelty_spot_check(batch_start,previous_ids,novelty_evidence,ledger_path)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--batch-start',type=int,required=True); ap.add_argument('--completed-ordinal',type=int,action='append',required=True); ap.add_argument('--novelty-evidence-json',required=True); ap.add_argument('--ledger',required=True); ap.add_argument('--previous-id',action='append',default=[]); a=ap.parse_args()
    print(json.dumps(complete_batch(a.batch_start,a.completed_ordinal,json.loads(Path(a.novelty_evidence_json).read_text()),a.ledger,a.previous_id),sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
