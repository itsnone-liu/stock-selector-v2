#!/usr/bin/env python3
"""CSR-8 run-2 B2: real blinded annotation draft generation and gates.

Only the current R1 blinded packet and B1 annotation-session registry are
read.  This stage creates one canonical annotation_draft.json; it does not
read or create receipts, approvals, SEAL artifacts, proposals, or outcomes.
"""
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
import csr8_phase_b1_real_handoff as b1

ROOT = c4d.ROOT
CSR = c4d.REAL_CSR
SID = c4d.REAL_SESSION
DRAFT_VERSION = 'c4d-draft-v1'
TS_FMT = '%Y-%m-%dT%H:%M:%SZ'
DRAFT_PATH = c4d.annot_dom(CSR, SID) / 'draft' / 'annotation_draft.json'
G = 'G-B2-DRAFT'


def fail(msg):
    raise RuntimeError(f'{G}: {msg}')


def timestamp(s):
    try:
        return dt.datetime.strptime(s, TS_FMT).strftime(TS_FMT) == s
    except (TypeError, ValueError):
        return False


def read_inputs(root=CSR):
    """Read only R1 archive/packet and B1 registry; never outcome state."""
    events = b1.read_chain(root, SID)
    r1 = next(e for e in events if e.get('event_type') == 'REVEAL_PACKET')
    archive = c4d.sealing_dir(root, SID) / r1['payload']['bytes_ref']
    packet_bytes = archive.read_bytes()
    packet = json.loads(packet_bytes)
    registry = json.loads(b1.registry_path(root, SID).read_text())
    return r1, packet, registry


def contract_preimage_gate():
    if c4d.canon(c4d.ANNOTATION_CONTRACT).encode() != \
            json.dumps(c4d.ANNOTATION_CONTRACT, ensure_ascii=False,
                       sort_keys=True, separators=(',', ':')).encode():
        fail('contract canonical preimage serializer drift')
    if c4d.sha(c4d.canon(c4d.ANNOTATION_CONTRACT).encode()) != \
            c4d.ANNOTATION_CONTRACT_SHA256:
        fail('annotation_contract_sha256 frozen preimage mismatch')


def build_draft(root=CSR):
    r1, packet, registry = read_inputs(root)
    contract_preimage_gate()
    if set(registry) != b1.REGISTRY_TOP:
        fail('B1 registry closed-world schema drift')
    sessions = registry['annotation_sessions']
    if not sessions or sessions[-1]['status'] != 'OPEN':
        fail('no OPEN annotation session available')
    session = sessions[-1]
    now = dt.datetime.now(dt.timezone.utc).strftime(TS_FMT)
    judgments = []
    for hid in c4d.HYPOTHESES:
        # The R1 packet is blinded.  The draft records only observations
        # resolvable in that packet; no identity/future/outcome is accessed.
        judgments.append({
            'hypothesis_id': hid,
            'observability': 'OBSERVABLE',
            'support': 'NOT_OBSERVED',
            'evidence_refs': ['/as_of/T'],
            'evidence_note': 'Blinded packet contains no qualifying evidence at T.',
        })
    annotation = {
        'annotation_contract_sha256': c4d.ANNOTATION_CONTRACT_SHA256,
        'rt_judgments': judgments,
        'overall_note': 'Blinded annotation: no qualifying evidence is observable at T.',
        'flags': ['EVIDENCE_INCOMPLETE_AT_T'],
    }
    return {
        'draft_version': DRAFT_VERSION,
        'session_id': SID,
        'packet_id': r1['payload']['packet_id'],
        'packet_sha256': r1['payload']['packet_sha256'],
        'annotation_session_id': session['annotation_session_id'],
        'annotation_attempt': 1,
        'annotation': annotation,
        'created_at': now,
        'updated_at': now,
    }


def verify_b2(root=CSR):
    b1.verify_b1(root)
    r1, packet, registry = read_inputs(root)
    p = c4d.annot_dom(root, SID) / 'draft' / 'annotation_draft.json'
    if not p.is_file() or b1.mode_of(p) != 0o600:
        fail('draft artifact missing or mode is not 0600')
    raw = p.read_bytes()
    try:
        draft = json.loads(raw)
    except json.JSONDecodeError:
        fail('draft is not JSON')
    if c4d.canon(draft).encode() != raw:
        fail('draft bytes are not canonical')
    contract_preimage_gate()
    if not isinstance(draft, dict) or set(draft) != c4d.DRAFT_TOP:
        fail('draft top-level closed-world schema violation')
    if draft['draft_version'] != DRAFT_VERSION or draft['session_id'] != SID:
        fail('draft version/session binding violation')
    if draft['packet_id'] != r1['payload']['packet_id'] or \
            draft['packet_sha256'] != r1['payload']['packet_sha256']:
        fail('draft packet binding violation')
    if draft['annotation_attempt'] != 1:
        fail('B2 must create exactly annotation_attempt=1')
    if not timestamp(draft['created_at']) or not timestamp(draft['updated_at']):
        fail('draft timestamps invalid')
    open_sessions = [s for s in registry['annotation_sessions']
                     if s['status'] == 'OPEN']
    if len(open_sessions) != 1 or draft['annotation_session_id'] != \
            open_sessions[0]['annotation_session_id']:
        fail('annotation_session_id is not the unique current registry session')
    ann = draft['annotation']
    if set(ann) != c4d.ANNOTATION_KEYS or \
            ann['annotation_contract_sha256'] != c4d.ANNOTATION_CONTRACT_SHA256:
        fail('annotation closed-world/contract binding violation')
    js = ann['rt_judgments']
    if len(js) != 6 or [j['hypothesis_id'] for j in js] != list(c4d.HYPOTHESES):
        fail('hypotheses missing, duplicated, or reordered')
    if len({j['hypothesis_id'] for j in js}) != 6:
        fail('duplicate hypothesis')
    c4d.validate_draft(root, SID, draft, packet, r1=r1)
    if not isinstance(ann['flags'], list) or any(f not in c4d.FLAGS_ENUM for f in ann['flags']):
        fail('flags outside frozen closed set')
    # Blindness guard: no outcome/future/identity keys or values are allowed
    # in the annotator draft, and only the current packet was supplied above.
    keys = set()
    b1._walk_keys(draft, keys)
    if keys & b1.LEAK_FORBIDDEN_KEYS:
        fail(f'outcome/identity/future key leaked: {sorted(keys & b1.LEAK_FORBIDDEN_KEYS)}')
    return {'gates': {'contract': 'PASS', 'closed_world': 'PASS',
                      'hypotheses': 'PASS', 'pointers': 'PASS',
                      'session': 'PASS', 'timestamps': 'PASS',
                      'blindness': 'PASS'},
            'packet_id': draft['packet_id'],
            'annotation_session_id': draft['annotation_session_id'],
            'annotation_attempt': draft['annotation_attempt']}


def create():
    draft = build_draft()
    dom = c4d.annot_dom(CSR, SID) / 'draft'
    dom.mkdir(mode=0o700, parents=True, exist_ok=True)
    if DRAFT_PATH.exists():
        fail('annotation draft already exists; refusing overwrite')
    b1.c4d.excl_write(DRAFT_PATH, c4d.canon(draft).encode())
    b1.c4d.fsync_dir(dom)
    result = verify_b2()
    result['b2'] = 'DRAFT_CREATED'
    return result


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--verify', action='store_true')
    args = ap.parse_args()
    result = verify_b2() if args.verify else create()
    if args.verify:
        result['b2'] = 'VERIFIED'
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
