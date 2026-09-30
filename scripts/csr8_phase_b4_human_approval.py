#!/usr/bin/env python3
"""CSR-8 run audit_20260930021152297 B4: exact-hash approval under the
UNATTENDED policy (taskbook §5 B4 + amendment v2-unattended-20260930).

Amendment v2 (owner directive 2026-09-30, 纯无人值守) removed the human
authorization gates: the executor no longer waits for any bound-session
human approval message and directly persists the approval artifact.
The preauthorization 节 (PREAUTH v1) mechanism was removed from the
bridge code together with it; the previously committed human-gate
evidence files (b4_human_approval_message.txt, b4_preauth_v1.json,
b4_session_record_excerpt.jsonl, ...) remain in the tree as inert
history and are no longer part of this gate.

What this script enforces (all machine-measured, fail-closed):

  1. chain-side artifact: seal_approval.json (frozen closed-world
     schema c4d-seal-approval-v1) is persisted through the frozen
     csr8_phase_c_annotation_seal.make_seal_approval transaction
     (O_EXCL / canonical / 0600 / fsync) and binds the exact bytes of
     the CURRENT session / reveal / attempt receipt:
         approved_receipt_sha256 == SHA256(receipt.json bytes)
  2. run-side record: docs/audit/evidence/b4_unattended_approval.json
     is persisted the same way (O_EXCL / canonical / 0600 / fsync) with
     approved_by=UNATTENDED_POLICY, binding=['EXACT'],
     scope=SEAL_ANNOTATION_ONLY, run/host/stage/iteration, the same
     session/reveal/attempt, the same receipt hash character-identical
     both in the approved_receipt_sha256 field and embedded in the
     taskbook §5 B4 fixed wording, plus the sha256 of the exact
     seal_approval.json bytes it authorizes;
  3. no authorization expansion: the record authorizes ONLY those exact
     bytes for this attempt (binding EXACT, scope
     SEAL_ANNOTATION_ONLY, explicit no-expansion statement).

Fail-closed: any hash drift, wording drift, binding drift, duplicate,
or non-canonical artifact raises before or after the write.
"""
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
import csr8_phase_b1_real_handoff as b1
import csr8_phase_b3_real_receipt as b3

ROOT = Path(__file__).resolve().parents[1]
CSR, SID, ORDINAL, ATTEMPT = c4d.REAL_CSR, c4d.REAL_SESSION, 1, 1
RECEIPT = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT) / 'receipt.json'
APPROVAL = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT) / 'seal_approval.json'
REVEAL = c4d.LIVE_R1_EVENT_HASH
RUN_ID = 'audit_20260930021152297'
HOST_ID = 'RainYun-c438TDGn'
STAGE, ITERATION = 'B4', 1
UNATTENDED_RECORD = ROOT / 'docs/audit/evidence/b4_unattended_approval.json'
AMENDMENT = 'v2-unattended-20260930'
APPROVED_BY = 'UNATTENDED_POLICY'
G = 'G-B4-APPROVAL'

# 任务书 §5 B4 固定批准措辞（逐字取自冻结任务书，不得改写）：
#   我明确批准 SEAL_ANNOTATION_ONLY receipt exact hash:
#   <64 hex>
#
#   该批准仅授权当前 session / reveal / attempt 所绑定的
#   这一份 exact receipt bytes，不授权任何其他 receipt、REVEAL、
#   outcome 或 next ordinal。
WORDING_HEAD = '我明确批准 SEAL_ANNOTATION_ONLY receipt exact hash:'
WORDING_TAIL = ('该批准仅授权当前 session / reveal / attempt 所绑定的\n'
                '这一份 exact receipt bytes，不授权任何其他 receipt、REVEAL、\n'
                'outcome 或 next ordinal。')
WORDING_RE = re.compile(
    re.escape(WORDING_HEAD) + r'\n([0-9a-f]{64})\n\n' + re.escape(WORDING_TAIL))

# v2 无扩张声明（固定常量，逐字符校验）
NO_EXPANSION = ('仅授权本次（该 session / reveal / attempt）对应的 '
                'exact receipt bytes；不授权任何其他 receipt、REVEAL、'
                'outcome 或 next ordinal。')

RECORD_VERSION = 'c4d-b4-unattended-approval-v1'
RECORD_KEYS = {
    'approval_version', 'amendment', 'run_id', 'host_id', 'stage',
    'iteration', 'approved_by', 'policy', 'binding', 'scope',
    'session_id', 'reveal_event_hash', 'annotation_attempt',
    'approved_receipt_sha256', 'taskbook_wording', 'authorized_artifact',
    'authorized_artifact_sha256', 'no_expansion', 'recorded_at',
}
TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')


