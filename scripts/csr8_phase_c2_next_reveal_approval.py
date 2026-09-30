#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C C2 — ordinal-2 NEXT_REVEAL_ONLY approval（真实授权点，仅 C2）。

任务书 §6 C2 + 修订 v2-unattended-20260930（run
audit_20260930021152297 阶段 C2，纯无人值守）。仅允许：

  1. 写前状态实测：C1 终态完好（scripts/csr8_phase_c1_ordinal2_proposal
     .verify_c1 全 gate PASS，阶段感知：authorization 域自本阶段起合法）。
  2. 持久化链侧授权工件（冻结 §7 builder verbatim 驱动，O_EXCL /
     canonical / 0600 / fsync）：
       production/<sid>/authorization/ordinal-0002/next_reveal.approval.json
         （c4d.approve_next_reveal — approved_authorization_sha256 ==
          SHA256(exact proposal bytes)）
       production/<sid>/authorization/ordinal-0002/next_reveal.permit.json
         （c4d.materialize_next_permit — permit exact bytes == proposal
          exact bytes）
  3. 持久化运行侧无人值守批准记录
     docs/audit/evidence/c2_unattended_approval.json
     （approved_by=UNATTENDED_POLICY，binding=['EXACT']，
      scope=NEXT_REVEAL_ONLY，措辞/字段中的 hash 与
      approved_proposal_sha256 逐字符一致，绑定被批准工件 exact hash）。

三方一致（机器实测）：proposal exact bytes == approved hash ==
permit exact bytes。

禁止（本模块物理上不包含对应代码路径）：append R2（C3 授权点，授权
保持 UNUSED）、SEAL/approve_seal（C4-C6 阶段）、outcome 读取、任何
授权扩张（仅授权本次 NEXT_REVEAL_ONLY 对应的 exact bytes）。

用法：
  python3 scripts/csr8_phase_c2_next_reveal_approval.py --persist  # 一次性真实事务
  python3 scripts/csr8_phase_c2_next_reveal_approval.py --verify   # 只读全 gate 实测
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402 (read-only reuse)
import csr8_phase_c1_ordinal2_proposal as c1  # noqa: E402 (read-only reuse)

ROOT = c4d.ROOT
REAL_CSR = c4d.REAL_CSR
SID = c4d.REAL_SESSION
ORDINAL = 2

RUN_ID = 'audit_20260930021152297'
HOST_ID = 'RainYun-c438TDGn'
STAGE, ITERATION = 'C2', 1
AMENDMENT = 'v2-unattended-20260930'
APPROVED_BY = 'UNATTENDED_POLICY'

UNATTENDED_RECORD = ROOT / 'docs/audit/evidence/c2_unattended_approval.json'

G_STATE = 'G-C2-STATE'
G_PROP = 'G-C2-PROPOSAL'
G_APPR = 'G-C2-APPROVAL'
G_PERM = 'G-C2-PERMIT'
G_THREE = 'G-C2-THREEWAY'
G_UNUSED = 'G-C2-UNUSED'
G_REC = 'G-C2-RECORD'
G_WORLD = 'G-C2-WORLD'

# 任务书 §6 C2 固定批准措辞（§5 B4 模板对 NEXT_REVEAL_ONLY 的逐字适配，
# 本脚本内为冻结常量，逐字符复验）：
WORDING_HEAD = '我明确批准 NEXT_REVEAL_ONLY proposal exact hash:'
WORDING_TAIL = ('该批准仅授权当前 session / sealed-prefix / reveal-ordinal 所绑定的\n'
                '这一份 exact proposal bytes，不授权任何其他 proposal、SEAL、\n'
                'outcome 或任何授权扩张。')
WORDING_RE = re.compile(
    re.escape(WORDING_HEAD) + r'\n([0-9a-f]{64})\n\n' + re.escape(WORDING_TAIL))

# v2 无扩张声明（固定常量，逐字符校验）
NO_EXPANSION = ('仅授权本次（该 session / sealed-prefix / reveal-ordinal）'
                '对应的 exact proposal bytes（NEXT_REVEAL_ONLY）；不授权'
                '任何其他 proposal、SEAL、outcome 或任何授权扩张。')

RECORD_VERSION = 'c4d-c2-unattended-approval-v1'
RECORD_KEYS = {
    'approval_version', 'amendment', 'run_id', 'host_id', 'stage',
    'iteration', 'approved_by', 'policy', 'binding', 'scope',
    'session_id', 'sealed_prefix_head', 'reveal_ordinal',
    'approved_proposal_sha256', 'taskbook_wording', 'authorized_artifact',
    'authorized_artifact_sha256', 'authorized_permit',
    'authorized_permit_sha256', 'no_expansion', 'recorded_at',
}
TS_RE = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z')

