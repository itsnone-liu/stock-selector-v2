#!/usr/bin/env python3
"""CSR-8 run audit_20260930010058058 B4: human exact-hash approval, real gate.

The run-2 predecessor hardcoded an "approval message" constant inside
this script and persisted from it — that is executor self-approval
(执行者代批), explicitly forbidden by the frozen taskbook §5 B4, and its
artifact was removed from the live tree.  This version removes any
in-script message constant: the ONLY acceptance path is an evidence file
(docs/audit/evidence/b4_human_approval_message.txt) whose bytes are a
verbatim transcription of the bound audit session's human reply, and
those bytes must be the taskbook §5 B4 fixed wording with the embedded
hash character-identical to SHA256 of the exact current-attempt receipt
bytes.  Persistence itself goes through the frozen
csr8_phase_c_annotation_seal.make_seal_approval transaction
(O_EXCL / canonical / 0600 / fsync).

Executor-side flow this script enforces (machine-checked traces the
reviewer audits against the session transcript):
  1. pre-gate:   --show-gate renders receipt_sha256 + the taskbook fixed
                 wording template (the one marker-free interaction turn);
  2. transcribe: the human reply is transcribed byte-exactly to the
                 evidence file by the executor;
  3. persist:    --message-file <evidence> validates wording + hash and
                 only then persists seal_approval.json + a canonical
                 provenance record bound to THIS run;
  4. verify:     --verify re-proves everything from persisted bytes only.

Fail-closed: nothing in this file can approve on its own; any wording
drift, hash drift, binding drift, duplicate, or non-canonical artifact
raises before or after the write.
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
import csr8_phase_b2_real_annotation as b2
import csr8_phase_b3_real_receipt as b3

ROOT = Path(__file__).resolve().parents[1]
CSR, SID, ORDINAL, ATTEMPT = c4d.REAL_CSR, c4d.REAL_SESSION, 1, 1
RECEIPT = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT) / 'receipt.json'
APPROVAL = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT) / 'seal_approval.json'
REVEAL = c4d.LIVE_R1_EVENT_HASH
RUN_ID = 'audit_20260930010058058'
HOST_ID = 'RainYun-c438TDGn'
STAGE, ITERATION = 'B4', 1
MESSAGE_EVIDENCE = ROOT / 'docs/audit/evidence/b4_human_approval_message.txt'
PROVENANCE = ROOT / 'docs/audit/evidence/b4_human_approval_provenance.json'
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
MESSAGE_RE = re.compile(
    re.escape(WORDING_HEAD) + r'\n([0-9a-f]{64})\n\n' + re.escape(WORDING_TAIL))

PROVENANCE_KEYS = {
    'evidence_version', 'run_id', 'host_id', 'stage', 'iteration',
    'source', 'message_file', 'message_sha256', 'approved_receipt_sha256',
    'session_id', 'reveal_event_hash', 'annotation_attempt',
    'recorded_at', 'recorded_by',
}


def fail(msg):
    raise RuntimeError(f'{G}: {msg}')


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def fixed_wording(receipt_sha):
    """The taskbook §5 B4 template rendered with a concrete hash."""
    return WORDING_HEAD + '\n' + receipt_sha + '\n\n' + WORDING_TAIL


def parse_human_message(raw):
    """Exact fixed-wording check. Returns the embedded 64-hex hash or
    fails closed on ANY wording drift (including trailing whitespace)."""
    if not isinstance(raw, (bytes, bytearray)):
        fail('human message must be exact bytes')
    try:
        text = bytes(raw).decode('utf-8')
    except UnicodeDecodeError:
        fail('human message is not valid UTF-8')
    m = MESSAGE_RE.fullmatch(text)
    if not m:
        fail('human message does not match the taskbook §5 B4 fixed '
             'wording (template + <64 hex>; no extra/missing characters)')
    return m.group(1)


def receipt_sha256(root=CSR):
    return sha256_bytes(
        (c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) / 'receipt.json')
        .read_bytes())


def show_gate():
    """Step 1 trace: display receipt_sha256 + the fixed wording only."""
    rsha = receipt_sha256()
    return {'run_id': RUN_ID, 'host_id': HOST_ID, 'stage': STAGE,
            'iteration': ITERATION, 'session_id': SID,
            'reveal_event_hash': REVEAL, 'annotation_attempt': ATTEMPT,
            'receipt_sha256': rsha,
            'approval_wording': fixed_wording(rsha)}


def _message_file_rel(message_path):
    p = Path(message_path).resolve()
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return p.as_posix()


def _expected_provenance(message_bytes, rsha, message_path=MESSAGE_EVIDENCE):
    return {
        'evidence_version': 'c4d-b4-approval-evidence-v1',
        'run_id': RUN_ID,
        'host_id': HOST_ID,
        'stage': STAGE,
        'iteration': ITERATION,
        'source': 'bound-session human reply, verbatim transcription '
                  '(trailing transport newline excluded)',
        'message_file': _message_file_rel(message_path),
        'message_sha256': sha256_bytes(message_bytes),
        'approved_receipt_sha256': rsha,
        'session_id': SID,
        'reveal_event_hash': REVEAL,
        'annotation_attempt': ATTEMPT,
        'recorded_at': datetime.now(timezone.utc)
                               .strftime('%Y-%m-%dT%H:%M:%SZ'),
        'recorded_by': 'executor persist triggered only after the '
                       'bound-session human approval message',
    }


def verify_b4(root=CSR, message_path=MESSAGE_EVIDENCE,
              provenance_path=PROVENANCE):
    """Re-prove the whole B4 gate from persisted bytes only."""
    b3.verify_b3(root)
    rbytes = (c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) /
              'receipt.json').read_bytes()
    rsha = sha256_bytes(rbytes)

    # --- human approval message: fixed wording + exact hash binding ---
    if not Path(message_path).is_file():
        fail(f'human approval message evidence absent: {message_path}')
    message_bytes = Path(message_path).read_bytes()
    approved_sha = parse_human_message(message_bytes)
    if approved_sha != rsha:
        fail('wording hash differs from SHA256(exact receipt bytes) — '
             'not character-identical')

    # --- persisted seal_approval.json (frozen closed-world schema) ---
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
    if approved_sha != approval['approved_receipt_sha256']:
        fail('human message hash != approval approved_receipt_sha256')
    if b1.mode_of(apath) != 0o600:
        fail('approval mode is not 0600')

    # --- frozen re-proof: the exact checks B5/seal preflight will run ---
    r1 = b1.read_chain(root, SID)[0]
    c4d._check_seal_approval(root, SID, ORDINAL, ATTEMPT, rbytes, r1, G)
    history = c4d.prove_attempt_history(root, SID, ORDINAL, gate=G)
    if history['live'] != [ATTEMPT]:
        fail(f'attempt {ATTEMPT} is not the sole live attempt '
             f'(live={history["live"]})')

    # --- provenance record binds THIS run + the message bytes ---
    if not Path(provenance_path).is_file():
        fail(f'approval provenance record absent: {provenance_path}')
    pb = Path(provenance_path).read_bytes()
    try:
        prov = json.loads(pb)
    except json.JSONDecodeError:
        fail('provenance record is not JSON')
    if not isinstance(prov, dict) or set(prov) != PROVENANCE_KEYS:
        fail('provenance closed-world schema violation')
    if c4d.canon(prov).encode() != pb:
        fail('provenance record is not canonical')
    expected = _expected_provenance(message_bytes, rsha, message_path)
    for key in ('run_id', 'host_id', 'stage', 'iteration', 'session_id',
                'reveal_event_hash', 'annotation_attempt',
                'approved_receipt_sha256', 'message_sha256',
                'message_file'):
        if prov.get(key) != expected[key]:
            fail(f'provenance {key} does not bind this run/message '
                 f'({prov.get(key)!r} != {expected[key]!r})')

    return {'gates': {'human_fixed_phrase': 'PASS',
                      'receipt_hash_exact': 'PASS',
                      'message_provenance': 'PASS',
                      'session_reveal_attempt': 'PASS',
                      'closed_world_canonical': 'PASS',
                      'frozen_reproof': 'PASS',
                      'o_excl_0600_fsync': 'PASS'},
            'receipt_sha256': rsha, 'attempt': ATTEMPT,
            'message_sha256': sha256_bytes(message_bytes)}


def persist(message_path=MESSAGE_EVIDENCE, root=CSR,
            provenance_path=PROVENANCE):
    """Persist ONLY from a valid human message evidence file. No
    in-script message exists; approval cannot be self-fabricated here
    without leaving a mismatched, verifiable trace."""
    b3.verify_b3(root)                      # full B1-B3 proof first
    if not Path(message_path).is_file():
        fail(f'human approval message evidence absent: {message_path} — '
             f'persistence is impossible without the bound-session human '
             f'reply')
    rsha = receipt_sha256(root)
    message_bytes = Path(message_path).read_bytes()
    approved_sha = parse_human_message(message_bytes)
    if approved_sha != rsha:
        fail('message hash mismatch vs exact receipt bytes; refusing '
             'persistence')
    apath = c4d.attempt_dir(root, SID, ORDINAL, ATTEMPT) / 'seal_approval.json'
    if apath.exists():
        fail('approval already exists; immutable O_EXCL artifact')
    # frozen transaction: O_EXCL / canonical / 0600 / fsync (file+parent)
    c4d.make_seal_approval(root, SID, ordinal=ORDINAL, attempt=ATTEMPT,
                           receipt_sha=approved_sha)
    prov_obj = _expected_provenance(message_bytes, rsha, message_path)
    c4d.excl_write(Path(provenance_path), c4d.canon(prov_obj).encode())
    result = verify_b4(root, message_path, provenance_path)
    result['b4'] = 'APPROVAL_PERSISTED'
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true')
    ap.add_argument('--show-gate', action='store_true')
    ap.add_argument('--message-file', default=str(MESSAGE_EVIDENCE))
    args = ap.parse_args()
    if args.show_gate:
        result = show_gate()
    elif args.verify:
        result = verify_b4()
        result['b4'] = 'VERIFIED'
    else:
        result = persist(Path(args.message_file))
    print(json.dumps(result, sort_keys=True, ensure_ascii=False,
                     separators=(',', ':')))
