#!/usr/bin/env python3
"""Mandatory Batch-H reviewer novelty boundary.

This module does not spawn production work. It defines the boundary that a
batch executor must call: capture a transcript prefix before spawning each
sampled reviewer, then submit the returned IDs plus that immutable snapshot.
Missing snapshots/evidence fail closed. This proves only a bounded
PLATFORM_OPAQUE_SUBAGENT novelty property.
"""
import argparse, hashlib, json

BATCH_SIZE = 8

def batch_boundary(batch_start, completed_count=BATCH_SIZE):
    if batch_start < 1 or completed_count != BATCH_SIZE:
        raise ValueError('batch must contain exactly eight ordinals')
    return batch_start + completed_count - 1

def snapshot_transcript(prefix, sequence_cutoff=None):
    if not isinstance(prefix, str):
        raise ValueError('transcript prefix must be text')
    if not prefix:
        raise ValueError('missing/empty pre-spawn transcript snapshot')
    raw = prefix.encode('utf-8')
    return {'transcript_prefix': prefix,
            'pre_spawn_transcript_sha256': hashlib.sha256(raw).hexdigest(),
            'pre_spawn_transcript_length': len(raw),
            'pre_spawn_sequence_cutoff': sequence_cutoff,
            'snapshot_version': 'csr8-reviewer-novelty-snapshot-v1'}

def reviewer_id_novelty_spot_check(batch_start, previous_ids, samples,
                                    completed_count=BATCH_SIZE):
    """Validate post-review IDs against each sample's pre-spawn prefix only.

    samples: [{reviewer_operation, reviewer_run_id, reviewer_session_id,
               pre_spawn_snapshot: snapshot_transcript(...)}]
    """
    end = batch_boundary(batch_start, completed_count)
    if not samples:
        raise ValueError('novelty evidence is required and cannot be empty')
    ids = []
    evidence = []
    for sample in samples:
        required = ('reviewer_operation', 'reviewer_run_id',
                    'reviewer_session_id', 'pre_spawn_snapshot')
        if any(k not in sample for k in required):
            raise ValueError('incomplete pre-spawn novelty evidence')
        run_id, session_id = sample['reviewer_run_id'], sample['reviewer_session_id']
        if not run_id or not session_id:
            raise ValueError('reviewer IDs must be nonempty')
        snap = sample['pre_spawn_snapshot']
        if not isinstance(snap, dict) or not snap.get('transcript_prefix'):
            raise ValueError('missing pre-spawn transcript snapshot')
        prefix = snap['transcript_prefix']
        if snap.get('pre_spawn_transcript_sha256') != hashlib.sha256(prefix.encode()).hexdigest():
            raise ValueError('pre-spawn transcript hash mismatch')
        premature_run = run_id in prefix
        premature_session = session_id in prefix
        if premature_run or premature_session:
            raise ValueError('premature reviewer id in pre-spawn transcript')
        ids += [run_id, session_id]
        evidence.append({'reviewer_operation': sample['reviewer_operation'],
                         'reviewer_run_id': run_id,
                         'reviewer_session_id': session_id,
                         'pre_spawn_transcript_sha256': snap['pre_spawn_transcript_sha256'],
                         'pre_spawn_transcript_length': snap['pre_spawn_transcript_length'],
                         'pre_spawn_sequence_cutoff': snap.get('pre_spawn_sequence_cutoff'),
                         'premature_run_id_found': False,
                         'premature_session_id_found': False})
    if len(ids) != len(set(ids)) or set(previous_ids) & set(ids):
        raise ValueError('reviewer-id duplicate/overlap with prior batches')
    return {'status': 'PASS', 'batch_start': batch_start,
            'batch_end': end, 'batch_size': completed_count,
            'checked_samples': len(samples), 'novelty': True,
            'evidence': evidence,
            'attestation_level': 'PLATFORM_OPAQUE_SUBAGENT'}

def complete_batch(batch_start, completed_ordinals, novelty_evidence,
                   previous_ids=()):
    """Hard completion gate: no evidence, no batch completion."""
    end = batch_boundary(batch_start, len(completed_ordinals))
    if list(completed_ordinals) != list(range(batch_start, end + 1)):
        raise ValueError('completed ordinals are not one contiguous eight-ordinal batch')
    novelty = reviewer_id_novelty_spot_check(batch_start, previous_ids,
                                              novelty_evidence)
    return {'status': 'BATCH_COMPLETE', 'batch_start': batch_start,
            'batch_end': end, 'novelty_gate': novelty}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch-start', type=int, required=True)
    ap.add_argument('--completed-ordinal', type=int, action='append', required=True)
    ap.add_argument('--novelty-evidence-json', required=True)
    a = ap.parse_args()
    with open(a.novelty_evidence_json, encoding='utf-8') as f:
        evidence = json.load(f)
    print(json.dumps(complete_batch(a.batch_start, a.completed_ordinal,
                                    evidence), sort_keys=True,
                     separators=(',', ':')))

if __name__ == '__main__':
    main()