APPROVAL_NAME = 'next_reveal.approval.json'
PERMIT_NAME = 'next_reveal.permit.json'
C2_PAIR = {APPROVAL_NAME, PERMIT_NAME}


def fail(msg):
    raise RuntimeError(msg)


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def authz_rel(root):
    return c4d.next_authz_dir(root, SID, ORDINAL).relative_to(root).as_posix()


def fixed_wording(proposal_sha):
    return WORDING_HEAD + '\n' + proposal_sha + '\n\n' + WORDING_TAIL


def parse_wording_hash(text):
    m = WORDING_RE.fullmatch(text)
    if not m:
        fail('wording does not match the taskbook §6 C2 fixed template '
             '(template + <64 hex>; no extra/missing characters)')
    return m.group(1)


def expected_record(proposal, psha, approval_bytes, root):
    return {
        'approval_version': RECORD_VERSION,
        'amendment': AMENDMENT,
        'run_id': RUN_ID,
        'host_id': HOST_ID,
        'stage': STAGE,
        'iteration': ITERATION,
        'approved_by': APPROVED_BY,
        'policy': APPROVED_BY,
        'binding': ['EXACT'],
        'scope': 'NEXT_REVEAL_ONLY',
        'session_id': SID,
        'sealed_prefix_head': proposal['sealed_prefix_head'],
        'reveal_ordinal': ORDINAL,
        'approved_proposal_sha256': psha,
        'taskbook_wording': fixed_wording(psha),
        'authorized_artifact': f'{authz_rel(root)}/{APPROVAL_NAME}',
        'authorized_artifact_sha256': sha256_bytes(approval_bytes),
        'authorized_permit': f'{authz_rel(root)}/{PERMIT_NAME}',
        'authorized_permit_sha256': psha,   # permit bytes == proposal bytes
        'no_expansion': NO_EXPANSION,
        'recorded_at': datetime.now(timezone.utc)
                               .strftime('%Y-%m-%dT%H:%M:%SZ'),
    }


def _verify_unattended_record(record_path, proposal, psha, approval_bytes,
                              root):
    """Re-prove the run-side unattended approval record from persisted
    bytes only: closed-world schema, canonical bytes, 0600 mode,
    run/host/stage/iteration + session/sealed-prefix/ordinal bindings,
    approved_by=UNATTENDED_POLICY, EXACT binding, NEXT_REVEAL_ONLY scope,
    character-identical proposal hash (field + taskbook wording), exact
    authorized approval/permit hashes, fixed no-expansion statement."""
    if not Path(record_path).is_file():
        fail(f'{G_REC}: unattended approval record absent: {record_path}')
    rb = Path(record_path).read_bytes()
    try:
        rec = json.loads(rb)
    except json.JSONDecodeError:
        fail(f'{G_REC}: unattended approval record is not JSON')
    if not isinstance(rec, dict) or set(rec) != RECORD_KEYS:
        fail(f'{G_REC}: unattended approval record closed-world schema '
             f'violation')
    if c4d.canon(rec).encode() != rb:
        fail(f'{G_REC}: unattended approval record is not canonical')
    if rec['approval_version'] != RECORD_VERSION or \
            rec['amendment'] != AMENDMENT:
        fail(f'{G_REC}: unattended approval record version/amendment drift')
    if rec['run_id'] != RUN_ID or rec['host_id'] != HOST_ID or \
            rec['stage'] != STAGE or rec['iteration'] != ITERATION:
        fail(f'{G_REC}: unattended approval record run/host/stage '
             f'binding drift')
    if rec['approved_by'] != APPROVED_BY or rec['policy'] != APPROVED_BY:
        fail(f'{G_REC}: approved_by/policy must be UNATTENDED_POLICY')
    if rec['binding'] != ['EXACT']:
        fail(f'{G_REC}: unattended approval binding must be EXACT')
    if rec['scope'] != 'NEXT_REVEAL_ONLY':
        fail(f'{G_REC}: unattended approval scope must be NEXT_REVEAL_ONLY')
    if rec['session_id'] != SID or \
            rec['sealed_prefix_head'] != proposal['sealed_prefix_head'] or \
            rec['reveal_ordinal'] != ORDINAL:
        fail(f'{G_REC}: unattended approval record session/prefix/ordinal '
             f'binding drift')
    if rec['approved_proposal_sha256'] != psha:
        fail(f'{G_REC}: unattended approval record does not bind the '
             f'exact proposal hash')
    if rec['taskbook_wording'] != fixed_wording(psha):
        fail(f'{G_REC}: taskbook wording drift (must be the §6 C2 fixed '
             f'template rendered with the exact proposal hash)')
    if parse_wording_hash(rec['taskbook_wording']) != psha:
        fail(f'{G_REC}: wording-embedded hash differs from '
             f'approved_proposal_sha256 — not character-identical')
    if rec['authorized_artifact'] != f'{authz_rel(root)}/{APPROVAL_NAME}' or \
            rec['authorized_permit'] != f'{authz_rel(root)}/{PERMIT_NAME}':
        fail(f'{G_REC}: authorized artifact path drift')
    if rec['authorized_artifact_sha256'] != sha256_bytes(approval_bytes):
        fail(f'{G_REC}: authorized_artifact_sha256 does not bind the '
             f'exact approval bytes')
    if rec['authorized_permit_sha256'] != psha:
        fail(f'{G_REC}: authorized_permit_sha256 must equal the proposal '
             f'hash (permit bytes == proposal bytes)')
    if rec['no_expansion'] != NO_EXPANSION:
        fail(f'{G_REC}: no-expansion statement drift')
    if not TS_RE.fullmatch(rec['recorded_at']):
        fail(f'{G_REC}: recorded_at is not a valid UTC timestamp')
    if c4d.mode_of(Path(record_path)) != 0o600:
        fail(f'{G_REC}: unattended approval record mode is not 0600')


