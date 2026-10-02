#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase H2 — reviewer-gated production executor for ordinal 4 (canary).

H1 executor (csr8_phase_h1_ordinal3.py) 的 ordinal-4 延伸，新增
NATIONAL_CTX_V1 证据层（自 NC 冻结 b78ae58 起，ordinal>=4 的
evidence_profile = BASE_V1+NATIONAL_CTX_V1）。

本模块是唯一 H2 生产执行入口，逐边界 fail-closed：

  每个不可逆动作之前，机器实测两件事：
    (1) machine gates PASS（冻结 c4d 事务 API 自带的前置证明）
    (2) 独立 reviewer 对该 operation 的 exact-hash APPROVE verdict
        （closed-world 10 字段、绑定 input_commitment_sha256、0600）

  子命令（严格按阶段顺序执行，各自一次性）：
    prepare  构建 h2 NEXT_REVEAL 评审 packet（canonical 0600，O_EXCL；
             嵌入冻结 §7 构造的 proposal 对象 + NC 扩展绑定）
    gate <op> <sha>   只读校验 verdict 文件（不写任何东西）
    authorize NEXT_REVEAL verdict → 冻结 builder 落 live proposal
              （必须与 packet 嵌入对象 canon 相等）→ approve_next_reveal
              → materialize_next_permit
    reveal    授权三方一致复证 → reveal_transaction(ordinal=4)
    annotate  handoff（C3 池 exact bytes）→ annotation session registry
              → NATIONAL_CTX_V1 sidecar（冻结 NC builder 子进程产出，
              packet 绑定 + commitment 等于冻结 preflight 承诺）→
              blinded stock-layer 枚举（selector 侧 join 只输出枚举，
              永不回显身份）→ blinded draft（H01–H06 契约判断）→
              write_draft → validate_draft → context_support_map
              （closed-world 5 字段，refs ⊆ context_record_id）→
              全域盲态键扫描
    receipt   ANNOTATION verdict（绑定 draft exact hash）→
              make_receipt(4) → ordinal-0004 证据拷贝
              （packet/registry/draft/national_ctx_v1/context_support_map，
              O_EXCL 0600）
    seal      RECEIPT + SEAL verdicts（绑定 receipt exact hash）→
              make_seal_approval → seal_transaction（replay →
              anchor durable → cleanup → POST_SEAL_FINAL）
    verify    终态全量机器实测（8 事件链/前缀 4/消费域/ordinal 1–4
              历史/replay/anchor/cleanup/全部 verdicts/授权域闭世界/
              h_campaign H1+H2 闭世界/NC 绑定复证）
    finalize  新增 H2 产物加固（sealing bins seq>=6 0400+immutable；
              proposal/authorization/ordinal-0004 receipts immutable；
              campaign 审查面保持 0600 不加锁，沿用 H1 约定）

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
import csr8_phase_c_annotation_seal as c4ab_mod  # noqa: E402

ROOT = c4d.ROOT
CSR = c4d.REAL_CSR
SID = c4d.REAL_SESSION
ORDINAL = 4
ATTEMPT = 1

RUN_ID = 'audit_20261002080000000_h2'
HOST_ID = 'RainYun-c438TDGn'
STAGE, ITERATION = 'H2', 1

CID = 'hc-46195669974db3b25610bef4d047d927'
CAMPAIGN = CSR / 'h_campaign' / CID
PACKET = CAMPAIGN / 'h2' / 'packets' / 'ordinal-0004-next-reveal.json'
REVIEWS = CAMPAIGN / 'h2' / 'reviews'
SIDECAR = CAMPAIGN / 'h2' / 'national_context' / \
    'ordinal-0004-national-ctx-v1.json'
SUPPORT_MAP = CAMPAIGN / 'h2' / 'context_support_map.json'
NC_BUILDER = ROOT / 'scripts' / 'build_national_capital_context.py'
# NC-ERRATUM-1 (H2-CANARY-FIX1): annotate builds sidecars with the v1e
# successor builder (explicit stock_layer_summary enum, in-band); the
# frozen v1 builder above remains the verifier for the sealed prefix.
NC_BUILDER_V1E = (ROOT / 'scripts'
                  / 'build_national_capital_context_v1e.py')
NC_PREFLIGHT_EVIDENCE = ROOT / 'docs' / 'audit' / 'evidence' / \
    'national_capital_context_preflight.json'
NC_FREEZE_EVIDENCE = ROOT / 'docs' / 'audit' / 'evidence' / \
    'national_capital_context_extension_frozen.json'
EVIDENCE_PROFILE = 'BASE_V1+NATIONAL_CTX_V1'

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

EXPECTED_FINAL_CHAIN = ['REVEAL_PACKET', 'SEAL_ANNOTATION',
                        'REVEAL_PACKET', 'SEAL_ANNOTATION',
                        'REVEAL_PACKET', 'SEAL_ANNOTATION',
                        'REVEAL_PACKET', 'SEAL_ANNOTATION']

SUPPORT_MAP_TOP = {'version', 'ordinal', 'packet_sha256', 'context_sha256',
                   'judgments'}
