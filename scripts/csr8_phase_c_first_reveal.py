#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C4-C — First Production Reveal Transaction, SYNTHETIC ONLY.

C4-C DESIGN FINAL FROZEN @ 4d9d29c; C4-C-SYNTH-AUDIT-FIX1 (user audit):

  F1 target-aware fixture harness — every fixture has a PREPARE phase that
     must succeed (any failure = whole selftest FAIL) and a TARGET operation
     that must fail with the exact expected gate (gate mismatch = FAIL).
  F2 target isolation — 03-06 re-sign the exact-hash authority consistently
     so the *field* binding gate rejects; 08 keeps the session manifest
     self-consistent so G-C4-NEXT rejects; 09 mutates a TEMP COPY of the C3
     state (real G-C4C-BYTES); the staging-byte case moved to 09b
     (G-C4C-STAGED-REPLAY); 10 hits G-C4C-PUBLISH via a foreign committed
     REVEAL + unused authorization; 10b = unresolvable sealing.
  F3 chain-derived consumption — `sealing exists` no longer means consumed:
     derive_consumption() = absent -> UNUSED; fresh C2 replay + semantic
     replay proving a REVEAL bound to THIS authorization -> CONSUMED;
     valid chain binding another authorization -> FOREIGN; anything
     unprovable -> UNRESOLVABLE (HALT/forensic, never "consumed", no retry).
  F4 persisted semantic replay closure — approval.session_id, permit ==
     record == recomputed C3 entry (packet_id and sha256), event
     candidate_packet_sha256 == entry sha256, all re-proven from persisted
     state only.
  F5 canonical/isolation proof — created_at canonical round-trip
     (strptime->strftime == original); real production asserted pristine by
     CONTENT fingerprint (per-file SHA256) + explicit read-only state
     assertions before and after the run.

C4-C-SYNTH-AUDIT-FIX2 (user audit):
  F6 permit-materialization ordering — materialize_permit() takes NO
     caller-supplied authority bytes; it reads ONLY the persisted approval
     and proposal files, verifies (closed-world + session binding +
     9-field canonical proposal + approved hash == SHA256(persisted
     proposal bytes)) BEFORE the O_EXCL creation, so a wrong approval chain
     can never leave a permit on disk (fixtures 06g/06h/06i prove the
     permit stays ABSENT). Report annotates fixture 09's gate as a
     delegated C4-B proof.

C4-C-SYNTH-AUDIT-FIX4 (user audit):
  F8 pre-materialization permission contract — BEFORE any content check
     the materializer proves the persisted authority objects satisfy the
     selector-only contract: authorization dir 0700, proposal dir 0700,
     approval file 0600, proposal file 0600. Fixtures 06m/06n/06o prove a
     permission-violating chain leaves the permit ABSENT.

C4-C-SYNTH-AUDIT-FIX3 (user audit):
  F7 permit pre-materialization legality — BEFORE the O_EXCL creation the
     materializer additionally proves: (A) proposal bytes ARE the exact
     canonical serialization (proposal_bytes == canon(json).encode()), so
     authorization_sha256 can only ever be SHA256(canonical bytes); and
     (B) the proposal exact-binds the FROZEN first candidate (session
     manifest reverified, candidate recomputed, record verified, packet
     bytes verified; proposal.candidate_packet_id == record == recomputed
     entry, same for sha256). Fixtures 06j/06k/06l prove illegal
     proposals leave the permit ABSENT. Real-domain isolation now also
     asserts the real c4c_proposals domain does not exist (pre/post).

HARD BOUNDARY (design §8): never touches the real production session, never
creates a real proposal/approval/permit, never appends outside a temp
sandbox. Real frozen artifacts (C1/C3 authorities, C3 manifest + packet
bytes) are consumed READ-ONLY.
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
REAL_PROPOSALS = ROOT / 'data/csr8_phase_c/c4c_proposals'
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


def expect_exact_gate(fn, expected):
    """F1: the TARGET operation must fail with exactly this gate substring.

    Any other failure (or no failure) is a selftest error, not a pass.
    """
    try:
        fn()
    except (RuntimeError, SystemExit) as e:
        msg = str(e) if isinstance(e, RuntimeError) else \
            f'sysexit:{e.code}'
        if expected not in msg:
            raise RuntimeError(
                f'fixture gate mismatch: expected "{expected}", got "{msg}"')
        print(f'NEGATIVE PASS: target gate hit -> {expected}')
        return msg
    raise RuntimeError('fixture did not fail as expected')


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
    """F5: CONTENT fingerprint — per-file SHA256; dirs record path/mode."""
    if not path.exists():
        return None
    items = []
    for p in sorted(path.rglob('*')):
        st = p.stat()
        rel = str(p.relative_to(path))
        if p.is_dir():
            items.append((rel, 'dir', st.st_mode))
        else:
            items.append((rel, 'file', st.st_mode, st.st_size,
                          sha(p.read_bytes())))
    return items


def assert_real_session_pristine():
    """Runtime read-only proof that the REAL production experiment has NOT
    started (0 events, no sealing/staging/authorization in real sessions)."""
    s1, s2 = REAL_PRODUCTION / 'c4-prod-0001', REAL_PRODUCTION / 'c4-prod-0002'
    if not (s1 / 'SUPERSEDED.json').exists():
        fail('real c4-prod-0001 SUPERSEDED marker missing')
    if not (s2 / 'session_manifest.json').exists() or \
            not (s2 / 'first_candidate_record.json').exists():
        fail('real c4-prod-0002 readiness session damaged')
    for sid_dir in (s1, s2):
        for bad in ('sealing', 'sealing.staging', 'authorization'):
            if (sid_dir / bad).exists():
                fail(f'real production mutated: {sid_dir.name}/{bad} exists')
    return 0


def assert_real_production_pristine():
    """F5/FIX3: synthetic-phase assertion — the real experiment has NOT
    started AND the real pre-authorization proposal domain does not exist
    (once the real proposal exists, the synthetic phase is closed)."""
    if REAL_PROPOSALS.exists():
        fail('real c4c_proposals domain exists — real proposal must NOT '
             'exist before the human FIRST_REVEAL_ONLY authorization')
    return assert_real_session_pristine()


# ---------------- three-stage authorization (design §2.2) ----------------

