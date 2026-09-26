#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C4-A/B — Production Session Initialization & Readiness.

Implements C4 DESIGN v1.0 FINAL FROZEN @ 6fa5380 — C4-A and C4-B ONLY:

    init        -> C4-A fresh production session + frozen authorities +
                   deterministic FIRST-CANDIDATE selector + immutable
                   first_candidate_record + immutable session manifest
                   (production events = 0)
    readiness   -> C4-B independent selector recompute + candidate record /
                   commitment equality + exact frozen C3 packet bytes
                   (production events = 0)
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
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[1]
PC = ROOT / 'output/research/csr/08_pilot_cases/phase_c'
C1_ART = PC / 'c1_artifacts'
C3_STATE = ROOT / 'data/csr8_phase_c/c3_preflight'
PROD_ROOT = ROOT / 'data/csr8_phase_c/production'
PUBLIC = PC / 'c4_public'

C3_COMMITMENT = ('883c9869f29d0f17316edea86e5b5e996dc11e1fca19db631cb12cd0a4cc2d0b')
C3_PACKET_SCHEMA = ('073673bb58043ac149344053a363c97f46e277dc803f3a1aa29508b8747ac676')
SELECTOR_VERSION = 'C4-FIRST-v1'
SESSION_VERSION = 'c4-v1.0'
# Frozen group axis (C1 PACKET_GENERATION_ALLOWED): exactly these four case
# groups are eligible; G5 is excluded (annotation-primary), XP excluded by
# axis.  This set is frozen by the C1 hidden plan itself.
ELIGIBLE_GROUPS = ('G1_complete_bull', 'G2_breakout_fail',
                   'G3_high_collapse', 'G4_quiet_then_go')


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


def load_c3_manifest():
    p = C3_STATE / 'packet_manifest.json'
    if not p.exists():
        fail('G-C4-MANIFEST: C3 selector-only packet manifest missing')
    manifest = json.loads(p.read_text())
    if sha(canon(manifest).encode()) != C3_COMMITMENT:
        fail('G-C4-MANIFEST: C3 manifest canonical hash mismatch')
    return manifest


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
    if frozen['fetch_manifest_sha256'] != ('f16b764e6a3358269eef229dde06f9ae37'
                                           'df8fd8a20ac6852fc39f9ceeade6b3'):
        fail('G-C4-AUTHORITY: price fetch manifest authority drift')
    if frozen['per_stock_root_sha256'] != ('783e5cd849eb486eba2aff854e418c4718'
                                           'ff3406e2ff9ceb5f4bb8aa7c1986d6'):
        fail('G-C4-AUTHORITY: price per-stock root authority drift')
    return c1


def first_candidate(c1):
    """FIRST-CANDIDATE SELECTOR (deterministic total order, design §3.0).

    eligible = G1-G4 (frozen group axis); per case take earliest T;
    first case = min over (HMAC-SHA256(salt, "C4-FIRST-v1|"+ocid), ocid).
    """
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
    if keys.count(keys[0]) > 1:
        fail('G-C4-NEXT: selector key collision (impossible under total order)')
    return {'digest': digest, 'opaque_case_id': ocid, 'T': earliest[ocid]}


def candidate_packet(c1, cand):
    """G-C4-MANIFEST/NEXT: candidate must be an exact frozen C3 manifest entry."""
    manifest = load_c3_manifest()
    salt = c1.load_salt()
    for entry in manifest:
        if entry['T'] != cand['T']:
            continue
        if c1.opaque_case_id(salt, entry['case_key']) == cand['opaque_case_id']:
            return entry
    fail('G-C4-NEXT: candidate not present in frozen C3 manifest')


def production_events(prod):
    """Runtime state is chain-derived: no sealing domain -> 0 events."""
    sealing = prod / 'sealing'
    if sealing.exists():
        fail('G-C4-SESSION: production sealing domain exists — first reveal '
             'already staged/published; C4-A/B must refuse')
    return 0