SUPPORT_MAP_VERSION = 'csr8-national-context-support-v1'


def fail(msg, gate='G-H2'):
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
# stage: prepare (campaign-side NEXT_REVEAL review packet)
# ---------------------------------------------------------------------------

def _expected_proposal(head):
    """Deterministic reconstruction of the frozen §7 proposal object for
    ordinal 4 WITHOUT persisting anything (the live file is written only
    inside authorize by the frozen builder; authorize re-proves byte
    equality)."""
    cand = c4d.candidate_for_ordinal(ORDINAL)
    packet_id = sha(f"{cand['opaque_case_id']}|{cand['T']}".encode())
    packet_file = c4ab_mod.c4ab.C3_STATE / 'packets' / f'{packet_id}.json'
    return {
        'authorization_version': c4d.REVEAL_AUTHZ_VERSION,
        'scope': 'NEXT_REVEAL_ONLY',
        'reveal_ordinal': ORDINAL,
        'session_id': SID,
        'sealed_prefix_head': head,
        'c3_manifest_commitment': c4ab_mod.c4ab.C3_COMMITMENT,
        'candidate_packet_id': packet_id,
        'candidate_packet_sha256': sha(packet_file.read_bytes()),
        'authorized': True,
        'authorization_id': f'synth-authz-ordinal-{ORDINAL}',
        'created_at': '2099-01-02T00:00:00Z',
    }


def cmd_prepare():
    types = chain_types()
    if types != EXPECTED_FINAL_CHAIN[:6]:
        fail(f'prepare requires closed chain [R1..S3] (6 events), '
             f'got {types}')
    c4d.prove_next_reveal_eligible(CSR, SID, ORDINAL)

    if PACKET.exists():
        fail('h2 NEXT_REVEAL packet already exists (O_EXCL)')
    head = c4d._current_prefix_head(CSR, SID)
    proposal = _expected_proposal(head)
    cand = c4d.candidate_for_ordinal(ORDINAL)

    # NC extension bindings (frozen at b78ae58)
    if not NC_FREEZE_EVIDENCE.is_file():
        fail('NC freeze marker missing', 'G-H2-PREP')
    frozen = json.loads(NC_FREEZE_EVIDENCE.read_bytes())
    if frozen.get('status') != 'NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN' \
            or frozen.get('effective_from_ordinal') != ORDINAL:
        fail('NC freeze marker does not unlock ordinal 4', 'G-H2-PREP')
    pre = json.loads(NC_PREFLIGHT_EVIDENCE.read_bytes())
    if pre.get('ordinal') != ORDINAL or \
            pre.get('packet_id') != proposal['candidate_packet_id'] or \
            pre.get('status') != 'PASS':
        fail('NC preflight evidence does not bind this candidate packet '
             '(ordinal/packet_id/status)', 'G-H2-PREP')

    packet = {
        'campaign_id': CID,
        'review_version': 'csr8-h-review-v2',
        'operation': 'NEXT_REVEAL',
        'ordinal': ORDINAL,
        'evidence_profile': EVIDENCE_PROFILE,
        'candidate_prefix_length': len(types) // 2,
        'open_reveals': 0,
        'reveal_count': len(types) // 2,
        'seal_count': len(types) // 2,
        'production_head': head,
        'prohibited': ['outcome', 'identity', 'future_data'],
        'machine_prerequisites': {
            'ordinal': ORDINAL,
            'chain': types,
            'candidate': {
                'opaque_case_id': cand['opaque_case_id'],
                'T': cand['T'],
            },
            'candidate_packet_id': proposal['candidate_packet_id'],
            'candidate_packet_sha256':
                proposal['candidate_packet_sha256'],
            'candidate_prefix_length': len(types) // 2,
            'open_reveals': 0,
            'production_head': head,
            'reveal_count': len(types) // 2,
            'seal_count': len(types) // 2,
        },
        'proposal': proposal,
        'proposal_sha256': sha(canon(proposal).encode()),
        'national_context_extension': {
            'freeze_marker_sha256': sha(NC_FREEZE_EVIDENCE.read_bytes()),
            'frozen_at_commit': frozen.get('audited_commit'),
            'context_preflight_sha256': sha(NC_PREFLIGHT_EVIDENCE.read_bytes()),
            'context_commitment_sha256':
                pre.get('context_commitment_sha256'),
            'sidecar_path': SIDECAR.relative_to(ROOT).as_posix(),
            'resume_gate_state': 'READY_FOR_ORDINAL_4',
        },
    }
    raw = canon(packet).encode()
    PACKET.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    c4d.excl_write(PACKET, raw)
    os.chmod(PACKET, 0o600)
    if json.loads(PACKET.read_bytes()) != packet or \
            PACKET.read_bytes() != raw:
        fail('prepared packet is not the canonical bytes (O_EXCL re-read)')
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'PACKET_PREPARED',
        'packet_sha256': sha(raw),
        'proposal_sha256': packet['proposal_sha256'],
        'candidate_packet_id': proposal['candidate_packet_id'],
        'context_commitment_sha256':
            pre.get('context_commitment_sha256'),
        'evidence_profile': EVIDENCE_PROFILE,
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: authorize
# ---------------------------------------------------------------------------