def fail(msg):
    raise RuntimeError(f'{G}: {msg}')


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fixed_wording(receipt_sha):
    """The taskbook §5 B4 template rendered with a concrete hash."""
    return WORDING_HEAD + '\n' + receipt_sha + '\n\n' + WORDING_TAIL


def parse_wording_hash(text):
    """Exact fixed-wording check. Returns the embedded 64-hex hash or
    fails closed on ANY wording drift (including trailing whitespace)."""
    m = WORDING_RE.fullmatch(text)
    if not m:
        fail('wording does not match the taskbook §5 B4 fixed template '
             '(template + <64 hex>; no extra/missing characters)')
    return m.group(1)


def receipt_sha256(root=CSR):
    return sha256_bytes(
        (c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) / 'receipt.json')
        .read_bytes())


def approval_rel(root=CSR):
    return (c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) /
            'seal_approval.json').relative_to(root).as_posix()


def expected_record(rsha, approval_bytes, root=CSR):
    return {
        'approval_version': RECORD_VERSION,
        'amendment': AMENDMENT,
        'run_id': RUN_ID,
        'host_id': HOST_ID,
        'stage': STAGE,
        'iteration': ITERATION,
        'approved_by': APPROVED_BY,
        'policy': APPROVED_BY,
        'binding': ['EXACT'],
        'scope': 'SEAL_ANNOTATION_ONLY',
        'session_id': SID,
        'reveal_event_hash': REVEAL,
        'annotation_attempt': ATTEMPT,
        'approved_receipt_sha256': rsha,
        'taskbook_wording': fixed_wording(rsha),
        'authorized_artifact': approval_rel(root),
        'authorized_artifact_sha256': sha256_bytes(approval_bytes),
        'no_expansion': NO_EXPANSION,
        'recorded_at': datetime.now(timezone.utc)
                               .strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def _verify_chain_approval(root, rbytes, rsha):
    """Re-prove the persisted seal_approval.json against the exact
    receipt bytes plus the frozen transaction re-proof."""
    apath = c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) / 'seal_approval.json'
    if not apath.is_file():
        fail('seal_approval.json is absent')
    ab = apath.read_bytes()
    try:
        approval = json.loads(ab)
    except json.JSONDecodeError:
        fail('seal_approval.json is not JSON')
    if not isinstance(approval, dict) or set(approval) != c4d.APPROVAL_KEYS:
        fail('seal_approval closed-world schema violation')
    if c4d.canon(approval).encode() != ab:
        fail('seal_approval.json is not canonical')
    if approval['approval_version'] != c4d.APPROVAL_VERSION or \
            approval['scope'] != 'SEAL_ANNOTATION_ONLY':
        fail('approval version/scope drift')
    if approval['session_id'] != SID or \
            approval['reveal_event_hash'] != REVEAL or \
            approval['annotation_attempt'] != ATTEMPT or \
            approval['approved'] is not True:
        fail('approval session/reveal/attempt binding drift')
    if approval['approved_receipt_sha256'] != rsha:
        fail('persisted approval does not bind exact receipt bytes')
    if b1.mode_of(apath) != 0o600:
        fail('approval mode is not 0600')
    # frozen re-proof: the exact checks B5/seal preflight will run
    r1 = b1.read_chain(root, SID)[0]
    c4d._check_seal_approval(root, SID, ORDINAL, ATTEMPT, rbytes, r1, G)
    history = c4d.prove_attempt_history(root, SID, ORDINAL, gate=G)
    if history['live'] != [ATTEMPT]:
        fail(f'attempt {ATTEMPT} is not the sole live attempt '
             f'(live={history["live"]})')
    return ab


