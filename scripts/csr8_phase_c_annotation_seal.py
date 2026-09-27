#!/usr/bin/env python3
"""CSR-8 Phase C4-D — annotation + SEAL synthetic executor (SYNTHETIC ONLY).

Implements the FROZEN design
  PHASE_C_C4D_ANNOTATION_SEAL_DESIGN.md v1.0 FINAL FROZEN @ 034d152
under the user's synthetic-only authorization:

  ALLOWED : synthetic code, sandbox construction, D01-D46 target-aware
            fixtures, recovery/crash matrix, C4-C regression, deterministic
            candidate tests.
  FORBIDDEN: real annotator / c4d_receipts / c4d_proposals domains, real
            draft/receipt/approval, production SEAL, ordinal-2 proposal on
            the real chain, a second real REVEAL, modifying the frozen C4-C
            executor or c4c_anchor.json.

Frozen modules are IMPORTED read-only (c1 / c2 / c4ab / c4c); nothing in
them is modified. Every operation here takes an explicit sandbox root;
cmd_synthetic is strictly read-only on real state and proves that.
"""

import contextlib
import hashlib
import hmac
import io
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_packet as c1         # frozen C1 (read-only use)
import csr8_phase_c_seal as c2           # frozen C2 state machine
import csr8_phase_c_activate as c4ab     # frozen C4-A/B helpers
import csr8_phase_c_first_reveal as c4c  # frozen C4-C (read-only reuse)

# --------------------------------------------------------------------------
# frozen constants (design v1.0 FINAL FROZEN @ 034d152)
# --------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
REAL_CSR = ROOT / 'data/csr8_phase_c'
REAL_SESSION = 'c4-prod-0002'
REAL_PRODUCTION = REAL_CSR / 'production'
REAL_ANNOTATOR = REAL_CSR / 'annotator'
REAL_RECEIPTS = REAL_CSR / 'c4d_receipts'
REAL_PROPOSALS_C4D = REAL_CSR / 'c4d_proposals'
PUBLIC_DIR = ROOT / ('output/research/csr/08_pilot_cases/phase_c/'
                     'c4_public')
C4D_ANCHOR_NAME = 'c4d_seal_anchor.json'
LIVE_R1_EVENT_HASH = ('b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16'
                      'faa80d8f19437d5')

G_VIS = 'G-C4D-VISIBILITY'
G_HAND = 'G-C4D-HANDOFF'
G_DRAFT = 'G-C4D-DRAFT'
G_REC = 'G-C4D-RECEIPT'
G_PRE = 'G-C4D-SEAL-PREFLIGHT'
G_REP = 'G-C4D-SEAL-REPLAY'
G_AUTHZ = 'G-C4D-AUTHZ'
G_BOUND = 'G-C4D-BOUNDARY'
G_CAND = 'G-C4D-CAND'

# §4.1 exact frozen preimage (byte-identical to design §4.1.1 single line)
ANNOTATION_CONTRACT = {
    "contract_version": "c4d-annotation-content-v1",
    "source": "CSR_7_CASE_PROTOCOL.yaml hypothesis_block (frozen) — copied "
              "verbatim, not redefined",
    "hypotheses": ["rt_H01", "rt_H02", "rt_H03", "rt_H04", "rt_H05",
                   "rt_H06"],
    "judgment_rule": "exactly one judgment per hypothesis; order fixed as "
                     "listed; none may be dropped",
    "observability_enum": ["OBSERVABLE", "UNOBSERVABLE"],
    "support_enum": ["SUPPORTED_STRONG", "SUPPORTED_PARTIAL", "MIXED",
                     "NOT_OBSERVED", "CONTRADICTED"],
    "support_presence_rule": "support present iff observability == "
                             "OBSERVABLE; UNOBSERVABLE leaves support "
                             "empty (data absence != disconfirmation)",
    "unjudgeable_mapping": "CSR-7-native UNOBSERVABLE realizes 'cannot "
                           "judge' — no hypothesis may be deleted",
    "flags_enum": ["DATA_QUALITY_ISSUE", "EVIDENCE_INCOMPLETE_AT_T",
                   "PACKET_PARSE_ANOMALY", "FLAGGED_FOR_REVIEW"],
    "flags_rule": "flags may be empty; values unique; closed set",
}
ANNOTATION_CONTRACT_SHA256 = (
    '5f5f01503ea255e87e784ea55da0709e5a53ff26b2b62dc9534cff46537509de')
HYPOTHESES = tuple(ANNOTATION_CONTRACT['hypotheses'])
OBS_ENUM = tuple(ANNOTATION_CONTRACT['observability_enum'])
SUPPORT_ENUM = tuple(ANNOTATION_CONTRACT['support_enum'])
FLAGS_ENUM = tuple(ANNOTATION_CONTRACT['flags_enum'])

DRAFT_TOP = {'draft_version', 'session_id', 'packet_id', 'packet_sha256',
             'annotation_session_id', 'annotation_attempt', 'annotation',
             'created_at', 'updated_at'}
ANNOTATION_KEYS = {'annotation_contract_sha256', 'rt_judgments',
                   'overall_note', 'flags'}
JUDGMENT_KEYS = {'hypothesis_id', 'observability', 'support',
                 'evidence_refs', 'evidence_note'}
RECEIPT_TOP = {'receipt_version', 'session_id', 'packet_id',
               'packet_sha256', 'reveal_event_hash', 'annotation_attempt',
               'draft_sha256', 'annotation', 'annotation_session_id',
               'receipt_id', 'created_at'}
APPROVAL_KEYS = {'approval_version', 'scope', 'session_id',
                 'reveal_event_hash', 'annotation_attempt',
                 'approved_receipt_sha256', 'approved', 'created_at'}
REVOCATION_KEYS = {'revocation_version', 'session_id', 'reveal_event_hash',
                   'annotation_attempt', 'receipt_sha256', 'reason_code',
                   'created_at'}
REASON_CODES = ('DRAFT_ERROR', 'BINDING_ERROR', 'ANNOTATOR_REQUEST',
                'OTHER')
REVEAL_PROPOSAL_KEYS = {'authorization_version', 'scope', 'reveal_ordinal',
                        'session_id', 'sealed_prefix_head',
                        'c3_manifest_commitment', 'candidate_packet_id',
                        'candidate_packet_sha256', 'authorized',
                        'authorization_id', 'created_at'}
REVEAL_APPROVAL_KEYS = {'approval_version', 'scope', 'session_id',
                        'reveal_ordinal', 'sealed_prefix_head',
                        'approved_authorization_sha256', 'approved',
                        'created_at'}

RECEIPT_VERSION = 'c4d-receipt-v1'
APPROVAL_VERSION = 'c4d-seal-approval-v1'
REVOCATION_VERSION = 'c4d-receipt-revocation-v1'
REVEAL_AUTHZ_VERSION = 'c4d-reveal-v1'

SYNTH_CASE = 'C4D_SYNTH_A'
SYNTH_T = '2099-01-02'


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fail(msg):
    print('FAIL-CLOSED:', msg)
    raise RuntimeError(msg)


class CrashSim(Exception):
    """Clean stop at a transaction checkpoint to simulate a crash point."""


def expect_exact_gate(fn, expected):
    try:
        fn()
    except (RuntimeError, SystemExit) as e:
        msg = str(e) if isinstance(e, RuntimeError) else f'sysexit:{e.code}'
        if expected not in msg:
            raise RuntimeError(f'fixture gate mismatch: expected '
                               f'"{expected}", got "{msg}"')
        print(f'NEGATIVE PASS: target gate hit -> {expected}')
        return msg
    raise RuntimeError('fixture did not fail as expected')