def cmd_authorize():
    types = chain_types()
    if types != EXPECTED_FINAL_CHAIN[:6]:
        fail(f'pre-authorize chain must be [R1,S1,R2,S2,R3,S3], '
             f'got {types}')
    c4d.prove_next_reveal_eligible(CSR, SID, ORDINAL)
    require_verdict('NEXT_REVEAL', packet_sha(), 'G-H2-AUTHZ')

    ppath = c4d.proposal_path(CSR, SID, ORDINAL)
    if ppath.exists():
        fail('live ordinal-0004 proposal already exists (O_EXCL)')
    head = c4d._current_prefix_head(CSR, SID)
    c4d.build_next_reveal_proposal(CSR, SID, ORDINAL, head)
    live = json.loads(ppath.read_bytes())
    pkt_obj = json.loads(PACKET.read_bytes())
    if canon(live) != canon(pkt_obj['proposal']):
        fail('live ordinal-0004 proposal != packet-embedded proposal '
             '(canon inequality)')
    if sha(canon(live).encode()) != pkt_obj['proposal_sha256']:
        fail('live ordinal-0004 proposal sha != packet proposal_sha256')

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
        'approval_bound_sha256': approval['approved_authorization_sha256'],
        'consumption': 'UNUSED',
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: reveal (append R4)
# ---------------------------------------------------------------------------

def cmd_reveal():
    types = chain_types()
    if types != EXPECTED_FINAL_CHAIN[:6]:
        fail(f'pre-reveal chain must be [R1,S1,R2,S2,R3,S3], got {types}')
    proposal = c4d.verify_next_authorization_chain(CSR, SID, ORDINAL)
    if c4d.derive_reveal_consumption(events(), proposal, SID) != 'UNUSED':
        fail('authorization not UNUSED at reveal boundary')
    require_verdict('NEXT_REVEAL', packet_sha(), 'G-H2-REVEAL')

    _unlock_sealing()
    try:
        c4d.reveal_transaction(CSR, SID, ORDINAL)
    finally:
        _relock_sealing()

    evs = events()
    types = [e['event_type'] for e in evs]
    if types != EXPECTED_FINAL_CHAIN[:7]:
        fail(f'post-reveal chain must be [R1..S3,R4], got {types}')
    if c4d.derive_reveal_consumption(evs, proposal, SID) != 'CONSUMED':
        fail('authorization not CONSUMED after reveal')
    order = c4d.candidate_total_order()
    revealed = [(e['payload']['opaque_case_id'], e['payload']['T'])
                for e in evs if e['event_type'] == 'REVEAL_PACKET']
    if revealed != [(x['opaque_case_id'], x['T']) for x in order[:4]]:
        fail('revealed candidates are not the frozen prefix 4')
    r4 = evs[-1]
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'REVEALED',
        'r4_event_hash': r4['event_hash'],
        'packet_id': r4['payload']['packet_id'],
        'packet_sha256': r4['payload']['packet_sha256'],
        'consumption': 'CONSUMED', 'candidate_prefix': 4,
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: annotate (blinded, with NATIONAL_CTX_V1)
# ---------------------------------------------------------------------------

def _candidate_pool_bytes():
    cand = c4d.candidate_for_ordinal(ORDINAL)
    pid = sha(f"{cand['opaque_case_id']}|{cand['T']}".encode())
    return (c4ab_mod.c4ab.C3_STATE / 'packets' / f'{pid}.json').read_bytes()


def _validate_support_map(m, sidecar, pool_sha):
    if not isinstance(m, dict) or set(m) != SUPPORT_MAP_TOP:
        fail(f'support map closed-world schema violation: '
             f'{sorted(m) if isinstance(m, dict) else type(m)}',
             'G-H2-SUPPORT')
    if m['version'] != SUPPORT_MAP_VERSION or m['ordinal'] != ORDINAL \
            or sidecar.get('ordinal') != ORDINAL:
        fail('support map version/ordinal binding mismatch',
             'G-H2-SUPPORT')
    for k in ('packet_sha256', 'context_sha256'):
        v = m[k]
        if not isinstance(v, str) or len(v) != 64 or \
                any(ch not in '0123456789abcdef' for ch in v):
            fail(f'support map {k} not a sha256 hex', 'G-H2-SUPPORT')
    if m['packet_sha256'] != pool_sha:
        fail('support map does not bind the revealed pool packet bytes',
             'G-H2-SUPPORT')
    if m['context_sha256'] != sidecar['context_commitment_sha256']:
        fail('support map does not bind the sidecar context commitment',
             'G-H2-SUPPORT')
    if set(m['judgments']) != set(c4d.HYPOTHESES):
        fail('support map judgments must cover exactly the frozen '
             'hypotheses', 'G-H2-SUPPORT')
    ids = {r['context_record_id']
           for r in sidecar['stock_capital_records']
           + sidecar['market_etf_records']}
    refs = [x for j in m['judgments'].values() for x in j]
    if not all(isinstance(x, str) and x in ids for x in refs):
        fail('support map references unknown context records',
             'G-H2-SUPPORT')
    # NC-ERRATUM-1 (H2-CANARY-FIX1 item 4): the SAME context record MAY
    # support several hypotheses (one stock record legitimately backs
    # rt_H01/rt_H02/rt_H05/rt_H06); duplicates are only forbidden
    # WITHIN a single hypothesis reference list.
    for hid, jrefs in m['judgments'].items():
        if len(jrefs) != len(set(jrefs)):
            fail(f'support map has duplicate references within '
                 f'{hid}', 'G-H2-SUPPORT')
    return len(refs)