def make_proposal(sb, sid, entry, authz_id=None, overrides=None):
    """Stage 1: exact 9-field proposal OUTSIDE the production session.

    `overrides` (fixtures only) re-signs a hash-consistent authority chain
    around a deliberately wrong field so the FIELD gate — not the hash
    gate — is what rejects it.
    """
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
    if overrides:
        proposal.update(overrides)
    pdir = sb / 'c4c_proposals' / sid
    pdir.mkdir(parents=True, mode=0o700)
    ppath = pdir / 'first_reveal.proposal.json'
    excl_write(ppath, canon(proposal).encode())
    return ppath, canon(proposal).encode()


def approve(sb, sid, proposal_sha):
    """Stage 2: persisted approval authority — machine representation of the
    single human FIRST_REVEAL_ONLY authorization (exact-hash)."""
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


def materialize_permit(sb, sid):
    """Stage 3 (C4-C-SYNTH-AUDIT-FIX2): exact-copy permit.

    Authority comes ONLY from persisted state — the approval file and the
    proposal file on disk. Caller-supplied bytes/hashes are NOT accepted
    (stale in-memory state must never be able to create a permit).

    Frozen order: read approval -> closed-world verify + session binding ->
    read persisted proposal bytes -> 9-field closed-world/canonical verify ->
    approved hash == SHA256(persisted proposal bytes) -> ONLY THEN O_EXCL
    permit from the exact persisted bytes -> re-read and re-prove.
    A wrong approval chain has no standing to create a permit, so any
    failure here leaves first_reveal.json ABSENT.
    """
    adir = sb / 'production' / sid / 'authorization'
    apath = adir / 'first_reveal.approval.json'
    if not apath.exists():
        fail('G-C4C-AUTHZ: approval authority missing — no basis to '
             'materialize a permit')
    ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
    if not ppath.exists():
        fail('G-C4C-AUTHZ: persisted proposal missing')
    # FIX4: selector-only permission contract BEFORE anything else —
    # persisted state that violates the authority contract has no standing
    # to produce a permit.
    for dpath, what in ((adir, 'authorization'),
                        (ppath.parent, 'proposal')):
        mode = dpath.stat().st_mode & 0o777
        if mode != 0o700:
            fail(f'G-C4C-AUTHZ: {what} directory must be selector-only '
                 f'0700 (is {mode:o})')
    for fpath, what in ((apath, 'first_reveal.approval.json'),
                        (ppath, 'first_reveal.proposal.json')):
        mode = fpath.stat().st_mode & 0o777
        if mode != 0o600:
            fail(f'G-C4C-AUTHZ: {what} must be selector-only 0600 '
                 f'(is {mode:o})')
    approval = read_json(apath)
    verify_approval(approval, sid)
    proposal_bytes = ppath.read_bytes()
    proposal = json.loads(proposal_bytes)
    verify_permit(proposal, sid)   # same 9-field closed-world + canonical
    # FIX3-A: the bytes themselves must be the exact canonical serialization
    if proposal_bytes != canon(proposal).encode():
        fail('G-C4C-AUTHZ: proposal bytes are not the canonical 9-field '
             'serialization (exact canonical bytes required)')
    # FIX3-B: the proposal must bind the FROZEN first candidate (design
    # §2.1) — a legal-looking proposal for any other packet has no
    # standing to become a formal permit.
    prod = sb / 'production' / sid
    manifest = c4ab.verify_session_manifest(sid, prod)
    c4ab.verify_session_permissions(prod)
    cand = c4ab.first_candidate(c1)
    entry = c4ab.candidate_packet(c1, cand)
    record = c4ab.verify_first_candidate_record(sid, prod, manifest, entry)
    c4ab.verify_candidate_bytes(entry)
    if proposal['candidate_packet_id'] != record['candidate_packet_id'] or \
            record['candidate_packet_id'] != entry['packet_id']:
        fail('G-C4C-AUTHZ: proposal candidate_packet_id != frozen first '
             'candidate — no standing to create a permit')
    if proposal['candidate_packet_sha256'] != record['candidate_packet_sha256'] \
            or record['candidate_packet_sha256'] != entry['sha256']:
        fail('G-C4C-AUTHZ: proposal candidate_packet_sha256 != frozen first '
             'candidate — no standing to create a permit')
    proposal_sha = sha(proposal_bytes)
    if approval['approved_authorization_sha256'] != proposal_sha:
        fail('G-C4C-AUTHZ: approved_authorization_sha256 != SHA256(persisted '
             'proposal bytes) — wrong approval chain has no standing to '
             'create a permit')
    permit_path = adir / 'first_reveal.json'
    excl_write(permit_path, proposal_bytes)      # exact persisted bytes
    permit_bytes = permit_path.read_bytes()
    if permit_bytes != proposal_bytes:
        fail('G-C4C-AUTHZ: permit bytes != persisted proposal bytes')
    if sha(permit_bytes) != approval['approved_authorization_sha256']:
        fail('G-C4C-AUTHZ: SHA256(permit bytes) != approved hash')
    return permit_path


def read_json(path):
    return json.loads(Path(path).read_text())


def verify_approval(approval, sid=None):
    if set(approval) != APPROVAL_KEYS:
        fail('G-C4C-AUTHZ: approval closed-world violation (c4c-approval-v1)')
    if (approval['approval_version'] != APPROVAL_VERSION
            or approval['scope'] != 'FIRST_REVEAL_ONLY'
            or approval['approved'] is not True):
        fail('G-C4C-AUTHZ: approval field drift')
    if sid is not None and approval['session_id'] != sid:
        fail('G-C4C-AUTHZ: approval session binding violation')


def verify_permit(permit, sid):
    if set(permit) != PERMIT_KEYS:
        fail('G-C4C-AUTHZ: permit closed-world violation (c4c-auth-v1)')
    if (permit['authorization_version'] != AUTHZ_VERSION
            or permit['scope'] != 'FIRST_REVEAL_ONLY'
            or permit['authorized'] is not True):
        fail('G-C4C-AUTHZ: permit field drift (version/scope/authorized)')
    if permit['session_id'] != sid:
        fail('G-C4C-AUTHZ: permit session binding violation')
    if permit['c3_manifest_commitment'] != c4ab.C3_COMMITMENT:
        fail('G-C4C-AUTHZ: permit C3 manifest commitment binding violation')
    try:
        parsed = time.strptime(permit['created_at'], '%Y-%m-%dT%H:%M:%SZ')
        if time.strftime('%Y-%m-%dT%H:%M:%SZ', parsed) != permit['created_at']:
            fail('G-C4C-AUTHZ: permit created_at not canonical '
                 '(round-trip mismatch)')
    except (ValueError, TypeError):
        fail('G-C4C-AUTHZ: permit created_at not canonical UTC timestamp')