def c2translate(fn, *a, **k):
    """Run a frozen-C2 call; translate its print+sys.exit FAIL-CLOSED into
    a RuntimeError carrying the same message (delegated gates stay
    target-aware assertable)."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            return fn(*a, **k)
    except SystemExit:
        raise RuntimeError(f'C2-delegated: {buf.getvalue().strip()}')


def fsync_file(path):
    c4c.fsync_file(path)


def fsync_dir(path):
    c4c.fsync_dir(path)


def excl_write(path, data):
    c4c.excl_write(path, data)


def read_json(path):
    return json.loads(Path(path).read_text())


def verify_contract_constant():
    if sha(canon(ANNOTATION_CONTRACT).encode()) != ANNOTATION_CONTRACT_SHA256:
        fail('FROZEN-CONTRACT: annotation contract constant does not hash '
             'to the frozen 5f5f0150…509de — do not proceed')


def mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


# --------------------------------------------------------------------------
# sandbox layout
# --------------------------------------------------------------------------

def prod_dir(sb, sid):
    return sb / 'production' / sid


def sealing_dir(sb, sid):
    return prod_dir(sb, sid) / 'sealing'


def log_path(sb, sid):
    return sealing_dir(sb, sid) / 'sealing_log.jsonl'


def head_path(sb, sid):
    return log_path(sb, sid).with_suffix('.head.json')


def annot_dom(sb, sid):
    return sb / 'annotator' / sid


def packet_path(sb, sid, packet_id):
    return annot_dom(sb, sid) / 'packet' / f'{packet_id}.json'


def draft_path(sb, sid):
    return annot_dom(sb, sid) / 'draft' / 'annotation_draft.json'


def receipts_dom(sb, sid):
    return sb / 'c4d_receipts' / sid


def ordinal_dir(sb, sid, ordinal):
    return receipts_dom(sb, sid) / f'ordinal-{ordinal:04d}'


def attempt_dir(sb, sid, ordinal, n):
    return ordinal_dir(sb, sid, ordinal) / f'attempt-{n:04d}'


def attempt_staging(sb, sid, ordinal, n):
    return ordinal_dir(sb, sid, ordinal) / f'attempt-{n:04d}.staging'


def proposals_dom(sb, sid, ordinal):
    return sb / 'c4d_proposals' / sid / f'ordinal-{ordinal:04d}'


def proposal_path(sb, sid, ordinal):
    return proposals_dom(sb, sid, ordinal) / 'next_reveal.proposal.json'


def next_authz_dir(sb, sid, ordinal):
    return prod_dir(sb, sid) / 'authorization' / f'ordinal-{ordinal:04d}'


def anchor_path_in(sb):
    return sb / 'c4_public' / C4D_ANCHOR_NAME


# --------------------------------------------------------------------------
# synthetic r1 chain + packet (C4-D-local fixtures, never the real secret)
# --------------------------------------------------------------------------

def synth_packet_obj(case, T):
    ocid = c2.synth_ocid(case)
    pid = sha(f'{ocid}|{T}'.encode())
    return {'as_of': T,
            'evidence': [{'id': 'E-MKT-01'}, {'id': 'E-STK-03'},
                         {'id': 'E-SEC-02'}],
            'opaque_case_id': ocid,
            'packet_id': pid,
            'price_panel': {'close': [1.0, 1.5, 2.0],
                            'volume': [10, 20, 30]}}


def synth_packet_bytes(case, T):
    return canon(synth_packet_obj(case, T)).encode()


def build_r1(sb, sid, case=SYNTH_CASE, T=SYNTH_T):
    """Sandbox chain with exactly one REVEAL r1 (ordinal-1 payload shape
    mirroring the live event)."""
    sealing_dir(sb, sid).mkdir(parents=True, exist_ok=True, mode=0o700)
    pkt = synth_packet_bytes(case, T)
    ocid = c2.synth_ocid(case)
    payload = {'opaque_case_id': ocid, 'T': T,
               'packet_id': sha(f'{ocid}|{T}'.encode()),
               'packet_sha256': sha(pkt), 'session_id': sid,
               'authorization_id': 'synthetic-authz-r1',
               'authorization_sha256': sha(b'synthetic-authz-r1'),
               'c3_manifest_commitment': c4ab.C3_COMMITMENT,
               'candidate_packet_sha256': sha(pkt)}
    log = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    ev = c2translate(log.append, c2.REVEAL, payload, pkt)
    return ev, pkt


def chain_events(sb, sid):
    return c2.read_events(log_path(sb, sid))


# --------------------------------------------------------------------------
# §2 visibility domain (closed-world, machine-asserted)
# --------------------------------------------------------------------------

EXPECTED_ANNOTATOR_TOP = {'packet', 'draft'}


def check_visibility_domain(sb, sid):
    dom = annot_dom(sb, sid)
    if not dom.exists():
        return  # absent/empty legal pre-handoff & post-cleanup
    if mode_of(dom) != 0o700:
        fail(f'{G_VIS}: annotator domain mode drift '
             f'({oct(mode_of(dom))})')
    for p in sorted(dom.rglob('*')):
        rel = p.relative_to(dom)
        if p.is_dir():
            if len(rel.parts) != 1 or rel.parts[0] not in \
                    EXPECTED_ANNOTATOR_TOP:
                fail(f'{G_VIS}: unexpected directory in annotator domain: '
                     f'{rel}')
            if mode_of(p) != 0o700:
                fail(f'{G_VIS}: annotator subdirectory mode drift: {rel}')
        else:
            if len(rel.parts) != 2 or rel.parts[0] not in \
                    EXPECTED_ANNOTATOR_TOP:
                fail(f'{G_VIS}: unexpected file in annotator domain: {rel}')
            m = mode_of(p)
            if rel.parts[0] == 'packet' and m != 0o600:
                fail(f'{G_VIS}: packet file mode drift: {rel}')
            if rel.parts[0] == 'draft' and m not in (0o600, 0o400):
                fail(f'{G_VIS}: draft file mode drift: {rel}')
    packets = list((dom / 'packet').glob('*')) \
        if (dom / 'packet').exists() else []
    drafts = list((dom / 'draft').glob('*')) \
        if (dom / 'draft').exists() else []
    if len(packets) > 1:
        fail(f'{G_VIS}: packet-count leak — {len(packets)} packet files '
             f'in active workspace')
    if len(drafts) > 1:
        fail(f'{G_VIS}: more than one draft file in active workspace')
    for p in packets:
        pid = p.stem
        if p.name != f'{pid}.json' or len(pid) != 64 or any(
                ch not in '0123456789abcdef' for ch in pid):
            fail(f'{G_VIS}: packet filename not <packet_id>.json: {p.name}')


def handoff(sb, sid, case=SYNTH_CASE, T=SYNTH_T, bytes_override=None):
    """§2.2: annotator receives exact packet bytes copy (O_EXCL)."""
    r1 = chain_events(sb, sid)[-1]
    pkt = bytes_override if bytes_override is not None else \
        synth_packet_bytes(case, T)
    if sha(pkt) != r1['payload']['packet_sha256']:
        fail(f'{G_HAND}: handoff bytes do not match REVEAL payload '
             f'packet_sha256 (exact-copy contract)')
    dom = annot_dom(sb, sid)
    dom.mkdir(parents=True, exist_ok=True, mode=0o700)
    (dom / 'packet').mkdir(exist_ok=True, mode=0o700)
    target = packet_path(sb, sid, r1['payload']['packet_id'])
    if target.exists():
        fail(f'{G_HAND}: duplicate handoff — packet file already exists '
             f'(O_EXCL contract)')
    excl_write(target, pkt)
    check_visibility_domain(sb, sid)
    return target


# --------------------------------------------------------------------------
# §4.1/§4.2 draft content validation (G-C4D-DRAFT)
# --------------------------------------------------------------------------

def resolve_pointer(ptr, obj):
    """Minimal JSON Pointer (RFC 6901); None => unresolved."""
    if not isinstance(ptr, str) or not ptr.startswith('/'):
        return None
    cur = obj
    for raw in ptr[1:].split('/'):
        tok = raw.replace('~1', '/').replace('~0', '~')
        try:
            if isinstance(cur, list):
                cur = cur[int(tok)]
            elif isinstance(cur, dict):
                cur = cur[tok]
            else:
                return None
        except (IndexError, KeyError, ValueError):
            return None
    return cur


def validate_draft(sb, sid, draft, packet_obj):
    r1 = chain_events(sb, sid)[-1]
    if not isinstance(draft, dict) or set(draft.keys()) != DRAFT_TOP:
        keys = set(draft.keys()) if isinstance(draft, dict) else set()
        extra, missing = keys - DRAFT_TOP, DRAFT_TOP - keys
        fail(f'{G_DRAFT}: draft top-level schema violation '
             f'(extra={sorted(extra)} missing={sorted(missing)})')
    if draft['draft_version'] != 'c4d-draft-v1':
        fail(f'{G_DRAFT}: unknown draft_version')
    if draft['session_id'] != sid:
        fail(f'{G_DRAFT}: draft session binding violated')
    if draft['packet_id'] != r1['payload']['packet_id'] or \
            draft['packet_sha256'] != r1['payload']['packet_sha256']:
        fail(f'{G_DRAFT}: draft packet binding violated')
    if not isinstance(draft['annotation_attempt'], int) or \
            draft['annotation_attempt'] < 1:
        fail(f'{G_DRAFT}: annotation_attempt must be a positive integer')
    if not isinstance(draft['annotation_session_id'], str) or \
            not draft['annotation_session_id']:
        fail(f'{G_DRAFT}: annotation_session_id missing (opaque session id)')
    ann = draft['annotation']
    if not isinstance(ann, dict) or set(ann.keys()) != ANNOTATION_KEYS:
        fail(f'{G_DRAFT}: annotation schema violation (closed-world)')
    if ann['annotation_contract_sha256'] != ANNOTATION_CONTRACT_SHA256:
        fail(f'{G_DRAFT}: annotation contract drift — frozen constant '
             f'mismatch')
    js = ann['rt_judgments']
    if not isinstance(js, list) or len(js) != len(HYPOTHESES):
        fail(f'{G_DRAFT}: rt_judgments must carry exactly one judgment per '
             f'hypothesis ({len(HYPOTHESES)}) — none may be dropped')
    for i, (j, hid) in enumerate(zip(js, HYPOTHESES)):
        if not isinstance(j, dict) or set(j.keys()) != JUDGMENT_KEYS:
            fail(f'{G_DRAFT}: judgment {i} schema violation (closed-world)')
        if j['hypothesis_id'] != hid:
            fail(f'{G_DRAFT}: rt_judgments out of frozen order at {i} '
                 f'({j["hypothesis_id"]} != {hid})')
        if j['observability'] not in OBS_ENUM:
            fail(f'{G_DRAFT}: observability outside frozen enum at {hid}')
        sup = j['support']
        if j['observability'] == 'OBSERVABLE':
            if sup not in SUPPORT_ENUM:
                fail(f'{G_DRAFT}: OBSERVABLE requires a frozen five-level '
                     f'support at {hid}')
        elif sup is not None:
            fail(f'{G_DRAFT}: UNOBSERVABLE must leave support empty at '
                 f'{hid} (data absence != disconfirmation)')
        refs = j['evidence_refs']
        if not isinstance(refs, list):
            fail(f'{G_DRAFT}: evidence_refs must be a list at {hid}')
        for ptr in refs:
            if resolve_pointer(ptr, packet_obj) is None:
                fail(f'{G_DRAFT}: evidence_ref does not resolve inside the '
                     f'current packet: {ptr} (at {hid})')
        if not isinstance(j['evidence_note'], str) or \
                len(j['evidence_note']) > 500:
            fail(f'{G_DRAFT}: evidence_note must be <=500 chars at {hid}')
    if not isinstance(ann['overall_note'], str) or \
            len(ann['overall_note']) > 2000:
        fail(f'{G_DRAFT}: overall_note must be <=2000 chars')
    flags = ann['flags']
    if not isinstance(flags, list) or len(set(flags)) != len(flags) or \
            any(f not in FLAGS_ENUM for f in flags):
        fail(f'{G_DRAFT}: flags outside frozen closed set (or duplicated)')


def sample_annotation(contract_hash=ANNOTATION_CONTRACT_SHA256):
    js = []
    for i, hid in enumerate(HYPOTHESES, start=1):
        observable = (i % 2 == 1)
        js.append({
            'hypothesis_id': hid,
            'observability': 'OBSERVABLE' if observable else 'UNOBSERVABLE',
            'support': 'SUPPORTED_PARTIAL' if observable else None,
            'evidence_refs': ['/evidence/0'] if observable else [],
            'evidence_note': f'synth note {i}',
        })
    return {'annotation_contract_sha256': contract_hash,
            'rt_judgments': js,
            'overall_note': 'synthetic overall note',
            'flags': []}


def sample_draft(sb, sid, attempt=1, ann_session='annsess-opaque-0001',
                 annotation=None):
    r1 = chain_events(sb, sid)[-1]
    return {
        'draft_version': 'c4d-draft-v1',
        'session_id': sid,
        'packet_id': r1['payload']['packet_id'],
        'packet_sha256': r1['payload']['packet_sha256'],
        'annotation_session_id': ann_session,
        'annotation_attempt': attempt,
        'annotation': annotation if annotation is not None else
        sample_annotation(),
        'created_at': '2099-01-02T00:00:00Z',
        'updated_at': '2099-01-02T00:00:00Z',
    }


def write_draft(sb, sid, draft, mode=0o600):
    dom = annot_dom(sb, sid) / 'draft'
    dom.mkdir(parents=True, exist_ok=True, mode=0o700)
    dp = draft_path(sb, sid)
    if dp.exists():
        dp.write_bytes(canon(draft).encode())   # OPEN state: free rewrite
        os.chmod(dp, mode)
    else:
        excl_write(dp, canon(draft).encode())
    return dp


# --------------------------------------------------------------------------
# attempt bookkeeping (F5) + receipt publication (§4.3, FIX3-F19)
# --------------------------------------------------------------------------

def active_ordinal(sb, sid):
    return sum(1 for e in chain_events(sb, sid)
               if e['event_type'] == c2.REVEAL)


def attempts_published(sb, sid, ordinal):
    d = ordinal_dir(sb, sid, ordinal)
    if not d.exists():
        return []
    return sorted(int(p.name.split('-')[1]) for p in d.iterdir()
                  if p.is_dir() and p.name.startswith('attempt-')
                  and not p.name.endswith('.staging'))


def next_attempt(sb, sid, ordinal):
    ns = attempts_published(sb, sid, ordinal)
    return (ns[-1] + 1) if ns else 1


def active_attempt(sb, sid, ordinal):
    """F5: max attempt number without a revocation (earlier attempts stay
    published and are permanently INELIGIBLE_FOR_SEAL)."""
    ns = attempts_published(sb, sid, ordinal)
    live = [n for n in ns
            if not (attempt_dir(sb, sid, ordinal, n) / 'revocation.json'
                    ).exists()]
    return live[-1] if live else None


def build_receipt_object(sb, sid, draft, r1, attempt):
    return {
        'receipt_version': RECEIPT_VERSION,
        'session_id': sid,
        'packet_id': draft['packet_id'],
        'packet_sha256': draft['packet_sha256'],
        'reveal_event_hash': r1['event_hash'],
        'annotation_attempt': attempt,
        'draft_sha256': sha(canon(draft).encode()),
        'annotation': draft['annotation'],
        'annotation_session_id': draft['annotation_session_id'],
        'receipt_id': f'receipt-{uuid.uuid4().hex[:12]}',
        'created_at': '2099-01-02T00:00:00Z',
    }


def make_receipt(sb, sid, ordinal=None, stop_after=None):
    """§4.3 F19 frozen 8-step order. Invariant: attempt exists => draft
    locked 0400 with bytes == draft_snapshot.bin."""
    if ordinal is None:
        ordinal = active_ordinal(sb, sid)
    r1 = [e for e in chain_events(sb, sid)
          if e['event_type'] == c2.REVEAL][-1]
    dp = draft_path(sb, sid)

    def stop(name):
        if stop_after == name:
            raise CrashSim(name)

    # 1. read exact active draft bytes D, closed-world validate
    D = dp.read_bytes()
    draft = json.loads(D)
    packet_obj = json.loads(
        packet_path(sb, sid, draft['packet_id']).read_bytes())
    validate_draft(sb, sid, draft, packet_obj)
    attempt = next_attempt(sb, sid, ordinal)
    if draft['annotation_attempt'] != attempt:
        fail(f'{G_REC}: draft annotation_attempt != next attempt number '
             f'(attempt bookkeeping)')
    # 2. staging construction (receipt canonical + snapshot == D)
    od = ordinal_dir(sb, sid, ordinal)
    od.mkdir(parents=True, exist_ok=True, mode=0o700)
    for anc in (sb / 'c4d_receipts', receipts_dom(sb, sid)):
        if not anc.exists():
            anc.mkdir(mode=0o700)
    staging = attempt_staging(sb, sid, ordinal, attempt)
    if staging.exists():
        fail(f'{G_REC}: staging leftover blocking make_receipt — run '
             f'recovery first ({staging})')
    staging.mkdir(mode=0o700)
    receipt = build_receipt_object(sb, sid, draft, r1, attempt)
    rbytes = canon(receipt).encode()
    excl_write(staging / 'receipt.json', rbytes)
    excl_write(staging / 'draft_snapshot.bin', D)
    # 3. fsync both files + staging dir
    fsync_file(staging / 'receipt.json')
    fsync_file(staging / 'draft_snapshot.bin')
    fsync_dir(staging)
    stop('after_staging_fsync')
    # 4. lock: chmod active draft 0400
    os.chmod(dp, 0o400)
    stop('after_lock')
    # 5. reread must still be exact == D (lock-race guard)
    if dp.read_bytes() != D:
        fail(f'{G_REC}: active draft content changed during lock — HALT '
             f'(no receipt published)')
    # 6. fsync draft + parent
    fsync_file(dp)
    fsync_dir(dp.parent)
    stop('after_draft_fsync')
    # 7. atomic publication of the WHOLE attempt
    rename_noreplace_wrap(staging, attempt_dir(sb, sid, ordinal, attempt))
    stop('after_rename')
    # 8. fsync ordinal parent
    fsync_dir(od)
    return receipt, rbytes


def rename_noreplace_wrap(src, dst):
    c4c.rename_noreplace(src, dst)


def receipt_bytes_of(sb, sid, ordinal, attempt):
    return (attempt_dir(sb, sid, ordinal, attempt) /
            'receipt.json').read_bytes()


# --------------------------------------------------------------------------
# attempt artifact validation (shared by approval gate + semantic replay)
# --------------------------------------------------------------------------

def _check_attempt_artifacts(sb, sid, ordinal, attempt, r1, gate):
    adir = attempt_dir(sb, sid, ordinal, attempt)
    rpath = adir / 'receipt.json'
    if not rpath.exists() or not (adir / 'draft_snapshot.bin').exists():
        fail(f'{gate}: attempt {attempt} incomplete (receipt/snapshot)')
    rbytes = rpath.read_bytes()
    try:
        obj = json.loads(rbytes)
    except json.JSONDecodeError:
        fail(f'{gate}: persisted receipt is not JSON')
    if not isinstance(obj, dict) or set(obj.keys()) != RECEIPT_TOP:
        fail(f'{gate}: receipt closed-world schema violation')
    if canon(obj).encode() != rbytes:
        fail(f'{gate}: persisted receipt bytes are noncanonical '
             f'(exact-bytes contract)')
    if obj['receipt_version'] != RECEIPT_VERSION:
        fail(f'{gate}: unknown receipt_version')
    if obj['session_id'] != sid:
        fail(f'{gate}: receipt session binding violated')
    if obj['reveal_event_hash'] != r1['event_hash']:
        fail(f'{gate}: receipt reveal binding violated')
    if obj['packet_id'] != r1['payload']['packet_id'] or \
            obj['packet_sha256'] != r1['payload']['packet_sha256']:
        fail(f'{gate}: receipt packet binding violated')
    if obj['annotation_attempt'] != attempt:
        fail(f'{gate}: receipt attempt binding violated')
    if obj['annotation'].get('annotation_contract_sha256') != \
            ANNOTATION_CONTRACT_SHA256:
        fail(f'{gate}: annotation contract drift inside receipt')
    if obj['draft_sha256'] != sha((adir / 'draft_snapshot.bin').read_bytes()):
        fail(f'{gate}: draft snapshot equality broken '
             f'(receipt.draft_sha256 != SHA256(snapshot))')
    if (adir / 'revocation.json').exists():
        fail(f'{gate}: attempt {attempt} is revoked (INELIGIBLE_FOR_SEAL)')
    return rbytes, obj


def make_seal_approval(sb, sid, ordinal=None, attempt=None,
                       r1=None, receipt_sha=None):
    """§4.4 persisted human exact-hash approval (c4d-seal-approval-v1)."""
    if ordinal is None:
        ordinal = active_ordinal(sb, sid)
    if r1 is None:
        r1 = [e for e in chain_events(sb, sid)
              if e['event_type'] == c2.REVEAL][-1]
    if attempt is None:
        attempt = active_attempt(sb, sid, ordinal)
        if attempt is None:
            if attempts_published(sb, sid, ordinal):
                fail(f'{G_REC}: all published attempts revoked — approval '
                     f'refused (append-only tombstone contract)')
            fail(f'{G_PRE}: no attempt published — nothing to approve')
    rbytes, _ = _check_attempt_artifacts(sb, sid, ordinal, attempt, r1,
                                         G_REC)
    adir = attempt_dir(sb, sid, ordinal, attempt)
    if (adir / 'seal_approval.json').exists():
        fail(f'{G_REC}: duplicate seal approval (O_EXCL, immutable)')
    if receipt_sha is None:
        receipt_sha = sha(rbytes)
    approval = {
        'approval_version': APPROVAL_VERSION,
        'scope': 'SEAL_ANNOTATION_ONLY',
        'session_id': sid,
        'reveal_event_hash': r1['event_hash'],
        'annotation_attempt': attempt,
        'approved_receipt_sha256': receipt_sha,
        'approved': True,
        'created_at': '2099-01-02T00:00:00Z',
    }
    excl_write(adir / 'seal_approval.json', canon(approval).encode())
    return approval


def revoke_receipt(sb, sid, reason_code, ordinal=None, attempt=None):
    """§4.5 append-only tombstone; NEVER delete the receipt."""
    if reason_code not in REASON_CODES:
        fail(f'{G_REC}: reason_code outside frozen closed set')
    if ordinal is None:
        ordinal = active_ordinal(sb, sid)
    if attempt is None:
        attempt = active_attempt(sb, sid, ordinal)
        if attempt is None:
            fail(f'{G_REC}: no active attempt to revoke')
    adir = attempt_dir(sb, sid, ordinal, attempt)
    if (adir / 'seal_approval.json').exists():
        fail(f'{G_REC}: revocation forbidden once seal_approval exists '
             f'(approve-A-seal-B complexity)')
    r1 = [e for e in chain_events(sb, sid)
          if e['event_type'] == c2.REVEAL][-1]
    tomb = {
        'revocation_version': REVOCATION_VERSION,
        'session_id': sid,
        'reveal_event_hash': r1['event_hash'],
        'annotation_attempt': attempt,
        'receipt_sha256': sha((adir / 'receipt.json').read_bytes()),
        'reason_code': reason_code,
        'created_at': '2099-01-02T00:00:00Z',
    }
    excl_write(adir / 'revocation.json', canon(tomb).encode())
    return tomb


# --------------------------------------------------------------------------
# §3 lifecycle derivation (persisted files only; no writable state field)
# --------------------------------------------------------------------------

def chain_has_legal_seal(sb, sid):
    """(seal_event_or_None, ok) — ok iff full replay incl. head passes."""
    try:
        lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
        c2translate(lg.load().verify, True)
    except RuntimeError:
        return None, False
    seals = [e for e in lg.events if e['event_type'] == c2.SEAL]
    return (seals[-1] if seals else None), True


def finalize_complete(sb, sid, seal_ev):
    expected = {'production_head_hash': seal_ev['event_hash'],
                'seal_receipt_sha256': seal_ev['payload']['receipt_sha256'],
                'sealed_count': 1, 'experiment_started': True}
    apath = anchor_path_in(sb)
    if not apath.exists() or read_json(apath) != expected:
        return False
    dom = annot_dom(sb, sid)
    return not (dom.exists() and any(dom.rglob('*')))


def derive_state(sb, sid):
    """-> (state, info) in the frozen lifecycle vocabulary."""
    ordinal = active_ordinal(sb, sid)
    seal_ev, ok = chain_has_legal_seal(sb, sid)
    if not ok:
        return 'FORENSIC', {'ordinal': ordinal}
    if seal_ev is not None:
        if finalize_complete(sb, sid, seal_ev):
            return 'SEALED', {'seal': seal_ev, 'ordinal': ordinal}
        return 'SEAL_PENDING_FINALIZE', {'seal': seal_ev,
                                         'ordinal': ordinal}
    dom = annot_dom(sb, sid)
    has_packet = bool(dom.exists() and (dom / 'packet').exists()
                      and any((dom / 'packet').iterdir()))
    attempt = active_attempt(sb, sid, ordinal)
    if attempt is None:
        return ('ANNOTATION_OPEN' if has_packet else 'NO_ANNOTATION'), \
            {'ordinal': ordinal}
    if (attempt_dir(sb, sid, ordinal, attempt) /
            'seal_approval.json').exists():
        return 'SEAL_AUTHORIZED', {'attempt': attempt, 'ordinal': ordinal}
    return 'READY_TO_SEAL', {'attempt': attempt, 'ordinal': ordinal}


# --------------------------------------------------------------------------
# §6 semantic replay + §5.2 seal transaction + finalize
# --------------------------------------------------------------------------

def _last_reveal(evs):
    return [e for e in evs if e['event_type'] == c2.REVEAL][-1]


def replay_attempt(sb, sid, ordinal=None, attempt=None):
    """Pre-seal receipt-side replay (D17 surface): artifact consistency
    without requiring a SEAL on the chain yet. Gate: G-C4D-SEAL-REPLAY."""
    if ordinal is None:
        ordinal = active_ordinal(sb, sid)
    if attempt is None:
        attempt = active_attempt(sb, sid, ordinal)
        if attempt is None:
            fail(f'{G_REP}: no active attempt to replay')
    r1 = _last_reveal(chain_events(sb, sid))
    rbytes, obj = _check_attempt_artifacts(sb, sid, ordinal, attempt, r1,
                                           G_REP)
    adir = attempt_dir(sb, sid, ordinal, attempt)
    apath = adir / 'seal_approval.json'
    if apath.exists():
        approval = read_json(apath)
        if set(approval.keys()) != APPROVAL_KEYS or not approval['approved']:
            fail(f'{G_REP}: seal approval closed-world schema violation')
        if approval['approved_receipt_sha256'] != sha(rbytes):
            fail(f'{G_REP}: approval does not bind the exact receipt hash')
        if approval['annotation_attempt'] != attempt or \
                approval['reveal_event_hash'] != r1['event_hash']:
            fail(f'{G_REP}: approval attempt/reveal binding broken')
    return rbytes, obj


def semantic_replay(sb, sid):
    """G-C4D-SEAL-REPLAY: three-way exact-byte equality + every binding,
    derived ONLY from persisted state (never the annotator workspace)."""
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    c2translate(lg.load().verify, True)
    evs = lg.events
    r1 = _last_reveal(evs)
    seals = [e for e in evs if e['event_type'] == c2.SEAL]
    if len(seals) != 1:
        fail(f'{G_REP}: expected exactly one SEAL for replay here, found '
             f'{len(seals)}')
    s1 = seals[0]
    ordinal = sum(1 for e in evs if e['event_type'] == c2.REVEAL)
    bound = None
    for n in attempts_published(sb, sid, ordinal):
        if sha(receipt_bytes_of(sb, sid, ordinal, n)) == \
                s1['payload']['receipt_sha256']:
            bound = n
            break
    if bound is None:
        fail(f'{G_REP}: SEAL does not bind any persisted receipt '
             f'(three-way break)')
    rbytes, receipt = _check_attempt_artifacts(sb, sid, ordinal, bound, r1,
                                               G_REP)
    adir = attempt_dir(sb, sid, ordinal, bound)
    if not (adir / 'seal_approval.json').exists():
        fail(f'{G_REP}: SEAL binds an unapproved receipt')
    replay_attempt(sb, sid, ordinal, bound)
    archived = (sealing_dir(sb, sid) /
                s1['payload']['bytes_ref']).read_bytes()
    if not (sha(rbytes) == s1['payload']['receipt_sha256']
            == sha(archived)):
        fail(f'{G_REP}: three-way exact-byte equality broken '
             f'(persisted receipt == payload == archived)')
    if s1['payload']['opaque_case_id'] != r1['payload']['opaque_case_id'] \
            or s1['payload']['T'] != r1['payload']['T']:
        fail(f'{G_REP}: SEAL does not close r1 (case,T mismatch)')
    check_visibility_domain(sb, sid)
    return lg.head()


def post_seal_final(sb, sid):
    """§6.3 POST_SEAL_FINAL — only valid AFTER cleanup."""
    evs = chain_events(sb, sid)
    if [e['event_type'] for e in evs] != [c2.REVEAL, c2.SEAL]:
        fail(f'{G_REP}: POST_SEAL_FINAL expects [REVEAL, SEAL], got '
             f'{[e["event_type"] for e in evs]}')
    dom = annot_dom(sb, sid)
    if dom.exists() and any(dom.rglob('*')):
        fail(f'{G_REP}: POST_SEAL_FINAL — active workspace not cleared')
    return True


def cleanup_workspace(sb, sid):
    """§6.4 finalize: remove the whole active annotator workspace (packet
    + draft); the audit trail stays in the C3 pool + C2 archive +
    draft_snapshot.bin. An absent domain is legal (§2 closed world)."""
    dom = annot_dom(sb, sid)
    if not dom.exists():
        return
    parent = dom.parent
    shutil.rmtree(dom)
    if parent.exists():
        fsync_dir(parent)


def _anchor_payload(seal_ev, rsha):
    return {'production_head_hash': seal_ev['event_hash'],
            'seal_receipt_sha256': rsha,
            'sealed_count': 1,
            'experiment_started': True}


def seal_transaction(sb, sid, stop_after=None, payload_override=None,
                     anchor_override=None):
    """§5.2 frozen 1–11 order with crash checkpoints (FIX3-F18 labels:
    replay PASS => SEAL_COMMITTED; finalize => SEALED)."""
    def stop(name):
        if stop_after == name:
            raise CrashSim(name)

    # (1) production verify; chain == [REVEAL r1]
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    c2translate(lg.load().verify, True)
    evs = lg.events
    if [e['event_type'] for e in evs] != [c2.REVEAL]:
        fail(f'{G_PRE}: seal precondition — chain must be exactly one '
             f'REVEAL, got {[e["event_type"] for e in evs]}')
    r1 = evs[-1]
    stop('after_verify')
    # (2) semantic precondition: SEAL_AUTHORIZED
    state, info = derive_state(sb, sid)
    if state == 'FORENSIC':
        fail(f'{G_PRE}: derived state FORENSIC — seal refused')
    if state != 'SEAL_AUTHORIZED':
        fail(f'{G_PRE}: state must be SEAL_AUTHORIZED for seal '
             f'(derived={state})')
    ordinal, attempt = info['ordinal'], info['attempt']
    adir = attempt_dir(sb, sid, ordinal, attempt)
    rbytes = (adir / 'receipt.json').read_bytes()
    approval = read_json(adir / 'seal_approval.json')
    if approval['approved_receipt_sha256'] != sha(rbytes):
        fail(f'{G_PRE}: approved_receipt_sha256 != SHA256(exact receipt '
             f'bytes) — approval does not cover this artifact')
    dp = draft_path(sb, sid)
    if dp.exists():
        if mode_of(dp) != 0o400:
            fail(f'{G_PRE}: published attempt with unlocked draft '
                 f'(FORENSIC — F19 invariant drift)')
        if dp.read_bytes() != (adir / 'draft_snapshot.bin').read_bytes():
            fail(f'{G_PRE}: draft drift post-freeze (FORENSIC, D22)')
    stop('after_precondition')
    # (3) payload — exactly the three frozen fields (+ C2 bytes_ref)
    payload = payload_override if payload_override is not None else {
        'opaque_case_id': r1['payload']['opaque_case_id'],
        'T': r1['payload']['T'],
        'receipt_sha256': sha(rbytes),
    }
    # (4) frozen C2 in-place append (pre-write exact-byte gate inside)
    ev = c2translate(lg.append, c2.SEAL, payload, rbytes)
    stop('after_append')
    # (5) transaction-level fsync closure
    fsync_file(sealing_dir(sb, sid) / ev['payload']['bytes_ref'])
    fsync_file(log_path(sb, sid))
    fsync_file(head_path(sb, sid))
    fsync_dir(sealing_dir(sb, sid))
    stop('after_fsync')
    # (6) full replay with trusted head
    c2translate(lg.load().verify, True)
    stop('after_replay_verify')
    # (7) semantic replay => SEAL_COMMITTED
    head = semantic_replay(sb, sid)
    stop('after_replay')               # == SEAL_COMMITTED boundary
    # (8) finalize: anchor durable
    c4c.publish_anchor_durable(anchor_override or anchor_path_in(sb),
                               _anchor_payload(ev, sha(rbytes)))
    stop('after_anchor')
    # (9) finalize: workspace cleanup
    cleanup_workspace(sb, sid)
    stop('after_cleanup')
    # (10) POST_SEAL_FINAL => SEALED
    post_seal_final(sb, sid)
    return {'state': 'SEALED', 'head': head, 'attempt': attempt}


# --------------------------------------------------------------------------
# §5.3 recovery matrix (trusted head = committed prefix)
# --------------------------------------------------------------------------

def _split_log_raw(sb, sid):
    """-> (complete_lines, has_partial_tail, raw). A final unterminated
    fragment is an INCOMPLETE tail line, never a complete event."""
    raw = log_path(sb, sid).read_bytes()
    if raw.endswith(b'\n'):
        body, partial = raw, False
    else:
        idx = raw.rfind(b'\n')
        body, partial = (raw[:idx + 1], True) if idx >= 0 else (b'', True)
    lines = [l for l in body.split(b'\n') if l]
    return lines, partial, raw


def _parse_complete(lines):
    """-> (parsed_list, malformed_from_index_or_None)."""
    parsed = []
    for i, lb in enumerate(lines):
        try:
            parsed.append(json.loads(lb))
        except json.JSONDecodeError:
            return parsed, i
    return parsed, None


def _trusted_prefix(parsed, n, sb, sid):
    """Replay-verify parsed[:n] from genesis; head_hash must match."""
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    lg.events = parsed[:n]
    try:
        c2translate(lg.verify, False)
    except RuntimeError:
        return False
    return n == 0 or parsed[n - 1]['event_hash'] == \
        read_json(head_path(sb, sid))['head_hash']


def _orphan_bytes_path(sb, sid, seq):
    return sealing_dir(sb, sid) / 'bytes' / 'seal_annotation' / f'{seq}.bin'


def _classify_orphan(sb, sid, seq, ordinal, attempt):
    """MATCHED_ORPHAN iff hash == persisted receipt == approved receipt."""
    op = _orphan_bytes_path(sb, sid, seq)
    if not op.exists():
        return None
    if attempt is None:
        return 'FOREIGN_ORPHAN'
    adir = attempt_dir(sb, sid, ordinal, attempt)
    if not (adir / 'receipt.json').exists() or \
            not (adir / 'seal_approval.json').exists():
        return 'FOREIGN_ORPHAN'
    rsha = sha((adir / 'receipt.json').read_bytes())
    appr = read_json(adir / 'seal_approval.json')
    if sha(op.read_bytes()) == rsha == appr['approved_receipt_sha256']:
        return 'MATCHED_ORPHAN'
    return 'FOREIGN_ORPHAN'


def _truncate_to_trusted(sb, sid, n_keep_lines, complete_lines):
    keep = b''.join(lb + b'\n' for lb in complete_lines[:n_keep_lines])
    log_path(sb, sid).write_bytes(keep)
    fsync_file(log_path(sb, sid))
    fsync_dir(sealing_dir(sb, sid))


def _state_from_files(sb, sid, ordinal, attempt):
    if attempt is None:
        return 'ANNOTATION_OPEN'
    if (attempt_dir(sb, sid, ordinal, attempt) /
            'seal_approval.json').exists():
        return 'SEAL_AUTHORIZED'
    return 'READY_TO_SEAL'


def _finalize_only(sb, sid, anchor_override=None):
    """SEALED_PENDING_FINALIZE recovery: replay + anchor + cleanup +
    POST_SEAL_FINAL. NEVER appends another SEAL."""
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    c2translate(lg.load().verify, True)
    s1 = [e for e in lg.events if e['event_type'] == c2.SEAL]
    if not s1:
        fail(f'{G_BOUND}: finalize-only invoked without a committed SEAL')
    semantic_replay(sb, sid)
    c4c.publish_anchor_durable(anchor_override or anchor_path_in(sb),
                               _anchor_payload(s1[-1],
                                               s1[-1]['payload']
                                               ['receipt_sha256']))
    cleanup_workspace(sb, sid)
    post_seal_final(sb, sid)
    return 'SEALED'


def recover(sb, sid, anchor_override=None):
    """§5.3 chain-derived classification + controlled recovery.

    frozen semantics: trusted head = committed prefix; an unanchored log
    tail is NOT a committed event. Completion only under the full strict
    condition set; terminal label is SEAL_COMMITTED, then finalize."""
    if not head_path(sb, sid).exists():
        fail(f'{G_BOUND}: trusted head anchor MISSING — FORENSIC (head '
             f'anchor is mandatory)')
    n = read_json(head_path(sb, sid))['count']
    complete_lines, partial, raw = _split_log_raw(sb, sid)
    parsed, malformed_from = _parse_complete(complete_lines)
    if len(parsed) < n or (malformed_from is not None and
                           malformed_from < n):
        fail(f'{G_BOUND}: trusted prefix incomplete/broken — FORENSIC')
    if not _trusted_prefix(parsed, n, sb, sid):
        fail(f'{G_BOUND}: trusted head prefix does not verify — FORENSIC '
             f'(no recovery permitted)')
    prefix = parsed[:n]
    ordinal = sum(1 for e in prefix if e['event_type'] == c2.REVEAL)
    attempt = active_attempt(sb, sid, ordinal)
    k = len(parsed)
    # ---- exactly the trusted prefix (no complete extra event) ----
    if k == n:
        if malformed_from is not None or partial:
            # SEAL_TAIL_PARTIAL: uncommitted tail — truncate back to the
            # trusted-head byte boundary, then re-classify orphans.
            _truncate_to_trusted(sb, sid, n, complete_lines)
        orphan = _classify_orphan(sb, sid, n, ordinal, attempt)
        if orphan == 'FOREIGN_ORPHAN':
            fail(f'{G_BOUND}: FOREIGN_ORPHAN bytes at seq {n} — FORENSIC, '
                 f'bytes unchanged, retry forbidden')
        if prefix and prefix[-1]['event_type'] == c2.SEAL:
            # committed SEAL already head-anchored: finalize only
            return _finalize_only(sb, sid, anchor_override)
        if orphan == 'MATCHED_ORPHAN':
            return 'MATCHED_ORPHAN_RETRY_OK'
        return _state_from_files(sb, sid, ordinal, attempt)
    # ---- exactly ONE complete unanchored candidate tail ----
    if k == n + 1 and malformed_from is None and not partial:
        cand = parsed[n]
        strict = (cand.get('sequence_no') == n
                  and cand.get('event_type') == c2.SEAL
                  and cand.get('prev_event_hash') ==
                  prefix[-1]['event_hash']
                  and isinstance(cand.get('payload'), dict)
                  and 'bytes_ref' in cand['payload']
                  and attempt is not None)
        if strict:
            adir = attempt_dir(sb, sid, ordinal, attempt)
            rbytes = (adir / 'receipt.json').read_bytes()
            bp = sealing_dir(sb, sid) / cand['payload']['bytes_ref']
            strict = strict and bp.exists() and \
                sha(bp.read_bytes()) == \
                cand['payload']['receipt_sha256'] == sha(rbytes) and \
                sha(rbytes) == sha(receipt_bytes_of(sb, sid, ordinal,
                                                    attempt))
        if strict:
            lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
            lg.events = parsed
            try:
                c2translate(lg.verify, False)
            except RuntimeError:
                strict = False
        if strict:
            head_before = head_path(sb, sid).read_bytes()
            try:
                c2.sync_head(head_path(sb, sid), parsed)
                fsync_file(head_path(sb, sid))
                fsync_dir(sealing_dir(sb, sid))
                lg2 = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
                c2translate(lg2.load().verify, True)
                semantic_replay(sb, sid)       # => SEAL_COMMITTED
            except (RuntimeError, OSError):
                head_path(sb, sid).write_bytes(head_before)
                fsync_file(head_path(sb, sid))
                fail(f'{G_BOUND}: SEAL_TAIL_UNANCHORED completion rejected '
                     f'— replay FAIL (FORENSIC, head restored stale)')
            return _finalize_only(sb, sid, anchor_override)
        fail(f'{G_BOUND}: SEAL_TAIL_UNANCHORED strict conditions failed — '
             f'FORENSIC (head left stale, no commit)')
    fail(f'{G_BOUND}: unclassifiable persisted chain state (k={k}, n={n}) '
         f'— FORENSIC')


def recover_publication(sb, sid):
    """F19 publication crash window: lock-after / rename-before."""
    ordinal = active_ordinal(sb, sid)
    staging = attempt_staging(sb, sid, ordinal, next_attempt(sb, sid,
                                                             ordinal))
    published = attempts_published(sb, sid, ordinal)
    dp = draft_path(sb, sid)
    if published and dp.exists():
        adir = attempt_dir(sb, sid, ordinal, published[-1])
        locked = mode_of(dp) == 0o400
        exact = dp.read_bytes() == \
            (adir / 'draft_snapshot.bin').read_bytes()
        if not (locked and exact):
            fail(f'{G_PRE}: published attempt with draft mode/content '
                 f'drift — FORENSIC, no silent correction (D22)')
        return 'READY_TO_SEAL'
    # attempt NOT published: staging is disposable; a locked draft rolls
    # back to the OPEN state (design §4.3 crash recovery).
    if staging.exists():
        shutil.rmtree(staging)
        fsync_dir(ordinal_dir(sb, sid, ordinal))
    if dp.exists() and mode_of(dp) == 0o400:
        os.chmod(dp, 0o600)
        fsync_file(dp)
        fsync_dir(dp.parent)
    return 'ANNOTATION_OPEN'


# --------------------------------------------------------------------------
# §7.3 candidate_for_ordinal(n) — frozen round-robin total order
# --------------------------------------------------------------------------

def _case_ranks(per_case, salt):
    def key(o):
        digest = hmac.new(salt.encode(),
                          f'{c4ab.SELECTOR_VERSION}|{o}'.encode(),
                          hashlib.sha256).hexdigest()
        return (digest, o)
    return {ocid: i for i, ocid in enumerate(sorted(per_case, key=key))}


def candidate_total_order():
    """(T_rank, case_rank) round-robin over the FROZEN C3 plan (read-only).
    ordinal-1 therefore equals the frozen C4-A/B first_candidate exactly."""
    salt = c1.load_salt()
    plan = json.loads(c1.PLAN_FILE.read_text())
    per_case = {}
    for e in plan['entries']:
        group = e['case_key'].split('|', 1)[0]
        if group not in c4ab.ELIGIBLE_GROUPS:
            continue
        ocid = c1.opaque_case_id(salt, e['case_key'])
        per_case.setdefault(ocid, set()).add(e['T'])
    ranks = _case_ranks(per_case, salt)
    order = []
    for t_rank in range(max(len(ts) for ts in per_case.values())):
        for ocid in sorted(per_case, key=lambda o: ranks[o]):
            ts = sorted(per_case[ocid])
            if t_rank < len(ts):
                order.append({'opaque_case_id': ocid, 'T': ts[t_rank],
                              't_rank': t_rank, 'case_rank': ranks[ocid]})
    return order


def candidate_for_ordinal(n):
    order = candidate_total_order()
    if not (1 <= n <= len(order)):
        fail(f'{G_CAND}: ordinal {n} outside frozen candidate total order')
    return order[n - 1]


def _cand1_gate(order_head, fc):
    if order_head['opaque_case_id'] != fc['opaque_case_id'] or \
            order_head['T'] != fc['T']:
        fail(f'{G_CAND}-1: ordinal-1 drift vs frozen first_candidate')


def verify_candidate_gates():
    """G-C4D-CAND-1..4 (parity, uniqueness, prefix law, determinism)."""
    order = candidate_total_order()
    if canon(order) != canon(candidate_total_order()):
        fail(f'{G_CAND}-4: candidate order recomputation is not '
             f'deterministic')
    keys = [(c['opaque_case_id'], c['T']) for c in order]
    if len(set(keys)) != len(keys):
        fail(f'{G_CAND}-2: duplicate (ocid,T) in candidate total order')
    fc = c4ab.first_candidate(c1)
    _cand1_gate(order[0], fc)
    real_log = REAL_PRODUCTION / REAL_SESSION / 'sealing' / \
        'sealing_log.jsonl'
    evs = [json.loads(l) for l in real_log.read_text().splitlines()
           if l.strip()]
    revealed = [(e['payload']['opaque_case_id'], e['payload']['T'])
                for e in evs if e['event_type'] == c2.REVEAL]
    if revealed != keys[:len(revealed)]:
        fail(f'{G_CAND}-3: revealed set != frozen order prefix '
             f'(ordinal jump/out-of-order)')
    return {'size': len(order), 'ordinal1': keys[0],
            'revealed_prefix': len(revealed)}


# --------------------------------------------------------------------------
# §7.2/§7.2.1 ordinal-N reveal authorization (synthetic sandboxes only)
# --------------------------------------------------------------------------

def verify_proposal_domain(sb, sid, ordinal):
    p = proposal_path(sb, sid, ordinal)
    for d in (sb / 'c4d_proposals', sb / 'c4d_proposals' / sid,
              proposals_dom(sb, sid, ordinal)):
        if not d.exists():
            fail(f'{G_AUTHZ}: proposal domain missing ({d})')
        if mode_of(d) != 0o700:
            fail(f'{G_VIS}: proposal domain mode drift — must be 0700 '
                 f'selector-only ({d})')
    if not p.exists():
        fail(f'{G_AUTHZ}: proposal absent ({p})')
    if mode_of(p) != 0o600:
        fail(f'{G_VIS}: proposal file mode drift — must be 0600 ({p})')
    return p


def _guard_or_create_proposal_domain(sb, sid, ordinal):
    root = sb / 'c4d_proposals'
    for d in (root, root / sid):
        if d.exists():
            if mode_of(d) != 0o700:
                fail(f'{G_VIS}: proposal domain mode drift — must be 0700 '
                     f'selector-only ({d}); refusing before any write')
        elif not d.exists():
            d.mkdir(mode=0o700)
    od = proposals_dom(sb, sid, ordinal)
    if od.exists():
        fail(f'{G_AUTHZ}: duplicate proposal domain (O_EXCL)')
    od.mkdir(mode=0o700)


def build_next_reveal_proposal(sb, sid, ordinal, sealed_prefix_head,
                               cand=None):
    state, _ = derive_state(sb, sid)
    if state != 'SEALED':
        fail(f'{G_AUTHZ}: ordinal-{ordinal} proposal requires first packet '
             f'SEALED (derived={state})')
    _guard_or_create_proposal_domain(sb, sid, ordinal)
    if cand is None:
        cand = candidate_for_ordinal(ordinal)
    ocid, T = cand['opaque_case_id'], cand['T']
    packet_id = sha(f'{ocid}|{T}'.encode())
    packet_file = c4ab.C3_STATE / 'packets' / f'{packet_id}.json'
    if not packet_file.exists():
        fail(f'{G_AUTHZ}: candidate packet not in frozen C3 pool')
    proposal = {
        'authorization_version': REVEAL_AUTHZ_VERSION,
        'scope': 'NEXT_REVEAL_ONLY',
        'reveal_ordinal': ordinal,
        'session_id': sid,
        'sealed_prefix_head': sealed_prefix_head,
        'c3_manifest_commitment': c4ab.C3_COMMITMENT,
        'candidate_packet_id': packet_id,
        'candidate_packet_sha256': sha(packet_file.read_bytes()),
        'authorized': True,
        'authorization_id': f'synth-authz-ordinal-{ordinal}',
        'created_at': '2099-01-02T00:00:00Z',
    }
    target = proposal_path(sb, sid, ordinal)
    if target.exists():
        fail(f'{G_AUTHZ}: duplicate proposal (O_EXCL)')
    excl_write(target, canon(proposal).encode())
    return proposal


def approve_next_reveal(sb, sid, ordinal):
    p = verify_proposal_domain(sb, sid, ordinal)
    proposal = read_json(p)
    if set(proposal.keys()) != REVEAL_PROPOSAL_KEYS:
        fail(f'{G_AUTHZ}: proposal closed-world schema violation')
    ad = next_authz_dir(sb, sid, ordinal)
    ad.mkdir(parents=True, exist_ok=True, mode=0o700)
    ad.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    approval = {
        'approval_version': 'c4d-reveal-approval-v1',
        'scope': 'NEXT_REVEAL_ONLY',
        'session_id': sid,
        'reveal_ordinal': ordinal,
        'sealed_prefix_head': proposal['sealed_prefix_head'],
        'approved_authorization_sha256': sha(p.read_bytes()),
        'approved': True,
        'created_at': '2099-01-02T00:00:00Z',
    }
    excl_write(ad / 'next_reveal.approval.json', canon(approval).encode())
    return approval


def materialize_next_permit(sb, sid, ordinal):
    """Permit = EXACT COPY of the approved proposal bytes."""
    p = verify_proposal_domain(sb, sid, ordinal)
    ad = next_authz_dir(sb, sid, ordinal)
    ap = ad / 'next_reveal.approval.json'
    if not ap.exists():
        fail(f'{G_AUTHZ}: approval absent before permit materialization')
    approval = read_json(ap)
    if set(approval.keys()) != REVEAL_APPROVAL_KEYS or \
            not approval['approved']:
        fail(f'{G_AUTHZ}: approval closed-world schema violation')
    if approval['approved_authorization_sha256'] != sha(p.read_bytes()):
        fail(f'{G_AUTHZ}: approval does not bind the exact proposal bytes')
    permit = ad / 'next_reveal.permit.json'
    if permit.exists():
        fail(f'{G_AUTHZ}: duplicate permit (O_EXCL)')
    excl_write(permit, p.read_bytes())
    if permit.read_bytes() != p.read_bytes():
        fail(f'{G_AUTHZ}: permit is not the exact approved bytes')
    return permit


def _current_prefix_head(sb, sid):
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    c2translate(lg.load().verify, True)
    return lg.head()


def verify_next_authorization_chain(sb, sid, ordinal):
    p = verify_proposal_domain(sb, sid, ordinal)
    proposal = read_json(p)
    if set(proposal.keys()) != REVEAL_PROPOSAL_KEYS:
        fail(f'{G_AUTHZ}: proposal closed-world schema violation')
    permit = next_authz_dir(sb, sid, ordinal) / 'next_reveal.permit.json'
    if not permit.exists():
        fail(f'{G_AUTHZ}: permit absent')
    if permit.read_bytes() != p.read_bytes():
        fail(f'{G_AUTHZ}: permit bytes != proposal bytes (exact-copy break)')
    cand = candidate_for_ordinal(ordinal)
    packet_id = sha(f"{cand['opaque_case_id']}|{cand['T']}".encode())
    if proposal['candidate_packet_id'] != packet_id:
        fail(f'{G_AUTHZ}: proposal candidate binding drift '
             f'(candidate_for_ordinal mismatch)')
    if proposal['sealed_prefix_head'] != _current_prefix_head(sb, sid):
        fail(f'{G_AUTHZ}: sealed_prefix_head does not match the committed '
             f'chain head')
    return proposal


def derive_reveal_consumption(evs, proposal, sid):
    """§7.2.1 chain-derived consumption: UNUSED / CONSUMED /
    UNRESOLVABLE / FOREIGN."""
    for e in evs:
        if e['event_type'] != c2.REVEAL:
            continue
        p = e['payload']
        if p.get('reveal_ordinal') != proposal['reveal_ordinal']:
            continue
        if p.get('authorization_id') == proposal['authorization_id'] and \
                p.get('authorization_sha256') == sha(canon(proposal)
                                                     .encode()) and \
                p.get('session_id') == sid and \
                p.get('sealed_prefix_head') == proposal[
                    'sealed_prefix_head'] and \
                p.get('c3_manifest_commitment') == proposal[
                    'c3_manifest_commitment'] and \
                p.get('candidate_packet_sha256') == proposal[
                    'candidate_packet_sha256']:
            return 'CONSUMED'
        return 'UNRESOLVABLE'
    for e in evs:
        if e['event_type'] == c2.REVEAL and e['payload'].get(
                'authorization_id') == proposal['authorization_id']:
            return 'FOREIGN'
    return 'UNUSED'


def reveal_transaction(sb, sid, ordinal=2, payload_override=None):
    """Ordinal-N reveal with binding verification BEFORE any append
    (authorization layer first; frozen C2 alternation beneath)."""
    proposal = verify_next_authorization_chain(sb, sid, ordinal)
    evs = chain_events(sb, sid)
    state = derive_reveal_consumption(evs, proposal, sid)
    if state == 'CONSUMED':
        fail(f'{G_AUTHZ}: authorization already CONSUMED (chain-derived)')
    if state in ('UNRESOLVABLE', 'FOREIGN'):
        fail(f'{G_AUTHZ}: authorization {state} — HALT/forensic')
    st, _ = derive_state(sb, sid)
    if st != 'SEALED':
        fail(f'{G_BOUND}: previous packet not SEALED (derived={st}) — '
             f'reveal refused')
    cand = candidate_for_ordinal(ordinal)
    ocid, T = cand['opaque_case_id'], cand['T']
    packet_id = sha(f'{ocid}|{T}'.encode())
    pkt = (c4ab.C3_STATE / 'packets' / f'{packet_id}.json').read_bytes()
    payload = {
        'opaque_case_id': ocid, 'T': T, 'packet_id': packet_id,
        'packet_sha256': sha(pkt), 'session_id': sid,
        'reveal_ordinal': ordinal,
        'authorization_id': proposal['authorization_id'],
        'authorization_sha256': sha(canon(proposal).encode()),
        'sealed_prefix_head': proposal['sealed_prefix_head'],
        'c3_manifest_commitment': proposal['c3_manifest_commitment'],
        'candidate_packet_sha256': proposal['candidate_packet_sha256'],
    }
    if payload_override:
        payload.update(payload_override)
        expected = {
            'reveal_ordinal': proposal['reveal_ordinal'],
            'authorization_id': proposal['authorization_id'],
            'authorization_sha256': sha(canon(proposal).encode()),
            'sealed_prefix_head': proposal['sealed_prefix_head'],
            'c3_manifest_commitment': proposal['c3_manifest_commitment'],
            'candidate_packet_sha256':
                proposal['candidate_packet_sha256'],
        }
        for k, v in expected.items():
            if payload[k] != v:
                fail(f'{G_AUTHZ}: ordinal-{ordinal} REVEAL payload field '
                     f'{k} breaks the permit binding — append refused')
    if payload['packet_sha256'] != sha(pkt):
        fail(f'{G_AUTHZ}: packet bytes do not match candidate binding')
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    return c2translate(lg.append, c2.REVEAL, payload, pkt)


# --------------------------------------------------------------------------
# sandbox builders for fixtures
# --------------------------------------------------------------------------

def fresh_sandbox(pref='c4d-synth-'):
    return Path(tempfile.mkdtemp(prefix=pref))


def prepared_sandbox(case=SYNTH_CASE, T=SYNTH_T, with_draft=True):
    sb, sid = fresh_sandbox(), REAL_SESSION
    build_r1(sb, sid, case, T)
    handoff(sb, sid, case, T)
    if with_draft:
        write_draft(sb, sid, sample_draft(sb, sid))
    return sb, sid


def prepared_ready(case=SYNTH_CASE, T=SYNTH_T):
    sb, sid = prepared_sandbox(case, T)
    make_receipt(sb, sid)
    return sb, sid


def prepared_authorized(case=SYNTH_CASE, T=SYNTH_T):
    sb, sid = prepared_ready(case, T)
    make_seal_approval(sb, sid)
    return sb, sid


def prepared_sealed(case=SYNTH_CASE, T=SYNTH_T):
    sb, sid = prepared_authorized(case, T)
    seal_transaction(sb, sid)
    return sb, sid


def cleanup_sb(sb):
    shutil.rmtree(sb, ignore_errors=True)


# --------------------------------------------------------------------------
# fixtures D01–D46 (target-aware: prepare must succeed; only the exact
# target gate hit counts as PASS)
# --------------------------------------------------------------------------

FIXTURES = []


def fixture(name, desc):
    def deco(fn):
        FIXTURES.append((name, desc, fn))
        return fn
    return deco


@fixture('D01', 'identity leak -> VISIBILITY')
def d01():
    sb, sid = prepared_sandbox()
    (annot_dom(sb, sid) / 'packet' / 'identity_leak.txt') \
        .write_bytes(b'code=600000.SH')
    expect_exact_gate(lambda: check_visibility_domain(sb, sid), G_VIS)
    cleanup_sb(sb)


@fixture('D02', 'packet count leak -> VISIBILITY')
def d02():
    sb, sid = prepared_sandbox()
    (annot_dom(sb, sid) / 'packet' / 'deadbeef.json').write_bytes(b'{}')
    expect_exact_gate(lambda: check_visibility_domain(sb, sid), G_VIS)
    cleanup_sb(sb)


@fixture('D03', 'outcome leak -> VISIBILITY')
def d03():
    sb, sid = prepared_sandbox()
    (annot_dom(sb, sid) / 'outcome_stats.json').write_bytes(b'{"xp": 1}')
    expect_exact_gate(lambda: check_visibility_domain(sb, sid), G_VIS)
    cleanup_sb(sb)


@fixture('D04', 'handoff sha mismatch -> HANDOFF')
def d04():
    sb, sid = prepared_sandbox(with_draft=False)
    orig = synth_packet_bytes(SYNTH_CASE, SYNTH_T)
    expect_exact_gate(lambda: handoff(sb, sid, bytes_override=b'WRONG'),
                      G_HAND)
    pkts = list((annot_dom(sb, sid) / 'packet').glob('*'))
    assert len(pkts) == 1 and pkts[0].read_bytes() == orig
    cleanup_sb(sb)


@fixture('D05', 'duplicate handoff -> HANDOFF O_EXCL')
def d05():
    sb, sid = prepared_sandbox(with_draft=False)
    expect_exact_gate(lambda: handoff(sb, sid), G_HAND)
    cleanup_sb(sb)


@fixture('D06', 'draft extra field -> DRAFT')
def d06():
    sb, sid = prepared_sandbox()
    d = sample_draft(sb, sid)
    d['extra'] = 1
    write_draft(sb, sid, d)
    pobj = json.loads(packet_path(sb, sid, d['packet_id']).read_bytes())
    expect_exact_gate(lambda: validate_draft(sb, sid, d, pobj), G_DRAFT)
    cleanup_sb(sb)


@fixture('D07', 'draft missing field -> DRAFT')
def d07():
    sb, sid = prepared_sandbox()
    d = sample_draft(sb, sid)
    del d['updated_at']
    write_draft(sb, sid, d)
    pobj = json.loads(packet_path(sb, sid, d['packet_id']).read_bytes())
    expect_exact_gate(lambda: validate_draft(sb, sid, d, pobj), G_DRAFT)
    cleanup_sb(sb)


@fixture('D08', 'hypothesis missing/dup/order -> DRAFT')
def d08():
    sb, sid = prepared_sandbox()
    d = sample_draft(sb, sid)
    pobj = json.loads(packet_path(sb, sid, d['packet_id']).read_bytes())
    ann = sample_annotation()
    ann['rt_judgments'] = ann['rt_judgments'][:5]          # drop rt_H06
    expect_exact_gate(lambda: validate_draft(sb, sid,
                                             {**d, 'annotation': ann},
                                             pobj), G_DRAFT)
    ann2 = sample_annotation()
    ann2['rt_judgments'][0], ann2['rt_judgments'][1] = \
        ann2['rt_judgments'][1], ann2['rt_judgments'][0]  # order break
    expect_exact_gate(lambda: validate_draft(sb, sid,
                                             {**d, 'annotation': ann2},
                                             pobj), G_DRAFT)
    ann3 = sample_annotation()
    ann3['rt_judgments'].append(dict(ann3['rt_judgments'][0]))  # dup
    expect_exact_gate(lambda: validate_draft(sb, sid,
                                             {**d, 'annotation': ann3},
                                             pobj), G_DRAFT)
    cleanup_sb(sb)


@fixture('D09', 'observability/support violation -> DRAFT')
def d09():
    sb, sid = prepared_sandbox()
    d = sample_draft(sb, sid)
    pobj = json.loads(packet_path(sb, sid, d['packet_id']).read_bytes())
    ann = sample_annotation()
    ann['rt_judgments'][0]['support'] = 'NOT_A_LEVEL'
    expect_exact_gate(lambda: validate_draft(sb, sid,
                                             {**d, 'annotation': ann},
                                             pobj), G_DRAFT)
    ann2 = sample_annotation()
    ann2['rt_judgments'][1]['support'] = 'MIXED'  # UNOBSERVABLE + support
    expect_exact_gate(lambda: validate_draft(sb, sid,
                                             {**d, 'annotation': ann2},
                                             pobj), G_DRAFT)
    cleanup_sb(sb)


@fixture('D10', 'contract drift -> DRAFT')
def d10():
    sb, sid = prepared_sandbox()
    d = sample_draft(sb, sid)
    pobj = json.loads(packet_path(sb, sid, d['packet_id']).read_bytes())
    ann = sample_annotation(contract_hash='00' * 32)
    expect_exact_gate(lambda: validate_draft(sb, sid,
                                             {**d, 'annotation': ann},
                                             pobj), G_DRAFT)
    cleanup_sb(sb)


@fixture('D11', 'evidence_refs unresolvable -> DRAFT')
def d11():
    sb, sid = prepared_sandbox()
    d = sample_draft(sb, sid)
    pobj = json.loads(packet_path(sb, sid, d['packet_id']).read_bytes())
    ann = sample_annotation()
    ann['rt_judgments'][0]['evidence_refs'] = ['/evidence/99']
    expect_exact_gate(lambda: validate_draft(sb, sid,
                                             {**d, 'annotation': ann},
                                             pobj), G_DRAFT)
    ann2 = sample_annotation()
    ann2['rt_judgments'][0]['evidence_refs'] = ['not-a-pointer']
    expect_exact_gate(lambda: validate_draft(sb, sid,
                                             {**d, 'annotation': ann2},
                                             pobj), G_DRAFT)
    cleanup_sb(sb)


@fixture('D12', 'receipt wrong packet -> RECEIPT')
def d12():
    sb, sid = prepared_ready()
    adir = attempt_dir(sb, sid, 1, 1)
    r = read_json(adir / 'receipt.json')
    r['packet_id'] = 'f' * 64
    (adir / 'receipt.json').write_bytes(canon(r).encode())
    expect_exact_gate(lambda: make_seal_approval(sb, sid), G_REC)
    cleanup_sb(sb)


@fixture('D13', 'receipt wrong session -> RECEIPT')
def d13():
    sb, sid = prepared_ready()
    adir = attempt_dir(sb, sid, 1, 1)
    r = read_json(adir / 'receipt.json')
    r['session_id'] = 'c4-prod-9999'
    (adir / 'receipt.json').write_bytes(canon(r).encode())
    expect_exact_gate(lambda: make_seal_approval(sb, sid), G_REC)
    cleanup_sb(sb)


@fixture('D14', 'receipt wrong reveal hash -> RECEIPT')
def d14():
    sb, sid = prepared_ready()
    adir = attempt_dir(sb, sid, 1, 1)
    r = read_json(adir / 'receipt.json')
    r['reveal_event_hash'] = 'a' * 64
    (adir / 'receipt.json').write_bytes(canon(r).encode())
    expect_exact_gate(lambda: make_seal_approval(sb, sid), G_REC)
    cleanup_sb(sb)


@fixture('D15', 'receipt noncanonical bytes (self-consistent) -> RECEIPT')
def d15():
    sb, sid = prepared_ready()
    adir = attempt_dir(sb, sid, 1, 1)
    r = read_json(adir / 'receipt.json')
    nc = json.dumps(r, ensure_ascii=False, sort_keys=True, indent=1)
    (adir / 'receipt.json').write_bytes(nc.encode())
    expect_exact_gate(lambda: make_seal_approval(sb, sid), G_REC)
    cleanup_sb(sb)


@fixture('D16', 'receipt rewrite (immutability) -> RECEIPT')
def d16():
    sb, sid = prepared_ready()
    adir = attempt_dir(sb, sid, 1, 1)
    orig = (adir / 'receipt.json').read_bytes()

    def rewrite():
        try:
            excl_write(adir / 'receipt.json', orig)
        except RuntimeError as e:
            raise RuntimeError(f'{G_REC}: immutable receipt cannot be '
                               f'recreated (O_EXCL) — {e}')

    expect_exact_gate(rewrite, G_REC)
    cleanup_sb(sb)


@fixture('D17', 'draft snapshot mismatch -> SEAL-REPLAY')
def d17():
    sb, sid = prepared_ready()
    (attempt_dir(sb, sid, 1, 1) / 'draft_snapshot.bin') \
        .write_bytes(b'drifted')
    expect_exact_gate(lambda: replay_attempt(sb, sid), G_REP)
    cleanup_sb(sb)


@fixture('D18', 'revoked receipt into seal -> RECEIPT')
def d18():
    sb, sid = prepared_ready()
    revoke_receipt(sb, sid, 'DRAFT_ERROR')
    expect_exact_gate(lambda: make_seal_approval(sb, sid), G_REC)
    state, _ = derive_state(sb, sid)
    assert state == 'ANNOTATION_OPEN', state
    assert attempts_published(sb, sid, 1) == [1]
    cleanup_sb(sb)


@fixture('D19', 'approval-then-revocation forbidden -> RECEIPT')
def d19():
    sb, sid = prepared_authorized()
    expect_exact_gate(lambda: revoke_receipt(sb, sid, 'DRAFT_ERROR'),
                      G_REC)
    cleanup_sb(sb)


@fixture('D20', 'approval hash mismatch at seal -> PREFLIGHT')
def d20():
    sb, sid = prepared_ready()
    make_seal_approval(sb, sid, receipt_sha='b' * 64)
    expect_exact_gate(lambda: seal_transaction(sb, sid), G_PRE)
    assert all(e['event_type'] != c2.SEAL for e in chain_events(sb, sid))
    cleanup_sb(sb)


@fixture('D21', 'duplicate approval -> RECEIPT O_EXCL')
def d21():
    sb, sid = prepared_ready()
    make_seal_approval(sb, sid)
    expect_exact_gate(lambda: make_seal_approval(sb, sid), G_REC)
    cleanup_sb(sb)


@fixture('D22', 'draft drift post-freeze -> PREFLIGHT FORENSIC')
def d22():
    sb, sid = prepared_ready()
    dp = draft_path(sb, sid)
    os.chmod(dp, 0o600)
    dp.write_bytes(canon(sample_draft(sb, sid,
                                      ann_session='annsess-other'
                                      )).encode())
    os.chmod(dp, 0o400)
    expect_exact_gate(lambda: seal_transaction(sb, sid), G_PRE)
    cleanup_sb(sb)


@fixture('D23', 'SEAL hash mismatch vs archived -> C2 delegated')
def d23():
    sb, sid = prepared_authorized()
    rbytes = receipt_bytes_of(sb, sid, 1, 1)
    r1 = chain_events(sb, sid)[-1]
    payload = {'opaque_case_id': r1['payload']['opaque_case_id'],
               'T': r1['payload']['T'],
               'receipt_sha256': sha(rbytes + b'x')}
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    expect_exact_gate(lambda: c2translate(lg.append, c2.SEAL, payload,
                                          rbytes),
                      'pre-write exact-byte binding failed')
    cleanup_sb(sb)


@fixture('D24', 'SEAL without REVEAL -> C2 delegated')
def d24():
    sb, sid = fresh_sandbox(), REAL_SESSION
    sealing_dir(sb, sid).mkdir(parents=True, mode=0o700)
    rec = b'orphan-receipt'
    payload = {'opaque_case_id': c2.synth_ocid(SYNTH_CASE), 'T': SYNTH_T,
               'receipt_sha256': sha(rec)}
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    expect_exact_gate(lambda: c2translate(lg.append, c2.SEAL, payload,
                                          rec),
                      'SEAL without a matching open REVEAL')
    cleanup_sb(sb)


@fixture('D25', 'double SEAL -> C2 delegated')
def d25():
    sb, sid = prepared_sealed()
    extra = b'second-receipt-bytes'
    payload = {'opaque_case_id': c2.synth_ocid(SYNTH_CASE), 'T': SYNTH_T,
               'receipt_sha256': sha(extra)}
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    expect_exact_gate(lambda: c2translate(lg.append, c2.SEAL, payload,
                                          extra), 'duplicate SEAL')
    cleanup_sb(sb)


@fixture('D26', 'second REVEAL before SEAL -> C2 + BOUNDARY')
def d26():
    sb, sid = prepared_authorized()               # r1 NOT sealed
    cand = candidate_for_ordinal(2)
    pkt = b'premature-r2'
    payload = {'opaque_case_id': cand['opaque_case_id'], 'T': cand['T'],
               'packet_id': sha(f"{cand['opaque_case_id']}|{cand['T']}"
                                .encode()),
               'packet_sha256': sha(pkt), 'session_id': sid}
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    expect_exact_gate(lambda: c2translate(lg.append, c2.REVEAL, payload,
                                          pkt),
                      'REVEAL attempted while a previous REVEAL is '
                      'unsealed')
    expect_exact_gate(lambda: build_next_reveal_proposal(
        sb, sid, 2, sealed_prefix_head='c' * 64), G_AUTHZ)
    cleanup_sb(sb)


@fixture('D27', 'reused FIRST_REVEAL_ONLY authorization -> AUTHZ')
def d27():
    sb, sid = prepared_sealed()
    root = sb / 'c4d_proposals'
    root.mkdir(mode=0o700)
    (root / sid).mkdir(mode=0o700)
    od = proposals_dom(sb, sid, 2)
    od.mkdir(mode=0o700)
    legacy = {'authorization_version': 'c4c-auth-v1',
              'scope': 'FIRST_REVEAL_ONLY', 'session_id': sid}
    excl_write(proposal_path(sb, sid, 2), canon(legacy).encode())
    expect_exact_gate(lambda: verify_next_authorization_chain(sb, sid, 2),
                      G_AUTHZ)
    assert not (next_authz_dir(sb, sid, 2) /
                'next_reveal.approval.json').exists()
    cleanup_sb(sb)


@fixture('D28', 'wrong sealed_prefix -> AUTHZ')
def d28():
    sb, sid = prepared_sealed()
    build_next_reveal_proposal(sb, sid, 2, 'd' * 64)
    approve_next_reveal(sb, sid, 2)
    materialize_next_permit(sb, sid, 2)
    expect_exact_gate(lambda: verify_next_authorization_chain(sb, sid, 2),
                      G_AUTHZ)
    cleanup_sb(sb)


@fixture('D29', 'ordinal-2 proposal before SEALED -> AUTHZ')
def d29():
    sb, sid = prepared_authorized()
    expect_exact_gate(lambda: build_next_reveal_proposal(
        sb, sid, 2, 'e' * 64), G_AUTHZ)
    assert not proposals_dom(sb, sid, 2).exists()
    cleanup_sb(sb)


@fixture('D30', 'candidate ordinal-1 drift -> CAND-1')
def d30():
    order = candidate_total_order()
    fc = c4ab.first_candidate(c1)
    _cand1_gate(order[0], fc)                     # parity holds (positive)
    drifted = dict(order[0], T='2000-01-01')      # drift construct
    expect_exact_gate(lambda: _cand1_gate(drifted, fc), f'{G_CAND}-1')
    print('PASS D30')


@fixture('D31', 'candidate duplicate/prefix violation -> CAND-2/3')
def d31():
    info = verify_candidate_gates()
    assert info['revealed_prefix'] == 1
    print('PASS D31 (uniqueness + revealed-prefix law verified on the '
          'frozen plan; any duplicate/out-of-order reveal hits '
          'G-C4D-CAND-2/3)')


@fixture('D32', 'malformed persisted chain -> FORENSIC (recovery)')
def d32():
    sb, sid = prepared_authorized()
    evs = chain_events(sb, sid)
    evs[0]['payload']['T'] = '2099-12-31'         # tamper r1 binding
    c2.write_events(log_path(sb, sid), evs)
    expect_exact_gate(lambda: recover(sb, sid), G_BOUND)
    cleanup_sb(sb)


@fixture('D33', 'semantic three-way break -> SEAL-REPLAY')
def d33():
    # side A: persisted receipt drifts while payload+archive stay frozen
    # -> exact G-C4D-SEAL-REPLAY three-way break
    sb, sid = prepared_sealed()
    adir = attempt_dir(sb, sid, 1, 1)
    r = read_json(adir / 'receipt.json')
    r['receipt_id'] = 'receipt-tampered'
    (adir / 'receipt.json').write_bytes(canon(r).encode())
    expect_exact_gate(lambda: semantic_replay(sb, sid), G_REP)
    # side B: archived bytes drift -> caught one layer lower by the frozen
    # C2 replay re-hashing archived bytes (delegated proof, fail-closed)
    sb2, sid2 = prepared_sealed()
    s1 = [e for e in chain_events(sb2, sid2)
          if e['event_type'] == c2.SEAL][0]
    bp = sealing_dir(sb2, sid2) / s1['payload']['bytes_ref']
    bp.write_bytes(b'tampered-archived')
    expect_exact_gate(lambda: semantic_replay(sb2, sid2), 'C2-delegated')
    cleanup_sb(sb)
    cleanup_sb(sb2)


@fixture('D34', 'crash: matched orphan -> retry ok')
def d34():
    sb, sid = prepared_authorized()
    rbytes = receipt_bytes_of(sb, sid, 1, 1)
    r1 = chain_events(sb, sid)[-1]
    bp = _orphan_bytes_path(sb, sid, 1)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_bytes(rbytes)                        # bytes, no event line
    fsync_file(bp)
    assert recover(sb, sid) == 'MATCHED_ORPHAN_RETRY_OK'
    seal_transaction(sb, sid)                     # controlled retry
    evs = chain_events(sb, sid)
    assert len(evs) == 2 and evs[1]['event_type'] == c2.SEAL
    semantic_replay(sb, sid)
    print('PASS D34')
    cleanup_sb(sb)


@fixture('D35', 'crash: partial JSONL tail -> truncate + retry')
def d35():
    sb, sid = prepared_authorized()
    rbytes = receipt_bytes_of(sb, sid, 1, 1)
    r1 = chain_events(sb, sid)[-1]
    payload = {'opaque_case_id': r1['payload']['opaque_case_id'],
               'T': r1['payload']['T'], 'receipt_sha256': sha(rbytes),
               'bytes_ref': 'bytes/seal_annotation/1.bin'}
    ev = dict(sequence_no=1, prev_event_hash=r1['event_hash'],
              event_type=c2.SEAL, payload=payload,
              event_hash=c2.event_hash(1, r1['event_hash'], c2.SEAL,
                                       payload),
              ts=time.time())
    with open(log_path(sb, sid), 'ab') as f:
        f.write(canon(ev).encode()[:20])          # HALF LINE only
    bp = _orphan_bytes_path(sb, sid, 1)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_bytes(rbytes)                        # matched orphan
    assert recover(sb, sid) == 'MATCHED_ORPHAN_RETRY_OK'
    assert len(chain_events(sb, sid)) == 1        # tail truncated away
    seal_transaction(sb, sid)
    semantic_replay(sb, sid)
    print('PASS D35')
    cleanup_sb(sb)


@fixture('D36', 'crash: unanchored complete tail -> SEAL_COMMITTED')
def d36():
    sb, sid = prepared_authorized()
    rbytes = receipt_bytes_of(sb, sid, 1, 1)
    r1 = chain_events(sb, sid)[-1]
    payload = {'opaque_case_id': r1['payload']['opaque_case_id'],
               'T': r1['payload']['T'], 'receipt_sha256': sha(rbytes),
               'bytes_ref': 'bytes/seal_annotation/1.bin'}
    ev = dict(sequence_no=1, prev_event_hash=r1['event_hash'],
              event_type=c2.SEAL, payload=payload,
              event_hash=c2.event_hash(1, r1['event_hash'], c2.SEAL,
                                       payload),
              ts=time.time())
    bp = _orphan_bytes_path(sb, sid, 1)
    bp.parent.mkdir(parents=True, exist_ok=True)
    bp.write_bytes(rbytes)
    fsync_file(bp)
    with open(log_path(sb, sid), 'a') as f:
        f.write(canon(ev) + '\n')                 # line durable, head NOT
    assert recover(sb, sid) == 'SEALED'           # completion + finalize
    assert [e['event_type'] for e in chain_events(sb, sid)] == \
        [c2.REVEAL, c2.SEAL]
    semantic_replay(sb, sid)
    post_seal_final(sb, sid)
    # negative: unanchored tail failing the strict condition set
    sb2, sid2 = prepared_authorized()
    bad_payload = dict(payload, receipt_sha256='9' * 64)
    ev2 = dict(ev, payload=bad_payload,
               event_hash=c2.event_hash(1, r1['event_hash'], c2.SEAL,
                                        bad_payload))
    bp2 = _orphan_bytes_path(sb2, sid2, 1)
    bp2.parent.mkdir(parents=True, exist_ok=True)
    bp2.write_bytes(rbytes)
    with open(log_path(sb2, sid2), 'a') as f:
        f.write(canon(ev2) + '\n')
    expect_exact_gate(lambda: recover(sb2, sid2),
                      'SEAL_TAIL_UNANCHORED strict conditions failed')
    print('PASS D36')
    cleanup_sb(sb)
    cleanup_sb(sb2)


@fixture('D37', 'attempt-2 positive flow after revocation')
def d37():
    sb, sid = prepared_ready()
    adir1 = attempt_dir(sb, sid, 1, 1)
    orig1 = (adir1 / 'receipt.json').read_bytes()
    revoke_receipt(sb, sid, 'DRAFT_ERROR')
    write_draft(sb, sid, sample_draft(sb, sid, attempt=2,
                                      ann_session='annsess-opaque-0002'))
    make_receipt(sb, sid)                         # attempt 0002 published
    make_seal_approval(sb, sid)
    seal_transaction(sb, sid)
    semantic_replay(sb, sid)
    assert (adir1 / 'receipt.json').read_bytes() == orig1  # never deleted
    assert attempts_published(sb, sid, 1) == [1, 2]
    print('PASS D37')
    cleanup_sb(sb)


@fixture('D38', 'post-SEAL cleanup + replay independent of workspace')
def d38():
    sb, sid = prepared_sealed()
    dom = annot_dom(sb, sid)
    assert not any(dom.rglob('*'))                # cleaned
    semantic_replay(sb, sid)                      # proves everything
    post_seal_final(sb, sid)
    assert derive_state(sb, sid)[0] == 'SEALED'
    print('PASS D38')
    cleanup_sb(sb)


@fixture('D39', 'C4-C anchor immutability through the seal flow')
def d39():
    before = c4c.anchor_path().read_bytes()
    prepared_sealed()
    if c4c.anchor_path().read_bytes() != before:
        fail(f'{G_BOUND}: c4c_anchor.json mutated by the seal flow')
    print('PASS D39')


@fixture('D40', 'foreign orphan -> FORENSIC, bytes unchanged')
def d40():
    sb, sid = prepared_authorized()
    bp = _orphan_bytes_path(sb, sid, 1)
    bp.parent.mkdir(parents=True, exist_ok=True)
    foreign = b'foreign-receipt-bytes'
    bp.write_bytes(foreign)
    expect_exact_gate(lambda: recover(sb, sid), 'FOREIGN_ORPHAN')
    assert bp.read_bytes() == foreign             # untouched
    cleanup_sb(sb)


@fixture('D41', 'attempt publication crash — both windows')
def d41():
    # window (a): staging half-built, draft not locked
    sb, sid = prepared_sandbox()
    try:
        make_receipt(sb, sid, stop_after='after_staging_fsync')
    except CrashSim:
        pass
    assert attempt_staging(sb, sid, 1, 1).exists()
    assert not attempts_published(sb, sid, 1)
    assert recover_publication(sb, sid) == 'ANNOTATION_OPEN'
    make_receipt(sb, sid)                         # redo cleanly
    assert derive_state(sb, sid)[0] == 'READY_TO_SEAL'
    cleanup_sb(sb)
    # window (b): draft locked 0400, staging not renamed (FIX3-F19)
    sb, sid = prepared_sandbox()
    try:
        make_receipt(sb, sid, stop_after='after_draft_fsync')
    except CrashSim:
        pass
    dp = draft_path(sb, sid)
    assert mode_of(dp) == 0o400
    assert not attempts_published(sb, sid, 1)     # no half-READY
    assert recover_publication(sb, sid) == 'ANNOTATION_OPEN'
    assert mode_of(dp) == 0o600
    assert derive_state(sb, sid)[0] == 'ANNOTATION_OPEN'
    make_receipt(sb, sid)
    assert derive_state(sb, sid)[0] == 'READY_TO_SEAL'
    print('PASS D41')
    cleanup_sb(sb)


@fixture('D42', 'SEAL committed / anchor missing -> finalize only')
def d42():
    sb, sid = prepared_authorized()
    try:
        seal_transaction(sb, sid, stop_after='after_replay')
    except CrashSim:
        pass
    assert derive_state(sb, sid)[0] == 'SEAL_PENDING_FINALIZE'
    assert not anchor_path_in(sb).exists()
    assert recover(sb, sid) == 'SEALED'           # finalize-only recovery
    post_seal_final(sb, sid)
    extra = b'second-receipt'
    payload = {'opaque_case_id': c2.synth_ocid(SYNTH_CASE), 'T': SYNTH_T,
               'receipt_sha256': sha(extra)}
    lg = c2.SealingLog(log_path(sb, sid), head_path(sb, sid))
    expect_exact_gate(lambda: c2translate(lg.append, c2.SEAL, payload,
                                          extra), 'duplicate SEAL')
    print('PASS D42')
    cleanup_sb(sb)


@fixture('D43', 'anchor durable / workspace uncleared -> cleanup recovery')
def d43():
    sb, sid = prepared_authorized()
    try:
        seal_transaction(sb, sid, stop_after='after_anchor')
    except CrashSim:
        pass
    assert derive_state(sb, sid)[0] == 'SEAL_PENDING_FINALIZE'
    assert anchor_path_in(sb).exists()
    assert any(annot_dom(sb, sid).rglob('*'))     # not cleaned yet
    assert recover(sb, sid) == 'SEALED'
    assert derive_state(sb, sid)[0] == 'SEALED'
    build_next_reveal_proposal(sb, sid, 2, _current_prefix_head(sb, sid))
    print('PASS D43')
    cleanup_sb(sb)


@fixture('D44', 'ordinal-N path/schema violations -> AUTHZ/VISIBILITY')
def d44():
    sb, sid = prepared_sealed()
    build_next_reveal_proposal(sb, sid, 2, _current_prefix_head(sb, sid))
    os.chmod(proposal_path(sb, sid, 2), 0o644)    # (a) file mode drift
    expect_exact_gate(lambda: verify_proposal_domain(sb, sid, 2), G_VIS)
    os.chmod(proposal_path(sb, sid, 2), 0o600)
    os.chmod(proposals_dom(sb, sid, 2), 0o755)    # (b) parent mode drift
    expect_exact_gate(lambda: verify_proposal_domain(sb, sid, 2), G_VIS)
    os.chmod(proposals_dom(sb, sid, 2), 0o700)
    assert not (next_authz_dir(sb, sid, 2) /
                'next_reveal.approval.json').exists()
    p = read_json(proposal_path(sb, sid, 2))      # (c) schema extra field
    p['extra'] = 1
    os.chmod(proposal_path(sb, sid, 2), 0o600)
    proposal_path(sb, sid, 2).write_bytes(canon(p).encode())
    expect_exact_gate(lambda: approve_next_reveal(sb, sid, 2), G_AUTHZ)
    print('PASS D44')
    cleanup_sb(sb)


@fixture('D45', 'ordinal-2 REVEAL binding break -> AUTHZ')
def d45():
    sb, sid = prepared_sealed()
    build_next_reveal_proposal(sb, sid, 2, _current_prefix_head(sb, sid))
    approve_next_reveal(sb, sid, 2)
    materialize_next_permit(sb, sid, 2)
    evs_before = chain_events(sb, sid)
    expect_exact_gate(lambda: reveal_transaction(
        sb, sid, 2, payload_override={'sealed_prefix_head': 'f' * 64}),
        G_AUTHZ)
    expect_exact_gate(lambda: reveal_transaction(
        sb, sid, 2, payload_override={'candidate_packet_sha256': 'e' * 64}),
        G_AUTHZ)
    assert chain_events(sb, sid) == evs_before    # nothing appended
    ev = reveal_transaction(sb, sid, 2)           # positive control
    assert ev['payload']['reveal_ordinal'] == 2
    proposal = read_json(proposal_path(sb, sid, 2))
    assert derive_reveal_consumption(chain_events(sb, sid), proposal,
                                     sid) == 'CONSUMED'
    print('PASS D45')
    cleanup_sb(sb)


@fixture('D46', 'proposal domain permission drift -> AUTHZ+VISIBILITY')
def d46():
    sb, sid = prepared_sealed()
    root = sb / 'c4d_proposals'
    root.mkdir(mode=0o755)                        # drift BEFORE any write
    expect_exact_gate(lambda: build_next_reveal_proposal(
        sb, sid, 2, '0' * 64), G_VIS)
    os.chmod(root, 0o700)
    build_next_reveal_proposal(sb, sid, 2, _current_prefix_head(sb, sid))
    print('PASS D46')
    cleanup_sb(sb)


# --------------------------------------------------------------------------
# live-state guards (read-only)
# --------------------------------------------------------------------------

def live_preflight():
    """Real chain still exactly [REVEAL r1]; no C4-D domain exists yet."""
    c4c.assert_real_experiment_started()
    log = REAL_PRODUCTION / REAL_SESSION / 'sealing' / 'sealing_log.jsonl'
    evs = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    if [e['event_type'] for e in evs] != ['REVEAL_PACKET']:
        fail('live preflight: production must hold exactly one REVEAL')
    if evs[0]['event_hash'] != LIVE_R1_EVENT_HASH:
        fail('live preflight: r1 event_hash drifted from the frozen '
             'b5ec0ba1… anchor')
    for dom in (REAL_ANNOTATOR, REAL_RECEIPTS, REAL_PROPOSALS_C4D):
        if dom.exists():
            fail(f'live preflight: forbidden real domain exists: {dom}')
    if (PUBLIC_DIR / C4D_ANCHOR_NAME).exists():
        fail('live preflight: c4d_seal_anchor.json must not exist before '
             'the real SEAL')
    return True


def fingerprint_real():
    return {'production': c4c.tree_fingerprint(REAL_PRODUCTION),
            'c4c_anchor': c4c.tree_fingerprint(c4c.anchor_path().parent)}


# --------------------------------------------------------------------------
# command surface
# --------------------------------------------------------------------------

def cmd_synthetic():
    verify_contract_constant()
    live_preflight()
    before = fingerprint_real()
    cand = verify_candidate_gates()
    print(f"CANDIDATE GATES PASS: order_size={cand['size']} "
          f"ordinal1=…{cand['ordinal1'][0][-12:]} T={cand['ordinal1'][1]} "
          f"revealed_prefix={cand['revealed_prefix']}")
    with tempfile.TemporaryDirectory(prefix='c4d-positive-') as td:
        sb, sid = Path(td), REAL_SESSION
        build_r1(sb, sid)
        handoff(sb, sid)
        write_draft(sb, sid, sample_draft(sb, sid))
        assert derive_state(sb, sid)[0] == 'ANNOTATION_OPEN'
        make_receipt(sb, sid)
        assert derive_state(sb, sid)[0] == 'READY_TO_SEAL'
        make_seal_approval(sb, sid)
        assert derive_state(sb, sid)[0] == 'SEAL_AUTHORIZED'
        result = seal_transaction(sb, sid)
        assert derive_state(sb, sid)[0] == 'SEALED'
        print(f"SYNTHETIC FULL FLOW PASS: head={result['head'][:16]}… "
              f"attempt={result['attempt']}")
    for name, desc, fn in FIXTURES:
        fn()
        print(f'[{name}] PASS — {desc}')
    reg = subprocess.run(
        [sys.executable,
         str(ROOT / 'scripts' / 'csr8_phase_c_first_reveal.py'),
         'synthetic'],
        capture_output=True, text=True)
    if reg.returncode != 0:
        print(reg.stdout[-2000:])
        print(reg.stderr[-2000:])
        fail('C4-C regression FAILED — frozen executor selftest must pass')
    if fingerprint_real() != before:
        fail('REAL PRODUCTION OR C4C ANCHOR MUTATED — fail-closed')
    live_preflight()
    report = {
        'mode': 'synthetic only; real chain/domains untouched',
        'design': 'PHASE_C_C4D_ANNOTATION_SEAL_DESIGN v1.0 FINAL FROZEN '
                  '@ 034d152',
        'fixtures': f'D01–D{len(FIXTURES):02d} ({len(FIXTURES)} PASS)',
        'candidate_gates': {k: cand[k] for k in
                            ('size', 'ordinal1', 'revealed_prefix')},
        'c4c_regression': 'PASS',
        'live_invariants': 'REVEAL=1 SEAL=0 annotation=0 '
                           'c4d_domains=absent anchor=absent',
    }
    print('C4-D SYNTHETIC AUDIT GREEN')
    print(canon(report))


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'synthetic'
    if cmd == 'synthetic':
        cmd_synthetic()
    elif cmd == 'candidates':
        verify_contract_constant()
        print(canon(verify_candidate_gates()))
    else:
        print(f'usage: {sys.argv[0]} synthetic|candidates')
        sys.exit(2)


if __name__ == '__main__':
    main()