def cmd_annotate():
    evs = events()
    if [e['event_type'] for e in evs] != EXPECTED_FINAL_CHAIN[:7]:
        fail('annotate requires chain [R1,S1,R2,S2,R3,S3,R4]')
    r4 = evs[-1]
    pool = _candidate_pool_bytes()
    if sha(pool) != r4['payload']['packet_sha256']:
        fail('C3 pool bytes do not match R4 packet_sha256')

    # §2.2 handoff: exact-copy into the annotator domain (O_EXCL inside)
    if c4d.annot_dom(CSR, SID).exists():
        fail('annotator domain already populated (one-shot annotate)')
    c4d.handoff(CSR, SID, bytes_override=pool)

    # NATIONAL_CTX_V1e sidecar via the erratum builder (NC-ERRATUM-1:
    # explicit stock_layer_summary enum in-band; NO selector-side
    # derivation is permitted anywhere in the annotation path —
    # H2-CANARY-FIX1 item 2)
    if SIDECAR.exists():
        fail('sidecar already exists (O_EXCL)')
    SIDECAR.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    res = subprocess.run(
        [sys.executable, str(NC_BUILDER_V1E), '--ordinal', str(ORDINAL),
         '--out', str(SIDECAR)],
        check=True, capture_output=True, text=True, cwd=str(ROOT))
    if not SIDECAR.is_file():
        fail('NC builder did not produce the sidecar', 'G-H2-ANNOTATE')
    os.chmod(SIDECAR, 0o600)
    sidecar = json.loads(SIDECAR.read_bytes())
    # determinism: the erratum builder must reproduce byte-identical
    # output
    import tempfile as _tf
    _tmp = Path(_tf.mkdtemp()) / 'sidecar.json'
    subprocess.run(
        [sys.executable, str(NC_BUILDER_V1E), '--ordinal', str(ORDINAL),
         '--out', str(_tmp)],
        check=True, capture_output=True, text=True, cwd=str(ROOT))
    if _tmp.read_bytes() != SIDECAR.read_bytes():
        fail('sidecar is not deterministic (rebuild differs)',
             'G-H2-ANNOTATE')
    if sidecar.get('packet_id') != r4['payload']['packet_id']:
        fail('sidecar does not bind the R4 packet_id', 'G-H2-ANNOTATE')
    if sidecar.get('context_version') != 'csr8-national-capital-v1e':
        fail('sidecar is not a v1e (NC-ERRATUM-1) sidecar',
             'G-H2-ANNOTATE')
    # commitment self-consistency (builder-independent re-proof)
    recomputed = hashlib.sha256(c4d.canon(
        {k: v for k, v in sidecar.items()
         if k != 'context_commitment_sha256'}).encode()).hexdigest()
    if recomputed != sidecar.get('context_commitment_sha256'):
        fail('sidecar commitment is not self-consistent',
             'G-H2-ANNOTATE')
    summary = sidecar.get('stock_layer_summary')
    if summary not in (
            'SOURCE_UNAVAILABLE', 'NO_PIT_VISIBLE_REPORT',
            'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10',
            'NATIONAL_ACTORS_PRESENT'):
        fail('sidecar lacks a valid stock_layer_summary enum '
             '(NC-ERRATUM-1 contract)', 'G-H2-ANNOTATE')
    latest_period = sidecar.get(
        'stock_layer_summary_report_period', '')
    if sidecar.get('evidence_profile') != EVIDENCE_PROFILE:
        fail('sidecar evidence_profile mismatch', 'G-H2-ANNOTATE')
    n_stock = len(sidecar['stock_capital_records'])
    n_market = len(sidecar['market_etf_records'])

    # annotation session registry (opaque session id; blinded bindings)
    reg_path = c4d.annot_dom(CSR, SID) / 'annotation_session_registry.json'
    if reg_path.exists():
        fail('annotation session registry already exists (O_EXCL)')
    ann_session = secrets.token_hex(16)
    session = {
        'annotation_session_id': ann_session,
        'created_at': now_utc(),
        'status': 'OPEN',
        'packet_id': r4['payload']['packet_id'],
        'packet_sha256': r4['payload']['packet_sha256'],
        'reveal_event_hash': r4['event_hash'],
    }
    registry = {
        'registry_version': REGISTRY_VERSION,
        'session_id': SID,
        'reveal_event_hash': r4['event_hash'],
        'packet_id': r4['payload']['packet_id'],
        'packet_sha256': r4['payload']['packet_sha256'],
        'annotation_contract_sha256': c4d.ANNOTATION_CONTRACT_SHA256,
        'annotation_sessions': [session],
    }
    c4d.excl_write(reg_path, canon(registry).encode())

    # blinded LLM annotation (executor judgment over blinded surfaces
    # only): every judgment cites packet pointers; national-context
    # linkage is recorded separately in the support map.
    # disclosure-semantics wording (NC-ERRATUM-1): a NOT_DISCLOSED_*
    # summary is a disclosure fact, NOT evidence of absence.
    stock_note = (f'NATIONAL_CTX_V1e stock layer at T: {summary}'
                  + (f' (period {latest_period})' if latest_period else '')
                  + f'; stock records: {n_stock}.'
                  + (' Non-disclosure in the latest PIT-visible top-10 '
                     'is not evidence that holdings do not exist.'
                     if summary == 'NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10'
                     else ''))
    market_note = (f'market layer: {n_market} SSE ETF share snapshots '
                   'PIT-visible to T, actor attribution FORBIDDEN.')
    judgments = [
        {'hypothesis_id': 'rt_H01',
         'observability': 'OBSERVABLE',
         'support': 'NOT_OBSERVED',
         'evidence_refs': ['/as_of/T'],
         'evidence_note': ('BASE packet evidence empty at T. ' + stock_note
                           + ' No national-actor accumulation evidence.')},
        {'hypothesis_id': 'rt_H02',
         'observability': 'OBSERVABLE',
         'support': 'NOT_OBSERVED',
         'evidence_refs': ['/as_of/T'],
         'evidence_note': ('No sustained national-actor position is '
                           'observable at T. ' + stock_note)},
        {'hypothesis_id': 'rt_H03',
         'observability': 'OBSERVABLE',
         'support': 'NOT_OBSERVED',
         'evidence_refs': ['/price_panel'],
         'evidence_note': ('Price panel observable to T; no capital-state '
                          'markup linkage in the context layer at T.')},
        {'hypothesis_id': 'rt_H04',
         'observability': 'OBSERVABLE',
         'support': 'NOT_OBSERVED',
         'evidence_refs': ['/as_of/T'],
         'evidence_note': ('No case-level external participation evidence. '
                           + market_note)},
        {'hypothesis_id': 'rt_H05',
         'observability': 'OBSERVABLE',
         'support': 'NOT_OBSERVED',
         'evidence_refs': ['/as_of/T'],
         'evidence_note': ('No national-actor holdings disclosed in the '
                           'latest PIT-visible report at T, so no '
                           'distribution evidence; non-disclosure is not '
                           'evidence of absence. ' + stock_note)},
        {'hypothesis_id': 'rt_H06',
         'observability': 'OBSERVABLE',
         'support': 'NOT_OBSERVED',
         'evidence_refs': ['/as_of/T'],
         'evidence_note': ('No control-position evidence in the context '
                           'layer at T. ' + stock_note)},
    ]
    ts = now_utc()
    draft = {
        'draft_version': 'c4d-draft-v1',
        'session_id': SID,
        'packet_id': r4['payload']['packet_id'],
        'packet_sha256': r4['payload']['packet_sha256'],
        'annotation_session_id': ann_session,
        'annotation_attempt': ATTEMPT,
        'annotation': {
            'annotation_contract_sha256': c4d.ANNOTATION_CONTRACT_SHA256,
            'rt_judgments': judgments,
            'overall_note': (
                'Blinded annotation at T under '
                'BASE_V1+NATIONAL_CTX_V1. BASE packet carries no evidence '
                'entries; the national-context sidecar contributes '
                f'{n_stock} stock-layer and {n_market} market-layer '
                'records. ' + stock_note + ' ' + market_note),
            'flags': ['EVIDENCE_INCOMPLETE_AT_T'],
        },
        'created_at': ts,
        'updated_at': ts,
    }
    packet_obj = json.loads(pool)
    c4d.validate_draft(CSR, SID, draft, packet_obj, r1=r4)
    dp = c4d.write_draft(CSR, SID, draft)
    c4d.validate_draft(CSR, SID, json.loads(dp.read_bytes()), packet_obj,
                       r1=r4)

    # context support map: judgments -> sidecar context_record_ids
    if SUPPORT_MAP.exists():
        fail('support map already exists (O_EXCL)')
    ids_market = [r['context_record_id']
                  for r in sidecar['market_etf_records']]
    ids_stock = [r['context_record_id']
                 for r in sidecar['stock_capital_records']]
    smap = {
        'version': SUPPORT_MAP_VERSION,
        'ordinal': ORDINAL,
        'packet_sha256': r4['payload']['packet_sha256'],
        'context_sha256': sidecar['context_commitment_sha256'],
        'judgments': {
            'rt_H01': list(ids_stock),
            'rt_H02': list(ids_stock),
            'rt_H03': [],
            'rt_H04': list(ids_market),
            'rt_H05': list(ids_stock),
            'rt_H06': list(ids_stock),
        },
    }
    _validate_support_map(smap, sidecar, r4['payload']['packet_sha256'])
    c4d.excl_write(SUPPORT_MAP, canon(smap).encode())
    os.chmod(SUPPORT_MAP, 0o600)

    # blindness guard over the whole annotator domain + NC surfaces
    keys = set()

    def walk(x):
        if isinstance(x, dict):
            keys.update(x)
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for p in sorted(list(c4d.annot_dom(CSR, SID).rglob('*.json'))
                    + [SIDECAR, SUPPORT_MAP]):
        walk(json.loads(p.read_bytes()))
    if keys & LEAK_FORBIDDEN_KEYS:
        fail('blindness leak: ' + repr(sorted(keys & LEAK_FORBIDDEN_KEYS)),
             'G-H2-ANNOTATE')
    c4d.check_visibility_domain(CSR, SID)
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'ANNOTATED',
        'draft_sha256': sha(dp.read_bytes()),
        'annotation_session_id': ann_session,
        'packet_id': r4['payload']['packet_id'],
        'context_commitment_sha256':
            sidecar['context_commitment_sha256'],
        'support_map_sha256': sha(SUPPORT_MAP.read_bytes()),
        'stock_layer_summary': summary,
        'stock_records': n_stock, 'market_records': n_market,
        'attempt': ATTEMPT,
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: receipt (exact freeze) — requires ANNOTATION APPROVE
# ---------------------------------------------------------------------------

