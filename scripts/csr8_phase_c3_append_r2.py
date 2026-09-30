#!/usr/bin/env python3
"""CSR-8 C3: append the authorized ordinal-2 reveal (R2) exactly once.

The append path is deliberately one-shot: C2 is re-verified from persisted
bytes immediately before the frozen transaction API is called.  Afterward,
the complete chain, chain-derived consumption, sealed-pair replay, and frozen
candidate prefix are measured from the resulting production state.
"""
import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import csr8_phase_c_annotation_seal as c4d
import csr8_phase_c2_next_reveal_approval as c2

ROOT = c4d.ROOT
SID = c4d.REAL_SESSION
ORDINAL = 2


def _events():
    path = c4d.log_path(c4d.REAL_CSR, SID)
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def verify_c3():
    events = _events()
    types = [event['event_type'] for event in events]
    if types != ['REVEAL_PACKET', 'SEAL_ANNOTATION', 'REVEAL_PACKET']:
        raise RuntimeError(f'G-C3-CHAIN: expected [R1,S1,R2], got {types}')
    c4d.c2translate(
        c4d.c2.SealingLog(c4d.log_path(c4d.REAL_CSR, SID),
                           c4d.head_path(c4d.REAL_CSR, SID)).load().verify,
        True)
    proposal = c4d.read_json(c4d.proposal_path(c4d.REAL_CSR, SID, ORDINAL))
    if c4d.derive_reveal_consumption(events, proposal, SID) != 'CONSUMED':
        raise RuntimeError('G-C3-AUTHORIZATION: ordinal-2 is not CONSUMED')
    c4d.semantic_replay(c4d.REAL_CSR, SID, events=events)
    reveals = [e for e in events if e['event_type'] == c4d.c2.REVEAL]
    order = c4d.candidate_total_order()
    revealed = [(e['payload']['opaque_case_id'], e['payload']['T'])
                for e in reveals]
    expected = [(e['opaque_case_id'], e['T']) for e in order[:2]]
    if revealed != expected:
        raise RuntimeError('G-C3-PREFIX: revealed candidates are not prefix 2')
    return {
        'chain': types,
        'authorization_2': 'CONSUMED',
        'candidate_prefix': len(revealed),
        'reveal_count': len(reveals),
        'seal_count': sum(t == 'SEAL_ANNOTATION' for t in types),
        's1_r1_replay': 'PASS',
        'head': events[-1]['event_hash'],
    }


def append_r2(root=c4d.REAL_CSR, record_path=None, record_witness=None):
    # This is the sole C3 append path.  The persisted C2 state is fully
    # verified immediately before the irreversible append; retain the exact
    # verifier result rather than a hand-written PASS label.
    c2_result = c2.verify_c2(root, record_path=record_path) if record_path else c2.verify_c2(root)
    if c2_result['consumption'] != 'UNUSED' or \
            set(c2_result['gates'].values()) != {'PASS'}:
        raise RuntimeError('G-C3-PRE: C2 full verify did not pass UNUSED')
    witness = {
        'source': 'C3 append transaction precondition',
        'chain_before_append': ['REVEAL_PACKET', 'SEAL_ANNOTATION'],
        'consumption_before_append': c2_result['consumption'],
        'gates': c2_result['gates'],
    }
    if record_witness is not None:
        Path(record_witness).write_bytes(c4d.canon(witness).encode())
    c4d.reveal_transaction(root, SID, ORDINAL)
    return verify_c3() if root == c4d.REAL_CSR else witness


def verify_live_c2_binding_after_append():
    """Verify the C2 authorization remains bound to the sealed S1 prefix.

    C2's full pre-append verifier is executed on the isolated replica below;
    after R2, the live chain is intentionally no longer a C1/C2 closed
    prefix.  This live check therefore proves only the immutable C2 bytes and
    their S1 prefix binding, never relabels a post-C3 chain as pre-C3.
    """
    events = _events()
    s1 = events[1]
    proposal_path = c4d.proposal_path(c4d.REAL_CSR, SID, ORDINAL)
    proposal = c4d.read_json(proposal_path)
    pbytes = proposal_path.read_bytes()
    approval_path = c4d.next_authz_dir(c4d.REAL_CSR, SID, ORDINAL) / 'next_reveal.approval.json'
    permit_path = c4d.next_authz_dir(c4d.REAL_CSR, SID, ORDINAL) / 'next_reveal.permit.json'
    approval = c4d.read_json(approval_path)
    if proposal['sealed_prefix_head'] != s1['event_hash']:
        raise RuntimeError('G-C3-C2-BOUNDARY: proposal is not bound to S1')
    if approval['approved_authorization_sha256'] != c4d.sha(pbytes):
        raise RuntimeError('G-C3-C2-BOUNDARY: approval hash drift')
    if permit_path.read_bytes() != pbytes:
        raise RuntimeError('G-C3-C2-BOUNDARY: permit bytes drift')
    return {'live_c2_prefix_binding': 'PASS', 'live_c2_approval_binding': 'PASS'}


def verify_pre_append_c2_on_replica():
    """Rebuild the C2 boundary in an isolated replica and prove it before
    append.  This is the repeatable evidence path; it never mutates live
    production and never enters C4."""
    sys.path.insert(0, str(ROOT / 'tests'))
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    import csr8_phase_c1_ordinal2_proposal as c1
    with tempfile.TemporaryDirectory(prefix='csr8-c3-proof-') as td:
        sb = build_pre_seal_sandbox(Path(td), through='B4')
        c4d.seal_transaction(sb.root, SID)
        c1.do_propose(sb.root)
        record = Path(td) / 'c2_record.json'
        c2.do_approve(sb.root, record)
        pre = Path(td) / 'c3_pre_append_c2_witness.json'
        append_r2(sb.root, record_path=record, record_witness=pre)
        witness = json.loads(pre.read_bytes())
        return {'replica_c2_full_verify': 'PASS',
                'replica_c2_consumption_before_append':
                    witness['consumption_before_append'],
                'replica_chain_before_append':
                    witness['chain_before_append'],
                'replica_c2_gate_count': len(witness['gates'])}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--verify', action='store_true')
    args = parser.parse_args(argv)
    if args.verify:
        result = verify_c3()
        result.update(verify_live_c2_binding_after_append())
        result.update(verify_pre_append_c2_on_replica())
        if result.get('replica_c2_consumption_before_append') != 'UNUSED':
            raise RuntimeError('G-C3-PRE: replica witness lacks pre-append UNUSED proof')
        evidence = ROOT / 'docs/audit/evidence/c3_append_r2.json'
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_bytes(c4d.canon(result).encode())
        result['evidence'] = str(evidence.relative_to(ROOT))
    else:
        result = append_r2()
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