def verify_c2(root=None, record_path=UNATTENDED_RECORD):
    """Post-state full gate verification（只读；可对任意 root 运行）。"""
    root = Path(root) if root is not None else REAL_CSR
    gates = {}

    # G-STATE: C1 终态完好（含阶段感知边界：authorization 域自 C2 起合法）
    c1_result = c1.verify_c1(root)
    if set(c1_result['gates'].values()) != {'PASS'}:
        fail(f'{G_STATE}: C1 post-state no longer verifies: '
             f'{c1_result["gates"]}')
    gates[G_STATE] = 'PASS'

    # G-PROPOSAL / G-APPROVAL / G-PERMIT: 冻结 builder 全量复证
    proposal, pbytes = c4d._check_proposal(root, SID, ORDINAL)
    gates[G_PROP] = 'PASS'
    psha = sha256_bytes(pbytes)

    ad = c4d.next_authz_dir(root, SID, ORDINAL)
    approval = c4d._check_reveal_approval(
        root, SID, ORDINAL, proposal, pbytes)
    approval_bytes = (ad / APPROVAL_NAME).read_bytes()
    if approval['approved_authorization_sha256'] != psha:
        fail(f'{G_APPR}: approval does not bind the exact proposal bytes')
    gates[G_APPR] = 'PASS'

    c4d._check_approval_permit(root, SID, ORDINAL, proposal, pbytes)
    permit_bytes = (ad / PERMIT_NAME).read_bytes()
    gates[G_PERM] = 'PASS'

    # G-THREEWAY: proposal exact bytes == approved hash == permit exact bytes
    if permit_bytes != pbytes or sha256_bytes(permit_bytes) != \
            approval['approved_authorization_sha256'] or \
            approval['approved_authorization_sha256'] != psha:
        fail(f'{G_THREE}: three-way exact-bytes consistency violated')
    gates[G_THREE] = 'PASS'

    # G-UNUSED: 授权未被消费（C3 才允许 append R2）；链仍恰为 [R1,S1]
    evs = c1.chain_events(root)
    types = [e['event_type'] for e in evs]
    if types != ['REVEAL_PACKET', 'SEAL_ANNOTATION']:
        fail(f'{G_UNUSED}: chain grew past [R1,S1] — R2 append is the C3 '
             f'authorization point, forbidden at C2 (measured {types})')
    state = c4d.derive_reveal_consumption(evs, proposal, SID)
    if state != 'UNUSED':
        fail(f'{G_UNUSED}: authorization consumption state must be UNUSED '
             f'at C2 (derived {state})')
    gates[G_UNUSED] = 'PASS'

    # G-RECORD: 运行侧无人值守批准记录全量复证
    _verify_unattended_record(record_path, proposal, psha, approval_bytes,
                              root)
    gates[G_REC] = 'PASS'

    # G-WORLD: authorization 域 closed-world（ordinal-0002 恰一对工件、
    # 0700/0600；顶层仍仅冻结 first_reveal 工件；c4c anchor 未变）
    entries = sorted(p.name for p in ad.rglob('*') if p.is_file())
    if entries != sorted(C2_PAIR):
        fail(f'{G_WORLD}: ordinal-2 authorization domain closed-world '
             f'violation (entries: {entries})')
    if any(p.is_dir() for p in ad.rglob('*')):
        fail(f'{G_WORLD}: unexpected subdirectory inside the ordinal-2 '
             f'authorization domain')
    for d in (c4d.prod_dir(root, SID) / 'authorization', ad):
        if c4d.mode_of(d) != 0o700:
            fail(f'{G_WORLD}: authorization domain mode drift — must be '
                 f'0700 ({d})')
    top = sorted(p.name for p in
                 (c4d.prod_dir(root, SID) / 'authorization').iterdir())
    expected_top = sorted(c1.FROZEN_FIRST_REVEAL_ARTIFACTS |
                          {f'ordinal-{ORDINAL:04d}'})
    if top != expected_top:
        fail(f'{G_WORLD}: production authorization top-level drift: {top}')
    anchor = json.loads((root / 'public' / 'c4c_anchor.json').read_bytes())
    if anchor.get('production_head_hash') != c4d.LIVE_R1_EVENT_HASH or \
            anchor.get('authorization_sha256') != \
            evs[0]['payload'].get('authorization_sha256'):
        fail(f'{G_WORLD}: c4c anchor no longer binds the frozen '
             f'reveal-phase R1 binding')
    gates[G_WORLD] = 'PASS'

    return {
        'root_scope': 'live' if root == REAL_CSR else 'replica',
        'gates': gates,
        'approved_by': APPROVED_BY,
        'scope': 'NEXT_REVEAL_ONLY',
        'reveal_ordinal': ORDINAL,
        'approved_proposal_sha256': psha,
        'authorized_artifact': f'{authz_rel(root)}/{APPROVAL_NAME}',
        'authorized_artifact_sha256': sha256_bytes(approval_bytes),
        'authorized_permit': f'{authz_rel(root)}/{PERMIT_NAME}',
        'authorized_permit_sha256': psha,
        'consumption': 'UNUSED',
    }


