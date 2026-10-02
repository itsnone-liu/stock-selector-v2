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
    eof = len(raw)
    if sequence_cutoff is None: sequence_cutoff = eof
    if not isinstance(sequence_cutoff,int) or sequence_cutoff != eof:
        raise ValueError('pre-spawn cutoff must equal current transcript EOF')
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

def _read_dsh_snapshot(snap, anchor_path=None):
    """DSH-v4 branch: the frozen raw zstd capture is the trust root; the
    decoded transcript text is a derived product and is re-derived here —
    never trusted from the snapshot alone (ruling 2026-10-02)."""
    import csr8_batch_h_recovery_novelty as rec
    req=('executor_session_id','live_source_path','source_device','source_inode',
         'frozen_capture_path','raw_zstd_sha256','raw_zstd_bytes',
         'pre_spawn_sequence_cutoff','decoder','decoded_sha256','decoded_bytes',
         'source_prefix_bytes','transcript_prefix','pre_spawn_transcript_sha256',
         'pre_spawn_transcript_length')
    if any(k not in snap for k in req): raise ValueError('invalid DSH snapshot: missing fields')
    if snap['pre_spawn_sequence_cutoff']!=snap['raw_zstd_bytes']:
        raise ValueError('invalid DSH snapshot: cutoff != raw EOF')
    frozen=Path(snap['frozen_capture_path'])
    if not frozen.is_file(): raise ValueError('DSH frozen capture missing')
    raw=frozen.read_bytes()
    if len(raw)!=snap['raw_zstd_bytes'] or digest(raw)!=snap['raw_zstd_sha256']:
        raise ValueError('DSH frozen capture hash/length mismatch')
    dec=snap.get('decoder') or {}
    here=Path(__file__).resolve().parent
    if dec.get('decoder_module_sha256')!=digest((here/'csr8_batch_h_recovery_novelty.py').read_bytes()):
        raise ValueError('decoder module hash mismatch')
    if dec.get('entry_gate_sha256')!=digest((here/'csr8_phase_h_entry_gate.py').read_bytes()):
        raise ValueError('decoder entry-gate hash mismatch')
    decoded=rec.decode_transcript_bytes(raw)
    if len(decoded)!=snap['decoded_bytes'] or digest(decoded)!=snap['decoded_sha256']:
        raise ValueError('DSH decoded re-derivation mismatch')
    if snap['pre_spawn_transcript_length']!=len(decoded) or snap['pre_spawn_transcript_sha256']!=digest(decoded):
        raise ValueError('DSH decoded pin mismatch')
    if snap['source_prefix_bytes']!=len(decoded): raise ValueError('DSH source length mismatch')
    p=snap['transcript_prefix']
    if not isinstance(p,str) or p.encode('utf-8')!=decoded:
        raise ValueError('DSH transcript_prefix is not the derived decode product')
    if anchor_path is not None:
        a=json.loads(Path(anchor_path).read_text()); data=canon(snap).encode()
        if a.get('anchor_version')!=DSH_ANCHOR_VERSION or a.get('snapshot_sha256')!=digest(data):
            raise ValueError('anchor mismatch')
        for k in ('executor_session_id','live_source_path','source_device','source_inode',
                  'frozen_capture_path','raw_zstd_sha256','raw_zstd_bytes',
                  'decoded_sha256','pre_spawn_sequence_cutoff'):
            if a.get(k)!=snap.get(k): raise ValueError('anchor provenance mismatch')
    view=dict(snap); view['source_path']=snap['frozen_capture_path']
    return view,p

def _read_snapshot(snap, anchor_path=None):
    if isinstance(snap,(str,Path)): snap=json.loads(Path(snap).read_text())
    if not isinstance(snap,dict): raise ValueError('invalid snapshot')
    if snap.get('snapshot_version')==DSH_SNAPSHOT_VERSION:
        return _read_dsh_snapshot(snap,anchor_path)
    if snap.get('snapshot_version')!=SNAPSHOT_VERSION: raise ValueError('invalid snapshot')
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
        ev={'ordinal':s['ordinal'],'reviewer_operation':s['reviewer_operation'],'ledger_sequence':seq,'review_hash':row['review_hash'],'reviewer_run_id':row['reviewer_run_id'],'reviewer_session_id':row['reviewer_session_id'],'executor_session_id':snap['executor_session_id'],'source_path':snap['source_path'],'source_prefix_bytes':snap['source_prefix_bytes'],'pre_spawn_transcript_sha256':snap['pre_spawn_transcript_sha256'],'pre_spawn_transcript_length':snap['pre_spawn_transcript_length'],'pre_spawn_sequence_cutoff':snap['pre_spawn_sequence_cutoff'],'snapshot_anchor_path':s['snapshot_anchor_path'],'premature_run_id_found':False,'premature_session_id_found':False}
        for k in ('frozen_capture_path','raw_zstd_sha256','raw_zstd_bytes','decoded_sha256','live_source_path'):
            if snap.get(k) is not None: ev[k]=snap[k]
        evidence.append(ev)
    if len(ids)!=len(set(ids)) or set(previous_ids)&set(ids): raise ValueError('reviewer duplicate/previous overlap')
    return {'status':'PASS','batch_start':batch_start,'batch_end':end,'batch_size':completed_count,'checked_samples':len(samples),'novelty':True,'evidence':evidence,'attestation_level':'PLATFORM_OPAQUE_SUBAGENT'}