def cmd_receipt():
    evs = events()
    if [e['event_type'] for e in evs] != EXPECTED_FINAL_CHAIN[:7]:
        fail('receipt requires chain [R1..S3,R4]')
    dp = c4d.draft_path(CSR, SID)
    if not dp.is_file():
        fail('active draft missing')
    dbytes = dp.read_bytes()
    require_verdict('ANNOTATION', sha(dbytes), 'G-H2-RECEIPT')

    od = c4d.ordinal_dir(CSR, SID, ORDINAL)
    if od.exists() and any(od.iterdir()):
        fail('ordinal-0004 receipts domain already populated (one-shot)')
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

    # ordinal-0004 evidence copies (C4 layout + NC extension, O_EXCL 0600)
    r4 = evs[-1]
    c4d.excl_write(od / 'packet.json', _candidate_pool_bytes())
    c4d.excl_write(od / 'annotation_session_registry.json',
                   (c4d.annot_dom(CSR, SID) /
                    'annotation_session_registry.json').read_bytes())
    c4d.excl_write(od / 'annotation_draft.json', dp.read_bytes())
    c4d.excl_write(od / 'national_ctx_v1.json', SIDECAR.read_bytes())
    c4d.excl_write(od / 'context_support_map.json',
                   SUPPORT_MAP.read_bytes())
    c4d.fsync_dir(od)

    names = sorted(p.name for p in od.iterdir())
    if names != ['annotation_draft.json', 'annotation_session_registry.json',
                 'attempt-0001', 'context_support_map.json',
                 'national_ctx_v1.json', 'packet.json']:
        fail(f'ordinal-0004 closed-world violation: {names}')
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'RECEIPT_FROZEN',
        'receipt_sha256': sha(rbytes),
        'draft_sha256': sha(dbytes),
        'reveal_event_hash': r4['event_hash'],
        'attempt': ATTEMPT,
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: seal — requires RECEIPT + SEAL APPROVE
# ---------------------------------------------------------------------------

