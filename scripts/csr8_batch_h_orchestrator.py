#!/usr/bin/env python3
"""Mandatory Batch-H reviewer novelty boundary with ledger-bound evidence."""
import argparse, hashlib, json, os
from pathlib import Path

BATCH_SIZE = 8
SNAPSHOT_VERSION = 'csr8-reviewer-novelty-snapshot-v2'

def canon(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))

def batch_boundary(batch_start, completed_count=BATCH_SIZE):
    if batch_start < 1 or completed_count != BATCH_SIZE:
        raise ValueError('batch must contain exactly eight ordinals')
    return batch_start + completed_count - 1

def snapshot_transcript(prefix, sequence_cutoff=None, path=None):
    if not isinstance(prefix, str) or not prefix:
        raise ValueError('missing/empty pre-spawn transcript snapshot')
    if not isinstance(sequence_cutoff, int) or sequence_cutoff < 0:
        raise ValueError('pre_spawn_sequence_cutoff is required')
    raw = prefix.encode('utf-8')
    obj = {'snapshot_version': SNAPSHOT_VERSION,
           'transcript_prefix': prefix,
           'pre_spawn_transcript_sha256': hashlib.sha256(raw).hexdigest(),
           'pre_spawn_transcript_length': len(raw),
           'pre_spawn_sequence_cutoff': sequence_cutoff}
    if path is not None:
        p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(p, flags, 0o600)
        try:
            os.write(fd, canon(obj).encode('utf-8'))
        finally:
            os.close(fd)
    return obj

def load_ledger(path):
    rows = [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]
    if not rows:
        raise ValueError('review ledger is empty')
    for i, row in enumerate(rows):
        if row.get('sequence') != i or not row.get('review_hash'):
            raise ValueError('ledger sequence drift')
        supplied = row['review_hash']; body = dict(row); body.pop('review_hash')
        if hashlib.sha256(canon(body).encode()).hexdigest() != supplied:
            raise ValueError('ledger review hash mismatch')
        if i and row.get('prev_review_hash') != rows[i-1].get('review_hash'):
            raise ValueError('ledger hash chain break')
    return rows

def _read_snapshot(snap):
    if isinstance(snap, (str, Path)):
        snap = json.loads(Path(snap).read_text())
    if not isinstance(snap, dict) or snap.get('snapshot_version') != SNAPSHOT_VERSION:
        raise ValueError('invalid or unfrozen snapshot version')
    prefix = snap.get('transcript_prefix')
    cutoff = snap.get('pre_spawn_sequence_cutoff')
    if not isinstance(prefix, str) or not prefix:
        raise ValueError('missing transcript snapshot')
    if not isinstance(cutoff, int) or cutoff < 0:
        raise ValueError('missing pre-spawn sequence cutoff')
    raw = prefix.encode('utf-8')
    if snap.get('pre_spawn_transcript_length') != len(raw):
        raise ValueError('transcript byte length mismatch')
    if snap.get('pre_spawn_transcript_sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('pre-spawn transcript hash mismatch')
    return snap, prefix

def reviewer_id_novelty_spot_check(batch_start, previous_ids, samples,
                                    ledger_path, completed_count=BATCH_SIZE):
    end = batch_boundary(batch_start, completed_count)
    if not samples:
        raise ValueError('novelty evidence is required and cannot be empty')
    rows = load_ledger(ledger_path)
    ids, evidence = [], []
    for sample in samples:
        required = ('ordinal', 'reviewer_operation', 'ledger_sequence',
                    'review_hash', 'reviewer_run_id', 'reviewer_session_id',
                    'pre_spawn_snapshot')
        if any(k not in sample for k in required):
            raise ValueError('incomplete ledger-bound novelty evidence')
        seq = sample['ledger_sequence']
        if not isinstance(seq, int) or seq < 0 or seq >= len(rows):
            raise ValueError('ledger sequence out of range')
        row = rows[seq]
        if (sample['ordinal'], sample['reviewer_operation'], sample['review_hash']) != \
           (row.get('ordinal'), row.get('operation'), row.get('review_hash')):
            raise ValueError('sample does not bind exact ledger row')
        run_id, session_id = sample['reviewer_run_id'], sample['reviewer_session_id']
        if (run_id, session_id) != (row.get('reviewer_run_id'), row.get('reviewer_session_id')):
            raise ValueError('sample IDs do not match ledger IDs')
        snap, prefix = _read_snapshot(sample['pre_spawn_snapshot'])
        premature_run, premature_session = run_id in prefix, session_id in prefix
        if premature_run or premature_session:
            raise ValueError('premature reviewer id in pre-spawn transcript')
        ids += [run_id, session_id]
        evidence.append({k: sample[k] for k in (
            'ordinal', 'reviewer_operation', 'ledger_sequence', 'review_hash',
            'reviewer_run_id', 'reviewer_session_id')})
        evidence[-1].update({
            'pre_spawn_transcript_sha256': snap['pre_spawn_transcript_sha256'],
            'pre_spawn_transcript_length': snap['pre_spawn_transcript_length'],
            'pre_spawn_sequence_cutoff': snap['pre_spawn_sequence_cutoff'],
            'premature_run_id_found': False,
            'premature_session_id_found': False})
    if len(ids) != len(set(ids)) or set(previous_ids) & set(ids):
        raise ValueError('reviewer-id duplicate/overlap with prior batches')
    return {'status': 'PASS', 'batch_start': batch_start, 'batch_end': end,
            'batch_size': completed_count, 'checked_samples': len(samples),
            'novelty': True, 'evidence': evidence,
            'attestation_level': 'PLATFORM_OPAQUE_SUBAGENT'}

def complete_batch(batch_start, completed_ordinals, novelty_evidence,
                   ledger_path, previous_ids=()):
    end = batch_boundary(batch_start, len(completed_ordinals))
    if list(completed_ordinals) != list(range(batch_start, end + 1)):
        raise ValueError('completed ordinals are not one contiguous eight-ordinal batch')
    novelty = reviewer_id_novelty_spot_check(batch_start, previous_ids,
                                              novelty_evidence, ledger_path)
    return {'status': 'BATCH_COMPLETE', 'batch_start': batch_start,
            'batch_end': end, 'novelty_gate': novelty}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch-start', type=int, required=True)
    ap.add_argument('--completed-ordinal', type=int, action='append', required=True)
    ap.add_argument('--novelty-evidence-json', required=True)
    ap.add_argument('--ledger', required=True)
    ap.add_argument('--previous-id', action='append', default=[])
    a = ap.parse_args()
    evidence = json.loads(Path(a.novelty_evidence_json).read_text())
    print(json.dumps(complete_batch(a.batch_start, a.completed_ordinal,
                                    evidence, a.ledger, a.previous_id),
                     sort_keys=True, separators=(',', ':')))

if __name__ == '__main__':
    main()
