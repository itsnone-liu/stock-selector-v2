#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C C1 — Real ordinal-2 next-reveal proposal（真实授权点，仅 C1）。

任务书 §6 C1（run audit_20260930021152297 阶段 C1）。仅允许：

  1. 前置全部直接从 committed chain 派生并机器实测（写前证明）：
     chain == [R1,S1]、open_reveals == 0（无 open REVEAL）、前一 sealed
     pair 的 attempt-history + semantic replay PASS、candidate prefix == 1
     （revealed 集恰为冻结 candidate total-order 的长度 1 前缀）。
  2. 生成 selector-only artifact：
     data/csr8_phase_c/c4d_proposals/c4-prod-0002/ordinal-0002/
     next_reveal.proposal.json（0700 域 / 0600 文件 / canonical bytes /
     O_EXCL 一次性），由冻结 §7 builder（c4d.build_next_reveal_proposal）
     verbatim 驱动 —— 字节确定性、无时钟依赖。
  3. 人类仅看到 proposal_sha256（本脚本输出的唯一许可披露物；ordinal-2
     candidate 的 ocid/T/packet_id 保持在 selector 侧不离开）。

禁止（本模块物理上不包含对应代码路径）：approval / permit（C2 授权点）、
append R2（C3 授权点）、annotator 域（post-B5 已清理）、outcome 读取。

用法：
  python3 scripts/csr8_phase_c1_ordinal2_proposal.py            # 执行真实 proposal（一次性）
  python3 scripts/csr8_phase_c1_ordinal2_proposal.py --verify   # 只读全 gate 实测

Gate（verify_c1 全部机器实测，可对任意 root（含 tmp 副本）运行）：
  G-C1-CHAIN     committed chain 恰为 [R1,S1]；R1 == LIVE_R1_EVENT_HASH；
                 trusted-head C2 full verify PASS
  G-C1-CLOSED    open_reveals == 0（恰 1 REVEAL / 1 SEAL / 末事件 SEAL）
  G-C1-REPLAY    前一 sealed pair 的 attempt-history + semantic replay PASS
  G-C1-PREFIX    candidate prefix == 1：revealed 集恰为冻结
                 candidate total-order 的长度 1 前缀（live 另测
                 verify_candidate_gates 的 parity/唯一性/确定性）
  G-C1-ELIGIBLE  prove_next_reveal_eligible(ordinal=2) 完整闭包证明 PASS
                 （C2 full verify / ordinal 精确 / 前缀律 / 恰一 matched
                 SEAL / sealed-pair replay）
  G-C1-PROPOSAL  persisted proposal 全量复证（冻结 _check_proposal）：
                 域 0700/文件 0600、closed-world schema、canonical bytes、
                 version/scope/ordinal/session/candidate/prefix-head 绑定
  G-C1-WORLD     proposal 域 closed-world：c4d_proposals/ 下仅
                 ordinal-0002/next_reveal.proposal.json 一个文件；无
                 approval/permit 工件
  G-C1-BOUNDARY  不 append R2（REVEAL 计数仍为 1）；c4c anchor 字节
                 未变（仍绑 R1）。阶段感知：ordinal-2 authorization
                 域自 C2 授权点起合法（恰一对 approval+permit，冻结
                 链路全量复证，closed-world），其余仍禁止

冻结模块（c1/c2/c4ab/c4c 与 C4-D synthetic executor）只读导入，不修改。
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402 (read-only reuse)

ROOT = c4d.ROOT
REAL_CSR = c4d.REAL_CSR
SID = c4d.REAL_SESSION
LIVE_R1 = c4d.LIVE_R1_EVENT_HASH
ORDINAL = 2

G_CHAIN = 'G-C1-CHAIN'
G_CLOSED = 'G-C1-CLOSED'
G_REPLAY = 'G-C1-REPLAY'
G_PREFIX = 'G-C1-PREFIX'
G_ELIG = 'G-C1-ELIGIBLE'
G_PROP = 'G-C1-PROPOSAL'
G_WORLD = 'G-C1-WORLD'
G_BOUND = 'G-C1-BOUNDARY'