def c4a_init(session_id, prod_root=PROD_ROOT):
    if not session_id or any(ch in session_id for ch in '/\\ .'):
        fail('G-C4-SESSION: invalid session id')
    prod = prod_root / session_id
    if prod.exists():
        fail('G-C4-SESSION: production session directory already exists')
    if (prod_root / session_id / 'sealing').exists():
        fail('G-C4-SESSION: sealing domain must not pre-exist')
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
        'c1_plan_commitment': json.loads(
            (C1_ART / 'plan_commitment.json').read_text())['plan_commitment'],
        'c1_salt_commitment': json.loads(
            (C1_ART / 'salt_commitment.json').read_text())['salt_commitment'],
        'c3_packet_manifest_commitment': C3_COMMITMENT,
        'c3_packet_schema_sha256': C3_PACKET_SCHEMA,
        'first_candidate_commitment': commitment,
        'price_source_commitments': {
            'source_id': 'baostock_unadjusted_v1',
            'fetch_manifest_sha256': 'f16b764e6a3358269eef229dde06f9ae37df8'
                                     'fd8a20ac6852fc39f9ceeade6b3',
            'per_stock_root_sha256': '783e5cd849eb486eba2aff854e418c4718ff'
                                     '3406e2ff9ceb5f4bb8aa7c1986d6',
        },
        'phase_b_input_commitments': {
            'case_index_blob': 'f69fdddd8fbf734c1173e929fac30a5ca736b764',
            'calendar_blob': 'f4d5190db9f4145bb5fec32449c79581d73152b9',
            'calendar_embedded_sha256': '87f8f959910295640ebdf89b40cedb8de'
                                        '03049bc88c6ad4aace3f39b249c3f80',
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
    print('C4-A INIT PASS  session=%s' % session_id)
    print('  G-C4-SESSION fresh, selector-only 0700/0600')
    print('  G-C4-AUTHORITY all frozen authorities reverified')
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
    c1 = verify_frozen_authorities()
    record = json.loads((prod / 'first_candidate_record.json').read_text())
    manifest = json.loads((prod / 'session_manifest.json').read_text())
    if sha(canon(record).encode()) != manifest['first_candidate_commitment']:
        fail('G-C4-NEXT: first candidate commitment mismatch (record tampered?)')
    cand = first_candidate(c1)
    entry = candidate_packet(c1, cand)
    if (record['version'] != SELECTOR_VERSION
            or record['session_id'] != session_id
            or record['c3_manifest_commitment'] != C3_COMMITMENT
            or record['candidate_packet_id'] != entry['packet_id']
            or record['candidate_packet_sha256'] != entry['sha256']):
        fail('G-C4-NEXT: recomputed candidate differs from frozen record')
    packet_path = C3_STATE / 'packets' / f"{entry['packet_id']}.json"
    if not packet_path.exists():
        fail('G-C4-BYTES: frozen C3 packet bytes missing')
    if file_sha(packet_path) != entry['sha256']:
        fail('G-C4-BYTES: frozen packet bytes hash mismatch')
    print('C4-B READINESS PASS  session=%s' % session_id)
    print('  G-C4-AUTHORITY all frozen authorities reverified')
    print('  G-C4-MANIFEST C3 commitment verified')
    print('  G-C4-NEXT independent recompute == frozen record + commitment')
    print('  G-C4-BYTES frozen C3 packet bytes exact hash verified')
    print('  PRODUCTION_EVENT_COUNT=0  (readiness writes no events)')
    print('  HARD STOP before first reveal: no authorization exists')
    return {
        'session_id': session_id,
        'c3_manifest_commitment': C3_COMMITMENT,
        'READY_FOR_FIRST_REVEAL': True,
        'PRODUCTION_EVENT_COUNT': 0,
        'HARD_STOP_BEFORE_FIRST_REVEAL': True,
    }


def reveal_first(session_id):
    fail('G-C4-AUTHZ: reveal-first is HARD-STOPPED. C4-C requires an explicit '
         'FIRST_REVEAL_ONLY authorization from the user; the production C2 '
         'append() path is not implemented in C4-A/B (design v1.0 §9).')


def expect_fail(fn, label):
    try:
        fn()
    except RuntimeError:
        print('NEGATIVE PASS:', label)
        return
    raise RuntimeError('negative fixture did not fail: ' + label)


def selftest():
    """Isolated synthetic/negative fixtures; real production root untouched."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / 'production'
        c4a_init('s1', root)
        expect_fail(lambda: c4a_init('s1', root),
                    'existing session dir -> G-C4-SESSION FAIL')
        expect_fail(lambda: c4b_readiness('missing', root),
                    'readiness on missing session -> G-C4-SESSION FAIL')
        c4b_readiness('s1', root)
        rec = root / 's1' / 'first_candidate_record.json'
        orig = rec.read_text()
        tampered = json.loads(orig)
        tampered['candidate_packet_sha256'] = '0' * 64
        rec.write_text(canon(tampered))
        expect_fail(lambda: c4b_readiness('s1', root),
                    'tampered candidate record -> G-C4-NEXT FAIL')
        rec.write_text(orig)
        sealing = root / 's1' / 'sealing'
        sealing.mkdir()
        expect_fail(lambda: c4b_readiness('s1', root),
                    'production sealing domain exists -> chain-derived state '
                    'refuses C4-A/B')
        expect_fail(lambda: reveal_first('s1'),
                    'reveal-first without authorization -> fail-closed')
    print('C4 SELFTEST PASS: 5 isolated fail-closed fixtures; production '
          'event count remains 0 everywhere')


def publish_public(name, summary):
    PUBLIC.mkdir(parents=True, exist_ok=True)
    tmp = PUBLIC / f'.{name}.tmp'
    tmp.write_text(canon(summary))
    os.replace(tmp, PUBLIC / name)


def main():
    args = sys.argv[1:]
    if len(args) != 2 or args[0] not in ('init', 'readiness', 'reveal-first',
                                         'selftest'):
        print('usage: csr8_phase_c_activate.py '
              'init|readiness|reveal-first|selftest <session_id>')
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
        else:
            reveal_first(session_id)
    except RuntimeError:
        sys.exit(1)


if __name__ == '__main__':
    main()
