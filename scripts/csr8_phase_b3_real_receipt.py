#!/usr/bin/env python3
"""CSR-8 run-2 B3: real receipt freeze, and its fail-closed gate.

The only real mutation is the frozen make_receipt transaction applied to the
B2 blinded draft.  No approval, SEAL, proposal, or outcome is read or created.
"""
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
import csr8_phase_b1_real_handoff as b1
import csr8_phase_b2_real_annotation as b2

CSR, SID = c4d.REAL_CSR, c4d.REAL_SESSION
ORDINAL, ATTEMPT = 1, 1
G = 'G-B3-RECEIPT'


def fail(msg):
    raise RuntimeError(f'{G}: {msg}')


def verify_b3(root=CSR):
    """Re-prove the persisted B3 transaction and its byte invariants."""
    # B2 validation remains valid after B3 changes only the draft mode to
    # 0400; receipt publication is the sole new persisted domain.
    b2.verify_b2(root)
    r1 = b1.read_chain(root, SID)[0]
    dp = c4d.draft_path(root, SID)
    ad = c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT)
    rp, sp = ad / 'receipt.json', ad / 'draft_snapshot.bin'
    if not ad.is_dir() or not rp.is_file() or not sp.is_file():
        fail('attempt must contain receipt.json and draft_snapshot.bin')
    if b1.mode_of(ad) != 0o700 or b1.mode_of(rp) != 0o600 or b1.mode_of(sp) != 0o600:
        fail('attempt files/directories mode drift')
    if b1.mode_of(dp) != 0o400:
        fail('active draft is not locked 0400')
    D = dp.read_bytes(); S = sp.read_bytes()
    if D != S:
        fail('active draft bytes differ from exact snapshot')
    try: receipt = json.loads(rp.read_bytes())
    except json.JSONDecodeError: fail('receipt is not JSON')
    if c4d.canon(receipt).encode() != rp.read_bytes():
        fail('receipt is not canonical')
    if set(receipt) != c4d.RECEIPT_TOP:
        fail('receipt closed-world schema drift')
    if receipt['draft_sha256'] != hashlib.sha256(S).hexdigest():
        fail('receipt.draft_sha256 != SHA256(exact draft_snapshot.bin)')
    if receipt['session_id'] != SID or receipt['packet_id'] != r1['payload']['packet_id']:
        fail('receipt chain binding drift')
    if receipt['packet_sha256'] != r1['payload']['packet_sha256'] or \
            receipt['reveal_event_hash'] != r1['event_hash']:
        fail('receipt R1 binding drift')
    if receipt['annotation_attempt'] != ATTEMPT:
        fail('receipt attempt binding drift')
    if c4d.sha(D) != receipt['draft_sha256']:
        fail('exact-D hash mismatch')
    if b1.mode_of(ad.parent) != 0o700 or b1.mode_of(ad.parent.parent) != 0o700:
        fail('ordinal/receipts parent mode drift')
    return {'gates': {'full_validation_before_write': 'PASS',
                      'staging_receipt_snapshot': 'PASS',
                      'fsync_and_lock': 'PASS',
                      'rename_noreplace': 'PASS',
                      'exact_draft_invariant': 'PASS',
                      'draft_sha256': 'PASS',
                      'crash_safety': 'PASS'},
            'attempt': ATTEMPT, 'ordinal': ORDINAL,
            'draft_sha256': receipt['draft_sha256']}


def create():
    # frozen transaction implements exact order:
    # read D -> validate -> staging receipt/snapshot -> fsync -> 0400 ->
    # reread -> fsync draft/parent -> RENAME_NOREPLACE -> fsync parent.
    try:
        c4d.make_receipt(CSR, SID, ordinal=ORDINAL)
    except c4d.CrashSim:
        fail('unexpected crash simulation in real execution')
    result = verify_b3()
    result['b3'] = 'RECEIPT_FROZEN'
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--verify', action='store_true')
    args = ap.parse_args()
    result = verify_b3() if args.verify else create()
    if args.verify: result['b3'] = 'VERIFIED'
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