PROPOSAL_REL = f'c4d_proposals/{SID}/ordinal-{ORDINAL:04d}/next_reveal.proposal.json'
# C1 边界内 c4d_proposals/ 域唯一合法文件（closed-world 白名单，相对域根）
ALLOWED_PROPOSAL_ENTRIES = {PROPOSAL_REL[len('c4d_proposals/'):]}
FORBIDDEN_PROPOSAL_NAMES = ('next_reveal.approval.json', 'next_reveal.permit.json')
# Phase-A 冻结的 C4-C first-reveal 授权工件（R1 既有授权，认证清单内字节）
FROZEN_FIRST_REVEAL_ARTIFACTS = {'first_reveal.json',
                                 'first_reveal.approval.json'}


def fail(msg):
    raise RuntimeError(msg)


def canon(x):
    return c4d.canon(x)


def chain_events(root):
    lg = c4d.c2.SealingLog(c4d.log_path(root, SID), c4d.head_path(root, SID))
    c4d.c2translate(lg.load().verify, True)
    return lg.events


def _prove_prerequisites(root, gates):
    """写前/验证期共用的链派生前置证明（无任何写路径）。"""
    evs = chain_events(root)                                   # G-CHAIN (verify)
    types = [e['event_type'] for e in evs]
    if types != ['REVEAL_PACKET', 'SEAL_ANNOTATION']:
        fail(f'{G_CHAIN}: committed chain must be exactly [R1,S1] '
             f'(measured {types})')
    if evs[0]['event_hash'] != LIVE_R1:
        fail(f'{G_CHAIN}: R1 is not the frozen b5ec0ba1… REVEAL')
    gates[G_CHAIN] = 'PASS'

    reveals = [e for e in evs if e['event_type'] == 'REVEAL_PACKET']
    seals = [e for e in evs if e['event_type'] == 'SEAL_ANNOTATION']
    if len(reveals) != 1 or len(seals) != 1 or types[-1] != 'SEAL_ANNOTATION':
        fail(f'{G_CLOSED}: open_reveals must be 0 with exactly one sealed '
             f'pair (measured R={len(reveals)} S={len(seals)})')
    gates[G_CLOSED] = 'PASS'

    c4d.prove_attempt_history(root, SID, 1, events=evs, reveal=reveals[0])
    c4d.semantic_replay(root, SID, events=evs)                # G-REPLAY
    gates[G_REPLAY] = 'PASS'

    revealed_keys = [(e['payload'].get('opaque_case_id'), e['payload'].get('T'))
                     for e in reveals]
    frozen = c4d.candidate_total_order()
    frozen_keys = [(c['opaque_case_id'], c['T']) for c in frozen]
    if revealed_keys != frozen_keys[:1]:
        fail(f'{G_PREFIX}: revealed set is not the frozen candidate '
             f'total-order prefix of length 1')
    if root == REAL_CSR:
        cg = c4d.verify_candidate_gates()   # parity/uniqueness/determinism
        if cg['revealed_prefix'] != 1 or not cg['ordinal1_matches_frozen_first']:
            fail(f'{G_PREFIX}: live candidate gates drifted: {cg}')
    gates[G_PREFIX] = 'PASS'

    c4d.prove_next_reveal_eligible(root, SID, ORDINAL)        # G-ELIGIBLE
    gates[G_ELIG] = 'PASS'


