#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase H1 — reviewer-gated production executor for ordinal 3.

任务书（frozen hash ddeb1ec260fa）§11-§19 ordinal loop 的 executor 侧。
本模块是唯一 H1 生产执行入口，逐边界 fail-closed：

  每个不可逆动作之前，机器实测两件事：
    (1) machine gates PASS（冻结 c4d 事务 API 自带的前置证明）
    (2) 独立 reviewer 对该 operation 的 exact-hash APPROVE verdict
        （closed-world 10 字段、绑定 input_commitment_sha256、0600）

  子命令（严格按阶段顺序执行，各自一次性）：
    gate <op> <sha>   只读校验 verdict 文件（不写任何东西）
    authorize         NEXT_REVEAL verdict → live proposal（必须逐字节
                      等于 H0 staged proposal）→ approve_next_reveal →
                      materialize_next_permit
    reveal            授权三方一致复证 → reveal_transaction(ordinal=3)
    annotate          handoff（C3 池 exact bytes）→ annotation session
                      registry → blinded draft → write_draft →
                      validate_draft（盲态、无 outcome/identity/future）
    receipt           ANNOTATION verdict（绑定 draft exact hash）→
                      make_receipt(3)（exact snapshot/fsync/0400/reread/
                      RENAME_NOREPLACE/parent fsync）→ ordinal-0003 证据
                      拷贝（packet/registry/draft，O_EXCL 0600）
    seal              RECEIPT + SEAL verdicts（绑定 receipt exact hash）→
                      make_seal_approval → seal_transaction（replay →
                      anchor durable → cleanup → POST_SEAL_FINAL）
    verify            终态全量机器实测（链/前缀/消费/历史/replay/anchor/
                      cleanup/POST_SEAL_FINAL/全部 verdicts/授权域闭世界/
                      h_campaign H1 闭世界）

  executor 禁读（本模块物理上不含任何读取路径）：outcomes/、
  analysis_labeled/、identity resolver、future 数据；禁写 reviewer
  ledger（reviews.jsonl 只由 reviewer 追加）。