def verify_authorization_chain(sb, sid, entry=None):
    """Steps 0a/0b + step 4 binding — exact-byte authority chain.

    Check order is deliberate so each audit fixture hits its OWN gate:
      files/permissions -> approval closed-world+session -> permit
      closed-world+fields+canonical time -> bytes equality (reconstruction)
      -> approved == object hash -> permit == record -> permit == entry
      -> C3 packet bytes.
    """
    prod = sb / 'production' / sid
    adir = prod / 'authorization'
    for name in ('first_reveal.approval.json', 'first_reveal.json'):
        p = adir / name
        if not p.exists() or (p.stat().st_mode & 0o777) != 0o600:
            fail(f'G-C4C-AUTHZ: {name} missing or not selector-only 0600')
    fsync_file(adir / 'first_reveal.json')       # (0a) re-prove durability
    fsync_dir(adir)
    approval = read_json(adir / 'first_reveal.approval.json')
    verify_approval(approval, sid)
    proposal_path = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
    if not proposal_path.exists():
        fail('G-C4C-AUTHZ: external proposal missing')
    proposal_bytes = proposal_path.read_bytes()
    permit_bytes = (adir / 'first_reveal.json').read_bytes()
    permit = json.loads(permit_bytes)
    verify_permit(permit, sid)
    approved_sha = approval['approved_authorization_sha256']
    # Discriminating order: proposal-drift vs permit-reconstruction vs
    # forged authority each hit their OWN gate message.
    if approved_sha == sha(permit_bytes) and approved_sha != sha(proposal_bytes):
        fail('G-C4C-AUTHZ: approved_authorization_sha256 != SHA256(exact '
             'proposal bytes) — proposal drifted after approval')
    if permit_bytes != proposal_bytes:
        fail('G-C4C-AUTHZ: permit bytes != proposal bytes '
             '(reconstruction forbidden)')
    if approved_sha != sha(permit_bytes) or approved_sha != sha(proposal_bytes):
        fail('G-C4C-AUTHZ: approval authority hash != SHA256(exact '
             'proposal/permit bytes)')
    record = read_json(prod / 'first_candidate_record.json')
    if permit['candidate_packet_id'] != record['candidate_packet_id']:
        fail('G-C4C-AUTHZ: permit candidate_packet_id binding violation '
             '(record)')
    if permit['candidate_packet_sha256'] != record['candidate_packet_sha256']:
        fail('G-C4C-AUTHZ: permit candidate_packet_sha256 binding violation '
             '(record)')
    if entry is not None:
        if permit['candidate_packet_id'] != entry['packet_id']:
            fail('G-C4C-AUTHZ: permit candidate_packet_id binding violation '
                 '(recomputed frozen candidate)')
        if permit['candidate_packet_sha256'] != entry['sha256']:
            fail('G-C4C-AUTHZ: permit candidate_packet_sha256 binding '
                 'violation (recomputed frozen candidate)')
        c4ab.verify_candidate_bytes(entry)      # G-C4C-BYTES (real C3 bytes)
    return permit, sha(permit_bytes)


# ---------------- chain-derived consumption (design §2.4, F3) ----------------

def derive_consumption(sb, sid):
    """consumed ⇔ persisted replay proves a valid REVEAL bound to THIS
    authorization. `sealing exists` alone proves NOTHING."""
    prod = sb / 'production' / sid
    if not (prod / 'sealing').exists():
        return 'UNUSED'
    try:
        permit_bytes = (prod / 'authorization' / 'first_reveal.json'
                        ).read_bytes()
        permit_sha = sha(permit_bytes)
        sl = production_verify(prod)
        if len(sl.events) != 1 or sl.events[0]['event_type'] != c2.REVEAL:
            return 'UNRESOLVABLE'
        if sl.events[0]['payload'].get('authorization_sha256') != permit_sha:
            return 'FOREIGN'
        semantic_replay(sb, sid)          # full persisted proof, not dir stat
        return 'CONSUMED'
    except (RuntimeError, SystemExit):
        return 'UNRESOLVABLE'


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
    # (4) authorization exact binding incl. packet bytes (G-C4C-BYTES);
    # record-vs-recomputed (G-C4-NEXT) is proven BEFORE permit-vs-recomputed
    # so each audit fixture hits its own gate.
    permit, permit_sha = verify_authorization_chain(sb, sid)
    c4ab.verify_first_candidate_record(sid, prod, manifest, entry)
    verify_authorization_chain(sb, sid, entry)
    stop('after_binding')
    # (5) chain-derived unusedness (F3: replay-derived, never dir-existence)
    state = derive_consumption(sb, sid)
    if state == 'CONSUMED':
        fail('G-C4C-AUTHZ: authorization already consumed (chain-derived: '
             'production replay + semantic replay prove a valid REVEAL '
             'bound to this authorization)')
    if state == 'UNRESOLVABLE':
        fail('G-C4C-AUTHZ: production sealing present but chain/semantic '
             'replay FAIL-CLOSED — HALT/forensic, retry forbidden')
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
    try:
        n = sl.verify()
    except SystemExit:
        fail('G-C4C-STAGED-REPLAY: staged C2 chain replay FAIL-CLOSED '
             '(root cause printed above)')
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
    try:
        sl.verify()
    except SystemExit:
        fail('G-C4C-PROD-REPLAY: production C2 chain replay FAIL-CLOSED '
             '(root cause printed above)')
    return sl