def cmd_seal():
    evs = events()
    if [e['event_type'] for e in evs] != EXPECTED_FINAL_CHAIN[:7]:
        fail('seal requires chain [R1..S3,R4]')
    adir = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT)
    rbytes = (adir / 'receipt.json').read_bytes()
    rsha = sha(rbytes)
    require_verdict('RECEIPT', rsha, 'G-H2-SEAL')
    require_verdict('SEAL', rsha, 'G-H2-SEAL')

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
        fail(f'final chain must be [R1..S3,R4,S4], got {types}')
    if c4d.annot_dom(CSR, SID).exists():
        fail('annotator workspace not cleaned after seal')
    c4d.post_seal_final(CSR, SID)
    anchor = json.loads((CSR / 'c4_public' / 'c4d_seal_anchor.json')
                        .read_bytes())
    s4 = evs[-1]
    if anchor.get('production_head_hash') != s4['event_hash'] or \
            anchor.get('seal_receipt_sha256') != rsha:
        fail('durable anchor does not bind S4 head + receipt hash')
    print(json.dumps({
        'stage': STAGE, 'ordinal': ORDINAL, 'state': 'SEALED',
        's4_event_hash': s4['event_hash'],
        'production_head': s4['event_hash'],
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
        fail(f'final chain must be [R1..R4,S1..S4], got {types}',
             'G-H2-CHAIN')

    # C2 full replay from genesis
    lg = c4d.c2.SealingLog(c4d.log_path(CSR, SID), c4d.head_path(CSR, SID))
    c4d.c2translate(lg.load().verify, True)

    # frozen candidate prefix law (unique order, no skips, no reordering)
    order = c4d.candidate_total_order()
    reveals = [e for e in evs if e['event_type'] == 'REVEAL_PACKET']
    revealed = [(e['payload']['opaque_case_id'], e['payload']['T'])
                for e in reveals]
    if revealed != [(x['opaque_case_id'], x['T']) for x in order[:4]]:
        fail('revealed prefix != frozen candidate order prefix 4',
             'G-H2-PREFIX')

    # authorization single-use across all next-reveal ordinals
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
             'G-H2-AUTHZ')
    consumption = {1: 'CONSUMED'}
    for ordinal in (2, 3, 4):
        proposal = c4d.read_json(c4d.proposal_path(CSR, SID, ordinal))
        consumption[ordinal] = c4d.derive_reveal_consumption(evs, proposal,
                                                             SID)
    if set(consumption.values()) != {'CONSUMED'}:
        fail(f'authorization consumption drift: {consumption}',
             'G-H2-AUTHZ')

    # commit-time whole-history proof per ordinal + dual semantic replay
    for ordinal, reveal in ((1, reveals[0]), (2, reveals[1]),
                            (3, reveals[2]), (4, reveals[3])):
        c4d.prove_attempt_history(CSR, SID, ordinal, gate='G-H2-HIST',
                                  events=evs, reveal=reveal)
    c4d.semantic_replay(CSR, SID)

    # receipt triple exactness for ordinal 4
    adir = c4d.attempt_dir(CSR, SID, ORDINAL, ATTEMPT)
    rbytes = (adir / 'receipt.json').read_bytes()
    s4 = evs[-1]
    archived = (c4d.sealing_dir(CSR, SID) /
                s4['payload']['bytes_ref']).read_bytes()
    if not (sha(rbytes) == s4['payload']['receipt_sha256'] ==
            sha(archived)):
        fail('ordinal-4 receipt triple exact-byte equality broken',
             'G-H2-RECEIPT')

    # anchor durable + cleanup + POST_SEAL_FINAL
    anchor = json.loads((CSR / 'c4_public' / 'c4d_seal_anchor.json')
                        .read_bytes())
    if anchor.get('production_head_hash') != s4['event_hash'] or \
            anchor.get('seal_receipt_sha256') != sha(rbytes):
        fail('anchor does not bind the terminal sealed pair', 'G-H2-ANCHOR')
    if c4d.annot_dom(CSR, SID).exists():
        fail('annotator workspace not cleaned', 'G-H2-CLEANUP')
    c4d.post_seal_final(CSR, SID)

    # NC extension re-proof against the SEALED v1 sidecar (ordinal-4 was
    # sealed under the pre-erratum contract; NC-ERRATUM-1 applies from
    # ordinal-5 — see docs/audit/evidence/national_capital_context_
    # erratum_1.json and h2_ordinal4_canary_status.json)
    r4 = reveals[3]
    od = c4d.ordinal_dir(CSR, SID, ORDINAL)
    sidecar_ev = json.loads((od / 'national_ctx_v1.json').read_bytes())
    smap_ev = json.loads((od / 'context_support_map.json').read_bytes())
    pre = json.loads(NC_PREFLIGHT_EVIDENCE.read_bytes())
    if sidecar_ev.get('packet_id') != r4['payload']['packet_id'] or \
            sidecar_ev.get('ordinal') != ORDINAL:
        fail('archived sidecar does not bind R4 packet', 'G-H2-NC')
    # frozen-builder re-proof of the sealed v1 sidecar bytes
    import tempfile as _tf2
    _tmp2 = Path(_tf2.mkdtemp()) / 'sealed_sidecar.json'
    subprocess.run(
        [sys.executable, str(NC_BUILDER), '--ordinal', str(ORDINAL),
         '--out', str(_tmp2)],
        check=True, capture_output=True, text=True, cwd=str(ROOT))
    if _tmp2.read_bytes() != (od / 'national_ctx_v1.json').read_bytes():
        fail('sealed v1 sidecar is not reproducible by the frozen '
             'builder', 'G-H2-NC')
    if sidecar_ev.get('context_commitment_sha256') != \
            pre.get('context_commitment_sha256'):
        fail('archived sidecar commitment != frozen preflight',
             'G-H2-NC')
    n_refs = _validate_support_map(smap_ev, sidecar_ev,
                                   r4['payload']['packet_sha256'])
    if (od / 'national_ctx_v1.json').read_bytes() != \
            SIDECAR.read_bytes() or \
            (od / 'context_support_map.json').read_bytes() != \
            SUPPORT_MAP.read_bytes():
        fail('archived NC evidence copies are not byte-identical to the '
             'campaign surface', 'G-H2-NC')

    # verdicts: all five operations, exact bindings
    draft_ev = (od / 'annotation_draft.json').read_bytes()
    require_verdict('NEXT_REVEAL', packet_sha(), 'G-H2-VERDICTS')
    require_verdict('ANNOTATION', sha(draft_ev), 'G-H2-VERDICTS')
    require_verdict('RECEIPT', sha(rbytes), 'G-H2-VERDICTS')
    require_verdict('SEAL', sha(rbytes), 'G-H2-VERDICTS')
    require_verdict('POST_SEAL', s4['event_hash'], 'G-H2-VERDICTS')

    # reviewer ledger integrity: contiguous hash chain, H2 lines APPROVE,
    # reviewer sessions distinct from each other.
    ledger = [json.loads(x) for x in (CAMPAIGN /
                                       'reviews.jsonl').read_text()
              .splitlines() if x.strip()]
    for i, rec in enumerate(ledger):
        if rec.get('sequence') != i:
            fail(f'ledger sequence drift at line {i}', 'G-H2-LEDGER')
        h = rec.pop('review_hash')
        if sha(c4d.canon(rec).encode()) != h:
            fail(f'ledger hash-chain break at line {i}', 'G-H2-LEDGER')
        rec['review_hash'] = h
        if i:
            if rec.get('prev_review_hash') != \
                    ledger[i - 1]['review_hash']:
                fail(f'ledger prev-link break at line {i}', 'G-H2-LEDGER')
    h2 = [r for r in ledger if r.get('ordinal') == ORDINAL]
    if len(h2) != len(OPS) or any(r.get('state') != 'APPROVE'
                                  for r in h2):
        fail('H2 ledger lines incomplete or not APPROVE', 'G-H2-LEDGER')
    sessions = {r.get('reviewer_session_id') for r in h2}
    if len(sessions) != len(h2):
        fail('H2 verdicts were not produced by distinct reviewer '
             'sessions', 'G-H2-LEDGER')

    # authorization domain closed world: frozen first_reveal permit +
    # exactly one approval/permit pair per next-reveal ordinal
    authz_top = c4d.prod_dir(CSR, SID) / 'authorization'
    top = sorted(p.name for p in authz_top.iterdir())
    if top != ['first_reveal.approval.json', 'first_reveal.json',
               'ordinal-0002', 'ordinal-0003', 'ordinal-0004']:
        fail(f'authorization top-level closed-world violation: {top}',
             'G-H2-WORLD')
    for ordinal in (2, 3, 4):
        entries = sorted(p.name for p in
                         c4d.next_authz_dir(CSR, SID, ordinal).rglob('*')
                         if p.is_file())
        if entries != ['next_reveal.approval.json',
                       'next_reveal.permit.json']:
            fail(f'ordinal-{ordinal} authorization domain closed-world '
                 f'violation: {entries}', 'G-H2-WORLD')
    od_names = sorted(p.name for p in
                      c4d.ordinal_dir(CSR, SID, ORDINAL).iterdir())
    if od_names != ['annotation_draft.json',
                    'annotation_session_registry.json', 'attempt-0001',
                    'context_support_map.json', 'national_ctx_v1.json',
                    'packet.json']:
        fail(f'ordinal-0004 receipts closed-world violation: {od_names}',
             'G-H2-WORLD')

    # h_campaign H1+H2 closed world
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
    ] + [f'h1/reviews/{op}.verdict.json' for op in OPS]
      + ['h2/packets/ordinal-0004-next-reveal.json',
         'h2/national_context/ordinal-0004-national-ctx-v1.json',
         'h2/context_support_map.json']
      + [f'h2/reviews/{op}.verdict.json' for op in OPS])
    if got != expected:
        fail(f'h_campaign H1+H2 closed-world violation: '
             f'{got} != {expected}', 'G-H2-WORLD')

    print(json.dumps({
        'stage': STAGE, 'iteration': ITERATION, 'ordinal': ORDINAL,
        'state': 'ORDINAL_COMPLETE',
        'chain': types, 'candidate_prefix': 4,
        'evidence_profile': EVIDENCE_PROFILE,
        'authorization_consumption': consumption,
        'c2_full_replay': 'PASS', 'semantic_replay': 'PASS',
        'ordinal_histories': {1: 'PASS', 2: 'PASS', 3: 'PASS',
                              4: 'PASS'},
        'receipt_triple': 'PASS', 'anchor': 'DURABLE',
        'workspace_cleanup': 'PASS', 'post_seal_final': True,
        'nc_context_binding': 'PASS', 'support_map_refs': n_refs,
        'verdicts': {op: 'APPROVE' for op in OPS},
        'production_head': s4['event_hash'],
        'receipt_sha256': sha(rbytes),
    }, sort_keys=True, separators=(',', ':')))


# ---------------------------------------------------------------------------
# stage: finalize — harden new H2 artifacts (H1 discipline)
# ---------------------------------------------------------------------------

def cmd_finalize():
    hardened = []
    sd = c4d.sealing_dir(CSR, SID)
    for b in sorted((sd / 'bytes').rglob('*.bin')):
        seq = int(b.stem)
        if seq < 6:
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
    v = require_verdict(op, expected_sha, 'G-H2-GATE')
    print(json.dumps({'operation': op, 'state': v['state'],
                      'input_commitment_sha256':
                          v['input_commitment_sha256'],
                      'reviewer_run_id': v['reviewer_run_id'],
                      'created_at': v['created_at']},
                     sort_keys=True, separators=(',', ':')))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('prepare')
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
    if args.cmd == 'prepare':
        cmd_prepare()
    elif args.cmd == 'authorize':
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