def complete_batch(batch_start,completed_ordinals,novelty_evidence,ledger_path,previous_ids=(),previous_batch_record=None):
    end=batch_boundary(batch_start,len(completed_ordinals))
    if list(completed_ordinals)!=list(range(batch_start,end+1)): raise ValueError('non-contiguous batch')
    if previous_batch_record is not None:
        derived=derive_previous_ids(previous_batch_record)
        if previous_ids and tuple(sorted(previous_ids))!=tuple(derived):
            raise ValueError('manual previous_ids conflict with previous_batch_record derivation')
        previous_ids=derived
    return {'status':'BATCH_COMPLETE','batch_start':batch_start,'batch_end':end,'novelty_gate':reviewer_id_novelty_spot_check(batch_start,previous_ids,novelty_evidence,ledger_path)}

def complete_batch_recovery(batch_start,completed_ordinals,evidence_path,ledger_path,previous_ids=()):
    """BATCH-H-RECOVERY-ERRATUM-1 explicit recovery branch (ordinal 7-14 ONLY).

    Hard gates: batch contiguity; independent re-derivation of APPEND_ONLY_
    RECOVERED_PREFIX evidence from the frozen transcript capture; full ledger
    coverage of every batch-ordinal row (no sampling); ID uniqueness and
    previous-batch overlap.  Realtime pre-spawn capture stays NOT_AVAILABLE
    and is reported as such — never rewritten as if captured.
    """
    import csr8_batch_h_recovery_novelty as rec
    end=batch_boundary(batch_start,len(completed_ordinals))
    if list(completed_ordinals)!=list(range(batch_start,end+1)): raise ValueError('non-contiguous batch')
    gate=rec.verify_recovery_evidence(evidence_path,ledger_path,previous_ids)
    rows=load_ledger(ledger_path)
    expected=len([r for r in rows if batch_start<=r.get('ordinal',-1)<=end])
    if gate['rows_checked']!=expected: raise ValueError('recovery coverage gap: %d of %d ledger rows'%(gate['rows_checked'],expected))
    if gate['batch_start']!=batch_start or gate['batch_end']!=end: raise ValueError('recovery batch range mismatch')
    return {'status':'BATCH_COMPLETE','evidence_mode':'APPEND_ONLY_RECOVERED_PREFIX',
            'erratum_id':'BATCH-H-RECOVERY-ERRATUM-1','realtime_pre_spawn_capture':'NOT_AVAILABLE',
            'attestation_level':'PLATFORM_OPAQUE_SUBAGENT','batch_start':batch_start,'batch_end':end,
            'novelty_gate':gate}

DSH_SNAPSHOT_VERSION='csr8-reviewer-novelty-snapshot-v4-dsh-zstd'
DSH_ANCHOR_VERSION='csr8-reviewer-novelty-anchor-v2-dsh'

