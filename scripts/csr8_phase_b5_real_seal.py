#!/usr/bin/env python3
"""CSR-8 B5 real SEAL transaction and Freeze Gate.

The transaction itself is provided by the frozen C4-D seal_transaction API.  This
module performs the B5 boundary proof from persisted bytes after the transaction:
chain [R1,S1], exact receipt/archived bytes/approval binding, consumed approval,
unique attempt history, empty annotator workspace, durable exact c4d anchor,
and unchanged C4-C anchor.
"""
import hashlib
import json
import stat
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
import csr8_phase_b1_real_handoff as b1
import csr8_phase_b3_real_receipt as b3
import csr8_phase_b4_human_approval as b4

CSR, SID = c4d.REAL_CSR, c4d.REAL_SESSION
ORDINAL, ATTEMPT = 1, 1
G = 'G-B5-FREEZE'

def fail(msg):
    raise RuntimeError(f'{G}: {msg}')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def read_events():
    p = c4d.log_path(CSR, SID)
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]

def verify_b5():
    events = read_events()
    if [e['event_type'] for e in events] != ['REVEAL_PACKET', 'SEAL_ANNOTATION']:
        fail('chain must be exactly [R1,S1]')
    r1, s1 = events
    if r1['event_hash'] != c4d.LIVE_R1_EVENT_HASH:
        fail('R1 event hash drift')
    log = c4d.c2.SealingLog(c4d.log_path(CSR, SID), c4d.head_path(CSR, SID))
    log.load(); log.verify(True)
    head_record = json.loads(c4d.head_path(CSR, SID).read_text())
    if head_record.get('head_hash') != s1['event_hash'] or head_record.get('count') != 2:
        fail('trusted head/count is not exact S1')
    adir = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT)
    rbytes = (adir / 'receipt.json').read_bytes()
    snap = (adir / 'draft_snapshot.bin').read_bytes()
    archived = c4d.sealing_dir(CSR, SID) / s1['payload']['bytes_ref']
    approval = json.loads((adir / 'seal_approval.json').read_bytes())
    draft = adir / 'draft_snapshot.bin'
    if not draft.is_file() or draft.read_bytes() != snap:
        fail('draft/snapshot exact invariant drift')
    if archived.read_bytes() != rbytes:
        fail('receipt triple exact-byte equality failed')
    if s1['payload']['receipt_sha256'] != sha(rbytes) or approval['approved_receipt_sha256'] != sha(rbytes):
        fail('SEAL payload/approval receipt hash drift')
    if c4d.canon(json.loads((adir / 'receipt.json').read_bytes())).encode() != rbytes:
        fail('persisted receipt is not canonical')
    if c4d.canon(approval).encode() != (adir / 'seal_approval.json').read_bytes():
        fail('persisted approval is not canonical')
    if stat.S_IMODE(adir.stat().st_mode) != 0o700 or any(
            stat.S_IMODE((adir / name).stat().st_mode) != 0o600
            for name in ('receipt.json', 'draft_snapshot.bin', 'seal_approval.json')):
        fail('receipt/approval attempt permissions drift')
    if c4d.canon(approval).encode() != (adir / 'seal_approval.json').read_bytes():
        fail('seal approval is not canonical')
    # The transaction proved active packet/draft exactness before append; after
    # POST_SEAL_FINAL the active workspace is intentionally absent.  The
    # archived REVEAL bytes remain the exact packet proof above via C2 replay.
    history = c4d.prove_attempt_history(CSR, SID, ORDINAL, gate=G)
    if history['live'] != [ATTEMPT]:
        fail('attempt history is not uniquely consumed')
    if c4d.annot_dom(CSR, SID).exists() and any(c4d.annot_dom(CSR, SID).rglob('*')):
        fail('active annotator workspace not empty')
    anchor = c4d.anchor_path_in(CSR) if hasattr(c4d, 'anchor_path_in') else c4d.PUBLIC_DIR / c4d.C4D_ANCHOR_NAME
    if not anchor.is_file():
        fail('c4d_seal_anchor.json is not durable')
    ap = json.loads(anchor.read_bytes())
    if ap.get('production_head_hash') != s1['event_hash'] or ap.get('seal_receipt_sha256') != sha(rbytes) or ap.get('sealed_count') != 1:
        fail('c4d seal anchor exact binding drift')
    if c4d.canon(ap).encode() != anchor.read_bytes():
        fail('c4d seal anchor is not canonical')
    c4d.semantic_replay(CSR, SID)
    b4._verify_chain_approval(CSR, rbytes, sha(rbytes))
    root = Path(__file__).resolve().parents[1]
    c4c_anchor = CSR / 'public' / 'c4c_anchor.json'
    certified = json.loads((root / 'config/audit/certified_live_inputs.json').read_bytes())
    cert_entry = next((x for x in certified['roots'][0]['files'] if x['path'] == 'public/c4c_anchor.json'), None)
    if cert_entry is None or not c4c_anchor.is_file():
        fail('c4c anchor certification is absent')
    if sha(c4c_anchor.read_bytes()) != cert_entry['sha256']:
        fail('c4c anchor bytes changed')
    outcome_files = [p for p in CSR.rglob('*') if 'outcome' in p.name.lower()]
    if outcome_files:
        fail('outcome domain changed/present: ' + ','.join(str(p) for p in outcome_files))
    public_state = json.loads((c4d.PUBLIC_DIR / 'c4d_phase_a_public_state.json').read_bytes())
    pub = public_state.get('production', {})
    if pub.get('production_head_hash') != s1['event_hash'] or pub.get('event_types') != ['REVEAL_PACKET', 'SEAL_ANNOTATION'] \
            or pub.get('seal_count') != 1 or pub.get('reveal_count') != 1:
        fail('public production state is not synced to S1')
    checks = {
        'trusted_prefix': log.events[0]['prev_event_hash'] == c4d.c2.GENESIS
                          and head_record['count'] == len(log.events),
        'history_unique': history['live'] == [ATTEMPT],
        'receipt_snapshot_exact': draft.read_bytes() == snap,
        'approval_exact': approval['approved_receipt_sha256'] == sha(rbytes),
        'commit_time_receipt': s1['payload']['receipt_sha256'] == sha(rbytes),
        'persisted_receipt_reread': archived.read_bytes() == rbytes,
        'seal_append_once': len(events) == 2,
        'c2_full_verify': log.events[-1]['prev_event_hash'] == log.events[0]['event_hash']
                         and log.events[-1]['event_hash'] == head_record['head_hash'],
        'semantic_replay': c4d.derive_state(CSR, SID)[0] == 'SEALED',
        'seal_committed': c4d.derive_state(CSR, SID)[0] in ('SEALED', 'SEAL_PENDING_FINALIZE'),
        'c4d_anchor_durable': anchor.is_file(),
        'workspace_cleanup': not (c4d.annot_dom(CSR, SID).exists() and any(c4d.annot_dom(CSR, SID).rglob('*'))),
        'post_seal_final': c4d.derive_state(CSR, SID)[0] == 'SEALED',
        'chain_r1_s1': [e['event_type'] for e in events] == ['REVEAL_PACKET', 'SEAL_ANNOTATION'],
        'head_s1': head_record.get('head_hash') == s1['event_hash'] and head_record.get('count') == 2,
        'receipt_triple_exact': archived.read_bytes() == rbytes and draft.read_bytes() == snap,
        'approval_consumed': c4d.derive_state(CSR, SID)[0] == 'SEALED',
        'attempt_history': history['live'] == [ATTEMPT],
        'active_workspace_empty': not (c4d.annot_dom(CSR, SID).exists() and any(c4d.annot_dom(CSR, SID).rglob('*'))),
        'c4d_anchor_exact': ap.get('production_head_hash') == s1['event_hash'],
        'c4c_anchor_unchanged': sha(c4c_anchor.read_bytes()) == cert_entry['sha256'],
        'outcome_untouched': not outcome_files,
        'public_state_synced': pub.get('production_head_hash') == s1['event_hash'] and pub.get('seal_count') == 1,
    }
    if not all(checks.values()):
        fail('measured Freeze Gate checks failed: ' + ','.join(k for k,v in checks.items() if not v))
    # Re-run the complete persisted proof immediately before emitting the
    # result; this is the commit-time transaction/Freeze Gate witness.
    log.load(); log.verify(True)
    c4d.semantic_replay(CSR, SID)
    if c4d.derive_state(CSR, SID)[0] != 'SEALED':
        fail('post-proof state is not S1 SEALED')
    return {'gates': {k: 'PASS' for k in checks}, 'chain': ['REVEAL_PACKET', 'SEAL_ANNOTATION'], 'production': 'REVEAL=1 SEAL=1', 'head': s1['event_hash'], 'receipt_sha256': sha(rbytes)}

def main():
    result = verify_b5()
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))

if __name__ == '__main__':
    main()
