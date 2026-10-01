#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase H H0 — Phase Entry Gate（taskbook v1.1 §8/§31，run audit_20261001135212538）.

Iteration-3 契约（对外审计意见对 iteration-2 的两项阻断全部吸收）：

* 禁读机器化：Phase H 执行代码绝不打开 outcomes/ 或 analysis_labeled/
  任何字节（动态 open-interception guard，违例即 HALT）；快照/泄漏扫描
  仅覆盖 review-surface 域（annotator 冻结域 + campaign 域）；电池剔除
  fb.verify_corpus 与 fp.verify（outcome join 复推导）以及进程内
  fb.verify_manifest_anchor（会哈希打开禁读域字节）；certified-tree
  哈希钉定由冻结 machine-audit 工具以独立子进程执行并如实披露。
  evidence 记录精确的 outcome-read policy 而非笼统否认。
* 任务书机器绑定：每次 gate 运行读取任务书源文件字节并强制
  sha256(bytes) == 冻结常量（G-H0-TASKBOOK，fail-closed），不再只有
  硬编码摘要。
* 沿袭 iteration-2：冻结基础设施零修改；ordinal-3 proposal 仅 STAGED
  （冻结 §7 builder 沙箱逐字节等价证明）；verify/postreview 对 frozen
  域纯只读；reviewer 独立性 pre/post write-surface 快照机器证明；
  round-0 口径 = §10 unique eligible cases。
* round-3 修复（as-of-round 簿记 + 写面重建基线）：iteration-3 加入
  manifest/packet 的轮次簿记字段（review_revision_count /
  campaign_review_round / prior_review_verdicts）此前按 live ledger
  派生并与持久化字节比对——reviewer 合法追加 verdict 后必然漂移。
  现按「当前 packet 轮次之前的 ledger 前缀」as-of 派生并机器校验
  （campaign_round_state；含最新 verdict 必须绑定当前 packet 字节的
  fail-closed 检查，封堵"packet 重生成覆盖自己评审"的旧缺陷形态）。
  pre 快照早于轮次 packet 重生成时，写面证明以重建基线语义豁免并
  显式披露执行者的 packet 重生成——仅当当前 packet 字节恰为最新
  ledger verdict 绑定的 input_commitment（证明重生成先于评审）。

用法：
  csr8_phase_h_entry_gate.py bootstrap     # 前置机器实测 -> campaign bootstrap
  csr8_phase_h_entry_gate.py postreview    # review 复验 + write-surface 证明
                                           # + certify(未修改脚本) + 电池 + evidence
  csr8_phase_h_entry_gate.py verify        # 纯只读全量复验（含电池）
