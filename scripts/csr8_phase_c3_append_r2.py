#!/usr/bin/env python3
"""CSR-8 C3: append the authorized ordinal-2 reveal (R2) exactly once.

The append path is deliberately one-shot: C2 is re-verified from persisted
bytes immediately before the frozen transaction API is called.  Afterward,
the complete chain, chain-derived consumption, sealed-pair replay, and frozen
candidate prefix are measured from the resulting production state.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
import csr8_phase_c2_next_reveal_approval as c2

ROOT = c4d.ROOT
SID = c4d.REAL_SESSION
ORDINAL = 2


def _events():
    path = c4d.log_path(c4d.REAL_CSR, SID)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify_c3():
    events = _events()
    types = [event['event_type'] for event in events]
    if types != ['REVEAL_PACKET', 'SEAL_ANNOTATION', 'REVEAL_PACKET']:
        raise RuntimeError(f'G-C3-CHAIN: expected [R1,S1,R2], got {types}')
    c4d.c2translate(
        c4d.c2.SealingLog(c4d.log_path(c4d.REAL_CSR, SID),
                           c4d.head_path(c4d.REAL_CSR, SID)).load().verify,
        True)
    proposal = c4d.read_json(c4d.proposal_path(c4d.REAL_CSR, SID, ORDINAL))
    if c4d.derive_reveal_consumption(events, proposal, SID) != 'CONSUMED':
        raise RuntimeError('G-C3-AUTHORIZATION: ordinal-2 is not CONSUMED')
    c4d.semantic_replay(c4d.REAL_CSR, SID, events=events)
    reveals = [e for e in events if e['event_type'] == c4d.c2.REVEAL]
    order = c4d.candidate_total_order()
    revealed = [(e['payload']['opaque_case_id'], e['payload']['T'])
                for e in reveals]
    expected = [(e['opaque_case_id'], e['T']) for e in order[:2]]
    if revealed != expected:
        raise RuntimeError('G-C3-PREFIX: revealed candidates are not prefix 2')
    return {
        'chain': types,
        'authorization_2': 'CONSUMED',
        'candidate_prefix': len(revealed),
        'reveal_count': len(reveals),
        'seal_count': sum(t == 'SEAL_ANNOTATION' for t in types),
        's1_r1_replay': 'PASS',
        'head': events[-1]['event_hash'],
    }


def append_r2():
    # C2's frozen verifier is intentionally run before any append.
    c2.verify_c2()
    c4d.reveal_transaction(c4d.REAL_CSR, SID, ORDINAL)
    return verify_c3()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    result = verify_c3() if args.verify else append_r2()
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
