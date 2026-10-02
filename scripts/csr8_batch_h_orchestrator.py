#!/usr/bin/env python3
"""Batch-H orchestration gates (no production work is started here).

The novelty check is intentionally executor-side: before a batch starts, scan
executor transcript text for declared reviewer ids. This is a bounded
PLATFORM_OPAQUE_SUBAGENT spot-check, not transcript-anchored identity proof.
"""
import argparse, json, sys
from pathlib import Path

BATCH_SIZE = 8

def batch_boundary(batch_start, completed_count=BATCH_SIZE):
    if batch_start < 1 or completed_count != BATCH_SIZE:
        raise ValueError('batch must contain exactly eight ordinals')
    return batch_start + completed_count - 1

def reviewer_id_novelty_spot_check(batch_start, previous_ids, declared_ids,
                                    executor_transcripts, completed_count=BATCH_SIZE):
    end = batch_boundary(batch_start, completed_count)
    ids = list(declared_ids)
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('declared reviewer ids must be nonempty and distinct')
    if set(previous_ids) & set(ids):
        raise ValueError('reviewer-id overlap with prior batches')
    # Any declared future id already present in executor-controlled transcript
    # is a premature occurrence and blocks the batch.
    premature = sorted({rid for rid in ids
                        if any(rid in text for text in executor_transcripts)})
    if premature:
        raise ValueError('premature reviewer ids in executor transcript: '
                         + repr(premature))
    return {'status': 'PASS', 'batch_start': batch_start,
            'batch_end': end, 'batch_size': completed_count,
            'checked_ids': len(ids), 'novelty': True,
            'transcript_premature_ids': [] ,
            'attestation_level': 'PLATFORM_OPAQUE_SUBAGENT'}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--batch-start', type=int, required=True)
    ap.add_argument('--previous-id', action='append', default=[])
    ap.add_argument('--declared-id', action='append', required=True)
    ap.add_argument('--transcript', action='append', default=[])
    a = ap.parse_args()
    print(json.dumps(reviewer_id_novelty_spot_check(
        a.batch_start, a.previous_id, a.declared_id, a.transcript),
        sort_keys=True, separators=(',', ':')))

if __name__ == '__main__':
    main()