def semantic_replay(sb, sid):
    """§6.1 (F4 closure): re-prove the WHOLE chain from persisted state —
    approval authority -> permit bytes -> record -> recomputed candidate ->
    C3 manifest -> C3 packet bytes -> event payload -> C2 head."""
    prod = sb / 'production' / sid
    approval = read_json(prod / 'authorization' /
                         'first_reveal.approval.json')
    verify_approval(approval, sid)
    permit_bytes = (prod / 'authorization' / 'first_reveal.json').read_bytes()
    permit = json.loads(permit_bytes)
    verify_permit(permit, sid)
    if sha(permit_bytes) != approval['approved_authorization_sha256']:
        fail('G-C4C-PROD-REPLAY: permit hash != approved hash')
    proposal_path = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
    if permit_bytes != proposal_path.read_bytes():
        fail('G-C4C-PROD-REPLAY: permit bytes != proposal bytes '
             '(reconstruction forbidden)')
    cand = c4ab.first_candidate(c1)
    entry = c4ab.candidate_packet(c1, cand)
    manifest = c4ab.verify_session_manifest(sid, prod)
    c4ab.verify_session_permissions(prod)
    record = c4ab.verify_first_candidate_record(sid, prod, manifest, entry)
    if permit['candidate_packet_id'] != record['candidate_packet_id']:
        fail('G-C4C-PROD-REPLAY: permit packet_id != record')
    if record['candidate_packet_id'] != entry['packet_id']:
        fail('G-C4C-PROD-REPLAY: record packet_id != recomputed candidate')
    if permit['candidate_packet_sha256'] != record['candidate_packet_sha256']:
        fail('G-C4C-PROD-REPLAY: permit packet sha256 != record')
    if record['candidate_packet_sha256'] != entry['sha256']:
        fail('G-C4C-PROD-REPLAY: record packet sha256 != recomputed entry')
    frozen_manifest = c4ab.load_c3_manifest()
    if sha(canon(frozen_manifest).encode()) != c4ab.C3_COMMITMENT:
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
    if p['packet_sha256'] != entry['sha256']:
        fail('G-C4C-PROD-REPLAY: event packet_sha256 != C3 entry sha256')
    if p['candidate_packet_sha256'] != entry['sha256']:
        fail('G-C4C-PROD-REPLAY: event candidate_packet_sha256 != C3 entry '
             'sha256')
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


# ---------------- boundary gates (HARD STOP, design §7-16..19) -------------

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
    state = derive_consumption(sb, sid)
    if state == 'CONSUMED':
        final_invariant(sb, sid)
        return {'state': 'FIRST_REVEAL_OPEN', 'consumed': True,
                'retry': False, 'action': 'none — authorization consumed'}
    if state in ('UNRESOLVABLE', 'FOREIGN'):
        return {'state': 'HALT_FORENSIC', 'consumed': None, 'retry': False,
                'action': 'HALT / forensic audit; retry forbidden'}
    staging = prod / 'sealing.staging'
    if staging.exists():
        shutil.rmtree(staging)
        return {'state': 'INITIALIZED_NO_REVEAL', 'consumed': False,
                'retry': True,
                'action': 'staging discarded; controlled retry allowed'}
    return {'state': 'INITIALIZED_NO_REVEAL', 'consumed': False,
            'retry': True, 'action': 'nothing to recover; retry allowed'}


# ---------------- sandbox construction ----------------

def build_sandbox(td, sid='synthetic-01', proposal_overrides=None):
    sb = Path(td)
    c4ab.c4a_init(sid, sb / 'production')          # synthetic C4-A session
    cand = c4ab.first_candidate(c1)
    entry = c4ab.candidate_packet(c1, cand)
    ppath, pbytes = make_proposal(sb, sid, entry,
                                  overrides=proposal_overrides)
    approve(sb, sid, sha(pbytes))
    materialize_permit(sb, sid)     # authority from persisted state only
    return sb, sid, entry


def build_sandbox_pre_permit(td, sid='synthetic-01'):
    """Sandbox stopped AFTER approval but BEFORE permit materialization —
    for fixtures proving a wrong approval chain / illegal proposal cannot
    create a permit."""
    sb = Path(td)
    c4ab.c4a_init(sid, sb / 'production')
    cand = c4ab.first_candidate(c1)
    entry = c4ab.candidate_packet(c1, cand)
    ppath, pbytes = make_proposal(sb, sid, entry)
    approve(sb, sid, sha(pbytes))
    return sb, sid, entry


def run_with_crash(sb, sid, stop):
    try:
        run_transaction(sb, sid, stop_after=stop)
    except CrashSim:
        return
    raise RuntimeError(f'crash simulation did not stop at {stop}')


# ---------------- fixtures (F1/F2: prepare must pass, target must hit) ----

def fixture(name, gate, prepare_and_target):
    """Run one fixture. PREPARE failures propagate (selftest FAIL); only the
    TARGET's exact gate failure counts as NEGATIVE PASS."""
    td = tempfile.mkdtemp(prefix='c4c-' + name + '-')
    try:
        prepare_and_target(td)
    finally:
        shutil.rmtree(td, ignore_errors=True)
    print(f'FIXTURE PASS: {name} (gate: {gate})')
    return {'name': name, 'gate': gate}


