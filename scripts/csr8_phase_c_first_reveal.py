#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C4-C — First Production Reveal Transaction, SYNTHETIC ONLY.

Implements C4-C DESIGN FINAL FROZEN @ 4d9d29c in an isolated temp sandbox:

    synthetic  -> three-stage authorization (external proposal -> persisted
                  approval authority -> exact-copy permit) + full crash-safe
                  transaction (staging append -> fsync closure -> no-replace
                  publication -> production replay -> semantic replay ->
                  final invariant -> external anchor) + 25 negative fixtures
                  + crash/recovery matrix simulation.

HARD BOUNDARY (design §8): this script NEVER touches the real production
session, never creates a real proposal/approval/permit, never calls the
production C2 append outside a temp sandbox, and asserts the real
data/csr8_phase_c/production tree is byte-identical before and after.

Real frozen artifacts (C1/C3 authorities, C3 manifest + packet bytes) are
consumed READ-ONLY, exactly as the design requires the synthetic transaction
to reverify them.
"""
import ctypes
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
import csr8_phase_c_packet as c1          # frozen C1 (read-only use)
import csr8_phase_c_seal as c2            # frozen C2 state machine
import csr8_phase_c_activate as c4ab      # frozen C4-A/B helpers

C3_STATE = c4ab.C3_STATE
REAL_PRODUCTION = ROOT / 'data/csr8_phase_c/production'
SYNTH_DIR = ROOT / 'output/research/csr/08_pilot_cases/phase_c/c4c_synthetic'

AUTHZ_VERSION = 'c4c-auth-v1'
APPROVAL_VERSION = 'c4c-approval-v1'
PERMIT_KEYS = {
    'authorization_version', 'scope', 'authorization_id', 'session_id',
    'c3_manifest_commitment', 'candidate_packet_id', 'candidate_packet_sha256',
    'authorized', 'created_at',
}
APPROVAL_KEYS = {
    'approval_version', 'scope', 'session_id',
    'approved_authorization_sha256', 'approved',
}
RENAME_NOREPLACE = 1
AT_FDCWD = -100
SYSCALL_RENAMEAT2 = {'x86_64': 316, 'aarch64': 276}


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


def expect_fail(fn, label):
    try:
        fn()
    except (RuntimeError, SystemExit):
        print('NEGATIVE PASS:', label)
        return
    raise RuntimeError('fixture did not fail: ' + label)


# ---------------- durability primitives ----------------

def fsync_file(path):
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_dir(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def excl_write(path, data):
    """O_CREAT|O_EXCL, 0600, fsync file + parent dir (design §2.2)."""
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        fail(f'G-C4C-AUTHZ: create-exclusive violated — {path} already '
             'exists (immutable object cannot be recreated)')
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def rename_noreplace(src, dst):
    """Atomic no-replace rename via renameat2(RENAME_NOREPLACE); FAIL-CLOSED
    if unsupported (never degrade to copy/delete)."""
    nr = SYSCALL_RENAMEAT2.get(platform.machine())
    if nr is None:
        fail('G-C4C-PUBLISH: renameat2 unavailable on this platform — '
             'FAIL-CLOSED, copy/delete degradation forbidden')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    res = libc.syscall(ctypes.c_long(nr), ctypes.c_int(AT_FDCWD),
                       ctypes.c_char_p(str(src).encode()),
                       ctypes.c_int(AT_FDCWD),
                       ctypes.c_char_p(str(dst).encode()),
                       ctypes.c_uint(RENAME_NOREPLACE))
    if res != 0:
        err = ctypes.get_errno()
        fail(f'G-C4C-PUBLISH: no-replace rename failed (errno={err})')


def tree_fingerprint(path):
    """Inventory of a real tree — used to prove the real production domain
    is never touched."""
    if not path.exists():
        return None
    items = []
    for p in sorted(path.rglob('*')):
        st = p.stat()
        items.append((str(p.relative_to(path)), st.st_mode, st.st_mtime_ns,
                      st.st_size))
    return items


# ---------------- three-stage authorization (design §2.2) ----------------

def make_proposal(sb, sid, entry, authz_id=None):
    """Stage 1: exact 9-field proposal OUTSIDE the production session."""
    proposal = {
        'authorization_version': AUTHZ_VERSION,
        'scope': 'FIRST_REVEAL_ONLY',
        'authorization_id': authz_id or uuid.uuid4().hex,
        'session_id': sid,
        'c3_manifest_commitment': c4ab.C3_COMMITMENT,
        'candidate_packet_id': entry['packet_id'],
        'candidate_packet_sha256': entry['sha256'],
        'authorized': True,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    pdir = sb / 'c4c_proposals' / sid
    pdir.mkdir(parents=True, mode=0o700)
    ppath = pdir / 'first_reveal.proposal.json'
    excl_write(ppath, canon(proposal).encode())
    return ppath, canon(proposal).encode()


def approve(sb, sid, proposal_sha):
    """Stage 2: persisted approval authority — the machine representation of
    the single human FIRST_REVEAL_ONLY authorization (exact-hash)."""
    approval = {
        'approval_version': APPROVAL_VERSION,
        'scope': 'FIRST_REVEAL_ONLY',
        'session_id': sid,
        'approved_authorization_sha256': proposal_sha,
        'approved': True,
    }
    apath = (sb / 'production' / sid / 'authorization' /
             'first_reveal.approval.json')
    apath.parent.mkdir(parents=True, mode=0o700)
    excl_write(apath, canon(approval).encode())
    return apath


def materialize_permit(sb, sid, proposal_bytes, proposal_sha):
    """Stage 3: exact-copy permit — reconstruction is forbidden."""
    verify_approval(read_json(sb / 'production' / sid / 'authorization' /
                              'first_reveal.approval.json'))
    if sha(proposal_bytes) != proposal_sha:
        fail('G-C4C-AUTHZ: proposal bytes do not hash to proposal_sha')
    permit_path = (sb / 'production' / sid / 'authorization' /
                   'first_reveal.json')
    excl_write(permit_path, proposal_bytes)   # exact bytes, O_EXCL
    if sha(permit_path.read_bytes()) != proposal_sha:
        fail('G-C4C-AUTHZ: permit bytes != approved hash')
    return permit_path


def read_json(path):
    return json.loads(Path(path).read_text())


def verify_approval(approval):
    if set(approval) != APPROVAL_KEYS:
        fail('G-C4C-AUTHZ: approval closed-world violation (c4c-approval-v1)')
    if (approval['approval_version'] != APPROVAL_VERSION
            or approval['scope'] != 'FIRST_REVEAL_ONLY'
            or approval['approved'] is not True):
        fail('G-C4C-AUTHZ: approval field drift')


def verify_permit(permit, sid):
    if set(permit) != PERMIT_KEYS:
        fail('G-C4C-AUTHZ: permit closed-world violation (c4c-auth-v1)')
    if (permit['authorization_version'] != AUTHZ_VERSION
            or permit['scope'] != 'FIRST_REVEAL_ONLY'
            or permit['authorized'] is not True
            or permit['session_id'] != sid
            or permit['c3_manifest_commitment'] != c4ab.C3_COMMITMENT):
        fail('G-C4C-AUTHZ: permit field drift')
    try:
        time.strptime(permit['created_at'], '%Y-%m-%dT%H:%M:%SZ')
    except (ValueError, TypeError):
        fail('G-C4C-AUTHZ: permit created_at not canonical')


def verify_authorization_chain(sb, sid, entry=None):
    """Steps 0a/0b + step 4 binding: approval -> proposal -> permit ->
    first_candidate_record -> recomputed candidate (exact, closed-world)."""
    prod = sb / 'production' / sid
    adir = prod / 'authorization'
    for name in ('first_reveal.approval.json', 'first_reveal.json'):
        p = adir / name
        if not p.exists() or (p.stat().st_mode & 0o777) != 0o600:
            fail(f'G-C4C-AUTHZ: {name} missing or not selector-only 0600')
    fsync_file(adir / 'first_reveal.json')       # (0a) re-prove durability
    fsync_dir(adir)
    approval = read_json(adir / 'first_reveal.approval.json')
    verify_approval(approval)
    if approval['session_id'] != sid:
        fail('G-C4C-AUTHZ: approval session mismatch')
    proposal_path = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
    if not proposal_path.exists():
        fail('G-C4C-AUTHZ: external proposal missing')
    proposal_sha = sha(proposal_path.read_bytes())
    permit_bytes = (adir / 'first_reveal.json').read_bytes()
    permit = json.loads(permit_bytes)
    verify_permit(permit, sid)
    if not (proposal_sha == approval['approved_authorization_sha256']
            == sha(permit_bytes)):
        fail('G-C4C-AUTHZ: proposal/approval/permit hash inequality')
    if permit_bytes != proposal_path.read_bytes():
        fail('G-C4C-AUTHZ: permit bytes != proposal bytes '
             '(reconstruction forbidden)')
    record = read_json(prod / 'first_candidate_record.json')
    if (permit['candidate_packet_id'] != record['candidate_packet_id']
            or permit['candidate_packet_sha256']
            != record['candidate_packet_sha256']):
        fail('G-C4C-AUTHZ: permit does not bind frozen first candidate')
    if entry is not None:
        if (permit['candidate_packet_id'] != entry['packet_id']
                or permit['candidate_packet_sha256'] != entry['sha256']):
            fail('G-C4C-AUTHZ: permit != recomputed frozen candidate')
        c4ab.verify_candidate_bytes(entry)      # G-C4C-BYTES
    return permit, sha(permit_bytes)


# ---------------- the transaction (design §4) ----------------

def run_transaction(sb, sid, stop_after=None, staging_override=None):
    """Steps 0a–22 with crash-simulation checkpoints. Raises RuntimeError on
    any gate failure; raises CrashSim at the requested checkpoint."""
    prod = sb / 'production' / sid
    sealing = prod / 'sealing'
    staging = staging_override or (prod / 'sealing.staging')

    def stop(name):
        if stop_after == name:
            raise CrashSim(name)

    # (0a/0b) authorization durability + approval/proposal/permit chain
    verify_authorization_chain(sb, sid)
    stop('after_authz')
    # (1) frozen C4-A/B session (manifest closed-world + permissions)
    manifest = c4ab.verify_session_manifest(sid, prod)
    c4ab.verify_session_permissions(prod)
    stop('after_session')
    # (2) all frozen authorities (real, read-only)
    c4ab.verify_frozen_authorities()
    stop('after_authorities')
    # (3) independently recompute first candidate
    cand = c4ab.first_candidate(c1)
    entry = c4ab.candidate_packet(c1, cand)
    stop('after_candidate')
    # (4) authorization exact binding incl. packet bytes (G-C4C-BYTES)
    permit, permit_sha = verify_authorization_chain(sb, sid, entry)
    record = c4ab.verify_first_candidate_record(sid, prod, manifest, entry)
    stop('after_binding')
    # (5) chain-derived unusedness: production sealing absent -> 0 events
    if sealing.exists():
        fail('G-C4C-AUTHZ: authorization already consumed '
             '(production sealing domain exists)')
    stop('after_unused')
    # (6) publication target absent
    if sealing.exists():
        fail('G-C4C-PUBLISH: production sealing target already exists')
    stop('after_target_absent')
    # (7) same-filesystem staging domain
    if staging.exists():
        fail('G-C4C-PUBLISH: staging domain already exists')
    staging.mkdir(parents=True, mode=0o700)
    if os.stat(staging).st_dev != os.stat(prod).st_dev:
        fail('G-C4C-PUBLISH: staging not on the same filesystem')
    stop('after_staging')
    # (8) frozen C2 append (real append(), not batch writer)
    log, head = staging / 'sealing_log.jsonl', staging / 'sealing_log.head.json'
    payload = {
        'opaque_case_id': cand['opaque_case_id'],
        'T': entry['T'],
        'packet_id': entry['packet_id'],
        'packet_sha256': entry['sha256'],
        'session_id': sid,
        'authorization_id': permit['authorization_id'],
        'authorization_sha256': permit_sha,
        'c3_manifest_commitment': c4ab.C3_COMMITMENT,
        'candidate_packet_sha256': entry['sha256'],
    }
    packet_bytes = (C3_STATE / 'packets' / f"{entry['packet_id']}.json"
                    ).read_bytes()
    c2.SealingLog(log, head).append(c2.REVEAL, payload, packet_bytes)
    stop('after_append')
    # (9/10) staged fresh replay + 1 REVEAL / 0 SEAL
    staged_verify(staging)
    stop('after_staged_replay')
    # (11–16) complete fsync closure incl. nested C2-created directories
    fsync_closure(staging)
    stop('after_fsync')
    # (17) atomic no-replace publication
    if sealing.exists():
        fail('G-C4C-PUBLISH: target appeared before rename')
    rename_noreplace(staging, sealing)
    stop('after_rename')
    # (18) production parent directory durability
    fsync_dir(prod)
    stop('after_parent_fsync')
    # (19) production fresh replay + semantic replay
    production_verify(prod)
    head_hash = semantic_replay(sb, sid)
    stop('after_replay')
    # (20) final invariant
    final_invariant(sb, sid)
    # anchor (post-commit, §6.2)
    anchor = {
        'production_head_hash': head_hash,
        'authorization_sha256': permit_sha,
    }
    pub = sb / 'public'
    pub.mkdir(parents=True, exist_ok=True)
    (pub / 'c4c_anchor.json').write_text(canon(anchor))
    return {'state': 'FIRST_REVEAL_OPEN', 'consumed': True,
            'head_hash': head_hash}


def staged_verify(staging):
    log = staging / 'sealing_log.jsonl'
    head = staging / 'sealing_log.head.json'
    sl = c2.SealingLog(log, head).load()
    n = sl.verify()
    reveals = [e for e in sl.events if e['event_type'] == c2.REVEAL]
    seals = [e for e in sl.events if e['event_type'] == c2.SEAL]
    if n != 1 or len(reveals) != 1 or seals:
        fail('G-C4C-STAGED-REPLAY: staged chain is not exactly '
             '1 REVEAL / 0 SEAL')
    return sl


def fsync_closure(staging):
    log = staging / 'sealing_log.jsonl'
    head = staging / 'sealing_log.head.json'
    packet = staging / 'bytes' / 'reveal_packet' / '0.bin'
    fsync_file(packet)
    fsync_dir(staging / 'bytes' / 'reveal_packet')
    fsync_dir(staging / 'bytes')
    fsync_file(log)
    fsync_file(head)
    fsync_dir(staging)


def production_verify(prod):
    sealing = prod / 'sealing'
    sl = c2.SealingLog(sealing / 'sealing_log.jsonl',
                       sealing / 'sealing_log.head.json').load()
    sl.verify()
    return sl


def semantic_replay(sb, sid):
    """§6.1: re-prove the whole chain from persisted state only."""
    prod = sb / 'production' / sid
    approval = read_json(prod / 'authorization' /
                         'first_reveal.approval.json')
    verify_approval(approval)
    permit_bytes = (prod / 'authorization' / 'first_reveal.json').read_bytes()
    permit = json.loads(permit_bytes)
    verify_permit(permit, sid)
    if sha(permit_bytes) != approval['approved_authorization_sha256']:
        fail('G-C4C-PROD-REPLAY: permit hash != approved hash')
    cand = c4ab.first_candidate(c1)
    entry = c4ab.candidate_packet(c1, cand)
    manifest = c4ab.verify_session_manifest(sid, prod)
    c4ab.verify_session_permissions(prod)
    c4ab.verify_first_candidate_record(sid, prod, manifest, entry)
    record = c4ab.load_c3_manifest()
    if sha(canon(record).encode()) != c4ab.C3_COMMITMENT:
        fail('G-C4C-PROD-REPLAY: C3 manifest commitment drift')
    packet_path = C3_STATE / 'packets' / f"{entry['packet_id']}.json"
    if sha(packet_path.read_bytes()) != entry['sha256']:
        fail('G-C4C-PROD-REPLAY: C3 packet bytes hash mismatch')
    sl = production_verify(prod)
    if len(sl.events) != 1 or sl.events[0]['event_type'] != c2.REVEAL:
        fail('G-C4C-PROD-REPLAY: production chain is not exactly one REVEAL')
    p = sl.events[0]['payload']
    if p['packet_id'] != entry['packet_id']:
        fail('G-C4C-PROD-REPLAY: event packet_id != recomputed candidate')
    if p['packet_id'] != permit['candidate_packet_id']:
        fail('G-C4C-PROD-REPLAY: event packet_id != permit')
    if p['packet_sha256'] != entry['sha256'] or \
            p['candidate_packet_sha256'] != permit['candidate_packet_sha256']:
        fail('G-C4C-PROD-REPLAY: event packet hash binding broken')
    if p['authorization_id'] != permit['authorization_id']:
        fail('G-C4C-PROD-REPLAY: event authorization_id != permit')
    if p['authorization_sha256'] != sha(permit_bytes):
        fail('G-C4C-PROD-REPLAY: event authorization_sha256 != permit hash')
    if p['session_id'] != sid:
        fail('G-C4C-PROD-REPLAY: event session binding broken')
    if p['c3_manifest_commitment'] != c4ab.C3_COMMITMENT:
        fail('G-C4C-PROD-REPLAY: event C3 commitment binding broken')
    return sl.events[0]['event_hash']


def final_invariant(sb, sid):
    prod = sb / 'production' / sid
    sl = production_verify(prod)
    reveals = [e for e in sl.events if e['event_type'] == c2.REVEAL]
    seals = [e for e in sl.events if e['event_type'] == c2.SEAL]
    if len(sl.events) != 1 or len(reveals) != 1 or seals:
        fail('final invariant: not exactly 1 REVEAL / 0 SEAL')
    for forbidden in ('annotation', 'annotations', 'outcome', 'outcomes'):
        if (prod / forbidden).exists():
            fail(f'final invariant: {forbidden} must be absent')
    c4ab.verify_c3_authority()   # G5 BLOCKED / XP BLOCKED_FOR_PIT etc.


# ---------------- boundary gates (HARD STOP, design §6/§7-16..19) ----------

def attempt_second_reveal(sb, sid):
    fail('G-C4C-BOUNDARY: next reveal forbidden after first reveal '
         '(HARD STOP)')


def attempt_seal(sb, sid):
    fail('G-C4C-BOUNDARY: SEAL forbidden in C4-C — sealed_count must remain '
         '0; the annotation pipeline belongs to a later, separately '
         'authorized phase')


def attempt_annotation(sb, sid):
    fail('G-C4C-BOUNDARY: annotation session creation forbidden in C4-C')


def attempt_outcome(sb, sid):
    fail('G-C4C-BOUNDARY: outcome generation forbidden in C4-C')


# ---------------- recovery (design §5) ----------------

def recover(sb, sid):
    """Authoritative state from persisted filesystem fact only."""
    prod = sb / 'production' / sid
    sealing, staging = prod / 'sealing', prod / 'sealing.staging'
    if sealing.exists():
        try:
            semantic_replay(sb, sid)
            final_invariant(sb, sid)
        except (RuntimeError, SystemExit):
            return {'state': 'HALT_FORENSIC', 'consumed': None,
                    'retry': False,
                    'action': 'HALT / forensic audit; retry forbidden'}
        return {'state': 'FIRST_REVEAL_OPEN', 'consumed': True,
                'retry': False, 'action': 'none — authorization consumed'}
    if staging.exists():
        shutil.rmtree(staging)
        return {'state': 'INITIALIZED_NO_REVEAL', 'consumed': False,
                'retry': True,
                'action': 'staging discarded; controlled retry allowed'}
    return {'state': 'INITIALIZED_NO_REVEAL', 'consumed': False,
            'retry': True, 'action': 'nothing to recover; retry allowed'}


# ---------------- sandbox construction ----------------

def build_sandbox(td, sid='synthetic-01'):
    sb = Path(td)
    c4ab.c4a_init(sid, sb / 'production')          # synthetic C4-A session
    cand = c4ab.first_candidate(c1)
    entry = c4ab.candidate_packet(c1, cand)
    ppath, pbytes = make_proposal(sb, sid, entry)
    approve(sb, sid, sha(pbytes))
    materialize_permit(sb, sid, pbytes, sha(pbytes))
    return sb, sid, entry


def fresh_fixture(name):
    td = tempfile.mkdtemp(prefix='c4c-' + name + '-')
    return td


def run_with_crash(sb, sid, stop):
    try:
        run_transaction(sb, sid, stop_after=stop)
    except CrashSim:
        return
    raise RuntimeError(f'crash simulation did not stop at {stop}')


# ---------------- fixtures ----------------

def fixtures():
    results = []

    def record(label):
        results.append(label)
        print('NEGATIVE PASS:', label)

    def fx(name):
        def deco(fn):
            td = fresh_fixture(name)
            try:
                sb, sid, entry = build_sandbox(td)
                fn(sb, sid, entry, td)
            except (RuntimeError, SystemExit):
                record(name)
            else:
                raise RuntimeError('fixture did not fail: ' + name)
            finally:
                shutil.rmtree(td, ignore_errors=True)
        return deco

    # 1 authorization missing
    @fx('01-authz-missing')
    def _(sb, sid, entry, td):
        os.unlink(sb / 'production' / sid / 'authorization' /
                  'first_reveal.json')
        run_transaction(sb, sid)

    # 2 permit schema extra/missing field
    @fx('02-permit-schema')
    def _(sb, sid, entry, td):
        adir = sb / 'production' / sid / 'authorization'
        permit = read_json(adir / 'first_reveal.json')
        permit['extra_field'] = 'x'
        (adir / 'first_reveal.json').write_text(canon(permit))
        run_transaction(sb, sid)

    # 3 wrong session_id in permit (+approval consistency broken)
    @fx('03-wrong-session')
    def _(sb, sid, entry, td):
        ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        proposal = read_json(ppath)
        proposal['session_id'] = 'other-session'
        ppath.write_text(canon(proposal))
        run_transaction(sb, sid)

    # 4 wrong c3_manifest_commitment
    @fx('04-wrong-c3')
    def _(sb, sid, entry, td):
        ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        proposal = read_json(ppath)
        proposal['c3_manifest_commitment'] = '0' * 64
        ppath.write_text(canon(proposal))
        run_transaction(sb, sid)

    # 5 wrong candidate_packet_id
    @fx('05-wrong-packet-id')
    def _(sb, sid, entry, td):
        ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        proposal = read_json(ppath)
        proposal['candidate_packet_id'] = '0' * 64
        ppath.write_text(canon(proposal))
        run_transaction(sb, sid)

    # 6 wrong candidate_packet_sha256
    @fx('06-wrong-packet-sha')
    def _(sb, sid, entry, td):
        ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        proposal = read_json(ppath)
        proposal['candidate_packet_sha256'] = '0' * 64
        ppath.write_text(canon(proposal))
        run_transaction(sb, sid)

    # 6b wholesale permit replacement (legal schema, different id/created_at)
    @fx('06b-permit-replaced')
    def _(sb, sid, entry, td):
        adir = sb / 'production' / sid / 'authorization'
        permit = read_json(adir / 'first_reveal.json')
        permit['authorization_id'] = uuid.uuid4().hex
        permit['created_at'] = '2030-01-01T00:00:00Z'
        (adir / 'first_reveal.json').write_text(canon(permit))
        run_transaction(sb, sid)

    # 6c duplicate permit path (second FIRST_REVEAL_ONLY file)
    @fx('06c-duplicate-permit-path')
    def _(sb, sid, entry, td):
        adir = sb / 'production' / sid / 'authorization'
        excl_write(adir / 'first_reveal.json',
                   (adir / 'first_reveal.json').read_bytes())  # O_EXCL must fail

    # 6d proposal bytes rewritten after approval
    @fx('06d-proposal-rewritten')
    def _(sb, sid, entry, td):
        ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        proposal = read_json(ppath)
        proposal['created_at'] = '2031-01-01T00:00:00Z'
        ppath.write_text(canon(proposal))
        run_transaction(sb, sid)

    # 6e approval hash != permit hash
    @fx('06e-approval-permit-mismatch')
    def _(sb, sid, entry, td):
        apath = (sb / 'production' / sid / 'authorization' /
                 'first_reveal.approval.json')
        approval = read_json(apath)
        approval['approved_authorization_sha256'] = '1' * 64
        apath.write_text(canon(approval))
        run_transaction(sb, sid)

    # 6f permit bytes != proposal bytes (reconstructed, same semantics)
    @fx('06f-permit-reconstructed')
    def _(sb, sid, entry, td):
        adir = sb / 'production' / sid / 'authorization'
        permit = read_json(adir / 'first_reveal.json')
        # same semantic fields, NON-canonical byte layout -> different bytes
        permit_bytes = json.dumps(permit, ensure_ascii=False, sort_keys=True,
                                  indent=1).encode()
        (adir / 'first_reveal.json').write_bytes(permit_bytes)
        run_transaction(sb, sid)

    # 7 authorization reuse after success (chain-derived consumption)
    @fx('07-authz-reuse')
    def _(sb, sid, entry, td):
        run_transaction(sb, sid)
        run_transaction(sb, sid)

    # 8 candidate record tamper
    @fx('08-record-tamper')
    def _(sb, sid, entry, td):
        rpath = sb / 'production' / sid / 'first_candidate_record.json'
        rec = read_json(rpath)
        rec['candidate_packet_sha256'] = '0' * 64
        rpath.write_text(canon(rec))
        run_transaction(sb, sid)

    # 9 packet bytes tamper (real bytes are read-only -> simulate via record
    # pointing at a hash that disk bytes cannot match is fixture 8; here we
    # tamper the staging-side copy after append, before replay binding)
    @fx('09-packet-bytes-tamper')
    def _(sb, sid, entry, td):
        run_with_crash(sb, sid, 'after_append')
        pkt = (sb / 'production' / sid / 'sealing.staging' / 'bytes' /
               'reveal_packet' / '0.bin')
        data = bytearray(pkt.read_bytes())
        data[len(data) // 2] ^= 0x01
        pkt.write_bytes(bytes(data))
        staging = sb / 'production' / sid / 'sealing.staging'
        staged_verify(staging)

    # 10 existing production sealing target
    @fx('10-sealing-target-exists')
    def _(sb, sid, entry, td):
        (sb / 'production' / sid / 'sealing').mkdir()
        run_transaction(sb, sid)

    # 11 staging not same filesystem (tmpfs vs workspace fs)
    @fx('11-staging-cross-fs')
    def _(sb, sid, entry, td):
        shm = Path('/dev/shm') / ('c4c-crossfs-' + uuid.uuid4().hex)
        try:
            run_transaction(sb, sid, staging_override=shm)
        finally:
            shutil.rmtree(shm, ignore_errors=True)

    # 12 target exists at rename time (no-replace unavailable path)
    @fx('12-rename-target-exists')
    def _(sb, sid, entry, td):
        prod = sb / 'production' / sid
        run_with_crash(sb, sid, 'after_fsync')
        (prod / 'sealing').mkdir()          # target appears before rename
        rename_noreplace(prod / 'sealing.staging', prod / 'sealing')

    # 13 staged log tamper
    @fx('13-staged-log-tamper')
    def _(sb, sid, entry, td):
        run_with_crash(sb, sid, 'after_append')
        logp = (sb / 'production' / sid / 'sealing.staging' /
                'sealing_log.jsonl')
        evs = c2.read_events(logp)
        evs[0]['payload']['T'] = '2099-12-31'
        c2.write_events(logp, evs)          # hash NOT recomputed
        staged_verify(sb / 'production' / sid / 'sealing.staging')

    # 14 staged head missing
    @fx('14-staged-head-missing')
    def _(sb, sid, entry, td):
        run_with_crash(sb, sid, 'after_append')
        (sb / 'production' / sid / 'sealing.staging' /
         'sealing_log.head.json').unlink()
        staged_verify(sb / 'production' / sid / 'sealing.staging')

    # 15 published log tamper
    @fx('15-published-log-tamper')
    def _(sb, sid, entry, td):
        run_transaction(sb, sid)
        logp = (sb / 'production' / sid / 'sealing' / 'sealing_log.jsonl')
        evs = c2.read_events(logp)
        evs[0]['payload']['session_id'] = 'tampered'
        c2.write_events(logp, evs)
        production_verify(sb / 'production' / sid)

    # 15b C2-valid chain but semantic binding broken
    @fx('15b-semantic-binding-broken')
    def _(sb, sid, entry, td):
        prod = sb / 'production' / sid
        staging = prod / 'sealing.staging'
        run_with_crash(sb, sid, 'after_staged_replay')
        logp = staging / 'sealing_log.jsonl'
        evs = c2.read_events(logp)
        evs[0]['payload']['authorization_sha256'] = 'e' * 64
        c2.cascade_rehash(evs, 0)           # C2-legal rehash
        c2.write_events(logp, evs)
        c2.sync_head(staging / 'sealing_log.head.json', evs)
        staged_verify(staging)
        fsync_closure(staging)
        rename_noreplace(staging, prod / 'sealing')
        fsync_dir(prod)
        production_verify(prod)             # C2 replay PASSES...
        semantic_replay(sb, sid)            # ...semantic replay must FAIL

    # 16/17/18/19 boundary gates after a successful transaction
    def boundary_case(name, attempt):
        td = fresh_fixture(name)
        try:
            sb, sid, entry = build_sandbox(td)
            run_transaction(sb, sid)
            attempt(sb, sid)
        except (RuntimeError, SystemExit):
            record(name)
        else:
            raise RuntimeError('fixture did not fail: ' + name)
        finally:
            shutil.rmtree(td, ignore_errors=True)

    boundary_case('16-second-reveal', attempt_second_reveal)
    boundary_case('17-attempt-seal', attempt_seal)
    boundary_case('18-attempt-annotation', attempt_annotation)
    boundary_case('19-attempt-outcome', attempt_outcome)

    return results


# ---------------- crash / recovery matrix simulation ----------------

def crash_matrix():
    outcomes = []

    def sim(name, stop, mutate=None, expect_state=None, expect_consumed=None,
            expect_retry=None):
        td = fresh_fixture('crash-' + name)
        try:
            sb, sid, entry = build_sandbox(td)
            run_with_crash(sb, sid, stop)
            if mutate:
                mutate(sb, sid)
            res = recover(sb, sid)
            if expect_state and res['state'] != expect_state:
                raise RuntimeError(f'{name}: state {res["state"]} != '
                                   f'{expect_state}')
            if expect_consumed is not None and \
                    res['consumed'] is not expect_consumed:
                raise RuntimeError(f'{name}: consumed {res["consumed"]} != '
                                   f'{expect_consumed}')
            if expect_retry is not None and res['retry'] is not expect_retry:
                raise RuntimeError(f'{name}: retry {res["retry"]} != '
                                   f'{expect_retry}')
            outcomes.append(name)
            print(f'RECOVERY PASS: {name} -> {res["state"]} '
                  f'consumed={res["consumed"]} retry={res["retry"]}')
        finally:
            shutil.rmtree(td, ignore_errors=True)

    # (a)/(c)/(d)/(e): pre-rename crash -> 0 event, retry allowed
    sim('a-before-append', 'after_staging',
        expect_state='INITIALIZED_NO_REVEAL', expect_consumed=False,
        expect_retry=True)
    sim('e-after-fsync-before-rename', 'after_fsync',
        expect_state='INITIALIZED_NO_REVEAL', expect_consumed=False,
        expect_retry=True)

    # (b): mid-append — incomplete staging (bytes+log line, no head)
    def partial_staging(sb, sid):
        staging = sb / 'production' / sid / 'sealing.staging'
        head = staging / 'sealing_log.head.json'
        if head.exists():
            head.unlink()
    sim('b-mid-append-incomplete-staging', 'after_append',
        mutate=partial_staging,
        expect_state='INITIALIZED_NO_REVEAL', expect_consumed=False,
        expect_retry=True)

    # (f)/(g): post-rename — persisted fact decides; consumed only via replay
    sim('f-after-rename-gray-zone', 'after_rename',
        expect_state='FIRST_REVEAL_OPEN', expect_consumed=True,
        expect_retry=False)
    sim('g-after-parent-fsync-unknown-pending-replay', 'after_parent_fsync',
        expect_state='FIRST_REVEAL_OPEN', expect_consumed=True,
        expect_retry=False)

    # (g) forensic path: durable sealing whose semantic binding is broken
    def semantic_broken(sb, sid):
        prod = sb / 'production' / sid
        logp = prod / 'sealing' / 'sealing_log.jsonl'
        evs = c2.read_events(logp)
        evs[0]['payload']['authorization_sha256'] = 'e' * 64
        c2.cascade_rehash(evs, 0)
        c2.write_events(logp, evs)
        c2.sync_head(prod / 'sealing' / 'sealing_log.head.json', evs)
    td = fresh_fixture('crash-g-forensic')
    try:
        sb, sid, entry = build_sandbox(td)
        run_with_crash(sb, sid, 'after_parent_fsync')
        semantic_broken(sb, sid)
        res = recover(sb, sid)
        if res['state'] != 'HALT_FORENSIC' or res['retry'] is not False:
            raise RuntimeError('g-forensic: expected HALT_FORENSIC '
                               'retry=False')
        outcomes.append('g-forensic-halt')
        print('RECOVERY PASS: g-forensic-halt -> HALT_FORENSIC retry=False')
    finally:
        shutil.rmtree(td, ignore_errors=True)

    # (h): full success — HARD STOP semantics and retry refusal
    td = fresh_fixture('crash-h-full')
    try:
        sb, sid, entry = build_sandbox(td)
        summary = run_transaction(sb, sid)
        if summary['state'] != 'FIRST_REVEAL_OPEN' or \
                not summary['consumed']:
            raise RuntimeError('h: unexpected final state')
        anchor = read_json(sb / 'public' / 'c4c_anchor.json')
        if set(anchor) != {'production_head_hash', 'authorization_sha256'}:
            raise RuntimeError('h: anchor schema violation')
        try:
            run_transaction(sb, sid)
        except (RuntimeError, SystemExit):
            outcomes.append('h-hard-stop-retry-refused')
            print('RECOVERY PASS: h-hard-stop-retry-refused -> '
                  'second transaction FAIL-CLOSED')
        else:
            raise RuntimeError('h: retry after success was not refused')
    finally:
        shutil.rmtree(td, ignore_errors=True)

    return outcomes


# ---------------- entry point ----------------

def cmd_synthetic():
    before = tree_fingerprint(REAL_PRODUCTION)
    with tempfile.TemporaryDirectory(prefix='c4c-synthetic-') as td:
        sb, sid, entry = build_sandbox(td)
        summary = run_transaction(sb, sid)
        print(f'SYNTHETIC TRANSACTION PASS: state={summary["state"]} '
              f'consumed={summary["consumed"]}')
    fixture_results = fixtures()
    crash_results = crash_matrix()
    after = tree_fingerprint(REAL_PRODUCTION)
    if before != after:
        fail('REAL PRODUCTION DOMAIN WAS MUTATED — fail-closed')
    report = {
        'construction_mode': 'synthetic/staging only; real session untouched',
        'transaction_gates': ['G-C4C-AUTHZ', 'G-C4-NEXT', 'G-C4C-BYTES',
                              'G-C4C-STAGED-REPLAY', 'G-C4C-PUBLISH',
                              'G-C4C-PROD-REPLAY', 'G-C4C-BOUNDARY'],
        'fixtures_passed': len(fixture_results),
        'fixture_names': fixture_results,
        'crash_recovery_passed': len(crash_results),
        'crash_recovery_names': crash_results,
        'real_production_untouched': True,
        'production_event_count': 0,
        'experiment_started': False,
    }
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    (SYNTH_DIR / 'c4c_synthetic_report.json').write_text(canon(report))
    print(f'C4-C SYNTHETIC PASS: {len(fixture_results)} fixtures + '
          f'{len(crash_results)} recovery scenarios; real production '
          f'fingerprint unchanged')


def main():
    if len(sys.argv) != 2 or sys.argv[1] != 'synthetic':
        print('usage: csr8_phase_c_first_reveal.py synthetic')
        sys.exit(2)
    try:
        cmd_synthetic()
    except RuntimeError:
        sys.exit(1)


if __name__ == '__main__':
    main()
