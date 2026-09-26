#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C4-A/B — Production Session Initialization & Readiness.

Implements C4 DESIGN v1.0 FINAL FROZEN @ 6fa5380 — C4-A and C4-B ONLY,
with C4-A/B-AUDIT-FIX1 (session schema exactness, C3 authority closure,
selector-only permissions, production-helper negative wiring):

    init        -> C4-A fresh production session + frozen authorities +
                   deterministic FIRST-CANDIDATE selector + immutable
                   first_candidate_record + immutable session manifest
                   (production events = 0)
    readiness   -> C4-B independent selector recompute + candidate record /
                   commitment equality + exact frozen C3 packet bytes +
                   full immutable session-manifest verification
                   (production events = 0)
    supersede   -> mark an existing zero-event session SUPERSEDED /
                   INVALID_FOR_ACTIVATION (writes a marker; no events)
    selftest    -> isolated synthetic/negative fixtures in a temp domain
                   (never touches the real production root)
    reveal-first-> HARD STOP, fail-closed. C4-C requires a separate explicit
                   FIRST_REVEAL_ONLY authorization from the user; the
                   production C2 append() path is NOT implemented here.

This script never calls the production C2 append(); production event count
remains 0 after every command.  Session artifacts are selector-only
(0700/0600).  Public summaries expose commitments/booleans only.
"""
import hashlib
import hmac
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
PC = ROOT / 'output/research/csr/08_pilot_cases/phase_c'
C1_ART = PC / 'c1_artifacts'
C3_STATE = ROOT / 'data/csr8_phase_c/c3_preflight'
C3A = PC / 'c3_preflight_artifacts'
PROD_ROOT = ROOT / 'data/csr8_phase_c/production'
PUBLIC = PC / 'c4_public'

PROVENANCE_ANCHOR = '04f54e1'
C3_COMMITMENT = ('883c9869f29d0f17316edea86e5b5e996dc11e1fca19db631cb12cd0a4cc2d0b')
C3_PACKET_SCHEMA = ('073673bb58043ac149344053a363c97f46e277dc803f3a1aa29508b8747ac676')
C1_PLAN_COMMITMENT = ('6a3051cb26cea71849838a42a17a76836a431e841a6f146a8f4a214bb1278a34')
C1_SALT_COMMITMENT = ('d1df23bd0c33298d34274ac9ca8a1063defe42567c9a22b2c4b8e52baf9e5ee4')
C1_PROJECTION_SHA = ('862569492fe31519ea27ec297bd11696feea836f10a2e5ada4646761815b65ba')
PRICE_FETCH_MANIFEST = ('f16b764e6a3358269eef229dde06f9ae37df8fd8a20ac6852fc39f9ceeade6b3')
PRICE_PER_STOCK_ROOT = ('783e5cd849eb486eba2aff854e418c4718ff3406e2ff9ceb5f4bb8aa7c1986d6')
PRICE_SOURCE_ID = 'baostock_unadjusted_v1'
CASE_INDEX_BLOB = 'f69fdddd8fbf734c1173e929fac30a5ca736b764'
CALENDAR_BLOB = 'f4d5190db9f4145bb5fec32449c79581d73152b9'
CALENDAR_EMBEDDED_SHA = ('87f8f959910295640ebdf89b40cedb8de03049bc88c6ad4aace3f39b249c3f80')
SELECTOR_VERSION = 'C4-FIRST-v1'
SESSION_VERSION = 'c4-v1.0'
# Frozen group axis (C1 PACKET_GENERATION_ALLOWED): exactly these four case
# groups are eligible; G5 is excluded (annotation-primary), XP excluded by
# axis.  This set is frozen by the C1 hidden plan itself and additionally
# closed by the G5/XP boolean boundary inside verify_c3_authority().
ELIGIBLE_GROUPS = ('G1_complete_bull', 'G2_breakout_fail',
                   'G3_high_collapse', 'G4_quiet_then_go')

SESSION_MANIFEST_KEYS = {
    'session_version', 'session_id', 'c1_plan_commitment',
    'c3_packet_manifest_commitment', 'c3_packet_schema_sha256',
    'first_candidate_commitment', 'price_source_commitments',
    'phase_b_input_commitments', 'initial_state', 'created_at',
}
FIRST_CANDIDATE_RECORD_KEYS = {
    'version', 'session_id', 'c3_manifest_commitment',
    'candidate_packet_id', 'candidate_packet_sha256',
}
C3_COMMITMENT_KEYS = {
    'packet_manifest_commitment', 'packet_schema_sha256', 'source_commitments',
}
C3_SOURCE_COMMITMENT_KEYS = {
    'c1_plan', 'c1_projection', 'c1_salt', 'price_fetch_manifest_sha256',
    'price_per_stock_root_sha256', 'price_source_id',
}
C3_BOOLEAN_KEYS = {
    'ALL_GATES_PASS', 'G5_BLOCKED', 'NO_PRODUCTION_REVEAL',
    'NO_PRODUCTION_SEAL', 'NO_REAL_ANNOTATION', 'XP_BLOCKED_FOR_PIT',
}


def canon(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fail(msg):
    print('FAIL-CLOSED:', msg)
    raise RuntimeError(msg)


def file_sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------------- G-C4-MANIFEST ----------------

def load_c3_manifest(state_dir=C3_STATE):
    p = state_dir / 'packet_manifest.json'
    if not p.exists():
        fail('G-C4-MANIFEST: C3 selector-only packet manifest missing')
    manifest = json.loads(p.read_text())
    if sha(canon(manifest).encode()) != C3_COMMITMENT:
        fail('G-C4-MANIFEST: C3 manifest canonical hash mismatch')
    return manifest


def verify_candidate_bytes(entry, state_dir=C3_STATE):
    packet_path = state_dir / 'packets' / f"{entry['packet_id']}.json"
    if not packet_path.exists():
        fail('G-C4-BYTES: frozen C3 packet bytes missing')
    if file_sha(packet_path) != entry['sha256']:
        fail('G-C4-BYTES: frozen packet bytes hash mismatch')
    return True


# ---------------- G-C4-AUTHORITY ----------------

def verify_c3_authority(c3a_dir=C3A):
    """C4 design §6.1: 04f54e1 = provenance anchor + artifact equality."""
    for cmd in (['git', 'cat-file', '-e', f'{PROVENANCE_ANCHOR}^{{commit}}'],
                ['git', 'merge-base', '--is-ancestor', PROVENANCE_ANCHOR,
                 'HEAD']):
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True)
        if r.returncode != 0:
            fail('G-C4-AUTHORITY: C3 provenance anchor 04f54e1 missing or '
                 'not an ancestor of HEAD')
    art = json.loads((c3a_dir / 'c3_manifest_commitment.json').read_text())
    if set(art) != C3_COMMITMENT_KEYS:
        fail('G-C4-AUTHORITY: C3 commitment artifact key set mismatch')
    if art['packet_manifest_commitment'] != C3_COMMITMENT:
        fail('G-C4-AUTHORITY: C3 manifest commitment drift')
    if art['packet_schema_sha256'] != C3_PACKET_SCHEMA:
        fail('G-C4-AUTHORITY: C3 packet schema drift')
    src = art['source_commitments']
    if set(src) != C3_SOURCE_COMMITMENT_KEYS:
        fail('G-C4-AUTHORITY: C3 source commitment key set mismatch')
    expected_src = {
        'c1_plan': C1_PLAN_COMMITMENT, 'c1_projection': C1_PROJECTION_SHA,
        'c1_salt': C1_SALT_COMMITMENT,
        'price_fetch_manifest_sha256': PRICE_FETCH_MANIFEST,
        'price_per_stock_root_sha256': PRICE_PER_STOCK_ROOT,
        'price_source_id': PRICE_SOURCE_ID,
    }
    for k, v in expected_src.items():
        if src[k] != v:
            fail(f'G-C4-AUTHORITY: C3 source commitment drift: {k}')
    boolean = json.loads((c3a_dir / 'c3_boolean_summary.json').read_text())
    if set(boolean) != C3_BOOLEAN_KEYS or not all(boolean.values()):
        fail('G-C4-AUTHORITY: C3 boolean boundary violated '
             '(ALL_GATES_PASS/G5_BLOCKED/XP_BLOCKED_FOR_PIT/'
             'NO_PRODUCTION_REVEAL/NO_PRODUCTION_SEAL/NO_REAL_ANNOTATION)')
    return True


def verify_frozen_authorities():
    """G-C4-AUTHORITY: reverify every frozen authority (C1/C3/price/B)."""
    import csr8_phase_c_packet as c1
    import csr8_phase_c_preflight as c3
    c1.verify_salt_binding()
    c1.verify_plan_binding()
    c3.verify_projection_authority()
    c3.verify_phase_b_index_authority()
    c3.verify_calendar_authority()
    c3.verify_price_authority()
    frozen = json.loads((ROOT / 'config/universe_frozen.json').read_text())
    if frozen['fetch_manifest_sha256'] != PRICE_FETCH_MANIFEST:
        fail('G-C4-AUTHORITY: price fetch manifest authority drift')
    if frozen['per_stock_root_sha256'] != PRICE_PER_STOCK_ROOT:
        fail('G-C4-AUTHORITY: price per-stock root authority drift')
    verify_c3_authority()
    return c1


# ---------------- G-C4-NEXT (FIRST-CANDIDATE SELECTOR) ----------------

def first_candidate(c1):
    """Deterministic total order (design §3.0): per case earliest T;
    first case = min((HMAC digest, opaque_case_id)) — digest collisions are
    resolved deterministically by the opaque_case_id tie-break."""
    salt = c1.load_salt()
    plan = json.loads(c1.PLAN_FILE.read_text())
    earliest = {}
    for e in plan['entries']:
        group = e['case_key'].split('|', 1)[0]
        if group not in ELIGIBLE_GROUPS:
            continue
        ocid = c1.opaque_case_id(salt, e['case_key'])
        if ocid not in earliest or e['T'] < earliest[ocid]:
            earliest[ocid] = e['T']
    if not earliest:
        fail('G-C4-NEXT: no eligible first candidate')
    keys = sorted(
        (hmac.new(salt.encode(), f'{SELECTOR_VERSION}|{ocid}'.encode(),
                  hashlib.sha256).hexdigest(), ocid)
        for ocid in earliest)
    digest, ocid = keys[0]
    return {'digest': digest, 'opaque_case_id': ocid, 'T': earliest[ocid]}


def candidate_packet(c1, cand, state_dir=C3_STATE):
    """G-C4-MANIFEST/NEXT: candidate must be an exact frozen C3 manifest entry."""
    manifest = load_c3_manifest(state_dir)
    salt = c1.load_salt()
    for entry in manifest:
        if entry['T'] != cand['T']:
            continue
        if c1.opaque_case_id(salt, entry['case_key']) == cand['opaque_case_id']:
            return entry
    fail('G-C4-NEXT: candidate not present in frozen C3 manifest')


# ---------------- G-C4-SESSION (manifest + permissions) ----------------

def verify_session_permissions(prod):
    mode = lambda p: p.stat().st_mode & 0o777
    if not prod.parent.exists():
        fail('G-C4-SESSION: production root missing')
    if mode(prod.parent) != 0o700:
        fail('G-C4-SESSION: production root must be selector-only 0700')
    if mode(prod) != 0o700:
        fail('G-C4-SESSION: session directory must be 0700')
    for name in ('first_candidate_record.json', 'session_manifest.json'):
        p = prod / name
        if not p.exists() or mode(p) != 0o600:
            fail(f'G-C4-SESSION: {name} must exist with selector-only 0600')


def verify_first_candidate_record(session_id, prod, manifest=None, entry=None):
    """FIX2 closed-world gate: the frozen canonical record schema is exact.

    Rejects any record whose key set differs from the frozen five-field
    canonical form — including records that keep all five frozen values but
    add an extra field (even when the manifest commitment was re-hashed to
    match, which the schema gate must catch on its own).
    """
    record = json.loads((prod / 'first_candidate_record.json').read_text())
    if set(record) != FIRST_CANDIDATE_RECORD_KEYS:
        fail('G-C4-NEXT: first_candidate_record key set != frozen canonical '
             'schema (closed-world violation)')
    if record['version'] != SELECTOR_VERSION:
        fail('G-C4-NEXT: candidate record version drift')
    if record['session_id'] != session_id:
        fail('G-C4-NEXT: candidate record session_id drift')
    if record['c3_manifest_commitment'] != C3_COMMITMENT:
        fail('G-C4-NEXT: candidate record C3 commitment drift')
    if entry is not None:
        if record['candidate_packet_id'] != entry['packet_id']:
            fail('G-C4-NEXT: candidate record packet_id drift')
        if record['candidate_packet_sha256'] != entry['sha256']:
            fail('G-C4-NEXT: candidate record packet sha256 drift')
    if manifest is not None:
        if manifest['first_candidate_commitment'] != sha(canon(record).encode()):
            fail('G-C4-NEXT: candidate record commitment mismatch')
    return record


def verify_session_manifest(session_id, prod):
    """F1: exact immutable session-manifest schema + frozen value binding."""
    manifest = json.loads((prod / 'session_manifest.json').read_text())
    if set(manifest) != SESSION_MANIFEST_KEYS:
        fail('G-C4-SESSION: session manifest key set != frozen c4-v1.0 schema')
    if manifest['session_version'] != SESSION_VERSION:
        fail('G-C4-SESSION: session_version drift')
    if manifest['session_id'] != session_id:
        fail('G-C4-SESSION: session_id mismatch')
    plan_art = json.loads((C1_ART / 'plan_commitment.json').read_text())
    if (manifest['c1_plan_commitment'] != C1_PLAN_COMMITMENT
            or plan_art['plan_commitment'] != manifest['c1_plan_commitment']):
        fail('G-C4-SESSION: c1_plan_commitment drift')
    if manifest['c3_packet_manifest_commitment'] != C3_COMMITMENT:
        fail('G-C4-SESSION: c3 commitment drift')
    if manifest['c3_packet_schema_sha256'] != C3_PACKET_SCHEMA:
        fail('G-C4-SESSION: c3 packet schema drift')
    price = manifest['price_source_commitments']
    if set(price) != {'source_id', 'fetch_manifest_sha256',
                      'per_stock_root_sha256'}:
        fail('G-C4-SESSION: price commitments key set mismatch')
    if (price['source_id'] != PRICE_SOURCE_ID
            or price['fetch_manifest_sha256'] != PRICE_FETCH_MANIFEST
            or price['per_stock_root_sha256'] != PRICE_PER_STOCK_ROOT):
        fail('G-C4-SESSION: price commitments drift')
    pb = manifest['phase_b_input_commitments']
    if set(pb) != {'case_index_blob', 'calendar_blob', 'calendar_embedded_sha256'}:
        fail('G-C4-SESSION: phase-b commitments key set mismatch')
    if (pb['case_index_blob'] != CASE_INDEX_BLOB
            or pb['calendar_blob'] != CALENDAR_BLOB
            or pb['calendar_embedded_sha256'] != CALENDAR_EMBEDDED_SHA):
        fail('G-C4-SESSION: phase-b commitments drift')
    if manifest['initial_state'] != 'INITIALIZED_NO_REVEAL':
        fail('G-C4-SESSION: initial_state drift')
    try:
        parsed = time.strptime(manifest['created_at'], '%Y-%m-%dT%H:%M:%SZ')
        if time.strftime('%Y-%m-%dT%H:%M:%SZ', parsed) != manifest['created_at']:
            fail('G-C4-SESSION: created_at not canonical round-trip timestamp')
    except (ValueError, TypeError):
        fail('G-C4-SESSION: created_at not canonical UTC timestamp')
    record = json.loads((prod / 'first_candidate_record.json').read_text())
    if manifest['first_candidate_commitment'] != sha(canon(record).encode()):
        fail('G-C4-SESSION: first_candidate_commitment != record hash')
    return manifest


def production_events(prod):
    """Runtime state is chain-derived: no sealing domain -> 0 events."""
    if (prod / 'SUPERSEDED.json').exists():
        fail('G-C4-SESSION: session is SUPERSEDED / INVALID_FOR_ACTIVATION')
    sealing = prod / 'sealing'
    if sealing.exists():
        fail('G-C4-SESSION: production sealing domain exists — first reveal '
             'already staged/published; C4-A/B must refuse')
    return 0


# ---------------- C4-A / C4-B ----------------

def c4a_init(session_id, prod_root=PROD_ROOT):
    if not session_id or any(ch in session_id for ch in '/\\ .'):
        fail('G-C4-SESSION: invalid session id')
    prod = prod_root / session_id
    if prod.exists():
        fail('G-C4-SESSION: production session directory already exists')
    c1 = verify_frozen_authorities()
    cand = first_candidate(c1)
    entry = candidate_packet(c1, cand)
    record = {
        'version': SELECTOR_VERSION,
        'session_id': session_id,
        'c3_manifest_commitment': C3_COMMITMENT,
        'candidate_packet_id': entry['packet_id'],
        'candidate_packet_sha256': entry['sha256'],
    }
    commitment = sha(canon(record).encode())
    manifest = {
        'session_version': SESSION_VERSION,
        'session_id': session_id,
        'c1_plan_commitment': C1_PLAN_COMMITMENT,
        'c3_packet_manifest_commitment': C3_COMMITMENT,
        'c3_packet_schema_sha256': C3_PACKET_SCHEMA,
        'first_candidate_commitment': commitment,
        'price_source_commitments': {
            'source_id': PRICE_SOURCE_ID,
            'fetch_manifest_sha256': PRICE_FETCH_MANIFEST,
            'per_stock_root_sha256': PRICE_PER_STOCK_ROOT,
        },
        'phase_b_input_commitments': {
            'case_index_blob': CASE_INDEX_BLOB,
            'calendar_blob': CALENDAR_BLOB,
            'calendar_embedded_sha256': CALENDAR_EMBEDDED_SHA,
        },
        'initial_state': 'INITIALIZED_NO_REVEAL',
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    old = os.umask(0o077)
    try:
        prod_root.mkdir(parents=True, exist_ok=True)
        prod.mkdir(mode=0o700)
        (prod / 'first_candidate_record.json').write_text(canon(record))
        (prod / 'session_manifest.json').write_text(canon(manifest))
        for name in ('first_candidate_record.json', 'session_manifest.json'):
            os.chmod(prod / name, 0o600)
    finally:
        os.umask(old)
    verify_session_manifest(session_id, prod)
    verify_session_permissions(prod)
    verify_first_candidate_record(session_id, prod, manifest=manifest,
                                  entry=entry)
    print('C4-A INIT PASS  session=%s' % session_id)
    print('  G-C4-SESSION fresh, selector-only 0700/0600, exact c4-v1.0 schema')
    print('  G-C4-AUTHORITY all frozen authorities + C3 provenance/artifact '
          'equality reverified')
    print('  G-C4-MANIFEST C3 commitment verified')
    print('  G-C4-NEXT first candidate frozen (immutable record + commitment)')
    print('  PRODUCTION_EVENT_COUNT=0  state=INITIALIZED_NO_REVEAL')
    print('  HARD STOP before first reveal: no authorization exists')
    return {
        'session_id': session_id,
        'c3_manifest_commitment': C3_COMMITMENT,
        'READY_FOR_FIRST_REVEAL': False,
        'PRODUCTION_EVENT_COUNT': 0,
        'HARD_STOP_BEFORE_FIRST_REVEAL': True,
    }


def c4b_readiness(session_id, prod_root=PROD_ROOT):
    prod = prod_root / session_id
    if not prod.exists():
        fail('G-C4-SESSION: session not initialized')
    production_events(prod)
    verify_session_permissions(prod)
    manifest = verify_session_manifest(session_id, prod)
    c1 = verify_frozen_authorities()
    cand = first_candidate(c1)
    entry = candidate_packet(c1, cand)
    record = verify_first_candidate_record(session_id, prod, manifest=manifest,
                                           entry=entry)
    verify_candidate_bytes(entry)
    print('C4-B READINESS PASS  session=%s' % session_id)
    print('  G-C4-AUTHORITY all frozen authorities + C3 provenance/artifact '
          'equality reverified')
    print('  G-C4-MANIFEST C3 commitment verified')
    print('  G-C4-NEXT independent recompute == frozen record + commitment')
    print('  G-C4-BYTES frozen C3 packet bytes exact hash verified')
    print('  G-C4-SESSION immutable manifest + selector-only permissions '
          'verified')
    print('  PRODUCTION_EVENT_COUNT=0  (readiness writes no events)')
    print('  HARD STOP before first reveal: no authorization exists')
    return {
        'session_id': session_id,
        'c3_manifest_commitment': C3_COMMITMENT,
        'READY_FOR_FIRST_REVEAL': True,
        'PRODUCTION_EVENT_COUNT': 0,
        'HARD_STOP_BEFORE_FIRST_REVEAL': True,
    }


def supersede(session_id, prod_root=PROD_ROOT):
    """Retire a zero-event session: marker only; manifest stays untouched."""
    prod = prod_root / session_id
    if not prod.exists():
        fail('G-C4-SESSION: session not initialized')
    if production_events(prod) != 0:
        fail('G-C4-SESSION: cannot supersede a session with events')
    marker = {
        'status': 'SUPERSEDED / INVALID_FOR_ACTIVATION',
        'session_id': session_id,
        'reason': 'C4-A/B-AUDIT-FIX1: session manifest schema predates '
                  'final c4-v1.0 exact-schema closure',
        'production_events': 0,
    }
    (prod / 'SUPERSEDED.json').write_text(canon(marker))
    os.chmod(prod / 'SUPERSEDED.json', 0o600)
    print('SESSION SUPERSEDED  session=%s  production_events=0' % session_id)


def reveal_first(session_id):
    fail('G-C4-AUTHZ: reveal-first is HARD-STOPPED. C4-C requires an explicit '
         'FIRST_REVEAL_ONLY authorization from the user; the production C2 '
         'append() path is not implemented in C4-A/B (design v1.0 §9).')


# ---------------- synthetic / negative fixtures ----------------

def expect_fail(fn, label):
    try:
        fn()
    except RuntimeError:
        print('NEGATIVE PASS:', label)
        return
    raise RuntimeError('negative fixture did not fail: ' + label)


def selftest():
    """Isolated fixtures calling PRODUCTION helpers; real production root and
    real C3 artifacts are never mutated (mutated copies live in temp)."""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        root = tmp / 'production'
        c4a_init('s1', root)
        expect_fail(lambda: c4a_init('s1', root),
                    'existing session dir -> G-C4-SESSION FAIL')
        expect_fail(lambda: c4b_readiness('missing', root),
                    'readiness on missing session -> G-C4-SESSION FAIL')
        c4b_readiness('s1', root)
        # G-C4-NEXT: tampered immutable candidate record
        rec = root / 's1' / 'first_candidate_record.json'
        orig_rec = rec.read_text()
        bad = json.loads(orig_rec)
        bad['candidate_packet_sha256'] = '0' * 64
        rec.write_text(canon(bad))
        expect_fail(lambda: c4b_readiness('s1', root),
                    'tampered candidate record -> G-C4-NEXT FAIL')
        rec.write_text(orig_rec)
        # G-C4-NEXT closed-world: extra field + re-hashed manifest commitment
        smf = root / 's1' / 'session_manifest.json'
        orig_sm = smf.read_text()
        bad2 = json.loads(orig_rec)
        bad2['extra_field'] = 'anything'
        sm2 = json.loads(orig_sm)
        sm2['first_candidate_commitment'] = sha(canon(bad2).encode())
        rec.write_text(canon(bad2))
        smf.write_text(canon(sm2))
        expect_fail(lambda: c4b_readiness('s1', root),
                    'record extra field + re-hashed commitment -> '
                    'G-C4-NEXT closed-world FAIL')
        rec.write_text(orig_rec)
        smf.write_text(orig_sm)
        # G-C4-SESSION: session manifest mutation (schema drift)
        bad_sm = json.loads(orig_sm)
        bad_sm['session_version'] = 'c4-v9.9'
        smf.write_text(canon(bad_sm))
        expect_fail(lambda: c4b_readiness('s1', root),
                    'session manifest mutation -> G-C4-SESSION FAIL')
        smf.write_text(orig_sm)
        # G-C4-SESSION: permission mutation
        os.chmod(smf, 0o644)
        expect_fail(lambda: c4b_readiness('s1', root),
                    'permission mutation -> G-C4-SESSION FAIL')
        os.chmod(smf, 0o600)
        # G-C4-SESSION: sealing domain exists -> chain-derived refusal
        (root / 's1' / 'sealing').mkdir()
        expect_fail(lambda: c4b_readiness('s1', root),
                    'production sealing domain exists -> refusal')
        (root / 's1' / 'sealing').rmdir()
        # G-C4-AUTHORITY: C3 public commitment artifact mutation (copy)
        bad_c3a = tmp / 'c3a'
        bad_c3a.mkdir()
        shutil.copy(C3A / 'c3_manifest_commitment.json', bad_c3a)
        shutil.copy(C3A / 'c3_boolean_summary.json', bad_c3a)
        art = json.loads((bad_c3a / 'c3_manifest_commitment.json').read_text())
        art['packet_schema_sha256'] = '0' * 64
        (bad_c3a / 'c3_manifest_commitment.json').write_text(canon(art))
        expect_fail(lambda: verify_c3_authority(bad_c3a),
                    'C3 authority artifact mutation -> G-C4-AUTHORITY FAIL')
        art['packet_schema_sha256'] = C3_PACKET_SCHEMA
        boolean = json.loads((bad_c3a / 'c3_boolean_summary.json').read_text())
        boolean['G5_BLOCKED'] = False
        (bad_c3a / 'c3_boolean_summary.json').write_text(canon(boolean))
        (bad_c3a / 'c3_manifest_commitment.json').write_text(canon(art))
        expect_fail(lambda: verify_c3_authority(bad_c3a),
                    'G5 boundary violation -> G-C4-AUTHORITY FAIL')
        # G-C4-MANIFEST: secret C3 manifest mutation (copy)
        import csr8_phase_c_packet as c1
        bad_state = tmp / 'c3state'
        bad_state.mkdir()
        manifest = json.loads((C3_STATE / 'packet_manifest.json').read_text())
        manifest[0]['sha256'] = '0' * 64
        (bad_state / 'packet_manifest.json').write_text(canon(manifest))
        expect_fail(lambda: load_c3_manifest(bad_state),
                    'secret C3 manifest mutation -> G-C4-MANIFEST FAIL')
        # G-C4-BYTES: candidate packet one-byte mutation (copy)
        cand = first_candidate(c1)
        entry = candidate_packet(c1, cand)
        pk = bad_state / 'packets'
        pk.mkdir()
        src = C3_STATE / 'packets' / f"{entry['packet_id']}.json"
        data = bytearray(src.read_bytes())
        data[len(data) // 2] ^= 0x01
        (pk / f"{entry['packet_id']}.json").write_bytes(bytes(data))
        expect_fail(lambda: verify_candidate_bytes(entry, bad_state),
                    'candidate packet one-byte mutation -> G-C4-BYTES FAIL')
        # HARD STOP: reveal-first without authorization
        expect_fail(lambda: reveal_first('s1'),
                    'reveal-first without authorization -> fail-closed')
        # supersede marker refuses later activation attempts
        supersede('s1', root)
        expect_fail(lambda: c4b_readiness('s1', root),
                    'superseded session -> INVALID_FOR_ACTIVATION FAIL')
    print('C4 SELFTEST PASS: 13 isolated fail-closed fixtures calling '
          'production helpers; production event count remains 0 everywhere')


def publish_public(name, summary):
    PUBLIC.mkdir(parents=True, exist_ok=True)
    tmp = PUBLIC / f'.{name}.tmp'
    tmp.write_text(canon(summary))
    os.replace(tmp, PUBLIC / name)


def main():
    args = sys.argv[1:]
    if len(args) != 2 or args[0] not in ('init', 'readiness', 'reveal-first',
                                         'selftest', 'supersede'):
        print('usage: csr8_phase_c_activate.py '
              'init|readiness|reveal-first|selftest|supersede <session_id>')
        sys.exit(2)
    cmd, session_id = args
    try:
        if cmd == 'selftest':
            selftest()
        elif cmd == 'init':
            publish_public('c4a_public_summary.json', c4a_init(session_id))
        elif cmd == 'readiness':
            publish_public('c4b_readiness_public.json',
                           c4b_readiness(session_id))
        elif cmd == 'supersede':
            supersede(session_id)
        else:
            reveal_first(session_id)
    except RuntimeError:
        sys.exit(1)


if __name__ == '__main__':
    main()