def _verify_unattended_record(record_path, rsha, approval_bytes, root=CSR):
    """Re-prove the run-side unattended approval record from persisted
    bytes only: closed-world schema, canonical bytes, 0600 mode,
    run/host/stage/iteration + session/reveal/attempt bindings,
    approved_by=UNATTENDED_POLICY, EXACT binding, SEAL_ANNOTATION_ONLY
    scope, character-identical receipt hash (field + taskbook wording),
    exact authorized-artifact sha256, fixed no-expansion statement."""
    if not Path(record_path).is_file():
        fail(f'unattended approval record absent: {record_path}')
    rb = Path(record_path).read_bytes()
    try:
        rec = json.loads(rb)
    except json.JSONDecodeError:
        fail('unattended approval record is not JSON')
    if not isinstance(rec, dict) or set(rec) != RECORD_KEYS:
        fail('unattended approval record closed-world schema violation')
    if c4d.canon(rec).encode() != rb:
        fail('unattended approval record is not canonical')
    if rec['approval_version'] != RECORD_VERSION or \
            rec['amendment'] != AMENDMENT:
        fail('unattended approval record version/amendment drift')
    if rec['run_id'] != RUN_ID or rec['host_id'] != HOST_ID or \
            rec['stage'] != STAGE or rec['iteration'] != ITERATION:
        fail('unattended approval record run/host/stage binding drift')
    if rec['approved_by'] != APPROVED_BY or rec['policy'] != APPROVED_BY:
        fail('approved_by/policy must be UNATTENDED_POLICY')
    if rec['binding'] != ['EXACT']:
        fail('unattended approval binding must be EXACT')
    if rec['scope'] != 'SEAL_ANNOTATION_ONLY':
        fail('unattended approval scope must be SEAL_ANNOTATION_ONLY')
    if rec['session_id'] != SID or \
            rec['reveal_event_hash'] != REVEAL or \
            rec['annotation_attempt'] != ATTEMPT:
        fail('unattended approval record session/reveal/attempt drift')
    if rec['approved_receipt_sha256'] != rsha:
        fail('unattended approval record does not bind the exact '
             'receipt hash')
    if rec['taskbook_wording'] != fixed_wording(rsha):
        fail('taskbook wording drift (must be the §5 B4 fixed template '
             'rendered with the exact receipt hash)')
    if parse_wording_hash(rec['taskbook_wording']) != rsha:
        fail('wording-embedded hash differs from receipt_sha256 — not '
             'character-identical')
    if rec['authorized_artifact'] != approval_rel(root):
        fail('authorized_artifact path drift')
    if rec['authorized_artifact_sha256'] != sha256_bytes(approval_bytes):
        fail('authorized_artifact_sha256 does not bind the exact '
             'seal_approval.json bytes')
    if rec['no_expansion'] != NO_EXPANSION:
        fail('no-expansion statement drift')
    if not TS_RE.fullmatch(rec['recorded_at']):
        fail('recorded_at is not a valid UTC timestamp')
    if b1.mode_of(Path(record_path)) != 0o600:
        fail('unattended approval record mode is not 0600')


def verify_b4(root=CSR, record_path=UNATTENDED_RECORD):
    """Re-prove the whole B4 gate from persisted bytes only."""
    b3.verify_b3(root)
    rbytes = (c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) /
              'receipt.json').read_bytes()
    rsha = sha256_bytes(rbytes)

    approval_bytes = _verify_chain_approval(root, rbytes, rsha)
    _verify_unattended_record(record_path, rsha, approval_bytes, root)

    gates = {'receipt_hash_exact': 'PASS',
             'approval_artifact_binding': 'PASS',
             'approved_by_unattended_policy': 'PASS',
             'wording_hash_char_identical': 'PASS',
             'no_authorization_expansion': 'PASS',
             'closed_world_canonical': 'PASS',
             'frozen_reproof': 'PASS',
             'o_excl_0600_fsync': 'PASS'}
    return {'gates': gates,
            'receipt_sha256': rsha, 'attempt': ATTEMPT,
            'approved_by': APPROVED_BY,
            'authorized_artifact': approval_rel(root),
            'authorized_artifact_sha256': sha256_bytes(approval_bytes)}


def persist_unattended(root=CSR, record_path=UNATTENDED_RECORD):
    """Persist the approval artifacts directly (amendment v2: no human
    message is waited for).  The chain-side seal_approval.json goes
    through the frozen make_seal_approval transaction when absent
    (O_EXCL / canonical / 0600 / fsync); the run-side unattended record
    is then written the same way and both are fully re-proven."""
    # Check the run-side O_EXCL destination before touching the chain-side
    # artifact.  This preserves one-shot semantics even after a crash or a
    # retry: an already-filed record must never trigger a new chain mutation.
    if Path(record_path).exists():
        fail('unattended approval record already exists; immutable O_EXCL artifact')

    b3.verify_b3(root)                      # full B1-B3 proof first
    rsha = receipt_sha256(root)
    apath = c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) / 'seal_approval.json'
    if apath.exists():
        # immutable O_EXCL artifact already on the chain: it must bind
        # the exact current receipt bytes (re-proven below in full)
        rbytes = (c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) /
                  'receipt.json').read_bytes()
        _verify_chain_approval(root, rbytes, rsha)
    else:
        c4d.make_seal_approval(root, SID, ordinal=ORDINAL, attempt=ATTEMPT,
                               receipt_sha=rsha)
    approval_bytes = apath.read_bytes()
    if Path(record_path).exists():
        fail('unattended approval record already exists; '
             'immutable O_EXCL artifact')
    record = expected_record(rsha, approval_bytes, root)
    c4d.excl_write(Path(record_path), c4d.canon(record).encode())
    result = verify_b4(root, record_path)
    result['b4'] = 'APPROVAL_PERSISTED'
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--persist', action='store_true')
    args = ap.parse_args()
    if args.persist:
        result = persist_unattended()
    else:
        result = verify_b4()
        result['b4'] = 'VERIFIED'
    print(json.dumps(result, sort_keys=True, ensure_ascii=False,
                     separators=(',', ':')))