def fixtures():
    fx = []

    def add(name, gate, fn):
        fx.append(fixture(name, gate, fn))

    # 1 authorization missing
    def f01(td):
        sb, sid, entry = build_sandbox(td)
        os.unlink(sb / 'production' / sid / 'authorization' /
                  'first_reveal.json')
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'missing or not selector-only 0600')
    add('01-authz-missing', 'G-C4C-AUTHZ', f01)

    # 2 permit closed-world (extra field)
    def f02(td):
        sb, sid, entry = build_sandbox(td)
        adir = sb / 'production' / sid / 'authorization'
        permit = read_json(adir / 'first_reveal.json')
        permit['extra_field'] = 'x'
        (adir / 'first_reveal.json').write_text(canon(permit))
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'permit closed-world violation')
    add('02-permit-schema', 'G-C4C-AUTHZ', f02)

    # 3-6: TEST-SIDE re-signed authority (proposal+approval+permit all
    # hash-consistent) with one WRONG field — simulates a corrupt process
    # having persisted a legally-signed wrong chain. Since FIX2 the
    # production materialize path refuses such proposals outright; the
    # transaction PREFLIGHT must reject the on-disk chain at the FIELD gate.
    def rewrite_authority(sb, sid, overrides):
        ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        proposal = read_json(ppath)
        proposal.update(overrides)
        pbytes = canon(proposal).encode()
        ppath.write_bytes(pbytes)
        adir = sb / 'production' / sid / 'authorization'
        approval = {
            'approval_version': APPROVAL_VERSION,
            'scope': 'FIRST_REVEAL_ONLY',
            'session_id': sid,
            'approved_authorization_sha256': sha(pbytes),
            'approved': True,
        }
        (adir / 'first_reveal.approval.json').write_text(canon(approval))
        (adir / 'first_reveal.json').write_bytes(pbytes)
        for name in ('first_reveal.approval.json', 'first_reveal.json'):
            os.chmod(adir / name, 0o600)

    def wrong_field_fixture(name, overrides, expected):
        def fn(td):
            sb, sid, entry = build_sandbox(td)
            rewrite_authority(sb, sid, overrides)
            expect_exact_gate(lambda: run_transaction(sb, sid), expected)
        add(name, 'G-C4C-AUTHZ', fn)

    wrong_field_fixture('03-wrong-session', {'session_id': 'other-session'},
                        'permit session binding violation')
    wrong_field_fixture('04-wrong-c3',
                        {'c3_manifest_commitment': '0' * 64},
                        'permit C3 manifest commitment binding violation')
    wrong_field_fixture('05-wrong-packet-id',
                        {'candidate_packet_id': '0' * 64},
                        'permit candidate_packet_id binding violation (record)')
    wrong_field_fixture('06-wrong-packet-sha',
                        {'candidate_packet_sha256': '0' * 64},
                        'permit candidate_packet_sha256 binding violation '
                        '(record)')
    wrong_field_fixture(
        '06f2-noncanonical-created-at', {'created_at': '2026-9-1T1:2:3Z'},
        'permit created_at not canonical (round-trip mismatch)')

    # 6b wholesale permit replacement (legal schema, different id/time)
    def f06b(td):
        sb, sid, entry = build_sandbox(td)
        adir = sb / 'production' / sid / 'authorization'
        permit = read_json(adir / 'first_reveal.json')
        permit['authorization_id'] = uuid.uuid4().hex
        permit['created_at'] = '2030-01-01T00:00:00Z'
        (adir / 'first_reveal.json').write_text(canon(permit))
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'permit bytes != proposal bytes')
    add('06b-permit-replaced', 'G-C4C-AUTHZ', f06b)

    # 6c duplicate permit path (immutable object cannot be recreated)
    def f06c(td):
        sb, sid, entry = build_sandbox(td)
        adir = sb / 'production' / sid / 'authorization'
        expect_exact_gate(
            lambda: excl_write(adir / 'first_reveal.json',
                               (adir / 'first_reveal.json').read_bytes()),
            'create-exclusive violated')
    add('06c-duplicate-permit-path', 'G-C4C-AUTHZ', f06c)

    # 6d proposal bytes rewritten after approval
    def f06d(td):
        sb, sid, entry = build_sandbox(td)
        ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        proposal = read_json(ppath)
        proposal['created_at'] = '2031-01-01T00:00:00Z'
        ppath.write_text(canon(proposal))
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'approved_authorization_sha256 != SHA256(exact '
                          'proposal bytes)')
    add('06d-proposal-rewritten', 'G-C4C-AUTHZ', f06d)

    # 6e approval authority forged (approval hash != object hash)
    def f06e(td):
        sb, sid, entry = build_sandbox(td)
        apath = (sb / 'production' / sid / 'authorization' /
                 'first_reveal.approval.json')
        approval = read_json(apath)
        approval['approved_authorization_sha256'] = '1' * 64
        apath.write_text(canon(approval))
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'approval authority hash != SHA256(exact '
                          'proposal/permit bytes)')
    add('06e-approval-permit-mismatch', 'G-C4C-AUTHZ', f06e)

    # 6f permit bytes != proposal bytes (semantically identical, rebuilt)
    def f06f(td):
        sb, sid, entry = build_sandbox(td)
        adir = sb / 'production' / sid / 'authorization'
        permit = read_json(adir / 'first_reveal.json')
        permit_bytes = json.dumps(permit, ensure_ascii=False, sort_keys=True,
                                  indent=1).encode()
        (adir / 'first_reveal.json').write_bytes(permit_bytes)
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'permit bytes != proposal bytes')
    add('06f-permit-reconstructed', 'G-C4C-AUTHZ', f06f)

    # FIX2/FIX3 layer: a wrong approval chain or an illegal proposal has NO
    # STANDING to create a permit. These prove failure happens BEFORE permit
    # creation (permit ABSENT).

    def no_permit_fixture(name, gate_msg, forge=None, gate='G-C4C-AUTHZ'):
        def fn(td):
            sb, sid, entry = build_sandbox_pre_permit(td)
            if forge:
                forge(sb, sid)
            expect_exact_gate(lambda: materialize_permit(sb, sid), gate_msg)
            permit_path = (sb / 'production' / sid / 'authorization' /
                           'first_reveal.json')
            if permit_path.exists():
                raise RuntimeError(f'{name}: permit was created despite '
                                   'invalid approval chain / illegal proposal')
            print(f'NO-PERMIT PROOF: {name} -> first_reveal.json absent')
        add(name, gate, fn)

    def reapprove(sb, sid, proposal_bytes):
        apath = (sb / 'production' / sid / 'authorization' /
                 'first_reveal.approval.json')
        approval = read_json(apath)
        approval['approved_authorization_sha256'] = sha(proposal_bytes)
        apath.write_text(canon(approval))
        os.chmod(apath, 0o600)

    def rewrite_proposal(sb, sid, proposal):
        ppath = sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        pbytes = canon(proposal).encode()
        ppath.write_bytes(pbytes)
        reapprove(sb, sid, pbytes)
        return pbytes

    def forge_wrong_approval(sb, sid):
        apath = (sb / 'production' / sid / 'authorization' /
                 'first_reveal.approval.json')
        approval = read_json(apath)
        approval['approved_authorization_sha256'] = '9' * 64
        apath.write_text(canon(approval))
        os.chmod(apath, 0o600)

    def forge_session_mismatch(sb, sid):
        apath = (sb / 'production' / sid / 'authorization' /
                 'first_reveal.approval.json')
        approval = read_json(apath)
        approval['session_id'] = 'other-session'
        apath.write_text(canon(approval))
        os.chmod(apath, 0o600)

    no_permit_fixture(
        '06g-wrong-approval-no-permit',
        'approved_authorization_sha256 != SHA256(persisted proposal bytes)',
        forge=forge_wrong_approval)
    no_permit_fixture(
        '06h-proposal-drift-no-permit',
        'approved_authorization_sha256 != SHA256(persisted proposal bytes)',
        forge=lambda sb, sid: (
            sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
        ).write_text(canon(dict(
            read_json(sb / 'c4c_proposals' / sid /
                      'first_reveal.proposal.json'),
            created_at='2033-01-01T00:00:00Z'))))  # approval left stale
    no_permit_fixture(
        '06i-approval-session-no-permit',
        'approval session binding violation',
        forge=forge_session_mismatch)
    no_permit_fixture(
        '06j-noncanonical-proposal-bytes-no-permit',
        'not the canonical 9-field serialization',
        forge=lambda sb, sid: (lambda ppath: (
            ppath.write_bytes(json.dumps(
                read_json(ppath), ensure_ascii=False, sort_keys=True,
                indent=1).encode()),
            reapprove(sb, sid, ppath.read_bytes()),
        ))(sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'))
    no_permit_fixture(
        '06k-wrong-candidate-id-no-permit',
        'proposal candidate_packet_id != frozen first candidate',
        forge=lambda sb, sid: rewrite_proposal(
            sb, sid, dict(read_json(
                sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'),
                candidate_packet_id='d' * 64)))
    no_permit_fixture(
        '06l-wrong-candidate-sha-no-permit',
        'proposal candidate_packet_sha256 != frozen first candidate',
        forge=lambda sb, sid: rewrite_proposal(
            sb, sid, dict(read_json(
                sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'),
                candidate_packet_sha256='e' * 64)))
    no_permit_fixture(
        '06m-approval-not-0600-no-permit',
        'first_reveal.approval.json must be selector-only 0600',
        forge=lambda sb, sid: os.chmod(
            sb / 'production' / sid / 'authorization' /
            'first_reveal.approval.json', 0o644))
    no_permit_fixture(
        '06n-proposal-not-0600-no-permit',
        'first_reveal.proposal.json must be selector-only 0600',
        forge=lambda sb, sid: os.chmod(
            sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json',
            0o644))
    no_permit_fixture(
        '06o-authz-dir-not-0700-no-permit',
        'authorization directory must be selector-only 0700',
        forge=lambda sb, sid: os.chmod(
            sb / 'production' / sid / 'authorization', 0o755))

    # 7 authorization reuse after success — CHAIN-DERIVED consumption
    def f07(td):
        sb, sid, entry = build_sandbox(td)
        run_transaction(sb, sid)          # PREPARE must succeed
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'authorization already consumed (chain-derived')
    add('07-authz-reuse', 'G-C4C-AUTHZ', f07)

    # 8 record tamper with SELF-CONSISTENT session manifest -> G-C4-NEXT
    # (wrong-sha authority chain is written TEST-SIDE since FIX3: the
    # production materializer refuses it outright)
    def f08(td):
        sb, sid, entry = build_sandbox(td)
        rewrite_authority(sb, sid,
                          {'candidate_packet_sha256': '2' * 64})
        prod = sb / 'production' / sid
        rec = read_json(prod / 'first_candidate_record.json')
        rec['candidate_packet_sha256'] = '2' * 64
        (prod / 'first_candidate_record.json').write_text(canon(rec))
        manifest = read_json(prod / 'session_manifest.json')
        manifest['first_candidate_commitment'] = sha(canon(rec).encode())
        (prod / 'session_manifest.json').write_text(canon(manifest))
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'G-C4-NEXT: candidate record packet sha256 drift')
    add('08-record-tamper-self-consistent', 'G-C4-NEXT', f08)

    # 9 real G-C4C-BYTES: TEMP COPY of C3 state, mutate the packet bytes,
    # call the parameterized production helper.
    def f09(td):
        sb, sid, entry = build_sandbox(td)
        tmpc3 = Path(td) / 'c3_state_copy'
        shutil.copytree(C3_STATE, tmpc3)
        pkt = tmpc3 / 'packets' / f"{entry['packet_id']}.json"
        data = bytearray(pkt.read_bytes())
        data[len(data) // 2] ^= 0x01
        pkt.write_bytes(bytes(data))
        expect_exact_gate(lambda: c4ab.verify_candidate_bytes(
            entry, state_dir=tmpc3),
            'G-C4-BYTES: frozen packet bytes hash mismatch')
    add('09-c3-packet-bytes-tamper',
        'G-C4C-BYTES delegated -> C4-B verify_candidate_bytes '
        '(G-C4-BYTES)', f09)

    # 9b staged archive bytes tamper -> staged replay exact-byte binding
    def f09b(td):
        sb, sid, entry = build_sandbox(td)
        run_with_crash(sb, sid, 'after_append')
        pkt = (sb / 'production' / sid / 'sealing.staging' / 'bytes' /
               'reveal_packet' / '0.bin')
        data = bytearray(pkt.read_bytes())
        data[len(data) // 2] ^= 0x01
        pkt.write_bytes(bytes(data))
        expect_exact_gate(
            lambda: staged_verify(sb / 'production' / sid / 'sealing.staging'),
            'G-C4C-STAGED-REPLAY')
    add('09b-staged-bytes-tamper', 'G-C4C-STAGED-REPLAY', f09b)

    # 10 foreign committed REVEAL + unused authorization -> PUBLISH target
    def f10(td):
        sb, sid, entry = build_sandbox(td)
        run_transaction(sb, sid)                       # commit REVEAL(A)
        proposal_b = {
            'authorization_version': AUTHZ_VERSION,
            'scope': 'FIRST_REVEAL_ONLY',
            'authorization_id': 'b' * 32,
            'session_id': sid,
            'c3_manifest_commitment': c4ab.C3_COMMITMENT,
            'candidate_packet_id': entry['packet_id'],
            'candidate_packet_sha256': entry['sha256'],
            'authorized': True,
            'created_at': '2032-01-01T00:00:00Z',
        }
        pbytes_b = canon(proposal_b).encode()
        (sb / 'c4c_proposals' / sid / 'first_reveal.proposal.json'
         ).write_bytes(pbytes_b)
        adir = sb / 'production' / sid / 'authorization'
        approval_b = {
            'approval_version': APPROVAL_VERSION, 'scope': 'FIRST_REVEAL_ONLY',
            'session_id': sid,
            'approved_authorization_sha256': sha(pbytes_b), 'approved': True}
        (adir / 'first_reveal.approval.json').write_text(canon(approval_b))
        (adir / 'first_reveal.json').write_bytes(pbytes_b)
        for name in ('first_reveal.approval.json', 'first_reveal.json'):
            os.chmod(adir / name, 0o600)
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'G-C4C-PUBLISH: production sealing target already '
                          'exists')
    add('10-sealing-target-foreign-event', 'G-C4C-PUBLISH', f10)

    # 10b unresolvable sealing (empty dir) -> HALT/forensic, retry forbidden
    def f10b(td):
        sb, sid, entry = build_sandbox(td)
        (sb / 'production' / sid / 'sealing').mkdir()
        expect_exact_gate(lambda: run_transaction(sb, sid),
                          'HALT/forensic, retry forbidden')
    add('10b-sealing-unresolvable', 'G-C4C-AUTHZ', f10b)

    # 11 staging not same filesystem (tmpfs vs workspace fs)
    def f11(td):
        sb, sid, entry = build_sandbox(td)
        shm = Path('/dev/shm') / ('c4c-crossfs-' + uuid.uuid4().hex)
        try:
            expect_exact_gate(
                lambda: run_transaction(sb, sid, staging_override=shm),
                'G-C4C-PUBLISH: staging not on the same filesystem')
        finally:
            shutil.rmtree(shm, ignore_errors=True)
    add('11-staging-cross-fs', 'G-C4C-PUBLISH', f11)

    # 12 target exists at rename time (no-replace must refuse)
    def f12(td):
        sb, sid, entry = build_sandbox(td)
        prod = sb / 'production' / sid
        run_with_crash(sb, sid, 'after_fsync')
        (prod / 'sealing').mkdir()          # target appears before rename
        expect_exact_gate(
            lambda: rename_noreplace(prod / 'sealing.staging',
                                     prod / 'sealing'),
            'G-C4C-PUBLISH: no-replace rename failed')
    add('12-rename-target-exists', 'G-C4C-PUBLISH', f12)

    # 13 staged log tamper (no rehash)
    def f13(td):
        sb, sid, entry = build_sandbox(td)
        run_with_crash(sb, sid, 'after_append')
        logp = (sb / 'production' / sid / 'sealing.staging' /
                'sealing_log.jsonl')
        evs = c2.read_events(logp)
        evs[0]['payload']['T'] = '2099-12-31'
        c2.write_events(logp, evs)
        expect_exact_gate(
            lambda: staged_verify(sb / 'production' / sid / 'sealing.staging'),
            'G-C4C-STAGED-REPLAY')
    add('13-staged-log-tamper', 'G-C4C-STAGED-REPLAY', f13)

    # 14 staged head missing
    def f14(td):
        sb, sid, entry = build_sandbox(td)
        run_with_crash(sb, sid, 'after_append')
        (sb / 'production' / sid / 'sealing.staging' /
         'sealing_log.head.json').unlink()
        expect_exact_gate(
            lambda: staged_verify(sb / 'production' / sid / 'sealing.staging'),
            'G-C4C-STAGED-REPLAY')
    add('14-staged-head-missing', 'G-C4C-STAGED-REPLAY', f14)

    # 15 published log tamper -> production replay FAIL
    def f15(td):
        sb, sid, entry = build_sandbox(td)
        run_transaction(sb, sid)
        logp = (sb / 'production' / sid / 'sealing' / 'sealing_log.jsonl')
        evs = c2.read_events(logp)
        evs[0]['payload']['session_id'] = 'tampered'
        c2.write_events(logp, evs)
        expect_exact_gate(lambda: production_verify(sb / 'production' / sid),
                          'G-C4C-PROD-REPLAY')
    add('15-published-log-tamper', 'G-C4C-PROD-REPLAY', f15)

    # 15b four-stage proof: C2 PASS, C2 PASS, semantic FAIL, fixture PASS
    def f15b(td):
        sb, sid, entry = build_sandbox(td)
        prod = sb / 'production' / sid
        staging = prod / 'sealing.staging'
        run_with_crash(sb, sid, 'after_staged_replay')
        logp = staging / 'sealing_log.jsonl'
        evs = c2.read_events(logp)
        evs[0]['payload']['authorization_sha256'] = 'e' * 64
        c2.cascade_rehash(evs, 0)           # C2-legal rehash
        c2.write_events(logp, evs)
        c2.sync_head(staging / 'sealing_log.head.json', evs)
        print('15b stage-1: staged C2 replay PASS (cascade-rehashed chain '
              'accepted by frozen C2)')
        staged_verify(staging)                       # must PASS
        fsync_closure(staging)
        rename_noreplace(staging, prod / 'sealing')  # must PASS
        fsync_dir(prod)
        print('15b stage-2: published C2 replay PASS')
        production_verify(prod)                      # must PASS
        print('15b stage-3: C4-C semantic replay FAIL (expected)')
        expect_exact_gate(lambda: semantic_replay(sb, sid),
                          'G-C4C-PROD-REPLAY: event authorization_sha256 != '
                          'permit hash')
        print('15b stage-4: fixture PASS (semantic layer is the only gate '
              'that rejects)')
    add('15b-semantic-binding-broken', 'G-C4C-PROD-REPLAY', f15b)

    # 16-19 boundary gates after a successful transaction
    for name, attempt in (
            ('16-second-reveal', attempt_second_reveal),
            ('17-attempt-seal', attempt_seal),
            ('18-attempt-annotation', attempt_annotation),
            ('19-attempt-outcome', attempt_outcome)):
        def boundary(td, attempt=attempt):
            sb, sid, entry = build_sandbox(td)
            run_transaction(sb, sid)          # PREPARE must succeed
            expect_exact_gate(lambda: attempt(sb, sid), 'G-C4C-BOUNDARY')
        add(name, 'G-C4C-BOUNDARY', boundary)

    return fx


# ---------------- crash / recovery matrix simulation ----------------

def crash_matrix():
    outcomes = []

    def sim(name, stop, mutate=None, expect_state=None, expect_consumed=None,
            expect_retry=None):
        td = tempfile.mkdtemp(prefix='c4c-crash-' + name + '-')
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
    td = tempfile.mkdtemp(prefix='c4c-crash-g-forensic-')
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
    td = tempfile.mkdtemp(prefix='c4c-crash-h-full-')
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


# ---------------- REAL proposal preparation (design §9 steps 3-4) ----------

REAL_SESSION = 'c4-prod-0002'


def cmd_real_proposal():
    """Design §9 steps 3–4 ONLY (authorized after C4-C SYNTHETIC FINAL
    FROZEN @ aa04403): construct the exact canonical 9-field proposal for
    the REAL readiness session, persist it in the pre-authorization
    selector-only domain, and expose ONLY proposal_sha256.

    Creates NO approval authority, NO permit, NO sealing domain; NEVER
    calls the production C2 append. HARD STOP follows — the next state
    change requires the single human FIRST_REVEAL_ONLY authorization of
    the exact hash.
    """
    assert_real_session_pristine()
    prod = REAL_PRODUCTION / REAL_SESSION
    if not prod.exists():
        fail('real readiness session c4-prod-0002 missing')
    # reverify C4-A/B readiness + all frozen authorities (read-only)
    c4ab.c4b_readiness(REAL_SESSION)
    cand = c4ab.first_candidate(c1)
    entry = c4ab.candidate_packet(c1, cand)
    # construct the exact canonical proposal (id/created_at fixed HERE)
    proposal = {
        'authorization_version': AUTHZ_VERSION,
        'scope': 'FIRST_REVEAL_ONLY',
        'authorization_id': uuid.uuid4().hex,
        'session_id': REAL_SESSION,
        'c3_manifest_commitment': c4ab.C3_COMMITMENT,
        'candidate_packet_id': entry['packet_id'],
        'candidate_packet_sha256': entry['sha256'],
        'authorized': True,
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    proposal_bytes = canon(proposal).encode()
    # persist ONLY in the pre-authorization proposal domain: 0600 file,
    # 0700 dirs, fsync closure; O_EXCL refuses to recreate an existing
    # proposal — a persisted one is NEVER regenerated, only re-proven.
    REAL_PROPOSALS.mkdir(parents=True, exist_ok=True, mode=0o700)
    if REAL_PROPOSALS.stat().st_mode & 0o777 != 0o700:
        fail('G-C4C-AUTHZ: proposal domain root not selector-only 0700')
    pdir = REAL_PROPOSALS / REAL_SESSION
    pdir.mkdir(mode=0o700, exist_ok=True)
    ppath = pdir / 'first_reveal.proposal.json'
    if ppath.exists():
        print('C4-C REAL PROPOSAL: persisted object detected — verifying '
              'persisted state (no regeneration)')
    else:
        excl_write(ppath, proposal_bytes)
        fsync_dir(REAL_PROPOSALS)
    # persisted-state self-proof: exact canonical bytes + closed-world +
    # frozen-candidate binding + selector-only contract — all derived from
    # disk, identical rules to the synthetic materializer.
    persisted = ppath.read_bytes()
    persisted_obj = json.loads(persisted)
    verify_permit(persisted_obj, REAL_SESSION)
    if persisted != canon(persisted_obj).encode():
        fail('G-C4C-AUTHZ: persisted proposal is not the exact canonical '
             'bytes')
    if persisted_obj['candidate_packet_id'] != entry['packet_id'] or \
            persisted_obj['candidate_packet_sha256'] != entry['sha256']:
        fail('G-C4C-AUTHZ: persisted proposal does not bind the frozen '
             'first candidate')
    if ppath.stat().st_mode & 0o777 != 0o600:
        fail('G-C4C-AUTHZ: persisted proposal not selector-only 0600')
    if pdir.stat().st_mode & 0o777 != 0o700 or \
            REAL_PROPOSALS.stat().st_mode & 0o777 != 0o700:
        fail('G-C4C-AUTHZ: proposal domain not selector-only 0700')
    proposal_sha = sha(persisted)
    print('C4-C REAL PROPOSAL PREPARED (pre-authorization domain only)')
    print(f'  FIRST_REVEAL proposal hash = {proposal_sha}')
    print('  authorization_id / created_at fixed at proposal time; '
          'packet identity NOT exposed')
    print('  proposal exists != authorization granted')
    print('  HARD STOP: awaiting the single human FIRST_REVEAL_ONLY '
          'authorization of this exact hash')
    print('  no approval authority / permit / sealing / REVEAL created; '
          'PRODUCTION_EVENT_COUNT=0; experiment NOT STARTED')
    return proposal_sha


def cmd_synthetic():
    assert_real_production_pristine()               # F5 pre-run assertion
    before = tree_fingerprint(REAL_PRODUCTION)
    before_proposals = tree_fingerprint(REAL_PROPOSALS)
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
    if tree_fingerprint(REAL_PROPOSALS) != before_proposals:
        fail('REAL PROPOSAL DOMAIN WAS MUTATED — fail-closed')
    runtime_events = assert_real_production_pristine()  # F5 post-run
    report = {
        'construction_mode': 'synthetic/staging only; real session untouched',
        'audit_fix': 'C4-C-SYNTH-AUDIT-FIX4 (F1-F8)',
        'real_proposal_domain_absent': True,
        'transaction_gates': ['G-C4C-AUTHZ', 'G-C4-NEXT', 'G-C4C-BYTES',
                              'G-C4C-STAGED-REPLAY', 'G-C4C-PUBLISH',
                              'G-C4C-PROD-REPLAY', 'G-C4C-BOUNDARY'],
        'fixtures_passed': len(fixture_results),
        'fixtures': fixture_results,
        'crash_recovery_passed': len(crash_results),
        'crash_recovery_names': crash_results,
        'real_production_untouched': True,
        'real_production_fingerprint': 'per-file SHA256 content fingerprint',
        'production_event_count': runtime_events,
        'experiment_started': False,
    }
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    (SYNTH_DIR / 'c4c_synthetic_report.json').write_text(canon(report))
    print(f'C4-C SYNTHETIC PASS (AUDIT-FIX4): {len(fixture_results)} '
          f'target-isolated fixtures + {len(crash_results)} recovery '
          f'scenarios; real production + proposal domain content-fingerprint '
          f'unchanged, runtime-asserted {runtime_events} production events')


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ('synthetic', 'real-proposal'):
        print('usage: csr8_phase_c_first_reveal.py synthetic | real-proposal')
        sys.exit(2)
    try:
        if sys.argv[1] == 'synthetic':
            cmd_synthetic()
        else:
            cmd_real_proposal()
    except RuntimeError:
        sys.exit(1)


if __name__ == '__main__':
    main()