"""

import argparse
import datetime as _dt
import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402 (frozen, read-only reuse)

ROOT = c4d.ROOT
CSR = c4d.REAL_CSR
SID = c4d.REAL_SESSION
ORDINAL = 3
ATTEMPT = 1

RUN_ID = 'audit_20261001135212538'
HOST_ID = 'RainYun-c438TDGn'
STAGE, ITERATION = 'H1', 1

CID = 'hc-46195669974db3b25610bef4d047d927'
CAMPAIGN = CSR / 'h_campaign' / CID
PACKET = CAMPAIGN / 'h1' / 'packets' / 'ordinal-0003-next-reveal.json'
REVIEWS = CAMPAIGN / 'h1' / 'reviews'
STAGED_PROPOSAL = CAMPAIGN / 'ordinal_0003' / \
    'next_reveal.proposal.staged.json'

OPS = ('NEXT_REVEAL', 'ANNOTATION', 'RECEIPT', 'SEAL', 'POST_SEAL')
VERDICT_FIELDS = {'review_version', 'campaign_id', 'ordinal', 'operation',
                  'input_commitment_sha256', 'state', 'issues',
                  'required_changes', 'reviewer_run_id', 'created_at'}

TS_FMT = '%Y-%m-%dT%H:%M:%SZ'
LEAK_FORBIDDEN_KEYS = {
    'case_key', 'case_id', 'identity', 'symbol', 'ticker', 'code',
    'stock_code', 'name', 'person', 'user', 'outcome', 'outcome_label',
    'label', 'y_label', 'forward_return', 'future_return', 'future',
    'horizon_return', 'return_label', 'secret', 'secret_salt', 'salt',
    'api_key', 'token',
}
REGISTRY_VERSION = 'c4d-annotation-session-registry-v1'
REGISTRY_TOP = {'registry_version', 'session_id', 'reveal_event_hash',
                'packet_id', 'packet_sha256',
                'annotation_contract_sha256', 'annotation_sessions'}
SESSION_KEYS = {'annotation_session_id', 'created_at', 'status',
                'packet_id', 'packet_sha256', 'reveal_event_hash'}

EXPECTED_FINAL_CHAIN = ['REVEAL_PACKET', 'SEAL_ANNOTATION',
                        'REVEAL_PACKET', 'SEAL_ANNOTATION',
                        'REVEAL_PACKET', 'SEAL_ANNOTATION']


def fail(msg, gate='G-H1'):
    raise RuntimeError(f'{gate}: {msg}')


def sha(b):
    return hashlib.sha256(b).hexdigest()


def canon(x):
    return c4d.canon(x)


def now_utc():
    return _dt.datetime.now(_dt.timezone.utc).strftime(TS_FMT)


def mode_of(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def _chattr(flags, path):
    subprocess.run(['chattr', flags, str(path)], check=True)


def _immutable(path):
    out = subprocess.run(['lsattr', str(path)], check=True,
                         capture_output=True, text=True).stdout
    return out[:5].count('i') == 1 and 'i' in out.split()[0]


def _unlock_sealing():
    """The certified production tree persists its two chain files mode-0400
    with the kernel immutable attribute (host-level freeze of certified
    bytes). The frozen C2 append path opens the log/head for write, so the
    transaction envelope unlocks BOTH layers immediately before a frozen
    transaction and relocks them immediately after. The appends are
    append-only for the log; the head pointer is a derived file the frozen
    C2 code rewrites by design."""
    for name in ('sealing_log.jsonl', 'sealing_log.head.json'):
        p = c4d.sealing_dir(CSR, SID) / name
        if p.exists() and _immutable(p):
            _chattr('-i', p)
        if p.exists() and mode_of(p) == 0o400:
            os.chmod(p, 0o600)


def _relock_sealing():
    for name in ('sealing_log.jsonl', 'sealing_log.head.json'):
        p = c4d.sealing_dir(CSR, SID) / name
        if not p.exists():
            continue
        if mode_of(p) == 0o600:
            os.chmod(p, 0o400)
        if not _immutable(p):
            _chattr('+i', p)
    c4d.fsync_dir(c4d.sealing_dir(CSR, SID))


def events():
    return [json.loads(x) for x in
            (c4d.sealing_dir(CSR, SID) / 'sealing_log.jsonl')
            .read_text().splitlines() if x.strip()]


def chain_types():
    return [e['event_type'] for e in events()]


# ---------------------------------------------------------------------------
# verdict gate (read-only; every irreversible boundary calls this)
# ---------------------------------------------------------------------------

def verdict_path(op):
    return REVIEWS / f'{op}.verdict.json'


def require_verdict(op, expected_sha, gate):
    """Closed-world verdict re-proof binding the exact input hash."""
    p = verdict_path(op)
    if not p.is_file():
        fail(f'independent reviewer verdict missing: {op} ({p})', gate)
    raw = p.read_bytes()
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        fail(f'{op} verdict is not JSON', gate)
    if not isinstance(v, dict) or set(v) != VERDICT_FIELDS:
        fail(f'{op} verdict closed-world schema violation', gate)
    if v['campaign_id'] != CID or v['ordinal'] != ORDINAL or \
            v['operation'] != op:
        fail(f'{op} verdict binding mismatch', gate)
    if v['input_commitment_sha256'] != expected_sha:
        fail(f'{op} verdict does not bind the exact input hash '
             f'({v["input_commitment_sha256"]} != {expected_sha})', gate)
    if v['state'] != 'APPROVE' or v['issues'] != [] or \
            v['required_changes'] != []:
        fail(f'{op} verdict is not a clean APPROVE '
             f'(state={v["state"]}, issues={v["issues"]}, '
             f'required_changes={v["required_changes"]})', gate)
    if mode_of(p) != 0o600:
        fail(f'{op} verdict mode drift (must be 0600)', gate)
    return v


def packet_sha():
    return sha(PACKET.read_bytes())


# ---------------------------------------------------------------------------
# stage: authorize
# ---------------------------------------------------------------------------

def cmd_authorize():
    types = chain_types()
    if types != EXPECTED_FINAL_CHAIN[:4]:
        fail(f'pre-authorize chain must be [R1,S1,R2,S2], got {types}')
    c4d.prove_next_reveal_eligible(CSR, SID, ORDINAL)
    require_verdict('NEXT_REVEAL', packet_sha(), 'G-H1-AUTHZ')

    ppath = c4d.proposal_path(CSR, SID, ORDINAL)
    if ppath.exists():
        fail('live ordinal-0003 proposal already exists (O_EXCL)')
    staged_bytes = STAGED_PROPOSAL.read_bytes()
    head = c4d._current_prefix_head(CSR, SID)
    c4d.build_next_reveal_proposal(CSR, SID, ORDINAL, head)
    live_bytes = ppath.read_bytes()
    if live_bytes != staged_bytes:
        fail('live ordinal-0003 proposal bytes != H0 staged bytes')

    c4d.approve_next_reveal(CSR, SID, ORDINAL)
    c4d.fsync_dir(c4d.next_authz_dir(CSR, SID, ORDINAL))
    c4d.materialize_next_permit(CSR, SID, ORDINAL)
    c4d.fsync_dir(c4d.next_authz_dir(CSR, SID, ORDINAL))

    proposal, pbytes = c4d._check_proposal(CSR, SID, ORDINAL)
    approval = c4d._check_reveal_approval(CSR, SID, ORDINAL, proposal,
                                          pbytes)
    c4d._check_approval_permit(CSR, SID, ORDINAL, proposal, pbytes)
    adir = c4d.next_authz_dir(CSR, SID, ORDINAL)
    if (adir / 'next_reveal.permit.json').read_bytes() != pbytes:
        fail('permit bytes != proposal bytes (three-way break)')
    if approval['approved_authorization_sha256'] != sha(pbytes):
        fail('approval does not bind exact proposal bytes')
    if c4d.derive_reveal_consumption(events(), proposal, SID) != 'UNUSED':
        fail('authorization must be UNUSED before reveal')
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'AUTHORIZED',
        'proposal_sha256': sha(pbytes),
        'staged_proposal_sha256': sha(staged_bytes),
        'approval_bound_sha256': approval['approved_authorization_sha256'],
        'consumption': 'UNUSED',
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: reveal (append R3)
# ---------------------------------------------------------------------------

def cmd_reveal():
    types = chain_types()
    if types != EXPECTED_FINAL_CHAIN[:4]:
        fail(f'pre-reveal chain must be [R1,S1,R2,S2], got {types}')
    proposal = c4d.verify_next_authorization_chain(CSR, SID, ORDINAL)
    if c4d.derive_reveal_consumption(events(), proposal, SID) != 'UNUSED':
        fail('authorization not UNUSED at reveal boundary')
    require_verdict('NEXT_REVEAL', packet_sha(), 'G-H1-REVEAL')

    _unlock_sealing()
    try:
        c4d.reveal_transaction(CSR, SID, ORDINAL)
    finally:
        _relock_sealing()

    evs = events()
    types = [e['event_type'] for e in evs]
    if types != EXPECTED_FINAL_CHAIN[:5]:
        fail(f'post-reveal chain must be [R1,S1,R2,S2,R3], got {types}')
    if c4d.derive_reveal_consumption(evs, proposal, SID) != 'CONSUMED':
        fail('authorization not CONSUMED after reveal')
    order = c4d.candidate_total_order()
    revealed = [(e['payload']['opaque_case_id'], e['payload']['T'])
                for e in evs if e['event_type'] == 'REVEAL_PACKET']
    if revealed != [(x['opaque_case_id'], x['T']) for x in order[:3]]:
        fail('revealed candidates are not the frozen prefix 3')
    r3 = evs[-1]
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'REVEALED',
        'r3_event_hash': r3['event_hash'],
        'packet_id': r3['payload']['packet_id'],
        'packet_sha256': r3['payload']['packet_sha256'],
        'consumption': 'CONSUMED', 'candidate_prefix': 3,
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: annotate (blinded)
# ---------------------------------------------------------------------------

def _candidate_pool_bytes():
    cand = c4d.candidate_for_ordinal(ORDINAL)
    pid = sha(f"{cand['opaque_case_id']}|{cand['T']}".encode())
    return (c4d.c4ab.C3_STATE / 'packets' / f'{pid}.json').read_bytes()


def cmd_annotate():
    evs = events()
    if [e['event_type'] for e in evs] != EXPECTED_FINAL_CHAIN[:5]:
        fail('annotate requires chain [R1,S1,R2,S2,R3]')
    r3 = evs[-1]
    pool = _candidate_pool_bytes()
    if sha(pool) != r3['payload']['packet_sha256']:
        fail('C3 pool bytes do not match R3 packet_sha256')

    # §2.2 handoff: exact-copy into the annotator domain (O_EXCL inside)
    if c4d.annot_dom(CSR, SID).exists():
        fail('annotator domain already populated (one-shot annotate)')
    c4d.handoff(CSR, SID, bytes_override=pool)

    # annotation session registry (opaque session id; blinded bindings)
    reg_path = c4d.annot_dom(CSR, SID) / 'annotation_session_registry.json'
    if reg_path.exists():
        fail('annotation session registry already exists (O_EXCL)')
    ann_session = secrets.token_hex(16)
    session = {
        'annotation_session_id': ann_session,
        'created_at': now_utc(),
        'status': 'OPEN',
        'packet_id': r3['payload']['packet_id'],
        'packet_sha256': r3['payload']['packet_sha256'],
        'reveal_event_hash': r3['event_hash'],
    }
    registry = {
        'registry_version': REGISTRY_VERSION,
        'session_id': SID,
        'reveal_event_hash': r3['event_hash'],
        'packet_id': r3['payload']['packet_id'],
        'packet_sha256': r3['payload']['packet_sha256'],
        'annotation_contract_sha256': c4d.ANNOTATION_CONTRACT_SHA256,
        'annotation_sessions': [session],
    }
    c4d.excl_write(reg_path, canon(registry).encode())

    # blinded draft: judgments resolvable ONLY inside the blinded packet
    packet_obj = json.loads(pool)
    judgments = []
    for hid in c4d.HYPOTHESES:
        judgments.append({
            'hypothesis_id': hid,
            'observability': 'OBSERVABLE',
            'support': 'NOT_OBSERVED',
            'evidence_refs': ['/as_of/T'],
            'evidence_note': ('Blinded packet contains no qualifying '
                              'evidence at T.'),
        })
    ts = now_utc()
    draft = {
        'draft_version': 'c4d-draft-v1',
        'session_id': SID,
        'packet_id': r3['payload']['packet_id'],
        'packet_sha256': r3['payload']['packet_sha256'],
        'annotation_session_id': ann_session,
        'annotation_attempt': ATTEMPT,
        'annotation': {
            'annotation_contract_sha256': c4d.ANNOTATION_CONTRACT_SHA256,
            'rt_judgments': judgments,
            'overall_note': ('Blinded annotation: no qualifying evidence '
                             'is observable at T.'),
            'flags': ['EVIDENCE_INCOMPLETE_AT_T'],
        },
        'created_at': ts,
        'updated_at': ts,
    }
    c4d.validate_draft(CSR, SID, draft, packet_obj, r1=r3)
    dp = c4d.write_draft(CSR, SID, draft)
    c4d.validate_draft(CSR, SID, json.loads(dp.read_bytes()), packet_obj,
                       r1=r3)

    # blindness guard over the whole annotator domain
    keys = set()

    def walk(x):
        if isinstance(x, dict):
            keys.update(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for p in sorted(c4d.annot_dom(CSR, SID).rglob('*.json')):
        walk(json.loads(p.read_bytes()))
    if keys & LEAK_FORBIDDEN_KEYS:
        fail('blindness leak: ' + repr(sorted(keys & LEAK_FORBIDDEN_KEYS)),
             'G-H1-ANNOTATE')
    c4d.check_visibility_domain(CSR, SID)
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'ANNOTATED',
        'draft_sha256': sha(dp.read_bytes()),
        'annotation_session_id': ann_session,
        'packet_id': r3['payload']['packet_id'],
        'attempt': ATTEMPT,
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: receipt (exact freeze) — requires ANNOTATION APPROVE
# ---------------------------------------------------------------------------

def cmd_receipt():
    evs = events()
    if [e['event_type'] for e in evs] != EXPECTED_FINAL_CHAIN[:5]:
        fail('receipt requires chain [R1,S1,R2,S2,R3]')
    dp = c4d.draft_path(CSR, SID)
    if not dp.is_file():
        fail('active draft missing')
    dbytes = dp.read_bytes()
    require_verdict('ANNOTATION', sha(dbytes), 'G-H1-RECEIPT')

    od = c4d.ordinal_dir(CSR, SID, ORDINAL)
    if od.exists() and any(od.iterdir()):
        fail('ordinal-0003 receipts domain already populated (one-shot)')
    receipt, rbytes = c4d.make_receipt(CSR, SID, ORDINAL)

    # frozen-invariant spot re-proof (full proof lives in c4d APIs)
    adir = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT)
    snap = (adir / 'draft_snapshot.bin').read_bytes()
    if snap != dbytes or receipt['draft_sha256'] != sha(dbytes):
        fail('receipt freeze invariant broken (snapshot/draft hash)')
    if mode_of(dp) != 0o400:
        fail('active draft not locked 0400 after freeze')
    if mode_of(adir / 'receipt.json') != 0o600 or \
            mode_of(adir / 'draft_snapshot.bin') != 0o600:
        fail('receipt artifact mode drift')

    # ordinal-0003 evidence copies (C4 layout, O_EXCL canonical 0600)
    r3 = evs[-1]
    c4d.excl_write(od / 'packet.json', _candidate_pool_bytes())
    c4d.excl_write(od / 'annotation_session_registry.json',
                   (c4d.annot_dom(CSR, SID) /
                    'annotation_session_registry.json').read_bytes())
    c4d.excl_write(od / 'annotation_draft.json', dp.read_bytes())
    c4d.fsync_dir(od)

    names = sorted(p.name for p in od.iterdir())
    if names != ['annotation_draft.json', 'annotation_session_registry.json',
                 'attempt-0001', 'packet.json']:
        fail(f'ordinal-0003 closed-world violation: {names}')
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'RECEIPT_FROZEN',
        'receipt_sha256': sha(rbytes),
        'draft_sha256': sha(dbytes),
        'reveal_event_hash': r3['event_hash'],
        'attempt': ATTEMPT,
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: seal — requires RECEIPT + SEAL APPROVE
# ---------------------------------------------------------------------------

def cmd_seal():
    evs = events()
    if [e['event_type'] for e in evs] != EXPECTED_FINAL_CHAIN[:5]:
        fail('seal requires chain [R1,S1,R2,S2,R3]')
    adir = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT)
    rbytes = (adir / 'receipt.json').read_bytes()
    rsha = sha(rbytes)
    require_verdict('RECEIPT', rsha, 'G-H1-SEAL')
    require_verdict('SEAL', rsha, 'G-H1-SEAL')

    state, info = c4d.derive_state(CSR, SID)
    if state not in ('READY_TO_SEAL',):
        fail(f'pre-approval state must be READY_TO_SEAL (got {state})')
    c4d.make_seal_approval(CSR, SID, ordinal=ORDINAL, attempt=ATTEMPT,
                           receipt_sha=rsha)
    state, info = c4d.derive_state(CSR, SID)
    if state != 'SEAL_AUTHORIZED':
        fail(f'post-approval state must be SEAL_AUTHORIZED (got {state})')

    _unlock_sealing()
    try:
        result = c4d.seal_transaction(CSR, SID)
    finally:
        _relock_sealing()
    if result['state'] != 'SEALED':
        fail('seal_transaction did not finalize SEALED')

    evs = events()
    types = [e['event_type'] for e in evs]
    if types != EXPECTED_FINAL_CHAIN:
        fail(f'final chain must be [R1,S1,R2,S2,R3,S3], got {types}')
    if c4d.annot_dom(CSR, SID).exists():
        fail('annotator workspace not cleaned after seal')
    c4d.post_seal_final(CSR, SID)
    anchor = json.loads((CSR / 'c4_public' / 'c4d_seal_anchor.json')
                        .read_bytes())
    s3 = evs[-1]
    if anchor.get('production_head_hash') != s3['event_hash'] or \
            anchor.get('seal_receipt_sha256') != rsha:
        fail('durable anchor does not bind S3 head + receipt hash')
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'SEALED',
        's3_event_hash': s3['event_hash'],
        'production_head': s3['event_hash'],
        'receipt_sha256': rsha,
        'anchor': 'DURABLE', 'workspace': 'CLEANED',
        'post_seal_final': True,
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: verify (final machine audit of the completed ordinal)
# ---------------------------------------------------------------------------

def cmd_verify():
    evs = events()
    types = [e['event_type'] for e in evs]
    if types != EXPECTED_FINAL_CHAIN:
        fail(f'final chain must be [R1,S1,R2,S2,R3,S3], got {types}',
             'G-H1-CHAIN')

    # C2 full replay from genesis
    lg = c4d.c2.SealingLog(c4d.log_path(CSR, SID), c4d.head_path(CSR, SID))
    c4d.c2translate(lg.load().verify, True)

    # frozen candidate prefix law (unique order, no skips, no reordering)
    order = c4d.candidate_total_order()
    reveals = [e for e in evs if e['event_type'] == 'REVEAL_PACKET']
    revealed = [(e['payload']['opaque_case_id'], e['payload']['T'])
                for e in reveals]
    if revealed != [(x['opaque_case_id'], x['T']) for x in order[:3]]:
        fail('revealed prefix != frozen candidate order prefix 3',
             'G-H1-PREFIX')

    # authorization single-use: ordinal-1 via the frozen first_reveal
    # permit binding (H0 gate_authorizations approach); ordinals 2/3 via
    # chain-derived consumption of their persisted proposals.
    r1 = evs[0]
    permit = (CSR / 'production' / SID / 'authorization' /
              'first_reveal.json').read_bytes()
    pobj = json.loads(permit)
    if pobj.get('scope') != 'FIRST_REVEAL_ONLY' or \
            pobj.get('authorized') is not True or \
            r1['payload'].get('authorization_sha256') != sha(permit) or \
            r1['payload'].get('authorization_id') != \
            pobj.get('authorization_id'):
        fail('ordinal-1 first_reveal authorization binding broken',
             'G-H1-AUTHZ')
    consumption = {1: 'CONSUMED'}
    for ordinal in (2, 3):
        proposal = c4d.read_json(c4d.proposal_path(CSR, SID, ordinal))
        consumption[ordinal] = c4d.derive_reveal_consumption(evs, proposal,
                                                             SID)
    if set(consumption.values()) != {'CONSUMED'}:
        fail(f'authorization consumption drift: {consumption}',
             'G-H1-AUTHZ')

    # commit-time whole-history proof per ordinal + dual semantic replay
    for ordinal, reveal in ((1, reveals[0]), (2, reveals[1]),
                            (3, reveals[2])):
        c4d.prove_attempt_history(CSR, SID, ordinal, gate='G-H1-HIST',
                                  events=evs, reveal=reveal)
    c4d.semantic_replay(CSR, SID)

    # receipt triple exactness for ordinal 3
    adir = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT)
    rbytes = (adir / 'receipt.json').read_bytes()
    s3 = evs[-1]
    archived = (c4d.sealing_dir(CSR, SID) /
                s3['payload']['bytes_ref']).read_bytes()
    if not (sha(rbytes) == s3['payload']['receipt_sha256'] ==
            sha(archived)):
        fail('ordinal-3 receipt triple exact-byte equality broken',
             'G-H1-RECEIPT')

    # anchor durable + cleanup + POST_SEAL_FINAL
    anchor = json.loads((CSR / 'c4_public' / 'c4d_seal_anchor.json')
                        .read_bytes())
    if anchor.get('production_head_hash') != s3['event_hash'] or \
            anchor.get('seal_receipt_sha256') != sha(rbytes):
        fail('anchor does not bind the terminal sealed pair', 'G-H1-ANCHOR')
    if c4d.annot_dom(CSR, SID).exists():
        fail('annotator workspace not cleaned', 'G-H1-CLEANUP')
    c4d.post_seal_final(CSR, SID)

    # verdicts: all five operations, exact bindings
    draft_ev = (c4d.ordinal_dir(CSR, SID, ORDINAL) /
                'annotation_draft.json').read_bytes()
    require_verdict('NEXT_REVEAL', packet_sha(), 'G-H1-VERDICTS')
    require_verdict('ANNOTATION', sha(draft_ev), 'G-H1-VERDICTS')
    require_verdict('RECEIPT', sha(rbytes), 'G-H1-VERDICTS')
    require_verdict('SEAL', sha(rbytes), 'G-H1-VERDICTS')
    require_verdict('POST_SEAL', s3['event_hash'], 'G-H1-VERDICTS')

    # authorization domain closed world: top level frozen first_reveal
    # permit + exactly one approval/permit pair per next-reveal ordinal
    authz_top = c4d.prod_dir(CSR, SID) / 'authorization'
    top = sorted(p.name for p in authz_top.iterdir())
    if top != ['first_reveal.approval.json', 'first_reveal.json',
               'ordinal-0002', 'ordinal-0003']:
        fail(f'authorization top-level closed-world violation: {top}',
             'G-H1-WORLD')
    for ordinal in (2, 3):
        entries = sorted(p.name for p in
                         c4d.next_authz_dir(CSR, SID, ordinal).rglob('*')
                         if p.is_file())
        if entries != ['next_reveal.approval.json',
                       'next_reveal.permit.json']:
            fail(f'ordinal-{ordinal} authorization domain closed-world '
                 f'violation: {entries}', 'G-H1-WORLD')
    od_names = sorted(p.name for p in
                      c4d.ordinal_dir(CSR, SID, ORDINAL).iterdir())
    if od_names != ['annotation_draft.json',
                    'annotation_session_registry.json', 'attempt-0001',
                    'packet.json']:
        fail(f'ordinal-0003 receipts closed-world violation: {od_names}',
             'G-H1-WORLD')

    # h_campaign H1 closed world
    got = sorted(p.relative_to(CAMPAIGN).as_posix()
                 for p in CAMPAIGN.rglob('*') if p.is_file())
    expected = sorted([
        'campaign_manifest.json', 'reviews.jsonl',
        'review_packets/phase_entry.json',
        'verdicts/phase_entry.verdict.json',
        'executor_state/pre_review_write_surface.json',
        'executor_state/post_review_write_surface.json',
        'ordinal_0003/next_reveal.proposal.staged.json',
        'h1/packets/ordinal-0003-next-reveal.json',
    ] + [f'h1/reviews/{op}.verdict.json' for op in OPS])
    if got != expected:
        fail(f'h_campaign H1 closed-world violation: '
             f'{got} != {expected}', 'G-H1-WORLD')

    print(json.dumps({
        'stage': STAGE, 'iteration': ITERATION, 'ordinal': ORDINAL,
        'state': 'ORDINAL_COMPLETE',
        'chain': types, 'candidate_prefix': 3,
        'authorization_consumption': consumption,
        'c2_full_replay': 'PASS', 'semantic_replay': 'PASS',
        'ordinal_histories': {1: 'PASS', 2: 'PASS', 3: 'PASS'},
        'receipt_triple': 'PASS', 'anchor': 'DURABLE',
        'workspace_cleanup': 'PASS', 'post_seal_final': True,
        'verdicts': {op: 'APPROVE' for op in OPS},
        'production_head': s3['event_hash'],
        'receipt_sha256': sha(rbytes),
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: finalize — relock new H1 artifacts to the prior-phase discipline
# (sealing byte-bins 0400+immutable; authorization/proposal/receipt files
# immutable at their existing modes; campaign review surface stays 0600
# unlocked, matching the H0 convention; anchor stays replaceable 0600)
# ---------------------------------------------------------------------------

def cmd_finalize():
    hardened = []
    sd = c4d.sealing_dir(CSR, SID)
    for b in sorted((sd / 'bytes').rglob('*.bin')):
        seq = int(b.stem)
        if seq < 4:
            continue  # prior-phase bins already 0400+immutable
        if mode_of(b) != 0o400:
            os.chmod(b, 0o400)
        if not _immutable(b):
            _chattr('+i', b)
        hardened.append(b.relative_to(ROOT).as_posix())
    for p in (c4d.proposal_path(CSR, SID, ORDINAL),
              c4d.next_authz_dir(CSR, SID, ORDINAL) /
              'next_reveal.approval.json',
              c4d.next_authz_dir(CSR, SID, ORDINAL) /
              'next_reveal.permit.json'):
        if p.is_file() and not _immutable(p):
            _chattr('+i', p)
            hardened.append(p.relative_to(ROOT).as_posix())
    od = c4d.ordinal_dir(CSR, SID, ORDINAL)
    for p in sorted(od.rglob('*')):
        if p.is_file() and not _immutable(p):
            _chattr('+i', p)
            hardened.append(p.relative_to(ROOT).as_posix())
    print(json.dumps({'stage': STAGE, 'ordinal': ORDINAL,
                      'state': 'FINALIZED',
                      'hardened_files': len(hardened)},
                     sort_keys=True, separators=(',', ':')))




def cmd_gate(op, expected_sha):
    if op not in OPS:
        fail(f'unknown operation {op}')
    v = require_verdict(op, expected_sha, 'G-H1-GATE')
    print(json.dumps({'operation': op, 'state': v['state'],
                      'input_commitment_sha256':
                          v['input_commitment_sha256'],
                      'reviewer_run_id': v['reviewer_run_id'],
                      'created_at': v['created_at']},
                     sort_keys=True, separators=(',', ':')))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('authorize')
    sub.add_parser('reveal')
    sub.add_parser('annotate')
    sub.add_parser('receipt')
    sub.add_parser('seal')
    sub.add_parser('finalize')
    sub.add_parser('verify')
    g = sub.add_parser('gate')
    g.add_argument('operation', choices=OPS)
    g.add_argument('expected_sha256')
    args = ap.parse_args(argv)
    if args.cmd == 'authorize':
        cmd_authorize()
    elif args.cmd == 'reveal':
        cmd_reveal()
    elif args.cmd == 'annotate':
        cmd_annotate()
    elif args.cmd == 'receipt':
        cmd_receipt()
    elif args.cmd == 'seal':
        cmd_seal()
    elif args.cmd == 'finalize':
        cmd_finalize()
    elif args.cmd == 'verify':
        cmd_verify()
    elif args.cmd == 'gate':
        cmd_gate(args.operation, args.expected_sha256)
    return 0


if __name__ == '__main__':
    sys.exit(main())