def verify_c1(root=None):
    """Post-state full gate verification（只读；可对任意 root 运行）。"""
    root = Path(root) if root is not None else REAL_CSR
    gates = {}
    _prove_prerequisites(root, gates)

    proposal, pbytes = c4d._check_proposal(root, SID, ORDINAL)  # G-PROPOSAL
    gates[G_PROP] = 'PASS'

    # G-WORLD: proposal 域 closed-world（仅白名单文件；无 approval/permit；
    # 目录为结构层，不在 closed-world 文件枚举内）
    pdom = c4d.REAL_PROPOSALS_C4D if root == REAL_CSR else root / 'c4d_proposals'
    entries = sorted(p.relative_to(pdom).as_posix()
                     for p in pdom.rglob('*') if p.is_file()) \
        if pdom.exists() else []
    if entries != sorted(ALLOWED_PROPOSAL_ENTRIES):
        fail(f'{G_WORLD}: c4d_proposals closed-world violation '
             f'(entries: {entries})')
    for name in FORBIDDEN_PROPOSAL_NAMES:
        if any(e.endswith(name) for e in entries):
            fail(f'{G_WORLD}: forbidden C1-stage artifact present: {name}')
    gates[G_WORLD] = 'PASS'

    # G-BOUNDARY: 本阶段(C1)不 append R2；不生成 approval/permit。阶段
    # 感知（自 C2 授权点起）：authorization/ordinal-0002/ 域合法，但仅限
    # 恰一对 next_reveal.approval.json + next_reveal.permit.json 且经冻结
    # verify_next_authorization_chain 全量复证（closed-world）。production
    # 授权域顶层仍只有 Phase-A 冻结的 C4-C first-reveal 工件。
    evs = chain_events(root)
    if len([e for e in evs if e['event_type'] == 'REVEAL_PACKET']) != 1:
        fail(f'{G_BOUND}: chain grew past [R1,S1] — R2 append is the C3 '
             f'authorization point, forbidden at C1')
    ad = c4d.next_authz_dir(root, SID, ORDINAL)
    if ad.exists():
        try:
            c4d.verify_next_authorization_chain(root, SID, ORDINAL)
        except RuntimeError as e:
            fail(f'{G_BOUND}: ordinal-2 authorization domain exists but '
                 f'does not re-prove as the exact C2 approval+permit '
                 f'pair: {e}')
        entries = sorted(p.name for p in ad.rglob('*') if p.is_file())
        if entries != ['next_reveal.approval.json',
                       'next_reveal.permit.json']:
            fail(f'{G_BOUND}: ordinal-2 authorization domain is not the '
                 f'exact C2 pair (entries: {entries})')
        if any(p.is_dir() for p in ad.rglob('*')):
            fail(f'{G_BOUND}: unexpected subdirectory inside the '
                 f'ordinal-2 authorization domain')
    authz = c4d.prod_dir(root, SID) / 'authorization'
    if authz.exists():
        top_files = sorted(
            p.name for p in authz.iterdir() if p.is_file())
        if top_files != sorted(FROZEN_FIRST_REVEAL_ARTIFACTS):
            fail(f'{G_BOUND}: unauthorized new approval/permit artifacts '
                 f'in the production authorization domain: {top_files}')
        top_dirs = sorted(p.name for p in authz.iterdir() if p.is_dir())
        if top_dirs not in ([], [f'ordinal-{ORDINAL:04d}']):
            fail(f'{G_BOUND}: unauthorized authorization subdomains: '
                 f'{top_dirs}')
    c4c_bytes = (root / 'public' / 'c4c_anchor.json').read_bytes()
    anchor = json.loads(c4c_bytes)
    if anchor.get('production_head_hash') != LIVE_R1 or \
            anchor.get('authorization_sha256') != \
            evs[0]['payload'].get('authorization_sha256'):
        fail(f'{G_BOUND}: c4c anchor no longer binds the frozen reveal-'
             f'phase R1 binding (unchanged-by-C1 contract)')
    gates[G_BOUND] = 'PASS'

    return {
        'root_scope': 'live' if root == REAL_CSR else 'replica',
        'chain': ['REVEAL_PACKET', 'SEAL_ANNOTATION'],
        'open_reveals': 0,
        'candidate_prefix': 1,
        'proposal_rel': PROPOSAL_REL,
        'proposal_sha256': hashlib.sha256(pbytes).hexdigest(),
        'gates': gates,
    }


def do_propose(root=None):
    """真实 C1 事务：写前全前置实测 → 冻结 builder 一次性生成 → 全 gate 复证。"""
    root = Path(root) if root is not None else REAL_CSR
    gates = {}
    _prove_prerequisites(root, gates)          # 写前证明（fail-closed）

    target = root / PROPOSAL_REL
    if target.exists():
        fail(f'{G_PROP}: duplicate proposal (O_EXCL) — {PROPOSAL_REL} '
             f'already exists')
    head = c4d._current_prefix_head(root, SID)
    c4d.build_next_reveal_proposal(root, SID, ORDINAL, head)   # 冻结 §7 builder
    for d in (root / 'c4d_proposals', root / 'c4d_proposals' / SID,
              c4d.proposals_dom(root, SID, ORDINAL)):
        c4d.fsync_dir(d)

    result = verify_c1(root)
    result['c1'] = 'PROPOSAL_PERSISTED'
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--verify', action='store_true',
                    help='read-only full gate verification (no writes)')
    args = ap.parse_args(argv)
    if args.verify:
        result = verify_c1()
        result['c1'] = 'VERIFIED'
    else:
        result = do_propose()
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':'),
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