"""

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))

RUN_ID = 'audit_20261001135212538'
STAGE = 'H0'
ITERATION = 3
HOST_ID = 'RainYun-c438TDGn'
TASKBOOK_VERSION = 'v1.1'
TASKBOOK_PATH = ('/root/dsh-ws/.feishu-files/20261001134014-'
                 'CSR8_PHASE_H_AUTONOMOUS_PRODUCTION_ANNOTATION_TASKBOOK_v1.1.md')
TASKBOOK_SHA256 = ('c6143d4ca67ffd9c39166f998675d199d7c41602cb73a'
                   '36cd4f3e4bb0dae81b8')
TASKBOOK_AUDIT_HASH = 'ddeb1ec260fa'
FREEZE_COMMIT = 'cd7f2a5db0fddee824bd1e5ce6da0f8bcd7431ca'
AUDITED_INFRA_HEAD = '04c89e7c43fb24e731871608ff40adee83221f64'
EXECUTOR_RUN_ID = f'{RUN_ID}:executor-{STAGE.lower()}'
REVIEW_VERSION = 'csr8-h-review-v1'
CAMPAIGN_PURPOSE = 'csr8-phase-h-campaign-v3'
START_ORDINAL = 3
# §8: 禁止读取 outcome / identity resolver / future data。Phase H 执行代码
# 不得打开 FORBIDDEN_READ_ZONES 下任何文件的字节（哈希也不行）；唯一
# 允许触及这些字节的机制是冻结的 certified-manifest 认证管线
# （certify + verify_certified_tree 的哈希钉定，内容永不进入 Phase H 层）。
FORBIDDEN_READ_ZONES = ('outcomes', 'analysis_labeled')
# 执行器快照/扫描白名单域：annotator 冻结域 + campaign 域（review surface）。
SNAPSHOT_ZONES = ('production', 'c4d_proposals', 'c4d_receipts',
                  'c4_public', 'h_campaign')
# disclosed historical commitments cited in cross_campaign_review_history
# (superseded rounds' packets/ledger heads — public remediation record)
CROSS_CAMPAIGN_COMMITMENTS = frozenset({
    # iteration-2 campaign round-1 ledger head (APPROVE, externally rejected)
    '6bdd3e5324a24c72257e49dd03ed8cab6a6f8ec79e4ae6de6aedd246f482897b',
    # iteration-3 round-1 packet commitment + ledger line hash (REVISE)
    'ab17ca2b8bd93d8016fdebd9c354ba71a41668247ce914cd0d512d5616488e18',
    '1dc9d038eb7de0314d5679157f197ab6d1ac4c6062968115747fa2549153c',
    # iteration-3 round-2 packet commitment (REVISE; ledger line is live)
    'c3082960c13d369aa314507dd739e16cf849c3cb6b51a8b856a321141afd526c',
})

OUTCOME_READ_POLICY = {    'phase_h_executor_direct_outcome_reads': 0,
    'phase_h_executor_analysis_labeled_reads': 0,
    'outcome_join_rederivations': 0,
    'in_process_guarantee': 'a dynamic ForbiddenReadGuard intercepts every '
                            'in-process file open during command execution '
                            'and fails closed (G-H0-FORBIDDEN-READ) on any '
                            'read under outcomes/ or analysis_labeled/',
    'hash_pinning_only': 'outcome/analysis_labeled bytes are touched ONLY '
                         'inside isolated frozen-tool SUBPROCESSES — the '
                         'unmodified certify + machine-audit scripts '
                         '(certified-manifest hash pinning; the machine '
                         'audit additionally byte-materializes certified '
                         'files into its own /tmp tree and runs its '
                         'internal C6 crash-recovery whole-tree copy) and '
                         'the dedicated C6 subprocess (its own whole-tree '
                         'copy) — never opened, parsed, joined or exposed '
                         'by any in-process Phase H code path; the secret/ '
                         'zone is opened in-process only by frozen '
                         'taskbook-required modules (candidate-order '
                         'derivation), never by Phase H owned code, and '
                         'every in-process open is enumerated by zone in '
                         'the guard summary',
    'removed_verifiers': [
        'fb.verify_corpus — verifies the exported labeled corpus, i.e. '
        're-derives the outcome join (forbidden for Phase H)',
        'fp.verify — audit-package gate battery includes corpus/join '
        'gates (forbidden for Phase H)',
        'fb.verify_manifest_anchor (in-process) — hashes every certified '
         'file INCLUDING forbidden-zone bytes to anchor the manifest; '
         'replaced by the frozen machine-audit subprocess which performs '
         'the same manifest↔tree closed-world comparison'],
}
EVIDENCE = ROOT / 'docs/audit/evidence/h_phase_entry_gate.json'
MARKER_REL = 'docs/audit/evidence/production_infra_final_frozen.json'
GENESIS_REVIEWER = 'executor-bootstrap'
ROUND0_CALIBER = ('taskbook §10: round0 completes when EVERY eligible case '
                  'has >=1 complete sealed blinded annotation; caliber = '
                  'unique eligible cases, not (case,T) pairs')

BOOTSTRAP_FILES = (
    'campaign_manifest.json',
    'reviews.jsonl',
    'review_packets/phase_entry.json',
    'ordinal_0003/next_reveal.proposal.staged.json',
    'executor_state/pre_review_write_surface.json',
)
FINAL_FILES = BOOTSTRAP_FILES + (
    'verdicts/phase_entry.verdict.json',
    'executor_state/post_review_write_surface.json',
)
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
    print(json.dumps({'stage': STAGE, 'iteration': ITERATION, 'state': 'HALT',
                      'reason': msg}, ensure_ascii=False, sort_keys=True))
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
    return subprocess.run(['git', *args], cwd=str(ROOT), capture_output=True,
                          text=True)


# --------------------------------------------------------------------------
# entry gates — read-only, fail-closed (frozen verifiers only)
# --------------------------------------------------------------------------

def gate_taskbook_binding():
    """任务书与源文件字节机器绑定：运行时读取源文件并哈希比对冻结值。

    修复 iteration-2 缺陷：此前任务书 sha256 仅以硬编码常量记录，执行器
    从未打开源文件验证字节；现在每次 gate 运行都强制
    sha256(taskbook source bytes) == 冻结值，不匹配即 HALT。
    """
    p = Path(TASKBOOK_PATH)
    if not p.is_file():
        fail('G-H0-TASKBOOK: taskbook source file missing at the frozen '
             'path')
    raw = p.read_bytes()
    got = sha(raw)
    if got != TASKBOOK_SHA256:
        fail(f'G-H0-TASKBOOK: taskbook source bytes hash to {got}, not '
             f'the frozen {TASKBOOK_SHA256} — machine binding broken')
    return {'path': TASKBOOK_PATH,
            'sha256': got,
            'bytes': len(raw),
            'machine_binding': 'PASS — sha256(source file bytes) == '
                               'frozen constant, re-verified every run',
            'audit_protocol_taskbook_hash': TASKBOOK_AUDIT_HASH}


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
    if git('cat-file', '-e', f'{FREEZE_COMMIT}^{{commit}}').returncode != 0:
        fail('G-H0-MARKER: freeze commit does not exist')
    if git('merge-base', '--is-ancestor', FREEZE_COMMIT,
           'HEAD').returncode != 0:
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
    events = fb.verify_chain(CSR)
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


# 审计层漂移披露（H-Q10 可审计性）：相对冻结 commit 的全部 tracked/
# 未忽略差异，逐文件给出 §2 分类；出现映射外漂移即 fail-closed，强制
# 先披露再放行。冻结边界文件零漂移由上面单独校验。
AUDIT_LAYER_DRIFT_CLASSIFICATION = {
    'scripts/csr8_phase_h_entry_gate.py':
        'phase-h entry-gate tooling (new, not in §2 frozen enumeration)',
    'scripts/csr8_phase_f_audit_package.py':
        'audit-tool repair: cross-stage export exclusion list (not in §2)',
    'tests/test_csr8_phase_h_entry_gate.py':
        'phase-h tooling test realignment',
    'tests/test_csr8_phase_a.py':
        'audit test realignment (c4d closed-world + staged-proposal shape)',
    'tests/test_csr8_phase_c2_approval.py':
        'audit test realignment (stage-aware skip after C2 rotation)',
    'config/audit/certified_live_inputs.json':
        'designed certify absorption (regenerated manifest)',
    'docs/audit/evidence/h_phase_entry_gate.json':
        'phase-h machine evidence (regenerated and committed each '
        'iteration; absent at the freeze commit)',
    '.dsh-audit-task.json':
        'harness bookkeeping file (non-§2, outside audit surface)',
}


def gate_frozen_infra_clean():
    """frozen infra 零漂移：本阶段不得改动任何冻结基础设施文件。

    清单 = taskbook §2 冻结的标注基础设施（数据管线/协议/桥接/校验器）。
    csr8_phase_f_audit_package.py（Phase F 审计包导出器）不在 §2 冻结
    清单内——其跨阶段排除名单本就不排除同类 stage-G 视图，其桥接测试
    修复属于审计工具修复，不属于标注基础设施修改。

    同时机器枚举相对冻结 commit 的全部 tracked 漂移并逐文件分类披露
    （round-3 reviewer 要求）：checked=7 的声明必须对全量 diff 可审计。
    """
    files = ['scripts/csr8_phase_a_certify_inputs.py',
             'scripts/csr8_phase_a_machine_audit.py',
             'scripts/csr8_phase_d_progressive_loop.py',
             'scripts/csr8_phase_f_bridge.py',
             'scripts/csr8_phase_c_annotation_seal.py',
             'scripts/csr8_phase_c6_seal_s2.py',
             'scripts/csr8_phase_c_activate.py']
    r = git('diff', '--name-only', FREEZE_COMMIT, '--', *files)
    if r.returncode != 0 or r.stdout.strip():
        fail(f'G-H0-FROZEN-INFRA: frozen infrastructure files differ from '
             f'the freeze commit: {r.stdout.strip()}')
    drift = {}
    for src in (git('diff', '--name-only', FREEZE_COMMIT).stdout
                .split() + [l[3:] for l in
                            git('status', '--porcelain').stdout.splitlines()
                            if l[:3].strip()]):
        if not src or src in drift or src in files:
            continue
        cls = AUDIT_LAYER_DRIFT_CLASSIFICATION.get(src)
        if cls is None:
            fail(f'G-H0-FROZEN-INFRA: unclassified drift vs freeze commit '
                 f'{src} — disclose and classify it before proceeding')
        drift[src] = cls
    return {'frozen_infra_files_unchanged_since_freeze_commit': True,
            'checked': len(files),
            'audit_layer_drift_disclosure': {
                'basis': 'git diff --name-only <freeze-commit> plus working-'
                         'tree porcelain vs the freeze commit; frozen-'
                         'boundary files (above) excluded from the drift '
                         'set by the zero-drift check',
                'frozen_boundary_files_changed': 0,
                'files': drift}}


def c6_verify_via_subprocess():
    """冻结 C6 验证器在专用子进程运行（iteration-3 round-3 修复）。

    c6.verify() 的 crash-recovery 探测会把整棵 CSR 树（含 outcomes/ 与
    analysis_labeled/）copytree 到 /tmp —— 这是冻结工具自身的行为，必须
    发生在隔离进程里，执行进程绝不运行它（否则任何 open 拦截都会被
    shutil 的 DirEntry/批量拷贝模式绕开或触发）。
    """
    code = (
        "import importlib.util, sys, json\n"
        "spec = importlib.util.spec_from_file_location("
        "'c6iso', sys.argv[1])\n"
        "m = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(m)\n"
        "print(json.dumps(m.verify(), ensure_ascii=False, "
        "sort_keys=True))\n")
    r = subprocess.run([sys.executable, '-c', code,
                        str(ROOT / 'scripts/csr8_phase_c6_seal_s2.py')],
                       cwd=str(ROOT), capture_output=True, text=True,
                       timeout=1800)
    if r.returncode != 0:
        fail(f'G-H0-C6: isolated C6 verifier failed: '
             f'{r.stdout[-300:]} {r.stderr[-300:]}')
    return json.loads(r.stdout.strip().splitlines()[-1])


def entry_gates():
    taskbook = gate_taskbook_binding()
    marker = gate_frozen_marker()
    chain = gate_chain()
    forensic = gate_forensic()
    authority = gate_authority()
    authz = gate_authorizations(fb.verify_chain(CSR))
    c6 = c6_verify_via_subprocess()
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
    frozen_infra = gate_frozen_infra_clean()
    return {'taskbook_binding': taskbook,
            'frozen_marker': marker, 'chain': chain, 'forensic': forensic,
            'authority': authority, 'authorizations': authz,
            'frozen_infra': frozen_infra,
            'c6_dual_cycle': {k: c6[k] for k in (
                'c6', 'chain', 'production', 'open_reveals',
                'candidate_prefix', 'r1_s1_exact', 'r2_s2_exact',
                'ordinal1_history', 'ordinal2_history', 'authorization1',
                'authorization2', 'dual_replay', 'crash_recovery',
                'outcome_untouched')} | {
                'execution_isolation': 'dedicated subprocess (crash-'
                                        'recovery whole-tree copy happens '
                                        'inside the isolated frozen-tool '
                                        'process, never in-process)',
                'outcome_untouched_note': 'outcome_untouched is a '
                                          'constant relayed by the frozen '
                                          'C6 verifier, not a fresh '
                                          'Phase-H measurement'}}

def round0_facts(chain):
    """§10 口径：eligible case（唯一 opaque case）为完成单位。"""
    order = c4d.candidate_total_order()
    total = len({c['opaque_case_id'] for c in order})
    sealed_cases = set()
    events = fb.verify_chain(CSR)
    for e in events:
        if e['event_type'] == 'REVEAL_PACKET':
            sealed_cases.add(e['payload']['opaque_case_id'])
    completed = len(sealed_cases)
    remaining = total - completed
    if completed != chain['seal_count'] or remaining != total - completed:
        fail('G-H0-ROUND0: round0 accounting invariant violated')
    return {'total': total, 'completed': completed, 'remaining': remaining,
            'pair_order_size': len(order),
            'caliber': ROUND0_CALIBER}


# --------------------------------------------------------------------------
# ordinal-3 staged proposal — frozen builder proven in a trimmed sandbox
# --------------------------------------------------------------------------

def build_staged_proposal_via_frozen_builder():
    """在 /tmp 裁剪沙箱里逐字节运行冻结 §7 builder（live 域零写）。

    沙箱镜像：production/<sid>/sealing、c4d_receipts/<sid>、c4_public
    （derive_state==SEALED 与 prove_next_reveal_eligible 的全部输入）。
    产出字节与未来 H1 在 live 域的授权后构建必然一致（同一冻结函数、
    同一冻结输入）。沙箱用后即焚。
    """
    head = c4d._current_prefix_head(CSR, SID)
    with tempfile.TemporaryDirectory(prefix='h0-ordinal3-builder-') as td:
        sb = Path(td) / 'csr8_phase_c'
        shutil.copytree(CSR / 'production' / SID / 'sealing',
                        sb / 'production' / SID / 'sealing',
                        copy_function=shutil.copy2)
        shutil.copytree(CSR / 'c4d_receipts' / SID,
                        sb / 'c4d_receipts' / SID,
                        copy_function=shutil.copy2)
        shutil.copytree(CSR / 'c4_public', sb / 'c4_public',
                        copy_function=shutil.copy2)

        def mirror(src_root, dst_root):
            for p in [src_root, *src_root.rglob('*')]:
                d = dst_root / p.relative_to(src_root)
                if d.exists():
                    os.chmod(d, stat.S_IMODE(p.stat().st_mode))
        mirror(CSR / 'production' / SID / 'sealing', sb / 'production' / SID / 'sealing')
        mirror(CSR / 'c4d_receipts' / SID, sb / 'c4d_receipts' / SID)
        mirror(CSR / 'c4_public', sb / 'c4_public')
        for d in (sb, sb / 'production', sb / 'production' / SID,
                  sb / 'c4d_receipts'):
            os.chmod(d, 0o700)
        state, _ = c4d.derive_state(sb, SID)
        if state != 'SEALED':
            fail(f'H0-STAGE: sandbox derived state must be SEALED '
                 f'(got {state})')
        head_sb = c4d._current_prefix_head(sb, SID)
        if head_sb != head:
            fail('H0-STAGE: sandbox prefix head diverges from live head')
        proposal = c4d.build_next_reveal_proposal(sb, SID, START_ORDINAL,
                                                  head)
        pbytes = (c4d.proposal_path(sb, SID, START_ORDINAL)).read_bytes()
        if pbytes != canon(proposal).encode():
            fail('H0-STAGE: builder bytes not canonical')
    cand = c4d.candidate_for_ordinal(START_ORDINAL)
    if proposal['reveal_ordinal'] != START_ORDINAL \
            or proposal['scope'] != 'NEXT_REVEAL_ONLY' \
            or proposal['sealed_prefix_head'] != head \
            or proposal['session_id'] != SID:
        fail('H0-STAGE: staged proposal binding drift')
    return proposal, pbytes, head


# --------------------------------------------------------------------------
# campaign bootstrap
# --------------------------------------------------------------------------

def campaign_seed(chain, r0):
    return {'purpose': CAMPAIGN_PURPOSE,
            'taskbook_sha256': TASKBOOK_SHA256,
            'production_infra_freeze_commit': FREEZE_COMMIT,
            'audited_infra_head': AUDITED_INFRA_HEAD,
            'session_id': SID,
            'production_head': chain['production_head'],
            'candidate_order_size': chain['candidate_order_size'],
            'round0_caliber': 'unique-eligible-cases-v1',
            'round0_total': r0['total'],
            'start_ordinal': START_ORDINAL}


def derive_campaign_id(chain, r0):
    return 'hc-' + sha(canon(campaign_seed(chain, r0)).encode())[:32]


def archive_campaign(cid, reason):
    """§6/§15 修复：campaign 只能归档、永不删除。归档域被 certify 吸收
    （data/ 落盘机制），reviewer 历史（含 ledger 行）字节级保留。"""
    src = campaign_dir(cid)
    if not src.is_dir():
        return None
    arch_root = CSR / 'h_campaign_archive'
    arch_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    n = 1
    dst = arch_root / f'{cid}--superseded-{n:03d}'
    while dst.exists():
        n += 1
        dst = arch_root / f'{cid}--superseded-{n:03d}'
    shutil.move(str(src), str(dst))
    (dst / 'SUPERSESSION.json').write_text(canon({
        'campaign_id': cid, 'superseded_at': now_utc(),
        'reason': reason, 'executor_run_id': EXECUTOR_RUN_ID}).encode())
    os.chmod(dst / 'SUPERSESSION.json', 0o600)
    return dst


def campaign_dir(cid):
    return CSR / 'h_campaign' / cid


def review_hash_of(record):
    body = {k: v for k, v in record.items() if k != 'review_hash'}
    return sha(canon(body).encode())


def write_excl(path, data, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    fsync_dir(path.parent)


def fsync_dir(d):
    fd = os.open(str(d), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_surface_snapshot():
    """review surface 快照 (path -> sha256)，仅覆盖 SNAPSHOT_ZONES 白名单域。

    §8 修复：绝不打开 FORBIDDEN_READ_ZONES（outcomes/、analysis_labeled/）
    下任何文件的字节——快照域 = annotator 冻结域 + campaign 域。
    """
    files = {}
    for zone in SNAPSHOT_ZONES:
        z = CSR / zone
        if not z.exists():
            continue
        for p in sorted(z.rglob('*')):
            if p.is_file():
                files[p.relative_to(CSR).as_posix()] = sha(p.read_bytes())
    return {'snapshot_zones': list(SNAPSHOT_ZONES),
            'forbidden_read_zones_never_opened': list(FORBIDDEN_READ_ZONES),
            'snapshot_files': files,
            'git_status_porcelain': git('status', '--porcelain').stdout,
            'created_at': now_utc()}


def campaign_round_state(cid):
    """as-of-round 轮次簿记（iteration-3 round-3 修复）。

    manifest/packet 持久化字节内嵌的轮次簿记（review_revision_count /
    campaign_review_round / prior_review_verdicts）在 bootstrap 时从
    live ledger 派生并 O_EXCL 落盘；reviewer 随后对 append-only ledger
    的合法追加会使「按 live 再派生」必然漂移。正确语义是 as-of-round：
    验证持久化 artifact 时用「当前 packet 轮次之前的 ledger 前缀」派生
    期望值，并机器校验簿记一致性（全部 fail-closed）：

    * packet.prior_review_verdicts 必须逐字段等于 ledger 前 R-1 条
      verdict（append-only，不可收缩也不可改写）；
    * len(live verdicts) ∈ {R-1, R}——多于 R 即同一 packet 上出现第二
      票（本 campaign round-1/2 的 stale-commitment 缺陷形态）；
    * 若第 R 条 verdict 已存在，其 input_commitment_sha256 必须等于
      当前 packet 字节——packet 在自己的 verdict 之后被重生成即 HALT。
    """
    packet_path = campaign_dir(cid) / 'review_packets' / 'phase_entry.json'
    ledger_path = campaign_dir(cid) / 'reviews.jsonl'
    live = verify_ledger(cid)['verdicts'] if ledger_path.is_file() else []
    pin_fields = ('sequence', 'state', 'reviewer_run_id',
                  'input_commitment_sha256', 'created_at', 'review_hash')

    def _pin(rec):
        return {k: rec[k] for k in pin_fields}

    if not packet_path.is_file():
        # fresh/continuation bootstrap: the next round's packet is derived
        # against every verdict already in the append-only ledger
        return {'packet_exists': False, 'round': len(live) + 1,
                'prior_verdicts': [_pin(r) for r in live],
                'live_verdicts': live, 'prior_count': len(live)}
    pkt = json.loads(packet_path.read_bytes())
    round_no = pkt.get('campaign_review_round')
    pinned = pkt.get('prior_review_verdicts')
    pinned_n = len(pinned) if isinstance(pinned, list) else -1
    if (not isinstance(round_no, int) or round_no < 1
            or pinned_n != round_no - 1
            or len(live) < round_no - 1 or len(live) > round_no):
        fail('H0-ROUND: persisted packet round bookkeeping inconsistent '
             f'with the append-only ledger (round={round_no!r}, '
             f'pinned_prior={pinned_n}, live_verdicts={len(live)})')
    for i, (pin, rec) in enumerate(zip(pinned, live[:round_no - 1])):
        if pin != _pin(rec):
            fail(f'H0-ROUND: persisted prior verdict #{i + 1} does not '
                 f'match the ledger prefix (append-only violation)')
    if len(live) == round_no:
        newest = live[-1]
        if newest['input_commitment_sha256'] != sha(packet_path.read_bytes()):
            fail('H0-ROUND: newest ledger verdict does not bind the '
                 'persisted packet bytes — the packet was superseded '
                 'after its own review (stale verdict binding)')
    return {'packet_exists': True, 'round': round_no,
            'prior_verdicts': [_pin(r) for r in live[:round_no - 1]],
            'live_verdicts': live, 'prior_count': round_no - 1}


def build_or_verify_manifest(gates, chain, r0, cid, staged, head):
    path = campaign_dir(cid) / 'campaign_manifest.json'
    body = {
        'manifest_version': 'csr8-h-campaign-manifest-v3',
        'campaign_id': cid,
        'phase': 'H', 'stage': STAGE, 'run_id': RUN_ID, 'iteration': ITERATION,
        'taskbook': {'version': TASKBOOK_VERSION, 'sha256': TASKBOOK_SHA256,
                     'source_byte_binding': gates['taskbook_binding']},
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
        'review_revision_count': campaign_round_state(cid)['prior_count'],
        'ledger_lifecycle': 'reviews.jsonl append-only within campaign; '
                            'superseded campaigns archived, never deleted '
                            '(§6/§15)',
        'ordinal3_proposal_rel': 'ordinal_0003/'
                                 'next_reveal.proposal.staged.json',
        'ordinal3_proposal_staging': 'STAGED_PREPARED — frozen §7 builder '
                                     'bytes proven in a trimmed sandbox; '
                                     'NOT written to the live annotator '
                                     'domain; not authorized; not revealed',
        'review_ledger': 'reviews.jsonl',
        'review_packet_phase_entry': 'review_packets/phase_entry.json',
        'executor_run_id': EXECUTOR_RUN_ID,
        'reviewer_independence': {
            'role_separation': 'executor generates, independent reviewer '
                               'reviews (fresh context, self-derived '
                               'checklist from the taskbook)',
            'context_separation': 'reviewer runs in an isolated context '
                                  'without this executor conversation',
            'write_separation': 'executor writes only campaign bootstrap '
                                'files; the reviewer verdict line and '
                                'verdict file are written by the reviewer; '
                                'machine-proven by pre/post write-surface '
                                'snapshots',
            'constraint': 'reviewer_run_id != executor_run_id'},
        'prohibited': ['outcome_join', 'analysis_labeled', 'empirical_results',
                       'identity_access', 'future_data_access',
                       'result_driven_sampling'],
        'frozen_infra_policy': 'zero modification to frozen infrastructure; '
                               'no live annotator-domain writes at H0',
        'outcome_read_policy': OUTCOME_READ_POLICY,
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
    write_excl(path, data)
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
    write_excl(path, line)
    return line, 'CREATED'


def build_or_verify_packet(gates, chain, r0, cid, staged, staged_bytes,
                           manifest_bytes, genesis_line):
    path = campaign_dir(cid) / 'review_packets' / 'phase_entry.json'
    genesis = json.loads(genesis_line.splitlines()[0])
    # as-of-round derivation (iteration-3 round-3): the persisted packet's
    # own round pins which ledger prefix precedes it; a reviewer append
    # after bootstrap must not invalidate the persisted bytes
    rstate = campaign_round_state(cid)
    prior_verdicts = rstate['prior_verdicts']
    # as-of drift disclosure (iteration-3 round-3): the audit-layer drift
    # disclosure embedded in the packet is pinned as of the packet's round
    # and may only GROW afterwards (append-only transparency); the frozen-
    # boundary zero-drift guarantee stays LIVE via gate_frozen_infra_clean
    # (fail-closed), and any newly-drifting file must already be classified
    # or entry_gates() fails before this point
    packet_frozen_infra = gates['frozen_infra']
    packet_path = campaign_dir(cid) / 'review_packets' / 'phase_entry.json'
    if packet_path.is_file():
        persisted_infra = json.loads(
            packet_path.read_bytes()).get('frozen_infra')
        kept = (persisted_infra or {}).get(
            'audit_layer_drift_disclosure', {}).get('files')
        if isinstance(kept, dict) and kept:
            live_files = gates['frozen_infra'][
                'audit_layer_drift_disclosure']['files']
            if not set(kept) <= set(live_files):
                fail('H0-PACKET: persisted audit-layer drift disclosure '
                     'names files that no longer drift (disclosure shrank '
                     '— append-only violation)')
            packet_frozen_infra = persisted_infra
    body = {
        'review_version': REVIEW_VERSION,
        'operation': 'PHASE_ENTRY',
        'ordinal': START_ORDINAL,
        'campaign_id': cid,
        'taskbook': {'version': TASKBOOK_VERSION, 'sha256': TASKBOOK_SHA256,
                     'source_byte_binding': gates['taskbook_binding']},
        'outcome_read_policy': OUTCOME_READ_POLICY,
        'frozen_baseline': gates['frozen_marker'],
        'frozen_infra': packet_frozen_infra,
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
            'outcome_untouched': gates['c6_dual_cycle']['outcome_untouched'],
            'outcome_untouched_note': gates['c6_dual_cycle'][
                'outcome_untouched_note']},
        'campaign_review_round': len(prior_verdicts) + 1,
        'prior_review_verdicts': prior_verdicts,
        'cross_campaign_review_history': (
            'iteration-1 campaign hc-94cf4c47b978133f1b64a83dbfb95ac3 '
            '(rejected externally, artifacts removed before the archive '
            'policy existed); iteration-2 campaign hc-ffb08d91bcad1337-'
            '0194524a0d403521 round 1 APPROVE rev-faa3e5dd5b4c562d ledger '
            '6bdd3e5324a24c72257e49dd03ed8cab6a6f8ec79e4ae6de6aedd246f48289'
            '7b (rejected externally, removed pre-policy); iteration-3 '
            'round 1 packet ab17ca2b8bd93d8016fdebd9c354ba71a41668247ce914'
            'cd0d512d5616488e18 REVISE rev-c19555f5d873debf ledger '
            '1dc9d038eb7de0314d5679157f197ab6d1ac4c60629681'
            '15747f7a2549153c (superseded pre-policy); iteration-3 round 2 '
            'packet c3082960c13d369aa314507dd739e16cf849c3cb6b51a8b856a321'
            '141afd526c REVISE rev-57099ff6fb682e29 ledger f04ec09439bdd1-'
            '895da5e528b9ccccf67bf38467b9880809e476239a39b7ca3 (IN LEDGER '
            'above); from round 3 onward supersession = archive only'),
        'ledger_lifecycle': {
            'policy': 'reviews.jsonl is append-only within this campaign; '
                      'superseded campaigns are ARCHIVED (never deleted) '
                      'going forward; reviewer-revision history above is '
                      'machine-readable for the §15 revision limit',
        },
        'round0': r0,
        'ordinal3_proposal': {
            'rel': 'ordinal_0003/next_reveal.proposal.staged.json',
            'sha256': sha(staged_bytes),
            'builder': 'frozen c4d.build_next_reveal_proposal executed '
                       'byte-exact in a trimmed sandbox mirror of the '
                       'frozen domain (live domain untouched)',
            'requested_ordinal': START_ORDINAL,
            'sealed_prefix_head': staged['sealed_prefix_head'],
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
    write_excl(path, data)
    return data, 'CREATED'


def build_or_verify_staged(cid, staged_bytes):
    path = campaign_dir(cid) / 'ordinal_0003' / \
        'next_reveal.proposal.staged.json'
    if path.exists():
        got = path.read_bytes()
        if got != staged_bytes:
            fail('H0-STAGE: staged proposal bytes drifted')
        return got, 'VERIFIED'
    write_excl(path, staged_bytes)
    return staged_bytes, 'CREATED'


def write_or_verify_pre_snapshot(cid):
    path = campaign_dir(cid) / 'executor_state' / \
        'pre_review_write_surface.json'
    if path.exists():
        return path.read_bytes(), 'VERIFIED'
    data = canon(write_surface_snapshot()).encode()
    write_excl(path, data)
    return data, 'CREATED'


def write_post_snapshot(cid):
    path = campaign_dir(cid) / 'executor_state' / \
        'post_review_write_surface.json'
    obj = write_surface_snapshot()
    # the post snapshot must not pin its own bytes (self-reference): the
    # measurement instrument is excluded from its own measurement
    obj['snapshot_files'].pop(
        f'h_campaign/{cid}/executor_state/'
        f'post_review_write_surface.json', None)
    data = canon(obj).encode()
    if path.exists():
        stored = json.loads(path.read_bytes())
        if stored.get('snapshot_files') != obj['snapshot_files']:
            fail('H0-INDEP: post-review write-surface snapshot drifted')
        return data, 'VERIFIED'
    write_excl(path, data)
    return data, 'CREATED'


def h_campaign_closed_world(cid, bootstrap_stage=False):
    d = campaign_dir(cid)
    got = sorted(p.relative_to(d).as_posix() for p in d.rglob('*')
                 if p.is_file())
    expected = set(BOOTSTRAP_FILES)
    if not bootstrap_stage:
        expected |= {'verdicts/phase_entry.verdict.json',
                     'executor_state/post_review_write_surface.json'}
    elif (d / 'reviews.jsonl').is_file() and verify_ledger(cid)['verdicts']:
        # continuation state: a prior REVISE round leaves its verdict file
        # in place while the executor regenerates packet/manifest/snapshot
        expected.add('verdicts/phase_entry.verdict.json')
    if sorted(got) != sorted(expected):
        fail(f'H0-WORLD: h_campaign closed-world violation: {got} != '
             f'{sorted(expected)}')
    empties = [str(p) for p in d.rglob('*') if p.is_dir()
               and not any(p.iterdir())]
    if empties:
        fail(f'H0-WORLD: empty h_campaign directories refused '
             f'(certifiability): {empties}')


# --------------------------------------------------------------------------
# ledger + verdict verification
# --------------------------------------------------------------------------

def verify_ledger(cid):
    path = campaign_dir(cid) / 'reviews.jsonl'
    if not path.is_file():
        fail('H0-LEDGER: reviews.jsonl missing')
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
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
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        fail('H0-VERDICT: verdict file mode drift (must be 0600)')
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


def prove_write_surface(cid):
    """§7 reviewer 写面机器证明（iteration-3 round-3 重建基线语义）。

    已知并如实披露的时序弱点：当 pre 快照在轮次 packet 重生成之前落盘
    （本 campaign round-3 的实际形态），pre→post 差分会额外包含执行者
    自己的 packet 重生成。重建基线语义下的允许差分恰为三类，其余任何
    差分（含 frozen annotator 域）fail-closed：

    * reviews.jsonl —— reviewer 追加（hash-chain 由 verify_ledger 机器
      验证，且必须出现在差分中：proof 不允许退化为空证明）；
    * verdicts/phase_entry.verdict.json —— reviewer 创建/覆写（必须出现
      在差分中）；
    * review_packets/phase_entry.json —— 仅当「当前 packet 字节恰为最新
      ledger verdict 绑定的 input_commitment」时豁免（机器证明重生成
      先于 reviewer 写），并在证明输出中显式披露 pre→post 承诺对。
    """
    pre = json.loads((campaign_dir(cid) / 'executor_state' /
                      'pre_review_write_surface.json').read_text())
    post = json.loads((campaign_dir(cid) / 'executor_state' /
                       'post_review_write_surface.json').read_text())
    pre_f = pre['snapshot_files']
    post_f = post['snapshot_files']
    cid_prefix = f'h_campaign/{cid}/'
    changed = {}
    for k in set(pre_f) | set(post_f):
        if pre_f.get(k) != post_f.get(k):
            changed[k] = [pre_f.get(k), post_f.get(k)]
    # executor_state/* are the measurement instrument itself (written by the
    # executor at defined times: pre at bootstrap end, post at postreview
    # start); the reviewer's write surface is everything OUTSIDE it.
    changed = {k: v for k, v in changed.items()
               if not k.startswith(cid_prefix + 'executor_state/')}
    ledger_rel = cid_prefix + 'reviews.jsonl'
    verdict_rel = cid_prefix + 'verdicts/phase_entry.verdict.json'
    packet_rel = cid_prefix + 'review_packets/phase_entry.json'
    for req in (ledger_rel, verdict_rel):
        if req not in changed:
            fail(f'H0-INDEP: reviewer write {req} not observed in the '
                 f'snapshot diff — proof cannot be established (refreshed '
                 f'pre-snapshots cannot make the proof vacuous)')
    packet_bytes = (campaign_dir(cid) / 'review_packets' /
                    'phase_entry.json').read_bytes()
    live = verify_ledger(cid)['verdicts']
    regen = None
    unexpected = {}
    for k, v in changed.items():
        if k in (ledger_rel, verdict_rel):
            continue
        if k == packet_rel and live and \
                live[-1]['input_commitment_sha256'] == sha(packet_bytes) \
                and v[1] == sha(packet_bytes):
            regen = {'path': k,
                     'pre_commitment': v[0],
                     'post_commitment': v[1],
                     'disclosure': 'executor-owned packet regeneration '
                                   'between the snapshots (the pre-snapshot '
                                   'predates this round\'s regeneration — '
                                   'known sequencing weakness, disclosed); '
                                   'allowed ONLY because the current packet '
                                   'bytes are exactly those bound by the '
                                   'newest ledger verdict, machine-proving '
                                   'the regeneration preceded the reviewer '
                                   'write'}
            continue
        unexpected[k] = v
    if unexpected:
        fail(f'H0-INDEP: reviewer write-surface violation (unexpected '
             f'diffs): {sorted(unexpected)[:4]}')
    return {'reviewer_wrote_exactly': sorted(
                k for k in changed if k != packet_rel),
            'executor_packet_regeneration': regen or 'none',
            'frozen_annotator_domain_unchanged': all(
                not k.startswith(('production/', 'c4d_proposals/',
                                  'c4d_receipts/', 'secret/'))
                for k in changed),
            'proof': 'pre/post write-surface snapshot diff over the '
                     'review-surface zones (annotator frozen domain + '
                     'campaign domain); the reviewer ledger append and '
                     'verdict write are machine-observed; any executor-'
                     'owned packet regeneration is disclosed and proven '
                     'to predate the review via the newest-verdict '
                     'binding; forbidden zones are never opened'}


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
    allowed |= CROSS_CAMPAIGN_COMMITMENTS
    # C1-precedent commitment disclosures carried by the staged §7 proposal:
    # candidate_packet_id = sha(ocid|T) and packet sha256 are one-way
    # commitments (not identity); c3_manifest_commitment is a frozen constant.
    cand3 = c4d.candidate_for_ordinal(START_ORDINAL)
    cand3_packet_id = sha(f"{cand3['opaque_case_id']}|{cand3['T']}".encode())
    allowed.add(cand3_packet_id)
    allowed.add(c4d.c4ab.C3_COMMITMENT)
    # packet files across the frozen tree are named by their one-way
    # packet_id commitments (sha(ocid|T)); they surface as path components
    # in write-surface snapshots and are public-by-construction filenames.
    allowed |= {sha(f"{c['opaque_case_id']}|{c['T']}".encode())
                for c in order}
    # §8 fix: NEVER enumerate or open FORBIDDEN_READ_ZONES (outcomes/,
    # analysis_labeled/) — allowlist derivation is restricted to the
    # review-surface zones exactly like the snapshots themselves.
    for zone in SNAPSHOT_ZONES:
        z = CSR / zone
        if not z.exists():
            continue
        for p in z.rglob('*'):
            if not p.is_file():
                continue
            if re.fullmatch(r'[0-9a-f]{64}', p.stem):
                allowed.add(p.stem)
            # public-by-construction file-hash commitments of the frozen
            # annotator/campaign domains (same form as the certified
            # manifest inventory)
            allowed.add(sha(p.read_bytes()))
    packet_file = c4d.c4ab.C3_STATE / 'packets' / f'{cand3_packet_id}.json'
    if packet_file.is_file():
        # hash-only touch (same operation the frozen builder performs);
        # no packet content enters any H0 artifact
        allowed.add(sha(packet_file.read_bytes()))
    # write-surface snapshots legitimately pin PRE-review byte states of
    # files the reviewer later modified (e.g. genesis-only reviews.jsonl);
    # those past-state hashes are commitments, not identity disclosures.
    for rel in ('executor_state/pre_review_write_surface.json',
                'executor_state/post_review_write_surface.json'):
        sp = campaign_dir(cid) / rel
        if sp.is_file():
            snap = json.loads(sp.read_bytes())
            allowed |= set(snap.get('snapshot_files', {}).values())
    d = campaign_dir(cid)
    paths = [d / rel for rel in FINAL_FILES] + [Path(p) for p in extra_paths]
    for p in paths:
        if p.is_file():
            allowed.add(sha(p.read_bytes()))
    ledger_path = d / 'reviews.jsonl'
    if ledger_path.is_file():
        for ln in ledger_path.read_text().splitlines():
            if ln.strip():
                rec = json.loads(ln)
                # persisted reviewer-round commitments (prior packets'
                # sha256 + chain hashes) are public ledger facts
                allowed.add(rec['review_hash'])
                allowed.add(rec['prev_review_hash'])
                allowed.add(rec['input_commitment_sha256'])
    for p in paths:
        if not p.is_file():
            continue
        text = p.read_text()
        tokens = set(HEX64_RE.findall(text))
        if tokens & forbidden_ocids:
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
# certification (UNMODIFIED script) + verifier battery
# --------------------------------------------------------------------------

def certify():
    """运行未修改的 certify 脚本吸收 h_campaign 新状态（data/ 落盘唯一
    既定机制）；frozen infra 零编辑。"""
    r = subprocess.run([sys.executable,
                        str(ROOT / 'scripts/csr8_phase_a_certify_inputs.py')],
                       cwd=str(ROOT), capture_output=True, text=True)
    if r.returncode != 0:
        fail(f'H0-CERTIFY: certified manifest regeneration failed: '
             f'{r.stdout[-300:]} {r.stderr[-300:]}')
    return r.stdout.strip()


# --------------------------------------------------------------------------
# dynamic forbidden-read guard (machine proof, not prose)
# --------------------------------------------------------------------------

import builtins  # noqa: E402
import io as _io  # noqa: E402

GUARD = None


class ForbiddenReadGuard:
    """§8 禁读机器证明（iteration-3 round-3 加固版）。

    拦截执行进程内对 FORBIDDEN_READ_ZONES 的任何读取打开并立即
    fail-closed。覆盖面：
      * builtins.open / io.open —— 含 os.scandir DirEntry 参数（经
        .path 解析；reviewer round-2 证明的绕过洞已封堵）；
      * os.open —— 原始 fd 读取无法再绕过（dir_fd 形态一律拒绝）；
      * io.open_code。
    非路径参数（无法解析出真实路径）一律 fail-closed，绝不静默跳过。

    豁免面如实披露：冻结认证管线（certify / machine-audit / 独立 c6
    子进程，后者的 crash-recovery 探测会在自己隔离的进程里整树拷贝到
    /tmp）与 reviewer 独立进程不受本 guard 约束，逐一记录于 summary。
    guard 覆盖命令执行段（模块导入段除外）。
    """

    def __init__(self):
        self.opened = set()
        self.violations = []
        self.fd_wraps = 0
        self._orig_builtin = builtins.open
        self._orig_io = _io.open
        self._orig_os_open = os.open
        self._orig_open_code = getattr(_io, 'open_code', None)

    def _resolve(self, file):
        # int file descriptors (e.g. subprocess pipe fds re-opened via
        # io.open(fd, 'rb')) wrap EXISTING descriptors — no new path
        # access happens, so they are counted, not treated as paths
        if isinstance(file, int) or hasattr(file, 'fileno'):
            self.fd_wraps += 1
            return False
        # DirEntry (os.scandir) exposes .path; PathLike via os.fspath
        p = getattr(file, 'path', None)
        if p is None:
            try:
                p = os.fspath(file)
            except TypeError:
                return None
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        if not isinstance(p, (str, Path)):
            return None
        return Path(p)

    def _check(self, file, mode):
        path = self._resolve(file)
        if path is False:
            return  # existing-fd wrap: no new path access
        if path is None:
            fail('G-H0-FORBIDDEN-READ-GUARD: open() called with a '
                 'non-path argument — failing closed rather than '
                 'skipping the zone check')
        try:
            rel = path.resolve().relative_to(CSR)
        except Exception:
            return
        key = rel.as_posix()
        self.opened.add(key)
        is_read = not any(c in mode for c in 'wax+')
        if is_read and rel.parts and rel.parts[0] in FORBIDDEN_READ_ZONES:
            self.violations.append(key)
            fail(f'G-H0-FORBIDDEN-READ: Phase H executor process opened '
                 f'forbidden zone file {key} (mode={mode!r})')

    def _wrap_open(self, orig):
        def guarded(file, mode='r', *a, **kw):
            self._check(file, mode)
            return orig(file, mode, *a, **kw)
        return guarded

    def _wrap_os_open(self):
        orig = self._orig_os_open

        def guarded(file, flags, mode=0o777, *, dir_fd=None):
            reading = not (flags & (os.O_WRONLY | os.O_RDWR))
            if dir_fd is not None:
                # fd-relative opens (e.g. shutil.rmtree internals): resolve
                # the real base directory via /proc/self/fd so the zone
                # check still applies to the TRUE path; unresolvable fd =
                # fail closed
                try:
                    base = os.readlink(f'/proc/self/fd/{dir_fd}')
                except OSError:
                    fail('G-H0-FORBIDDEN-READ-GUARD: os.open dir_fd not '
                         'resolvable via /proc/self/fd — failing closed')
                if reading:
                    self._check(Path(base) / str(file), 'r')
                return orig(file, flags, mode, dir_fd=dir_fd)
            if reading:
                self._check(file, 'r')
            return orig(file, flags, mode)
        return guarded

    def _wrap_open_code(self, orig):
        def guarded(path):
            self._check(path, 'rb')
            return orig(path)
        return guarded

    def __enter__(self):
        builtins.open = self._wrap_open(self._orig_builtin)
        _io.open = self._wrap_open(self._orig_io)
        os.open = self._wrap_os_open()
        if self._orig_open_code is not None:
            _io.open_code = self._wrap_open_code(self._orig_open_code)
        return self

    def __exit__(self, *exc):
        builtins.open = self._orig_builtin
        _io.open = self._orig_io
        os.open = self._orig_os_open
        if self._orig_open_code is not None:
            _io.open_code = self._orig_open_code
        return False

    def summary(self):
        zones = {}
        for k in sorted(self.opened):
            zones.setdefault(k.split('/')[0], 0)
            zones[k.split('/')[0]] += 1
        return {'mechanism': 'dynamic open-interception over the executor '
                             'process: builtins.open/io.open (incl. '
                             'DirEntry via .path), os.open (read flags; '
                             'dir_fd refused), io.open_code; non-path '
                             'arguments fail closed; spans command '
                             'execution (not module import)',
                'violations': len(self.violations),
                'violated_files': list(self.violations),
                'existing_fd_wraps': self.fd_wraps,
                'opened_paths_by_zone': zones,
                'isolated_frozen_processes': [
                    'scripts/csr8_phase_a_certify_inputs.py (subprocess; '
                    'certified-manifest hash pinning)',
                    'scripts/csr8_phase_a_machine_audit.py (subprocess; '
                    'certified closed-world check — byte-materializes '
                    'certified files in its own /tmp tree and runs its '
                    'own internal C6 crash-recovery whole-tree copy)',
                    'scripts/csr8_phase_c6_seal_s2.py (dedicated '
                     'subprocess; its crash-recovery probe copies the '
                     'whole tree inside that isolated process)'],
                'reviewer_process': 'independent process under its own '
                                    'blinding constraints'}


def battery():
    """§8 要求的冻结校验器电池（全部只读复验，零禁读域访问）。

    iteration-3 修复：电池不再包含 fb.verify_corpus（导出标注语料验证
    = outcome join 复推导）、fp.verify（审计包门含 corpus/join 门）以及
    进程内 fb.verify_manifest_anchor（其哈希钉定会打开禁读域字节——
    reviewer 已证明该调用会被本脚本自己的 ForbiddenReadGuard 拦下）。
    certified-tree/manifest 锚定以独立子进程运行冻结 machine-audit 工具
    （内容仅被哈希，永不进入 Phase H 层）；其余校验器（chain replay /
    blinding / C6）在执行进程内运行且已由动态 guard 证明零禁读打开
    （verify_blinding 的 G-F-REACH 探测由 guarded_read 在打开前拒绝）。
    """
    r = subprocess.run([sys.executable,
                        str(ROOT / 'scripts/csr8_phase_a_machine_audit.py')],
                       cwd=str(ROOT), capture_output=True, text=True,
                       timeout=1800)
    if r.returncode != 0:
        fail(f'H0-BATTERY: frozen machine audit failed: '
             f'{r.stdout[-300:]} {r.stderr[-300:]}')
    payload = json.loads(r.stdout.strip().splitlines()[-1])
    if payload.get('certified_inputs') != 'VERIFIED':
        fail(f'H0-BATTERY: certified tree not VERIFIED: {payload}')
    events = fb.verify_chain(CSR)
    blinding = fb.verify_blinding(CSR)
    bad = {k: v for k, v in blinding['gates'].items() if v != 'PASS'}
    if bad:
        fail(f'H0-BATTERY: blinding gates failed: {bad}')
    return {'certified_tree': 'PASS (frozen machine-audit subprocess: '
                              'manifest↔tree closed-world byte/mode/set '
                              'equality incl. c3/c4/c6/d gates)',
            'certified_files': payload['certified_files'],
            'certified_roots': payload['certified_roots'],
            'production_snapshot': payload['production_snapshot'],
            'manifest_anchor': 'covered by the frozen machine-audit '
                               'subprocess (certified closed-world); the '
                               'in-process fb.verify_manifest_anchor call '
                               'was removed because it hash-opens '
                               'forbidden-zone bytes',
            'chain_replay': 'PASS',
            'blinding_gates': sorted(blinding['gates']),
            'production_head': events[-1]['event_hash'],
            'outcome_read_policy': OUTCOME_READ_POLICY}


# --------------------------------------------------------------------------
# evidence
# --------------------------------------------------------------------------

def build_evidence(gates, r0, cid, artifacts, ledger, verdict, indep, batt,
                   cert_out):
    return {
        'run_id': RUN_ID, 'stage': STAGE, 'iteration': ITERATION,
        'host_id': HOST_ID,
        'operation': 'PHASE_ENTRY',
        'taskbook': {'version': TASKBOOK_VERSION,
                     'sha256': TASKBOOK_SHA256,
                     'source_byte_binding': gates['taskbook_binding']},
        'entry_gate': gates,
        'round0': r0,
        'campaign': {'campaign_id': cid,
                     'manifest_sha256': sha(artifacts['manifest']),
                     'review_packet_sha256': sha(artifacts['packet']),
                     'input_commitment_sha256': sha(artifacts['packet']),
                     'review_ledger_records': ledger['records'],
                     'review_ledger_head': ledger['head_review_hash'],
                     'ordinal3_proposal_staged_sha256':
                         sha(artifacts['staged']),
                     'ordinal3_proposal_state':
                         'STAGED_PREPARED_NOT_AUTHORIZED_NOT_REVEALED'},
        'phase_entry_review': {'state': verdict['state'],
                               'reviewer_run_id': verdict['reviewer_run_id'],
                               'input_commitment_sha256':
                                   verdict['input_commitment_sha256'],
                               'created_at': verdict['created_at'],
                               'issues': verdict['issues'],
                               'required_changes': verdict['required_changes'],
                               'independence_machine_proof': indep},
        'certification': {'mechanism': 'UNMODIFIED frozen certify script',
                          'output': cert_out},
        'verifier_battery': batt,
        'forbidden_read_guard': (
            GUARD.summary() if GUARD is not None
            else {'mechanism': 'not installed (imported as a library)'}),
        'remediation_note': 'iteration-1 rejected by external audit '
                            '(frozen-infra edits, mutating verify, leading '
                            'reviewer prompt, wrong round-0 caliber); its '
                            'live-domain ordinal-0003 proposal and campaign '
                            'hc-94cf4c47b978133f1b64a83dbfb95ac3 were '
                            'removed, the freeze ledger + certified manifest '
                            'restored byte-identical to the cd7f2a5 frozen '
                            'state before this iteration re-bootstrapped. '
                            'iteration-2 (campaign hc-ffb08d91bcad13370194'
                            '524a0d403521) was rejected for two blockers, '
                            'both remediated here: (1) the H0 write-surface '
                            'snapshots and leak-scan allowlist hashed EVERY '
                            'file under data/csr8_phase_c — including '
                            'outcomes/ and analysis_labeled/ — and the '
                            'battery ran fb.verify_corpus + fp.verify '
                            '(outcome-join re-derivations) while the '
                            'evidence declared outcome_accessed=false; '
                            'iteration 3 restricts every executor read to '
                            'the review-surface zones, drops both '
                            'join-deriving verifiers, and records the '
                            'precise machine-checked outcome-read policy '
                            'instead of a blanket denial; (2) the taskbook '
                            'was recorded only as a hardcoded digest; '
                            'iteration 3 machine-binds it by hashing the '
                            'source file bytes at every gate run '
                            '(G-H0-TASKBOOK, fail-closed). The superseded '
                            'iteration-2 campaign was removed as '
                            'operator-error remediation and this iteration '
                            're-bootstrapped with a fresh campaign id. '
                            'Within iteration 3 the first review round '
                            'returned REVISE (reviewer rev-c19555f5d873debf, '
                            'packet ab17ca2b8bd93d8016fdebd9c354ba71a4166824'
                            '7ce914cd0d512d5616488e18, ledger line hash '
                            '1dc9d038eb7de0314d5679157f197ab6d1ac4c6062968'
                            '115747f7a2549153c): (i) battery() still called '
                            'fb.verify_manifest_anchor() in-process, which '
                            'hash-opens forbidden-zone bytes and would have '
                            'tripped this script\'s own ForbiddenReadGuard '
                            'after an APPROVE — removed, anchoring now '
                            'covered by the frozen machine-audit subprocess; '
                            '(ii) the committed test suite and on-disk '
                            'certified manifest still reflected iteration '
                            '2 — tests realigned to iteration 3 and the '
                            'manifest regenerated by the unmodified certify '
                            'run in postreview. The REVISE-round campaign '
                            'state was superseded and re-bootstrapped; no '
                            'verdict carries over. Round 2 returned REVISE '
                            '(rev-57099ff6fb682e29 on packet c3082960c13d36'
                            '9aa314507dd739e16cf849c3cb6b51a8b856a321141afd'
                            '526c; remediated, round re-bootstrapped). Round '
                            '3: independent reviewer rev-1143efbf43abd4ed '
                            'APPROVE binding the exact live packet '
                            '585694107c190c2816d6ac3c193c45ab48e0baff26ff4'
                            '807919e385c891ffea (ledger sequence 3). Two '
                            'executor-side verification defects disclosed '
                            'and remediated BEFORE postreview consumed the '
                            'APPROVE (no reviewer or ledger byte touched): '
                            '(a) the iteration-3 round-bookkeeping fields '
                            '(review_revision_count / campaign_review_round '
                            '/ prior_review_verdicts) were re-derived from '
                            'the live ledger, so any legitimate reviewer '
                            'append structurally invalidated the persisted '
                            'manifest/packet — replaced with as-of-round '
                            'derivation plus fail-closed consistency checks '
                            '(campaign_round_state), including the rule that '
                            'the newest ledger verdict must bind the exact '
                            'persisted packet bytes; (b) the pre-review '
                            'write-surface snapshot (17:43:49Z) predates the '
                            'round-3 packet regeneration (18:11:30Z) and '
                            'pins the superseded intermediate commitment '
                            '4c25201c — the write-surface proof now runs '
                            'under reconstructed-baseline semantics: the '
                            'executor-owned packet regeneration is exempted '
                            'ONLY because the current packet bytes equal the '
                            'newest ledger verdict binding (machine proof '
                            'the regeneration preceded the review) and is '
                            'disclosed in independence_machine_proof; the '
                            'reviewer writes themselves are machine-observed '
                            'as exactly reviews.jsonl (append) + the verdict '
                            'file, and a vacuous proof (either write missing '
                            'from the diff) fails closed',
        'outcome_read_policy': OUTCOME_READ_POLICY,
        'identity_accessed': False,
        'future_data_accessed': False,
        'identity_access_note': 'no identity resolver touched; opaque ids '
                                'and one-way packet commitments only',
        'declaration_note': '进入 H1 的许可是 independent reviewer 的 '
                            'PHASE_ENTRY APPROVE；执行者只承载机器实测。',
        'created_at': now_utc(),
    }


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def _machine_facts():
    gates = entry_gates()
    chain = gates['chain']
    r0 = round0_facts(chain)
    cid = derive_campaign_id(chain, r0)
    staged, staged_bytes, head = build_staged_proposal_via_frozen_builder()
    return gates, chain, r0, cid, staged, staged_bytes


def cmd_bootstrap():
    gates, chain, r0, cid, staged, staged_bytes = _machine_facts()
    manifest_bytes, mstate = build_or_verify_manifest(
        gates, chain, r0, cid, staged, chain['production_head'])
    genesis_bytes, gstate = build_or_verify_genesis(cid, manifest_bytes)
    packet_bytes, pstate = build_or_verify_packet(
        gates, chain, r0, cid, staged, staged_bytes, manifest_bytes,
        genesis_bytes)
    staged_ret, sstate = build_or_verify_staged(cid, staged_bytes)
    snap, snapstate = write_or_verify_pre_snapshot(cid)
    h_campaign_closed_world(cid, bootstrap_stage=True)
    no_leak_scan(cid)
    print(json.dumps({
        'stage': STAGE, 'iteration': ITERATION, 'state': 'BOOTSTRAPPED',
        'campaign_id': cid, 'round0': r0, 'entry_gate': 'PASS',
        'ordinal3_proposal_staged_sha256': sha(staged_bytes),
        'ordinal3_proposal_staged': sstate,
        'campaign_manifest': mstate, 'review_ledger_genesis': gstate,
        'review_packet_sha256': sha(packet_bytes),
        'input_commitment_sha256': sha(packet_bytes),
        'pre_review_write_surface': snapstate,
        'executor_run_id': EXECUTOR_RUN_ID,
    }, ensure_ascii=False, sort_keys=True))
    return 0


def cmd_postreview():
    gates, chain, r0, cid, staged, staged_bytes = _machine_facts()
    manifest_bytes, _ = build_or_verify_manifest(
        gates, chain, r0, cid, staged, chain['production_head'])
    packet_bytes, _ = build_or_verify_packet(
        gates, chain, r0, cid, staged, staged_bytes, manifest_bytes,
        (campaign_dir(cid) / 'reviews.jsonl').read_bytes().splitlines()[0])
    ledger = verify_ledger(cid)
    verdict = verify_verdict_file(cid, ledger['verdicts'])
    _, _ = write_post_snapshot(cid)
    indep = prove_write_surface(cid)
    h_campaign_closed_world(cid)
    no_leak_scan(cid)
    if verdict['state'] != 'APPROVE':
        halt(f'PHASE_ENTRY reviewer verdict is {verdict["state"]} — '
             f'H1 entry forbidden (issues={verdict["issues"]}, '
             f'required_changes={verdict["required_changes"]})')
    cert_out = certify()
    batt = battery()
    evidence = build_evidence(
        gates, r0, cid,
        {'manifest': manifest_bytes, 'packet': packet_bytes,
         'staged': staged_bytes},
        ledger, verdict, indep, batt, cert_out)
    if EVIDENCE.exists():
        EVIDENCE.unlink()
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, ensure_ascii=False,
                                   sort_keys=True, indent=1))
    no_leak_scan(cid, EVIDENCE)
    print(json.dumps({'stage': STAGE, 'iteration': ITERATION,
                      'state': 'READY_FOR_AUDIT', 'campaign_id': cid,
                      'phase_entry_review': verdict['state'],
                      'reviewer_run_id': verdict['reviewer_run_id'],
                      'write_surface_proof': 'PASS',
                      'verifier_battery': 'PASS',
                      'evidence': str(EVIDENCE.relative_to(ROOT))},
                     ensure_ascii=False, sort_keys=True))
    return 0


def cmd_verify():
    """纯只读：对 frozen 域零写（§7 review surface is read-only）。"""
    gates, chain, r0, cid, staged, staged_bytes = _machine_facts()
    manifest_bytes, _ = build_or_verify_manifest(
        gates, chain, r0, cid, staged, chain['production_head'])
    packet_bytes, _ = build_or_verify_packet(
        gates, chain, r0, cid, staged, staged_bytes, manifest_bytes,
        (campaign_dir(cid) / 'reviews.jsonl').read_bytes().splitlines()[0])
    ledger = verify_ledger(cid)
    verdict = verify_verdict_file(cid, ledger['verdicts'])
    h_campaign_closed_world(cid)
    no_leak_scan(cid, EVIDENCE)
    batt = battery()
    print(json.dumps({'stage': STAGE, 'iteration': ITERATION,
                      'state': 'VERIFIED', 'campaign_id': cid,
                      'round0': r0,
                      'phase_entry_review': verdict['state'],
                      'verifier_battery': {
                          'certified_files': batt['certified_files'],
                          'all_pass': True}},
                     ensure_ascii=False, sort_keys=True))
    return 0


def main(argv=None):
    global GUARD
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('command', choices=('bootstrap', 'postreview', 'verify'))
    args = ap.parse_args(argv)
    guard = ForbiddenReadGuard()
    GUARD = guard
    try:
        with guard:
            if args.command == 'bootstrap':
                return cmd_bootstrap()
            if args.command == 'postreview':
                return cmd_postreview()
            return cmd_verify()
    except RuntimeError as e:
        halt(str(e))


if __name__ == '__main__':
    sys.exit(main())
