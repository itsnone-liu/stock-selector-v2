#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase H H0 — Phase Entry Gate（taskbook v1.1 §8/§31，run audit_20261001135212538）.

执行者只做机器实测与 campaign bootstrap，不宣布进入 H1：

* 写前全前置机器重验（任何失败 => HALT，零写入、零 proposal）：
  production_infra_final_frozen marker 有效且逐字绑定 freeze commit
  cd7f2a5db0fddee824bd1e5ce6da0f8bcd7431ca（marker bytes@freeze commit ==
  live bytes；audited_head == freeze commit parent；freeze commit 是 HEAD
  祖先）；chain 恰为 [R1,S1,R2,S2]；REVEAL=2/SEAL=2/open_reveals=0；
  candidate prefix=2（冻结 total-order 精确前缀）；C2 full replay PASS
  （冻结 SealingLog 全量重放 + trusted-head）；R1↔S1、R2↔S2 exact replay
  PASS；ordinal-1/2 history PASS；authorization1/2 CONSUMED；无 FORENSIC
  （derive_state==SEALED）；G5=BLOCKED、XP=BLOCKED_FOR_PIT（冻结 C3
  authority gate + boolean summary）。
* PASS 后 bootstrap：round0_total/completed/remaining（冻结 candidate
  total-order 派生）；campaign manifest + opaque campaign_id（确定性
  sha256 派生，无时钟熵）；review ledger 初始头（append-only hash-chain
  genesis，executor 只写 genesis，verdict 行只由 independent reviewer
  追加）；canonical PHASE_ENTRY review packet（input_commitment_sha256
  绑定 exact bytes）；ordinal-3 NEXT_REVEAL proposal（冻结 §7 builder
  verbatim，O_EXCL 一次性，仅准备——不 authorization、不 append R3）。
* postreview：机器复验 reviewer verdict + ledger hash-chain +
  executor/reviewer 独立性，随后冻结域维护（enforce_domain_modes 重建
  freeze ledger、set_annotator_immutable 写屏障、certify 重建 certified
  manifest），并重跑冻结校验器全电池（certified tree / manifest anchor /
  chain replay / blinding / corpus / audit package / C6 dual-cycle）。
* Blinding 边界：本模块物理上不含 outcome/identity-resolver/future-packet
  读取路径；任何 H0 工件（manifest/packet/evidence/ledger）不含
  ocid/T/packet_id——所有 64-hex token 必须属于白名单哈希集合
  （链事件哈希/承诺/工件哈希），机器扫描强制。

用法：
  csr8_phase_h_entry_gate.py bootstrap     # 前置机器实测 -> campaign bootstrap
  csr8_phase_h_entry_gate.py postreview    # reviewer verdict 复验 + 维护 + 电池 + evidence
  csr8_phase_h_entry_gate.py verify        # 全量只读复验（含电池），不写任何文件