def capture_pre_spawn_dsh_snapshot(dsh_session_jsonl_zstd,executor_session_id,snapshot_path,anchor_path,frozen_path,sequence_cutoff=None):
    """PRE-SPAWN capture from the REAL DSH zstd source (approved for ordinal 15-22).

    Pipeline (ruling 2026-10-02): freeze quiescent raw bytes [0:EOF] of the
    live session.jsonl.zstd (trust root, O_EXCL 0600->fsync->0400), pin raw
    zstd sha256/length/inode/device, decode with the frozen H0 multi-frame
    decoder, pin decoded sha256/length + decoder identity, then write snapshot
    + anchor.  FIX6 EOF rule applies to the zstd source: an explicit cutoff
    must equal the raw EOF at freeze.  The decoded text in the snapshot is a
    derived product; the frozen raw capture is the trust root.
    """
    import csr8_batch_h_recovery_novelty as rec
    prov=rec.freeze_transcript(dsh_session_jsonl_zstd,frozen_path)
    if sequence_cutoff is not None and sequence_cutoff!=prov['raw_zstd_bytes']:
        raise ValueError('pre-spawn cutoff must equal current zstd EOF')
    raw=Path(prov['frozen_path']).read_bytes()
    if digest(raw)!=prov['raw_zstd_sha256']: raise ValueError('frozen capture hash drift')
    decoded=rec.decode_transcript_bytes(raw)
    sess=rec._pin_session_record(decoded)
    if sess['session_id']!=executor_session_id: raise ValueError('dsh transcript session != executor session')
    out=Path(snapshot_path); out.parent.mkdir(parents=True,exist_ok=True)
    snap={'snapshot_version':DSH_SNAPSHOT_VERSION,'executor_session_id':executor_session_id,
          'live_source_path':prov['live_path'],'source_device':prov['live_device'],'source_inode':prov['live_inode'],
          'frozen_capture_path':prov['frozen_path'],'raw_zstd_sha256':prov['raw_zstd_sha256'],
          'raw_zstd_bytes':prov['raw_zstd_bytes'],'pre_spawn_sequence_cutoff':prov['raw_zstd_bytes'],
          'decoder':{'decoder':'csr8_phase_h_entry_gate._zstd_lib + csr8_batch_h_recovery_novelty.decode_transcript_bytes',
                     'decoder_module_sha256':digest(Path(__file__).with_name('csr8_batch_h_recovery_novelty.py').read_bytes()),
                     'entry_gate_sha256':digest(Path(__file__).with_name('csr8_phase_h_entry_gate.py').read_bytes())},
          'decoded_sha256':digest(decoded),'decoded_bytes':len(decoded),
          'source_prefix_bytes':len(decoded),'transcript_prefix':decoded.decode('utf-8'),
          'pre_spawn_transcript_sha256':digest(decoded),'pre_spawn_transcript_length':len(decoded),
          'captured_at_unix':prov['captured_at_unix']}
    data=canon(snap).encode(); fd=os.open(out,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try: os.write(fd,data); os.fsync(fd)
    finally: os.close(fd)
    os.chmod(out,0o400)
    ap=Path(anchor_path); ap.parent.mkdir(parents=True,exist_ok=True)
    anch={'anchor_version':DSH_ANCHOR_VERSION,'executor_session_id':executor_session_id,
          'live_source_path':prov['live_path'],'source_device':prov['live_device'],'source_inode':prov['live_inode'],
          'frozen_capture_path':prov['frozen_path'],'raw_zstd_sha256':prov['raw_zstd_sha256'],
          'raw_zstd_bytes':prov['raw_zstd_bytes'],'decoded_sha256':digest(decoded),
          'pre_spawn_sequence_cutoff':prov['raw_zstd_bytes'],'snapshot_sha256':digest(data)}
    afd=os.open(ap,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    try: os.write(afd,canon(anch).encode()); os.fsync(afd)
    finally: os.close(afd)
    os.chmod(ap,0o400)
    for p in (out.parent,ap.parent):
        d=os.open(p,os.O_RDONLY); os.fsync(d); os.close(d)
    return snap,anch

def derive_previous_ids(previous_batch_record_path):
    """Derive previous reviewer IDs from a prior BATCH_COMPLETE record (ruling:
    previous_ids must not be hand-typed across batches)."""
    rec=json.loads(Path(previous_batch_record_path).read_text())
    if rec.get('status')!='BATCH_COMPLETE': raise ValueError('previous record is not BATCH_COMPLETE')
    gate=rec.get('novelty_gate') or {}
    ids=[]
    for row in gate.get('rows') or gate.get('evidence') or []:
        ids += [row['reviewer_run_id'],row['reviewer_session_id']]
    if not ids: raise ValueError('previous record carries no reviewer IDs')
    return sorted(set(ids))

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--batch-start',type=int,required=True); ap.add_argument('--completed-ordinal',type=int,action='append',required=True); ap.add_argument('--novelty-evidence-json',required=True); ap.add_argument('--ledger',required=True); ap.add_argument('--previous-id',action='append',default=[],help='DEPRECATED: only empty use (first batch) or recovery branch; batch 2+ must use --previous-batch-record')
    ap.add_argument('--previous-batch-record',default=None,help='prior BATCH_COMPLETE record path; previous IDs are derived from it, never hand-assembled')
    ap.add_argument('--recovery',action='store_true',help='BATCH-H-RECOVERY-ERRATUM-1 branch: novelty-evidence-json is the recovery evidence file')
    a=ap.parse_args()
    if not a.recovery and a.previous_batch_record and a.previous_id:
        raise SystemExit('refusing manual --previous-id together with --previous-batch-record')
    if a.recovery:
        print(json.dumps(complete_batch_recovery(a.batch_start,a.completed_ordinal,a.novelty_evidence_json,a.ledger,a.previous_id),sort_keys=True,separators=(',',':')))
    else:
        print(json.dumps(complete_batch(a.batch_start,a.completed_ordinal,json.loads(Path(a.novelty_evidence_json).read_text()),a.ledger,a.previous_id,previous_batch_record=a.previous_batch_record),sort_keys=True,separators=(',',':')))
if __name__=='__main__': main()