def do_approve(root=None, record_path=UNATTENDED_RECORD):
    """真实 C2 事务：写前 C1 终态实测 → 冻结 builder 一次性持久化
    approval + permit → 运行侧记录 → 全 gate 复证。"""
    root = Path(root) if root is not None else REAL_CSR
    record_path = Path(record_path)

    # 写前状态（fail-closed；C1 verify 自身保证 proposal 前置与闭域）
    c1_result = c1.verify_c1(root)
    if set(c1_result['gates'].values()) != {'PASS'}:
        fail(f'{G_STATE}: pre-write C1 verification failed: '
             f'{c1_result["gates"]}')

    # O_EXCL 前置（重跑/崩溃后不得再触发任何链侧变更）
    if record_path.exists():
        fail(f'{G_REC}: unattended approval record already exists; '
             f'immutable O_EXCL artifact')
    ad = c4d.next_authz_dir(root, SID, ORDINAL)
    if (ad / APPROVAL_NAME).exists() or (ad / PERMIT_NAME).exists():
        fail(f'{G_APPR}: duplicate authorization artifacts (O_EXCL) — '
             f'{authz_rel(root)} already holds the C2 pair')

    # 冻结 §7 builder verbatim（内部含 prove_next_reveal_eligible 前置）
    c4d.approve_next_reveal(root, SID, ORDINAL)
    c4d.fsync_dir(ad)
    c4d.materialize_next_permit(root, SID, ORDINAL)
    c4d.fsync_dir(ad)

    proposal, pbytes = c4d._check_proposal(root, SID, ORDINAL)
    psha = sha256_bytes(pbytes)
    approval_bytes = (ad / APPROVAL_NAME).read_bytes()
    record = expected_record(proposal, psha, approval_bytes, root)
    c4d.excl_write(record_path, c4d.canon(record).encode())

    result = verify_c2(root, record_path)
    result['c2'] = 'APPROVAL_PERSISTED'
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--verify', action='store_true',
                    help='read-only full gate verification (no writes)')
    ap.add_argument('--persist', action='store_true',
                    help='execute the real one-shot C2 transaction')
    args = ap.parse_args(argv)
    if args.persist:
        result = do_approve()
    else:
        result = verify_c2()
        result['c2'] = 'VERIFIED'
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':'),
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