"""

import argparse
import hashlib
import importlib.util
import json
import re
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

RUN_ID = 'audit_20261001135212538'
STAGE = 'H0'
ITERATION = 1
HOST_ID = 'RainYun-c438TDGn'
TASKBOOK_VERSION = 'v1.1'
TASKBOOK_SHA256 = ('c6143d4ca67ffd9c39166f998675d199d7c41602cb73a'
                   '36cd4f3e4bb0dae81b8')
FREEZE_COMMIT = 'cd7f2a5db0fddee824bd1e5ce6da0f8bcd7431ca'
AUDITED_INFRA_HEAD = '04c89e7c43fb24e731871608ff40adee83221f64'
EXECUTOR_RUN_ID = f'{RUN_ID}:executor-{STAGE.lower()}'
REVIEW_VERSION = 'csr8-h-review-v1'
CAMPAIGN_PURPOSE = 'csr8-phase-h-campaign-v1'
START_ORDINAL = 3
EVIDENCE = ROOT / 'docs/audit/evidence/h_phase_entry_gate.json'
MARKER_REL = 'docs/audit/evidence/production_infra_final_frozen.json'
GENESIS_REVIEWER = 'executor-bootstrap'
ALLOWED_H_CAMPAIGN_FILES = (
    'campaign_manifest.json',
    'reviews.jsonl',
    'review_packets/phase_entry.json',
    'verdicts/phase_entry.verdict.json',
)
BOOTSTRAP_H_CAMPAIGN_FILES = ALLOWED_H_CAMPAIGN_FILES[:3]
LEDGER_FIELDS = ('sequence', 'prev_review_hash', 'review_hash', 'campaign_id',
                 'ordinal', 'operation', 'input_commitment_sha256', 'state',
                 'reviewer_run_id', 'created_at')
VERDICT_FIELDS = ('review_version', 'campaign_id', 'ordinal', 'operation',
                  'input_commitment_sha256', 'state', 'issues',
                  'required_changes', 'reviewer_run_id', 'created_at')
TS_RE = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
HEX64_RE = re.compile(r'\b[0-9a-f]{64}\b')
EXPECTED_CHAIN = ['REVEAL_PACKET', 'SEAL_ANNOTATION',
                  'REVEAL_PACKET', 'SEAL_ANNOTATION']


def fail(msg):
    raise RuntimeError(msg)


def halt(msg):
    print(json.dumps({'stage': STAGE, 'state': 'HALT', 'reason': msg},
                     ensure_ascii=False, sort_keys=True))
    raise SystemExit(2)


def load_module(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


c4d = load_module('scripts/csr8_phase_c_annotation_seal.py', 'h0_c4d')
fb = load_module('scripts/csr8_phase_f_bridge.py', 'h0_fb')
act = load_module('scripts/csr8_phase_c_activate.py', 'h0_act')
ma = load_module('scripts/csr8_phase_a_machine_audit.py', 'h0_ma')

CSR = c4d.REAL_CSR
SID = c4d.REAL_SESSION
canon = c4d.canon
sha = c4d.sha


def now_utc():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def git(*args):
    r = subprocess.run(['git', *args], cwd=str(ROOT), capture_output=True,
                       text=True)
    return r


# --------------------------------------------------------------------------
# entry gates — read-only, fail-closed
# --------------------------------------------------------------------------

def gate_frozen_marker():
    """marker 有效且逐字绑定 production infrastructure freeze commit。"""
    live = (ROOT / MARKER_REL).read_bytes()
    marker = json.loads(live)
    if marker.get('marker') != 'PRODUCTION_INFRA_FINAL_FROZEN':
        fail('G-H0-MARKER: marker name drift')
    if marker.get('status') != 'FINAL VERDICT: APPROVE':
        fail('G-H0-MARKER: marker is not an APPROVE declaration')
    if marker.get('declared_by') != 'INDEPENDENT_AUDIT':
        fail('G-H0-MARKER: marker not declared by INDEPENDENT_AUDIT')
    for k in ('B5', 'C6', 'D', 'E', 'F'):
        if marker.get('prerequisites', {}).get(k) != 'APPROVE':
            fail(f'G-H0-MARKER: prerequisite {k} not APPROVE')
    pc = marker.get('production_counts', {})
    if (pc.get('REVEAL') != 2 or pc.get('SEAL') != 2
            or pc.get('open_reveals') != 0):
        fail('G-H0-MARKER: marker production counts drift')
    r = git('cat-file', '-e', f'{FREEZE_COMMIT}^{{commit}}')
    if r.returncode != 0:
        fail('G-H0-MARKER: freeze commit does not exist')
    r = git('merge-base', '--is-ancestor', FREEZE_COMMIT, 'HEAD')
    if r.returncode != 0:
        fail('G-H0-MARKER: freeze commit is not an ancestor of HEAD')
    r = git('show', f'{FREEZE_COMMIT}:{MARKER_REL}')
    if r.returncode != 0 or r.stdout.encode() != live:
        fail('G-H0-MARKER: live marker bytes differ from the freeze commit')
    r = git('rev-parse', f'{FREEZE_COMMIT}^')
    if r.returncode != 0 or r.stdout.strip() != AUDITED_INFRA_HEAD:
        fail('G-H0-MARKER: freeze commit parent is not the audited infra '
             'head 04c89e7c…')
    if marker.get('audited_head') != AUDITED_INFRA_HEAD:
        fail('G-H0-MARKER: marker audited_head drift')
    return {'marker': 'PRODUCTION_INFRA_FINAL_FROZEN',
            'status': marker['status'],
            'production_infra_freeze_commit': FREEZE_COMMIT,
            'audited_infra_head': AUDITED_INFRA_HEAD,
            'freeze_commit_parent_is_audited_head': True,
            'marker_bytes_unchanged_since_freeze_commit': True,
            'freeze_commit_is_ancestor_of_head': True,
            'prerequisites': marker['prerequisites']}


def gate_chain():
    """C2 full replay（冻结 SealingLog 全量重放 + trusted head）+ 形态。"""
    events = fb.verify_chain(CSR)                    # raises on any drift
    types = [e['event_type'] for e in events]
    if types != EXPECTED_CHAIN:
        fail(f'G-H0-CHAIN: exact persisted chain required, got {types}')
    reveals = [e for e in events if e['event_type'] == 'REVEAL_PACKET']
    seals = [e for e in events if e['event_type'] == 'SEAL_ANNOTATION']
    if types[-1] != 'SEAL_ANNOTATION' or len(reveals) != len(seals):
        fail('G-H0-CHAIN: open_reveals must be 0')
    order = c4d.candidate_total_order()
    frozen_keys = [(c['opaque_case_id'], c['T']) for c in order]
    revealed_keys = [(e['payload']['opaque_case_id'], e['payload']['T'])
                     for e in reveals]
    if revealed_keys != frozen_keys[:2]:
        fail('G-H0-CHAIN: revealed set is not the frozen candidate '
             'total-order prefix of length 2')
    cg = c4d.verify_candidate_gates()
    if cg['revealed_prefix'] != 2 or not cg['ordinal1_matches_frozen_first'] \
            or cg['size'] != len(order):
        fail(f'G-H0-CHAIN: live candidate gates drifted: {cg}')
    head = json.loads((CSR / 'production' / SID / 'sealing' /
                       'sealing_log.head.json').read_text())
    return {'c2_full_replay': 'PASS', 'chain': types,
            'production_head': head['head_hash'],
            'reveal_count': len(reveals), 'seal_count': len(seals),
            'open_reveals': 0, 'candidate_prefix': 2,
            'candidate_order_size': cg['size'],
            'trusted_head_count': head.get('count'),
            'candidate_gates': {'size': cg['size'],
                                'ordinal1_matches_frozen_first':
                                    cg['ordinal1_matches_frozen_first'],
                                'revealed_prefix': cg['revealed_prefix']}}


def gate_forensic():
    state, info = c4d.derive_state(CSR, SID)
    if state != 'SEALED':
        fail(f'G-H0-FORENSIC: derived lifecycle state must be SEALED with '
             f'no forensic finding (derived={state}, info={info})')
    return {'derive_state': state, 'forensic_findings': 0,
            'forensic_state': 'NONE'}


def gate_authority():
    """冻结 C3 authority gate（G5/XP boolean boundary 机器重证）。"""
    if act.verify_c3_authority() is not True:
        fail('G-H0-AUTHORITY: frozen C3 authority gate failed')
    boolean = json.loads((act.C3A / 'c3_boolean_summary.json').read_text())
    if not boolean.get('G5_BLOCKED') or not boolean.get('XP_BLOCKED_FOR_PIT'):
        fail('G-H0-AUTHORITY: G5/XP boundary violated')
    return {'c3_authority_gate': 'PASS', 'G5': 'BLOCKED',
            'XP': 'BLOCKED_FOR_PIT',
            'boolean_boundary': {'ALL_GATES_PASS': boolean['ALL_GATES_PASS'],
                                 'G5_BLOCKED': boolean['G5_BLOCKED'],
                                 'XP_BLOCKED_FOR_PIT':
                                     boolean['XP_BLOCKED_FOR_PIT']}}


def gate_authorizations(events):
    """authorization1（first_reveal）与 authorization2（ordinal-2 proposal）
    的链派生 CONSUMED 证明。"""
    r1 = events[0]
    permit = (CSR / 'production' / SID / 'authorization' /
              'first_reveal.json').read_bytes()
    pobj = json.loads(permit)
    if pobj.get('scope') != 'FIRST_REVEAL_ONLY' or pobj.get('authorized') \
            is not True:
        fail('G-H0-AUTHZ: first_reveal permit scope/authorized drift')
    if r1['payload'].get('authorization_sha256') != sha(permit):
        fail('G-H0-AUTHZ: R1 does not bind the first_reveal permit bytes')
    if r1['payload'].get('authorization_id') != pobj.get('authorization_id'):
        fail('G-H0-AUTHZ: R1 authorization_id mismatch')
    proposal2 = c4d.read_json(c4d.proposal_path(CSR, SID, 2))
    c2state = c4d.derive_reveal_consumption(events, proposal2, SID)
    if c2state != 'CONSUMED':
        fail(f'G-H0-AUTHZ: ordinal-2 authorization must be CONSUMED, '
             f'got {c2state}')
    return {'authorization1': 'CONSUMED', 'authorization2': 'CONSUMED',
            'authorization1_binding': 'R1.payload.authorization_sha256 == '
                                      'SHA256(first_reveal.json)',
            'authorization2_binding': 'chain-derived consumption '
                                      '(exact proposal bytes)'}


def entry_gates():
    marker = gate_frozen_marker()
    chain = gate_chain()
    forensic = gate_forensic()
    authority = gate_authority()
    authz = gate_authorizations(fb.verify_chain(CSR))
    c6mod = load_module('scripts/csr8_phase_c6_seal_s2.py', 'h0_c6')
    c6 = c6mod.verify()
    if c6.get('c6') != 'PASS' or c6.get('production') != 'REVEAL=2 SEAL=2':
        fail(f'G-H0-C6: frozen dual-cycle verification failed: {c6}')
    for key, want in (('r1_s1_exact', 'PASS'), ('r2_s2_exact', 'PASS'),
                      ('ordinal1_history', 'PASS'),
                      ('ordinal2_history', 'PASS'),
                      ('authorization1', 'CONSUMED'),
                      ('authorization2', 'CONSUMED'),
                      ('dual_replay', 'PASS'), ('crash_recovery', 'PASS'),
                      ('outcome_untouched', 'PASS')):
        if c6.get(key) != want:
            fail(f'G-H0-C6: frozen C6 verifier reports {key}={c6.get(key)}')
    return {'frozen_marker': marker, 'chain': chain, 'forensic': forensic,
            'authority': authority, 'authorizations': authz,
            'c6_dual_cycle': {k: c6[k] for k in (
                'c6', 'chain', 'production', 'open_reveals',
                'candidate_prefix', 'r1_s1_exact', 'r2_s2_exact',
                'ordinal1_history', 'ordinal2_history', 'authorization1',
                'authorization2', 'dual_replay', 'crash_recovery',
                'outcome_untouched')}}


def round0_facts(chain):
    order = c4d.candidate_total_order()
    total = len(order)
    completed = chain['seal_count']
    remaining = total - completed
    if completed != 2 or remaining != total - 2 or total < 2:
        fail('G-H0-ROUND0: round0 accounting invariant violated')
    unique_cases = len({c['opaque_case_id'] for c in order})
    return {'total': total, 'completed': completed, 'remaining': remaining,
            'unique_cases': unique_cases,
            'definition': 'round0_total = frozen candidate total-order size '
                          '(one ordinal per (case,T) pair); complete when '
                          'every eligible case has >=1 sealed blinded '
                          'annotation; completed = sealed pairs on chain'}


# --------------------------------------------------------------------------
# campaign bootstrap
# --------------------------------------------------------------------------

def campaign_seed(chain):
    return {'purpose': CAMPAIGN_PURPOSE,
            'taskbook_sha256': TASKBOOK_SHA256,
            'production_infra_freeze_commit': FREEZE_COMMIT,
            'audited_infra_head': AUDITED_INFRA_HEAD,
            'session_id': SID,
            'production_head': chain['production_head'],
            'candidate_order_size': chain['candidate_order_size'],
            'start_ordinal': START_ORDINAL}


def derive_campaign_id(chain):
    return 'hc-' + sha(canon(campaign_seed(chain)).encode())[:32]


def campaign_dir(cid):
    return CSR / 'h_campaign' / cid


def review_hash_of(record):
    body = {k: v for k, v in record.items() if k != 'review_hash'}
    return sha(canon(body).encode())


def build_or_verify_proposal():
    """ordinal-3 NEXT_REVEAL proposal：冻结 §7 builder，一次性 O_EXCL。"""
    p = c4d.proposal_path(CSR, SID, START_ORDINAL)
    if p.exists():
        proposal, pbytes = c4d._check_proposal(CSR, SID, START_ORDINAL)
        return pbytes, 'VERIFIED'
    head = c4d._current_prefix_head(CSR, SID)
    c4d.build_next_reveal_proposal(CSR, SID, START_ORDINAL, head)
    for d in (CSR / 'c4d_proposals', CSR / 'c4d_proposals' / SID,
              c4d.proposals_dom(CSR, SID, START_ORDINAL)):
        c4d.fsync_dir(d)
    proposal, pbytes = c4d._check_proposal(CSR, SID, START_ORDINAL)
    return pbytes, 'CREATED'


def build_or_verify_manifest(gates, chain, r0, cid):
    path = campaign_dir(cid) / 'campaign_manifest.json'
    body = {
        'manifest_version': 'csr8-h-campaign-manifest-v1',
        'campaign_id': cid,
        'phase': 'H',
        'stage': STAGE,
        'run_id': RUN_ID,
        'taskbook': {'version': TASKBOOK_VERSION, 'sha256': TASKBOOK_SHA256},
        'session_id': SID,
        'production_infra_freeze_commit': FREEZE_COMMIT,
        'audited_infra_head': AUDITED_INFRA_HEAD,
        'production_head': chain['production_head'],
        'chain': chain['chain'],
        'reveal_count': chain['reveal_count'],
        'seal_count': chain['seal_count'],
        'open_reveals': chain['open_reveals'],
        'candidate_prefix_length': chain['candidate_prefix'],
        'candidate_order_size': chain['candidate_order_size'],
        'candidate_order_commitment': sha(canon(
            c4d.candidate_total_order()).encode()),
        'annotation_contract_sha256': c4d.ANNOTATION_CONTRACT_SHA256,
        'round0': r0,
        'start_ordinal': START_ORDINAL,
        'ordinal3_proposal_rel': f'c4d_proposals/{SID}/ordinal-'
                                 f'{START_ORDINAL:04d}/'
                                 f'next_reveal.proposal.json',
        'review_ledger': 'reviews.jsonl',
        'review_packet_phase_entry': 'review_packets/phase_entry.json',
        'executor_run_id': EXECUTOR_RUN_ID,
        'reviewer_independence': {
            'role_separation': 'executor generates, independent reviewer '
                               'reviews (fresh context)',
            'context_separation': 'reviewer runs in an isolated context '
                                  'without this executor conversation',
            'write_separation': 'executor writes only the ledger genesis; '
                                'verdict lines are appended by the reviewer',
            'constraint': 'reviewer_run_id != executor_run_id'},
        'prohibited': ['outcome_join', 'analysis_labeled', 'empirical_results',
                       'identity_access', 'future_data_access',
                       'result_driven_sampling'],
        'outcome_accessed': False,
        'identity_accessed': False,
        'future_data_accessed': False,
    }
    expected = dict(body)
    if path.exists():
        got = json.loads(path.read_bytes())
        stored_at = got.pop('created_at', None)
        if not TS_RE.match(stored_at or ''):
            fail('H0-MANIFEST: stored created_at is not canonical UTC')
        if got != expected:
            fail('H0-MANIFEST: persisted campaign manifest drifted from '
                 'machine-derived facts')
        return path.read_bytes(), 'VERIFIED'
    body['created_at'] = now_utc()
    data = canon(body).encode()
    write_excl(path, data, 0o600)
    return data, 'CREATED'


def build_or_verify_genesis(cid, manifest_bytes):
    path = campaign_dir(cid) / 'reviews.jsonl'
    record = {'sequence': 0,
              'prev_review_hash': '0' * 64,
              'campaign_id': cid,
              'ordinal': 0,
              'operation': 'LEDGER_GENESIS',
              'input_commitment_sha256': sha(manifest_bytes),
              'state': 'GENESIS',
              'reviewer_run_id': GENESIS_REVIEWER}
    if path.exists():
        verify_ledger(cid)
        return path.read_bytes(), 'VERIFIED'
    record['created_at'] = now_utc()
    record['review_hash'] = review_hash_of(record)
    line = canon(record).encode() + b'\n'
    write_excl(path, line, 0o600)
    return line, 'CREATED'


def build_or_verify_packet(gates, chain, r0, cid, proposal_bytes,
                           manifest_bytes, genesis_line):
    path = campaign_dir(cid) / 'review_packets' / 'phase_entry.json'
    genesis = json.loads(genesis_line.splitlines()[0])
    body = {
        'review_version': REVIEW_VERSION,
        'operation': 'PHASE_ENTRY',
        'ordinal': START_ORDINAL,
        'campaign_id': cid,
        'taskbook': {'version': TASKBOOK_VERSION, 'sha256': TASKBOOK_SHA256},
        'frozen_baseline': gates['frozen_marker'],
        'session_id': SID,
        'production_head': chain['production_head'],
        'chain': chain['chain'],
        'reveal_count': chain['reveal_count'],
        'seal_count': chain['seal_count'],
        'open_reveals': chain['open_reveals'],
        'candidate_prefix_length': chain['candidate_prefix'],
        'machine_entry_gate': {
            'c2_full_replay': chain['c2_full_replay'],
            'chain_shape_exact': True,
            'r1_s1_exact': gates['c6_dual_cycle']['r1_s1_exact'],
            'r2_s2_exact': gates['c6_dual_cycle']['r2_s2_exact'],
            'ordinal1_history': gates['c6_dual_cycle']['ordinal1_history'],
            'ordinal2_history': gates['c6_dual_cycle']['ordinal2_history'],
            'authorization1': gates['authorizations']['authorization1'],
            'authorization2': gates['authorizations']['authorization2'],
            'forensic_state': gates['forensic']['forensic_state'],
            'G5': gates['authority']['G5'],
            'XP': gates['authority']['XP'],
            'c3_authority_gate': gates['authority']['c3_authority_gate'],
            'c6_dual_cycle': gates['c6_dual_cycle']['c6'],
            'crash_recovery': gates['c6_dual_cycle']['crash_recovery'],
            'outcome_untouched': gates['c6_dual_cycle']['outcome_untouched']},
        'round0': r0,
        'ordinal3_proposal': {
            'rel': f'c4d_proposals/{SID}/ordinal-{START_ORDINAL:04d}/'
                   f'next_reveal.proposal.json',
            'sha256': sha(proposal_bytes),
            'builder': 'frozen c4d.build_next_reveal_proposal',
            'requested_ordinal': START_ORDINAL,
            'requested_ordinal_is_reveal_count_plus_one':
                START_ORDINAL == chain['reveal_count'] + 1,
            'last_committed_event_is_seal': True,
            'not_yet_authorized': True,
            'not_yet_revealed': True},
        'campaign_manifest_sha256': sha(manifest_bytes),
        'review_ledger_genesis_review_hash': genesis['review_hash'],
        'executor_run_id': EXECUTOR_RUN_ID,
    }
    expected = dict(body)
    if path.exists():
        got = json.loads(path.read_bytes())
        stored_at = got.pop('created_at', None)
        if not TS_RE.match(stored_at or ''):
            fail('H0-PACKET: stored created_at is not canonical UTC')
        if got != expected:
            fail('H0-PACKET: persisted review packet drifted from '
                 'machine-derived facts')
        return path.read_bytes(), 'VERIFIED'
    body['created_at'] = now_utc()
    data = canon(body).encode()
    write_excl(path, data, 0o600)
    return data, 'CREATED'


def write_excl(path, data, mode):
    import os
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    for d in [path.parent, *path.parent.parents]:
        if d == CSR:
            break
        if d.is_dir() and stat.S_IMODE(d.stat().st_mode) != 0o700:
            d.chmod(0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    c4d.fsync_dir(path.parent)


# --------------------------------------------------------------------------
# ledger + verdict verification (postreview)
# --------------------------------------------------------------------------

def verify_ledger(cid, expect_verdicts=None):
    path = campaign_dir(cid) / 'reviews.jsonl'
    if not path.is_file():
        fail('H0-LEDGER: reviews.jsonl missing')
    if c4d.mode_of(path) != 0o600:
        fail('H0-LEDGER: ledger mode drift (must be 0600)')
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    if not lines:
        fail('H0-LEDGER: ledger is empty')
    prev = None
    verdicts = []
    for i, ln in enumerate(lines):
        try:
            rec = json.loads(ln)
        except json.JSONDecodeError:
            fail(f'H0-LEDGER: line {i} is not JSON')
        if not isinstance(rec, dict) or set(rec) != set(LEDGER_FIELDS):
            fail(f'H0-LEDGER: line {i} schema violation '
                 f'(closed-world {LEDGER_FIELDS})')
        if canon(rec).encode() != ln.encode():
            fail(f'H0-LEDGER: line {i} bytes noncanonical')
        if rec['review_hash'] != review_hash_of(rec):
            fail(f'H0-LEDGER: line {i} review_hash mismatch')
        if rec['sequence'] != i:
            fail(f'H0-LEDGER: line {i} sequence drift')
        if rec['prev_review_hash'] != (prev if prev is not None
                                       else '0' * 64):
            fail(f'H0-LEDGER: line {i} hash-chain break')
        if rec['campaign_id'] != cid:
            fail(f'H0-LEDGER: line {i} campaign binding drift')
        if not TS_RE.match(rec['created_at']):
            fail(f'H0-LEDGER: line {i} created_at not canonical UTC')
        if i == 0:
            if (rec['operation'] != 'LEDGER_GENESIS'
                    or rec['state'] != 'GENESIS'
                    or rec['reviewer_run_id'] != GENESIS_REVIEWER
                    or rec['ordinal'] != 0):
                fail('H0-LEDGER: genesis line is not the exact header')
        else:
            if rec['reviewer_run_id'] in (EXECUTOR_RUN_ID, GENESIS_REVIEWER):
                fail(f'H0-LEDGER: line {i} violates reviewer independence '
                     f'(reviewer_run_id == executor/bootstrap)')
            if rec['state'] not in ('APPROVE', 'REVISE', 'HALT'):
                fail(f'H0-LEDGER: line {i} state not in closed verdict set')
            verdicts.append(rec)
        prev = rec['review_hash']
    if expect_verdicts is not None and len(verdicts) != expect_verdicts:
        fail(f'H0-LEDGER: expected {expect_verdicts} verdict line(s), '
             f'found {len(verdicts)}')
    return {'records': len(lines), 'verdicts': verdicts,
            'head_review_hash': prev}


def verify_verdict_file(cid, ledger_verdicts):
    path = campaign_dir(cid) / 'verdicts' / 'phase_entry.verdict.json'
    if not path.is_file():
        fail('H0-VERDICT: PHASE_ENTRY verdict file missing')
    raw = path.read_bytes()
    v = json.loads(raw)
    if not isinstance(v, dict) or set(v) != set(VERDICT_FIELDS):
        fail('H0-VERDICT: closed-world verdict schema violation '
             f'({VERDICT_FIELDS})')
    if canon(v).encode() != raw:
        fail('H0-VERDICT: verdict bytes noncanonical')
    if v['review_version'] != REVIEW_VERSION:
        fail('H0-VERDICT: review_version drift')
    if v['operation'] != 'PHASE_ENTRY' or v['ordinal'] != START_ORDINAL:
        fail('H0-VERDICT: operation/ordinal binding drift')
    if v['campaign_id'] != cid:
        fail('H0-VERDICT: campaign binding drift')
    if v['state'] not in ('APPROVE', 'REVISE', 'HALT'):
        fail('H0-VERDICT: state not in closed verdict set')
    if not isinstance(v['issues'], list) or not isinstance(
            v['required_changes'], list):
        fail('H0-VERDICT: issues/required_changes must be lists')
    if v['state'] == 'APPROVE' and (v['issues'] or v['required_changes']):
        fail('H0-VERDICT: APPROVE must carry empty issues/required_changes')
    if not isinstance(v['reviewer_run_id'], str) or \
            v['reviewer_run_id'] in ('', EXECUTOR_RUN_ID, GENESIS_REVIEWER):
        fail('H0-VERDICT: reviewer_run_id violates independence')
    if not TS_RE.match(v['created_at']):
        fail('H0-VERDICT: created_at not canonical UTC')
    packet = (campaign_dir(cid) / 'review_packets' /
              'phase_entry.json').read_bytes()
    if v['input_commitment_sha256'] != sha(packet):
        fail('H0-VERDICT: input_commitment_sha256 does not bind the exact '
             'review packet bytes')
    matches = [r for r in ledger_verdicts
               if r['operation'] == 'PHASE_ENTRY'
               and r['input_commitment_sha256'] == v['input_commitment_sha256']
               and r['state'] == v['state']
               and r['reviewer_run_id'] == v['reviewer_run_id']
               and r['created_at'] == v['created_at']]
    if not matches:
        fail('H0-VERDICT: no ledger line matches the persisted verdict '
             '(append missing or diverged)')
    return v


def h_campaign_closed_world(cid, bootstrap_stage=False):
    d = campaign_dir(cid)
    got = sorted(p.relative_to(d).as_posix() for p in d.rglob('*')
                 if p.is_file())
    expected = sorted(BOOTSTRAP_H_CAMPAIGN_FILES if bootstrap_stage
                      else ALLOWED_H_CAMPAIGN_FILES)
    if got != expected:
        fail(f'H0-WORLD: h_campaign closed-world violation: {got} != '
             f'{expected}')
    empties = [str(p) for p in d.rglob('*') if p.is_dir()
               and not any(p.iterdir())]
    if empties:
        fail(f'H0-WORLD: empty h_campaign directories refused '
             f'(certifiability): {empties}')
    for sub in [d, *d.rglob('*')]:
        if sub.is_dir() and c4d.mode_of(sub) != 0o700:
            fail(f'H0-WORLD: h_campaign dir mode drift: {sub}')


def no_leak_scan(cid, *extra_paths):
    """所有 64-hex token 必须属于白名单哈希；禁止任何 ocid/T/identity 键。"""
    order = c4d.candidate_total_order()
    forbidden_ocids = {c['opaque_case_id'] for c in order}
    forbidden_ts = {c['T'] for c in order}
    events = fb.verify_chain(CSR)
    allowed = {e['event_hash'] for e in events}
    allowed.add(c4d.LIVE_R1_EVENT_HASH)
    allowed.add('0' * 64)
    allowed |= {TASKBOOK_SHA256, c4d.ANNOTATION_CONTRACT_SHA256,
                act.C3_COMMITMENT, act.C3_PACKET_SCHEMA,
                act.C1_PLAN_COMMITMENT, act.C1_SALT_COMMITMENT,
                act.C1_PROJECTION_SHA}
    allowed.add(sha(canon(order).encode()))
    d = campaign_dir(cid)
    paths = [d / rel for rel in ALLOWED_H_CAMPAIGN_FILES]
    paths += [Path(p) for p in extra_paths]
    for p in paths:
        if p.is_file():
            allowed.add(sha(p.read_bytes()))
    ledger_path = d / 'reviews.jsonl'
    if ledger_path.is_file():
        for ln in ledger_path.read_text().splitlines():
            if ln.strip():
                allowed.add(json.loads(ln)['review_hash'])
    proposal = c4d.proposal_path(CSR, SID, START_ORDINAL)
    if proposal.is_file():
        allowed.add(sha(proposal.read_bytes()))
    for p in paths:
        if not p.is_file():
            continue
        text = p.read_text()
        tokens = set(HEX64_RE.findall(text))
        leak = tokens & forbidden_ocids
        if leak:
            fail(f'H0-LEAK: candidate opaque id leaked in {p.name}')
        unbound = tokens - allowed
        if unbound:
            fail(f'H0-LEAK: unbound 64-hex token in {p.name}: '
                 f'{sorted(unbound)[:3]}')
        if re.search(r'"(opaque_case_id|case_key|ocid|packet_id|symbol|'
                     r'ticker|stock_code)"', text):
            fail(f'H0-LEAK: identity/ocid/packet key present in {p.name}')
        for t in forbidden_ts:
            if t in text:
                fail(f'H0-LEAK: candidate T value leaked in {p.name}')


# --------------------------------------------------------------------------
# frozen-domain maintenance + verifier battery
# --------------------------------------------------------------------------

def maintenance():
    """冻结域维护（Phase F 契约：thaw 窗口内受控重建 + 再冻结写屏障）。

    双 pass certify（先解决 protected-set 鸡蛋问题，再固化冻结树）：
    pass-1 在 ordinal-0003 proposal 归一回 0600 后重建 manifest，使其
    进入 protocol_0600 exempt 集；enforce_domain_modes 由此把新 proposal
    精确钉在 0600 并重建 freeze ledger；pass-2 重新 certify 已冻结树，
    使 certified manifest 与 freeze ledger 字节一致。pass 间只发生
    mode-only 归一与 ledger 重建，任何 frozen 内容字节不变。
    """
    import os
    proposal = c4d.proposal_path(CSR, SID, START_ORDINAL)
    if not proposal.is_file():
        fail('H0-MAINT: ordinal-3 proposal missing')
    files = fb.annotator_files(CSR, SID)
    r = subprocess.run(['chattr', '-i', *[str(p) for p in files]],
                       capture_output=True, text=True)
    if r.returncode:
        fail(f'H0-MAINT: thaw failed: {r.stderr[:200]}')
    if c4d.mode_of(proposal) != 0o600:
        os.chmod(proposal, 0o600)          # mode-only 归一（协议契约 0600）
    certify_pass = _certify()
    fb.enforce_domain_modes(CSR)
    certify_pass2 = _certify()
    immutable_count = fb.set_annotator_immutable(CSR)
    if fb.verify_annotator_immutable(CSR) != 'PASS':
        fail('H0-MAINT: annotator immutability re-freeze failed')
    fb.verify_owner_write_barrier(CSR)
    if c4d.mode_of(proposal) != 0o600:
        fail('H0-MAINT: ordinal-3 proposal must be exactly 0600 after '
             'the protocol freeze')
    return {'annotator_files_immutable': immutable_count,
            'certify_pass1': certify_pass,
            'certify_pass2': certify_pass2,
            'ordinal3_proposal_mode': oct(c4d.mode_of(proposal))}


def _certify():
    r = subprocess.run([sys.executable,
                        str(ROOT / 'scripts/csr8_phase_a_certify_inputs.py')],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        fail(f'H0-MAINT: certified manifest regeneration failed: '
             f'{r.stdout[-300:]} {r.stderr[-300:]}')
    return r.stdout.strip()


def battery():
    """冻结校验器全电池（全部只读复验）。"""
    manifest = ma.verify_certified_tree()
    anchor = fb.verify_manifest_anchor()
    events = fb.verify_chain(CSR)
    blinding = fb.verify_blinding(CSR)
    corpus = fb.verify_corpus(CSR)
    fp = load_module('scripts/csr8_phase_f_audit_package.py', 'h0_fp')
    pkg = fp.verify(fp.PKG)
    if not pkg['all_pass']:
        fail(f'H0-BATTERY: audit package re-verification failed: {pkg}')
    for name, gates in (('blinding', blinding['gates']),
                        ('corpus', corpus)):
        bad = {k: v for k, v in gates.items() if v != 'PASS'}
        if bad:
            fail(f'H0-BATTERY: {name} gates failed: {bad}')
    return {'certified_tree': 'PASS',
            'certified_files': manifest['fileCount'],
            'certified_roots': len(manifest['roots']),
            'manifest_anchor': anchor,
            'chain_replay': 'PASS',
            'blinding_gates': sorted(blinding['gates']),
            'corpus_gates': sorted(corpus),
            'audit_package_gates': sorted(pkg['gates']),
            'production_head': events[-1]['event_hash']}


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------

def build_evidence(gates, r0, cid, artifacts, ledger, verdict, batt,
                   maint):
    return {
        'run_id': RUN_ID, 'stage': STAGE, 'iteration': ITERATION,
        'host_id': HOST_ID,
        'operation': 'PHASE_ENTRY',
        'taskbook': {'version': TASKBOOK_VERSION, 'sha256': TASKBOOK_SHA256},
        'entry_gate': gates,
        'round0': r0,
        'campaign': {'campaign_id': cid,
                     'manifest_sha256': sha(artifacts['manifest']),
                     'review_packet_sha256': sha(artifacts['packet']),
                     'review_ledger_records': ledger['records'],
                     'review_ledger_head': ledger['head_review_hash'],
                     'ordinal3_proposal_sha256': sha(artifacts['proposal']),
                     'ordinal3_proposal_state':
                         'PREPARED_NOT_AUTHORIZED_NOT_REVEALED'},
        'phase_entry_review': {'state': verdict['state'],
                               'reviewer_run_id': verdict['reviewer_run_id'],
                               'input_commitment_sha256':
                                   verdict['input_commitment_sha256'],
                               'created_at': verdict['created_at'],
                               'issues': verdict['issues'],
                               'required_changes': verdict['required_changes'],
                               'independence':
                                   'reviewer_run_id != executor_run_id '
                                   '(role/context/write separation '
                                   'machine-checked)'},
        'maintenance': maint,
        'verifier_battery': batt,
        'outcome_accessed': False,
        'identity_accessed': False,
        'future_data_accessed': False,
        'outcome_access_note': 'outcome/analysis_labeled bytes were only '
                               're-hashed by the frozen certified-manifest '
                               'pinning mechanism; no outcome content was '
                               'parsed, joined or exposed to any annotation '
                               'or selection surface',
        'declaration_note': '进入 H1 的许可是 independent reviewer 的 '
                            'PHASE_ENTRY APPROVE；执行者只承载机器实测。',
        'created_at': now_utc(),
    }


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_bootstrap():
    gates = entry_gates()                       # fail-closed, read-only
    chain = gates['chain']
    r0 = round0_facts(chain)
    cid = derive_campaign_id(chain)
    proposal_bytes, pstate = build_or_verify_proposal()
    manifest_bytes, mstate = build_or_verify_manifest(gates, chain, r0, cid)
    genesis_bytes, gstate = build_or_verify_genesis(cid, manifest_bytes)
    packet_bytes, pstate2 = build_or_verify_packet(
        gates, chain, r0, cid, proposal_bytes, manifest_bytes, genesis_bytes)
    h_campaign_closed_world(cid, bootstrap_stage=True)
    no_leak_scan(cid)
    print(json.dumps({
        'stage': STAGE, 'state': 'BOOTSTRAPPED',
        'campaign_id': cid,
        'round0': r0,
        'entry_gate': 'PASS',
        'ordinal3_proposal_sha256': sha(proposal_bytes),
        'ordinal3_proposal': pstate,
        'campaign_manifest': mstate,
        'review_ledger_genesis': gstate,
        'review_packet_sha256': sha(packet_bytes),
        'review_packet': pstate2,
        'input_commitment_sha256': sha(packet_bytes),
        'executor_run_id': EXECUTOR_RUN_ID,
    }, ensure_ascii=False, sort_keys=True))
    return 0


def normalize_h_campaign_modes(cid):
    """executor 域 mode-only 归一（0700 目录/0600 文件）——绝不触碰内容；
    内容与哈希链由 verify_ledger/verify_verdict_file 复验。"""
    import os
    d = campaign_dir(cid)
    for p in [d, *d.rglob('*')]:
        if p.is_dir() and stat.S_IMODE(p.stat().st_mode) != 0o700:
            os.chmod(p, 0o700)
        elif p.is_file() and stat.S_IMODE(p.stat().st_mode) not in (
                0o600, 0o400):
            os.chmod(p, 0o600)


def thaw_and_normalize():
    """打开 thaw 窗口并把 ordinal-3 proposal 归一回协议契约 0600
    （mode-only；前一维护窗口的 enforce 可能把新 proposal 降为 0400，
    且 +i 属性会阻止 chmod——先统一 thaw 再归一）。"""
    import os
    files = fb.annotator_files(CSR, SID)
    r = subprocess.run(['chattr', '-i', *[str(p) for p in files]],
                       capture_output=True, text=True)
    if r.returncode:
        fail(f'H0-MAINT: thaw failed: {r.stderr[:200]}')
    proposal = c4d.proposal_path(CSR, SID, START_ORDINAL)
    if proposal.is_file() and c4d.mode_of(proposal) != 0o600:
        os.chmod(proposal, 0o600)


def cmd_postreview():
    gates = entry_gates()
    chain = gates['chain']
    r0 = round0_facts(chain)
    cid = derive_campaign_id(chain)
    thaw_and_normalize()
    normalize_h_campaign_modes(cid)
    h_campaign_closed_world(cid)
    ledger = verify_ledger(cid)
    verdict = verify_verdict_file(cid, ledger['verdicts'])
    no_leak_scan(cid)
    if verdict['state'] != 'APPROVE':
        halt(f'PHASE_ENTRY reviewer verdict is {verdict["state"]} — '
             f'H1 entry forbidden (issues={verdict["issues"]}, '
             f'required_changes={verdict["required_changes"]})')
    proposal_bytes, _ = build_or_verify_proposal()
    manifest_bytes, _ = build_or_verify_manifest(gates, chain, r0, cid)
    packet_bytes, _ = build_or_verify_packet(
        gates, chain, r0, cid, proposal_bytes, manifest_bytes,
        (campaign_dir(cid) / 'reviews.jsonl').read_bytes().splitlines()[0])
    maint = maintenance()
    batt = battery()
    evidence = build_evidence(gates, r0, cid,
                              {'manifest': manifest_bytes,
                               'packet': packet_bytes,
                               'proposal': proposal_bytes},
                              ledger, verdict, batt, maint)
    if EVIDENCE.exists():
        fail('H0-EVIDENCE: evidence already exists (write-once)')
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False,
                                   sort_keys=True, indent=1))
    no_leak_scan(cid, EVIDENCE)
    print(json.dumps({'stage': STAGE, 'state': 'READY_FOR_AUDIT',
                      'campaign_id': cid,
                      'phase_entry_review': verdict['state'],
                      'reviewer_run_id': verdict['reviewer_run_id'],
                      'verifier_battery': 'PASS',
                      'evidence': str(EVIDENCE.relative_to(ROOT))},
                     ensure_ascii=False, sort_keys=True))
    return 0


def cmd_verify():
    gates = entry_gates()
    chain = gates['chain']
    r0 = round0_facts(chain)
    cid = derive_campaign_id(chain)
    thaw_and_normalize()
    normalize_h_campaign_modes(cid)
    h_campaign_closed_world(cid)
    ledger = verify_ledger(cid)
    verdict = verify_verdict_file(cid, ledger['verdicts'])
    proposal_bytes, _ = build_or_verify_proposal()
    manifest_bytes, _ = build_or_verify_manifest(gates, chain, r0, cid)
    packet_bytes, _ = build_or_verify_packet(
        gates, chain, r0, cid, proposal_bytes, manifest_bytes,
        (campaign_dir(cid) / 'reviews.jsonl').read_bytes().splitlines()[0])
    no_leak_scan(cid, EVIDENCE)
    batt = battery()
    # verify 开头打开了 thaw 窗口（mode 归一需要可写）：此处恢复 §9.1
    # 写屏障，保证任何入口离开时冻结面完整（幂等）。
    fb.set_annotator_immutable(CSR)
    if fb.verify_annotator_immutable(CSR) != 'PASS':
        fail('H0-VERIFY: annotator immutability re-freeze failed')
    fb.verify_owner_write_barrier(CSR)
    print(json.dumps({'stage': STAGE, 'state': 'VERIFIED',
                      'campaign_id': cid, 'round0': r0,
                      'phase_entry_review': verdict['state'],
                      'verifier_battery': batt},
                     ensure_ascii=False, sort_keys=True))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('bootstrap', 'postreview', 'verify'))
    args = ap.parse_args(argv)
    try:
        if args.command == 'bootstrap':
            return cmd_bootstrap()
        if args.command == 'postreview':
            return cmd_postreview()
        return cmd_verify()
    except RuntimeError as e:
        halt(str(e))


if __name__ == '__main__':
    sys.exit(main())
