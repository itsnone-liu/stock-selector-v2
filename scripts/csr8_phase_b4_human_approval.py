#!/usr/bin/env python3
"""CSR-8 run-2 B4: persist the received human exact-hash approval.

This entry point is intentionally fail-closed: the approval text is an
exact human message received in the audit session, and only that fixed
SEAL_ANNOTATION_ONLY wording can authorize creation of seal_approval.json.
"""
import hashlib
import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
import csr8_phase_b1_real_handoff as b1
import csr8_phase_b2_real_annotation as b2
import csr8_phase_b3_real_receipt as b3

CSR, SID, ORDINAL, ATTEMPT = c4d.REAL_CSR, c4d.REAL_SESSION, 1, 1
RECEIPT = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT) / 'receipt.json'
APPROVAL = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT) / 'seal_approval.json'
REVEAL = c4d.LIVE_R1_EVENT_HASH
HUMAN_APPROVAL_MESSAGE = (
    'I APPROVE SEAL for session c4-prod-0002, reveal '
    'b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5, '
    'attempt 1, receipt_sha256=85a224a3e748b569060a14aea8fe5fe353b62e8a804e0f43cfb4c51a18063aa6.'
)
PREFIX = 'I APPROVE SEAL for session c4-prod-0002, reveal '
SUFFIX = ', attempt 1, receipt_sha256='


def fail(msg):
    raise RuntimeError('G-B4-APPROVAL: ' + msg)


def parse_human_message(message):
    if message != HUMAN_APPROVAL_MESSAGE:
        fail('human approval wording is not the exact received fixed phrase')
    m = re.fullmatch(
        r'I APPROVE SEAL for session (c4-prod-0002), reveal ([0-9a-f]{64}), '
        r'attempt (1), receipt_sha256=([0-9a-f]{64})\.', message)
    if not m or m.group(2) != REVEAL:
        fail('message session/reveal/attempt binding or wording mismatch')
    return m.group(4)


def verify_b4():
    b3.verify_b3()
    if not APPROVAL.is_file():
        fail('seal_approval.json is absent')
    receipt_bytes = RECEIPT.read_bytes()
    receipt_sha = hashlib.sha256(receipt_bytes).hexdigest()
    approved_sha = parse_human_message(HUMAN_APPROVAL_MESSAGE)
    if approved_sha != receipt_sha:
        fail('human message hash differs from exact receipt_sha256')
    raw = APPROVAL.read_bytes()
    try: obj = json.loads(raw)
    except json.JSONDecodeError: fail('seal_approval.json is not JSON')
    if set(obj) != c4d.APPROVAL_KEYS or c4d.canon(obj).encode() != raw:
        fail('approval is not closed-world canonical JSON')
    if obj['approved_receipt_sha256'] != receipt_sha:
        fail('persisted approval does not bind exact receipt bytes')
    if b1.mode_of(APPROVAL) != 0o600:
        fail('approval mode is not 0600')
    if obj['session_id'] != SID or obj['reveal_event_hash'] != REVEAL \
            or obj['annotation_attempt'] != ATTEMPT or obj['approved'] is not True:
        fail('approval binding drift')
    return {'gates': {'human_fixed_phrase': 'PASS',
                      'receipt_hash_exact': 'PASS',
                      'session_reveal_attempt': 'PASS',
                      'closed_world_canonical': 'PASS',
                      'o_excl_0600_fsync': 'PASS'},
            'receipt_sha256': receipt_sha, 'attempt': ATTEMPT}


def persist():
    # Recompute and compare the human-provided hash before any write.
    b3.verify_b3()
    receipt_sha = hashlib.sha256(RECEIPT.read_bytes()).hexdigest()
    if parse_human_message(HUMAN_APPROVAL_MESSAGE) != receipt_sha:
        fail('approval hash mismatch; refusing persistence')
    if APPROVAL.exists():
        fail('approval already exists; immutable O_EXCL artifact')
    approval = c4d.make_seal_approval(CSR, SID, ordinal=ORDINAL,
                                       attempt=ATTEMPT,
                                       receipt_sha=receipt_sha)
    result = verify_b4()
    result['b4'] = 'APPROVAL_PERSISTED'
    return result


if __name__ == '__main__':
    result = verify_b4() if '--verify' in sys.argv else persist()
    if '--verify' in sys.argv: result['b4'] = 'VERIFIED'
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
