#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase F §9.4 — one-click audit package（全量可复验）。

导出 docs/audit/evidence/f_audit_package/：
    chain/     冻结生产链 log+head+归档字节（与 live 逐字节一致）
    receipts/  c4d_receipts 全域（receipt/批准/草稿/registry/packet）
    approvals/ 授权域（first_reveal + ordinal-2 proposal/approval/permit）
    gates/     docs/audit/evidence 各阶段 gate 证据
    corpus/    §9.1 corpus 全量哈希账本
    analysis/  §9.2 盲态 analysis 清单
    outcomes/  §9.3 outcome 行 + join contract（盲键 only）
    verdicts.jsonl  审计历史（hash-chain 逐行 prev 绑定，A→F）
    MANIFEST.json   包内全量 per-file sha256 账本

verify() 只依赖包内字节独立复验：冻结 SealingLog replay、receipt/approval/
授权/corpus 绑定、verdicts hash-chain、盲态扫描 —— 一键、零 live 依赖。
"""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402
import csr8_phase_c_seal as c2              # noqa: E402
from csr8_phase_f_bridge import (CSR, SID, ROOT, canon, fail, sealed_pairs,
                                 corpus_dir, ledger_path, analysis_dir,
                                 FORBIDDEN_KEYS, _walk, _tokens, UNIVERSE,
                                 _corpus_gates, DATE_RE)
from csr8_phase_f_outcome_join import (outcomes_dir, labeled_dir,
                                       OUTCOME_KEYS, OUTCOME_FORBIDDEN_KEYS,
                                       HORIZONS)

PKG = ROOT / 'docs/audit/evidence/f_audit_package'
RUN_ID = 'audit_20260930021152297'

# 审计历史（来源：verdict_A16.md 存档 + git 各阶段收尾提交；advancement 由
# 审计桥开启下一阶段这一事实背书 —— 不虚构未经存档的 APPROVE 文本）
VERDICT_HISTORY = [
    {'stage': 'A', 'iteration': 16, 'verdict': 'APPROVE',
     'commit': '6f9c9af8c4fca7f36bd0bee0d349546f0304621f',
     'source': 'docs/audit/evidence/verdict_A16.md'},
    {'stage': 'B', 'iteration': 19, 'verdict': 'STAGE_ADVANCED',
     'commit': 'abffe1f', 'source': 'git: close B5 i19 audit blockers'},
    {'stage': 'C1', 'iteration': 1, 'verdict': 'STAGE_ADVANCED',
     'commit': 'f33a436', 'source': 'git: C1 ordinal-2 proposal'},
    {'stage': 'C2', 'iteration': 11, 'verdict': 'STAGE_ADVANCED',
     'commit': '186dec9', 'source': 'git: C2 iteration-11 re-verification'},
    {'stage': 'C3', 'iteration': 1, 'verdict': 'STAGE_ADVANCED',
     'commit': 'a68e15d', 'source': 'git: C3 audit bridge authoritative'},
    {'stage': 'C4', 'iteration': 1, 'verdict': 'STAGE_ADVANCED',
     'commit': '03d93e8', 'source': 'git: bind C4 draft to independent session'},
    {'stage': 'C5', 'iteration': 1, 'verdict': 'STAGE_ADVANCED',
     'commit': 'b4dd2bc', 'source': 'git: persist ordinal-2 unattended approval'},
    {'stage': 'C6', 'iteration': 1, 'verdict': 'STAGE_ADVANCED',
     'commit': '75e1362', 'source': 'git: close C6 dual-cycle seal verification'},
    {'stage': 'D', 'iteration': 1, 'verdict': 'STAGE_ADVANCED',
     'commit': '65e86e0', 'source': 'git: construct same-chain ordinal-N loop'},
    {'stage': 'E', 'iteration': 28, 'verdict': 'STAGE_ADVANCED',
     'commit': '4a5ce14f768e36e968830e17e2ab0fc8ec23b314',
     'source': 'git: prove boundary recovery state independent of journal'},
    {'stage': 'F', 'iteration': 1, 'verdict': 'PENDING_AUDIT',
     'commit': None,
     'source': 'this export awaits the F verdict; append on verdict receipt'},
]

GATE_FILES = (
    'b4_gate_attempts.md', 'b4_gate_reconfirmation.txt',
    'b4_human_approval_message.txt', 'b4_human_approval_provenance.json',
    'b4_preauth_v1.json', 'b4_session_record_excerpt.jsonl',
    'b4_unattended_approval.json', 'b4_unattended_gate.md',
    'c1_ordinal2_proposal_gate.md', 'c2_unattended_approval.json',
    'c2_unattended_approval_gate.md', 'c3_append_r2.json',
    'c5_unattended_approval2.json', 'e_phase_runner_matrix.json',
    'f_phase_bridge.json', 'target_tree_6f9c9af.txt', 'verdict_A16.md',
)

STAGES = ['A', 'B', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'D', 'E', 'F']
# 审计历史权威载体：docs/audit/evidence/verdicts.jsonl（durable、append-only）。
# export 只 bootstrap 一次；之后逐行 prev 链校验并原样打包 —— 重写历史 =
# 断链，export/verify 都必须失败。裁决回执到达后经 append_verdict 追加。
DURABLE_VERDICTS = ROOT / 'docs/audit/evidence/verdicts.jsonl'


def sha(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def _verdict_line(v, prev):
    return canon({**v, 'run_id': RUN_ID, 'prev_sha256': prev})


def check_authoritative_history(lines):
    """Verify the real run's complete envelope, not a synthesized stage summary."""
    stages, prev_ts = [], -1
    for ln in lines:
        r = json.loads(ln)
        if (r.get('runId') != RUN_ID or not r.get('headCommit')
                or not re.fullmatch(r'[0-9a-f]{40}', r['headCommit'])):
            fail('authoritative verdict record malformed')
        v = r.get('verdict', {})
        if (not isinstance(v, dict) or v.get('stage') != r.get('stage')
                or v.get('iteration') != r.get('iteration')
                or v.get('state') not in ('APPROVE', 'REVISE', 'NEED_USER')):
            fail('authoritative verdict envelope mismatch')
        if not isinstance(r.get('iteration'), int) or r['iteration'] < 1:
            fail('authoritative verdict iteration invalid')
        if r.get('ts', prev_ts) < prev_ts:
            fail('authoritative verdict chronology reversed')
        prev_ts = r.get('ts', prev_ts)
        stages.append(r['stage'])
    required = {'B4', 'B5', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'D', 'E', 'F'}
    if not stages or stages[-1] != 'F' or not required <= set(stages):
        fail(f'authoritative history incomplete: {sorted(set(stages))}')
    return {'records': len(lines), 'stages': sorted(set(stages)),
            'first_ts': lines and json.loads(lines[0]).get('ts'),
            'last_ts': lines and json.loads(lines[-1]).get('ts')}


def check_verdict_chain(lines, allow_stages=None):
    """逐行 prev 链 + canonical + 阶段序列校验；返回最后一条记录。"""
    prev, stages = '0' * 64, []
    for ln in lines:
        rec = json.loads(ln)
        if rec.get('commit') is not None and not re.fullmatch(r'[0-9a-f]{40}', rec['commit']):
            fail('verdict commit is not a full 40-hex git object')
        if rec['prev_sha256'] != prev:
            fail('verdicts hash chain broken (history rewrite detected)')
        if canon(rec) != ln:
            fail('verdicts line not canonical')
        prev = sha(ln.encode())
        stages.append(rec['stage'])
    want = allow_stages if allow_stages is not None else STAGES
    if stages != want:
        fail(f'verdict stage coverage {stages} != {want}')
    return json.loads(lines[-1])


def derive_verdict_history():
    """从真实 git commit 对象解析完整 stage-final 历史（不接受短 hash）。"""
    out = []
    for v in VERDICT_HISTORY:
        rec = {k: v[k] for k in ('stage', 'iteration', 'verdict', 'source')}
        short = v.get('commit')
        if short:
            q = subprocess.run(['git', '-C', str(ROOT), 'rev-parse', short],
                               capture_output=True, text=True)
            if q.returncode or not q.stdout.strip().startswith(short):
                fail(f'git history missing commit {short}')
            full = q.stdout.strip()
            s = subprocess.run(['git', '-C', str(ROOT), 'show', '-s',
                                '--format=%s', full], capture_output=True,
                               text=True, check=True).stdout.strip()
            anc = subprocess.run(['git', '-C', str(ROOT), 'merge-base',
                                  '--is-ancestor', full, 'HEAD'])
            if anc.returncode:
                fail(f'commit is not an ancestor of current audit tree: {full}')
            rec['commit'] = full
            rec['commit_subject'] = s
        else:
            rec['commit'] = None
            rec['commit_subject'] = None
        out.append(rec)
    return out


def load_or_bootstrap_verdicts():
    """Use the authoritative run verdict log verbatim; only bootstrap if absent."""
    if DURABLE_VERDICTS.is_file():
        lines = DURABLE_VERDICTS.read_text().splitlines()
        if lines:
            probe = json.loads(lines[0])
            if 'runId' in probe and isinstance(probe.get('verdict'), dict):
                check_authoritative_history(lines)
                return lines
        last = check_verdict_chain(lines)
        if last['stage'] != 'F':
            fail('durable verdicts missing the F stage entry')
        return lines
    # No synthetic stage-summary fallback is permitted when the authoritative
    # run ledger is unavailable; this is a hard audit-package blocker.
    if not (ROOT / '.dsh-audit-task.json').is_file():
        fail('authoritative audit history unavailable')
    lines, prev = [], '0' * 64
    for v in derive_verdict_history():
        ln = _verdict_line(v, prev)
        prev = sha(ln.encode())
        lines.append(ln)
    DURABLE_VERDICTS.write_text(''.join(x + '\n' for x in lines))
    return lines


def append_verdict(stage, verdict, commit, source):
    """裁决回执追加（append-only；重复阶段/断链拒绝）。"""
    lines = load_or_bootstrap_verdicts()
    last = json.loads(lines[-1])
    if stage != STAGES[STAGES.index(last['stage']) + 1 if last['stage'] in STAGES else 0]:
        fail(f'append order violated after {last["stage"]}')
    rec = {'stage': stage, 'iteration': 1, 'verdict': verdict,
           'commit': commit, 'source': source}
    ln = _verdict_line(rec, sha(lines[-1].encode()))
    with open(DURABLE_VERDICTS, 'a') as f:
        f.write(ln + '\n')
    return ln


def export(pkg=PKG, root=CSR):
    root = Path(root)
    pkg = Path(pkg)
    if pkg.exists():
        shutil.rmtree(pkg)
    (pkg / 'chain').mkdir(parents=True)
    sdir = c4d.sealing_dir(root, SID)
    shutil.copy2(sdir / 'sealing_log.jsonl', pkg / 'chain/sealing_log.jsonl')
    shutil.copy2(sdir / 'sealing_log.head.json',
                 pkg / 'chain/sealing_log.head.json')
    shutil.copytree(sdir / 'bytes', pkg / 'chain/bytes')
    shutil.copytree(root / 'c4d_receipts' / SID, pkg / 'receipts')
    (pkg / 'approvals').mkdir()
    shutil.copytree(root / 'production' / SID / 'authorization',
                    pkg / 'approvals/authorization')
    shutil.copytree(root / 'c4d_proposals' / SID, pkg / 'approvals/proposals')
    (pkg / 'gates').mkdir()
    # Closed-world gate inventory: every THIS-RUN evidence artifact is copied,
    # rather than a hand-maintained partial allowlist.  Semantically
    # contradictory copies are excluded up front and re-detected at verify:
    #  - f_phase_audit_package.json: this exporter's own gate report; any
    #    shipped copy is by construction one export stale (its fileCount/
    #    totalBytes describe the PREVIOUS package and conflict with MANIFEST);
    #  - artifacts carrying a foreign audit run id (stale cross-run
    #    provenance contradicting this package's RUN_ID).
    evidence_root = ROOT / 'docs/audit/evidence'
    for src in sorted(evidence_root.rglob('*')):
        if (src.is_file() and src.name != 'verdicts.jsonl'
                and src.name != 'f_phase_audit_package.json'
                and not src.is_relative_to(evidence_root / 'f_audit_package')):
            text = src.read_text(errors='replace') if src.stat().st_size < 2_000_000 else ''
            if any(x != RUN_ID for x in re.findall(r'audit_\d{6,}', text)):
                continue
            rel = src.relative_to(evidence_root)
            dst = pkg / 'gates' / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    # Materialize normalized corpus before copying so its ledger entries and
    # table bytes are exported atomically as one closed-world snapshot.
    # build_corpus_table writes both the parquet and its canonical jsonl twin
    # and indexes both in the corpus ledger (pyarrow-free via duckdb).
    if not (corpus_dir(root, SID) / 'phase_c_annotation_corpus.parquet').is_file():
        from csr8_phase_f_bridge import build_corpus_table
        build_corpus_table(root, SID)
    # corpus 全量字节（非仅账本）→ 包内可独立复验不可变性
    shutil.copytree(corpus_dir(root, SID), pkg / 'corpus')
    for required in ('phase_c_annotation_corpus.parquet',
                     'phase_c_annotation_corpus.jsonl'):
        if not (pkg / 'corpus' / required).is_file():
            fail(f'normalized annotation corpus artifact missing: {required}')
    # The package ledger is copied verbatim from the source corpus: both
    # normalized tables are ledger entries there, no post-hoc patching.
    shutil.copy2(corpus_dir(root, SID) / 'ledger.json', pkg / 'corpus/ledger.json')
    (pkg / 'analysis').mkdir()
    shutil.copy2(analysis_dir(root, SID) / 'analysis_manifest.json',
                 pkg / 'analysis/analysis_manifest.json')
    shutil.copy2(analysis_dir(root, SID) / 'analysis_rows.jsonl',
                 pkg / 'analysis/analysis_rows.jsonl')
    (pkg / 'analysis_labeled').mkdir()
    shutil.copy2(labeled_dir(root, SID) / 'analysis_labeled.jsonl',
                 pkg / 'analysis_labeled/analysis_labeled.jsonl')
    shutil.copy2(labeled_dir(root, SID) / 'join_manifest.json',
                 pkg / 'analysis_labeled/join_manifest.json')
    (pkg / 'outcomes').mkdir()
    shutil.copy2(outcomes_dir(root, SID) / 'outcomes.jsonl',
                 pkg / 'outcomes/outcomes.jsonl')
    shutil.copy2(outcomes_dir(root, SID) / 'outcome_join_contract.json',
                 pkg / 'outcomes/outcome_join_contract.json')
    # 审计侧 identity 扫描底册：冻结 universe 代码表（codes only）
    (pkg / 'universe').mkdir()
    uni = json.loads(Path(UNIVERSE).read_text())
    (pkg / 'universe/codes.json').write_text(json.dumps(
        {'source': 'config/universe_frozen.json',
         'source_sha256': sha_file(Path(UNIVERSE)),
         'n_codes': len(uni['codes']), 'codes': uni['codes']},
        ensure_ascii=False, sort_keys=True, indent=1))
    (pkg / 'verdicts.jsonl').write_text(
        ''.join(x + '\n' for x in load_or_bootstrap_verdicts()))
    head = json.loads((pkg / 'chain/sealing_log.head.json').read_text())
    verdict_bytes = (pkg / 'verdicts.jsonl').read_bytes()
    # §9.4: per-line hash chain over the REAL authoritative verdict history.
    # chain[i] = sha256(chain[i-1] || sha256(line_i)); every record is bound
    # to all predecessors, so any single-line rewrite breaks the chain head.
    vlines = (pkg / 'verdicts.jsonl').read_text().splitlines()
    v_line_sha = [sha(x.encode()) for x in vlines]
    v_prev = '0' * 64
    for _h in v_line_sha:
        v_prev = sha((v_prev + _h).encode())
    # §9.2: closed-world classification of every packaged copy.
    # annotator_surface = files the annotator domain produced/may see
    # (corpus, analysis, labeled join, approvals); everything else is
    # auditor-side sensitive material (universe codes, outcomes, gates
    # evidence, envelopes).  Recorded explicitly and re-verified.
    annotator_surface = sorted(
        p.relative_to(pkg).as_posix() for p in pkg.rglob('*')
        if p.is_file() and p.relative_to(pkg).as_posix().startswith(
            ('corpus/', 'analysis/', 'approvals/')))
    # §9.4 envelope metadata must be real and machine-resolvable: the exact
    # exporting commit, a real UTC timestamp, true row counts and in-package
    # source paths.  Placeholders ('pending' / 'phase-f-export') are rejected
    # by verify (G-P-ENVELOPE).
    export_commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT,
                                   capture_output=True, text=True, check=True
                                   ).stdout.strip()
    if not re.fullmatch(r'[0-9a-f]{40}', export_commit):
        fail(f'G-P-ENVELOPE: cannot resolve exporting commit: {export_commit!r}')
    from datetime import datetime, timezone
    export_ts = datetime.now(timezone.utc).isoformat(timespec='seconds')
    corpus_rows = len([x for x in (pkg / 'corpus/phase_c_annotation_corpus.jsonl')
                       .read_text().splitlines() if x.strip()])
    n_pairs = len(sealed_pairs(root, SID))
    n_gates_copied = len([p for p in (pkg / 'gates').rglob('*') if p.is_file()])
    n_approvals = len([p for p in (pkg / 'approvals').rglob('*') if p.is_file()])
    for name, payload, rows in [
        ('infra_manifest.json', {'run_id': RUN_ID, 'session_id': SID}, {'chain_events': head['count']}),
        ('production_chain_snapshot.json', {'head': head}, {'chain_events': head['count']}),
        ('sealed_pair_manifest.json', {'pairs': n_pairs}, {'sealed_pairs': n_pairs}),
        ('annotation_corpus_manifest.json', {'path': 'corpus/phase_c_annotation_corpus.parquet', 'canonical_rows': 'corpus/phase_c_annotation_corpus.jsonl'}, {'corpus_rows': corpus_rows, 'corpus_columns': 19}),
        ('authorization_manifest.json', {'path': 'approvals'}, {'authorization_files': n_approvals}),
        ('recovery_audit.json', {'source': 'gates/e_phase_runner_matrix.json'}, {'gate_files_shipped': n_gates_copied}),
        ('gate_results.json', {'source': 'gates/f_phase_bridge.json'}, {'gate_files_shipped': n_gates_copied}),
        ('public_anchor_manifest.json', {'chain_head': head['head_hash'], 'verdicts_sha256': sha(verdict_bytes), 'verdict_records': len(vlines), 'verdict_line_sha256': v_line_sha, 'verdict_chain_head': v_prev, 'boundary_policy': 'annotator_surface = corpus/ analysis/ approvals/ (blind by construction); analysis_labeled/ carries post-reveal labels and stays auditor-side with all other sensitive copies', 'boundary_annotator_surface': annotator_surface}, {'verdict_records': len(vlines), 'annotator_surface_files': len(annotator_surface)})]:
        (pkg / name).write_text(json.dumps({'schema_version':'csr8-f-envelope-v2','source_commit':export_commit,'source_hashes':{'chain_head':head['head_hash'],'verdicts':sha(verdict_bytes)},'row_counts':rows,'created_at':export_ts,'payload':payload}, sort_keys=True, indent=1))
    files = []
    for p in sorted(pkg.rglob('*')):
        if p.is_file() and p.name != 'MANIFEST.json':
            files.append({'path': p.relative_to(pkg).as_posix(),
                          'sha256': sha_file(p), 'bytes': p.stat().st_size})
    manifest = {
        'package_version': 'csr8-f-audit-package-v1', 'run_id': RUN_ID,
        'session_id': SID, 'chain_head_hash': head['head_hash'],
        'chain_event_count': head['count'],
        'files': files, 'fileCount': len(files),
        'totalBytes': sum(f['bytes'] for f in files),
        'verify': 'python3 scripts/csr8_phase_f_audit_package.py --verify '
                  '--pkg docs/audit/evidence/f_audit_package',
    }
    (pkg / 'MANIFEST.json').write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1))
    return manifest


def _chain_of(pkg):
    lg = c2.SealingLog(pkg / 'chain/sealing_log.jsonl',
                       pkg / 'chain/sealing_log.head.json', check_head=True)
    return lg.load()


def verify(pkg=PKG):
    """包内独立复验（零 live 依赖）。"""
    pkg = Path(pkg)
    gates = {}
    manifest = json.loads((pkg / 'MANIFEST.json').read_text())
    on_disk = sorted(p.relative_to(pkg).as_posix()
                     for p in pkg.rglob('*') if p.is_file())
    listed = sorted([f['path'] for f in manifest['files']] + ['MANIFEST.json'])
    if on_disk != listed:
        fail(f'G-P-MANIFEST: package closed-world violated '
             f'(extra={set(on_disk) - set(listed)} missing={set(listed) - set(on_disk)})')
    for f in manifest['files']:
        fp = pkg / f['path']
        if sha_file(fp) != f['sha256'] or fp.stat().st_size != f['bytes']:
            fail(f"G-P-MANIFEST: hash mismatch {f['path']}")
    gates['G-P-MANIFEST'] = 'PASS'

    lg = _chain_of(pkg)
    lg.verify()                       # 冻结 replay：事件哈希 + 归档 exact-byte
    evs = list(lg.events)
    head = json.loads((pkg / 'chain/sealing_log.head.json').read_text())
    if head['head_hash'] != manifest['chain_head_hash']:
        fail('G-P-CHAIN: manifest/head drift')
    gates['G-P-CHAIN'] = 'PASS'

    pairs = [(i + 1, evs[2 * i], evs[2 * i + 1]) for i in range(len(evs) // 2)]
    # receipts/ 全域 ↔ 链 SEAL 绑定；approval ↔ receipt 绑定
    receipt_shas = {s['payload']['receipt_sha256'] for _, _, s in pairs}
    seen = set()
    for p in sorted((pkg / 'receipts').rglob('receipt.json')):
        h = sha_file(p)
        if h not in receipt_shas:
            fail(f'G-P-RECEIPTS: packaged receipt not chain-bound: {p}')
        seen.add(h)
        appr = p.parent / 'seal_approval.json'
        aobj = json.loads(appr.read_bytes())
        if (not aobj.get('approved')
                or aobj.get('approved_receipt_sha256') != h):
            fail(f'G-P-RECEIPTS: approval binding broken: {appr}')
    if seen != receipt_shas:
        fail('G-P-RECEIPTS: missing packaged receipts for chain SEALs')
    gates['G-P-RECEIPTS'] = 'PASS'

    # approvals/ ↔ 链 REVEAL 授权绑定
    r1, r2 = pairs[0][1]['payload'], pairs[1][1]['payload']
    if sha_file(pkg / 'approvals/authorization/first_reveal.json') != r1['authorization_sha256']:
        fail('G-P-AUTHZ: ordinal-1 authorization binding broken')
    prop2 = pkg / 'approvals/proposals/ordinal-0002/next_reveal.proposal.json'
    if sha_file(prop2) != r2['authorization_sha256']:
        fail('G-P-AUTHZ: ordinal-2 proposal/authorization binding broken')
    a2 = json.loads((pkg / 'approvals/authorization/ordinal-0002/'
                     'next_reveal.approval.json').read_bytes())
    p2 = json.loads((pkg / 'approvals/authorization/ordinal-0002/'
                     'next_reveal.permit.json').read_bytes())
    if (a2.get('approved_authorization_sha256') != r2['authorization_sha256']
            or not a2.get('approved')
            or p2.get('candidate_packet_sha256') != r2['packet_sha256']
            or not p2.get('authorized')):
        fail('G-P-AUTHZ: ordinal-2 approval/permit binding broken')
    gates['G-P-AUTHZ'] = 'PASS'

    # corpus 全量复验：closed-world + 账本 + 链绑定 + anchors —— 全部从
    # 包内字节重推导（mode 位不跨包，故只测 4/5 类绑定；RO 属 live 域）
    ledger = json.loads((pkg / 'corpus/ledger.json').read_text())
    raw = _corpus_gates('G-P-CORPUS', pkg / 'corpus', ledger, pairs, head,
                        len(evs), SID, check_modes=False)
    if set(raw.values()) != {'PASS'}:
        fail('G-P-CORPUS: packaged corpus failed re-derivation')
    gates['G-P-CORPUS'] = 'PASS'

    # verdicts：durable 历史的逐行 hash 链 + 阶段覆盖 + F 收尾
    lines = (pkg / 'verdicts.jsonl').read_text().splitlines()
    if lines and isinstance(json.loads(lines[0]).get('verdict'), dict):
        check_authoritative_history(lines)
        last = json.loads(lines[-1])['verdict']
        last_state = last.get('state') if isinstance(last, dict) else last
        last_stage = json.loads(lines[-1])['stage']
    else:
        last = check_verdict_chain(lines)
        last_state = last['verdict']
        last_stage = last['stage']
    if last_stage != 'F':
        fail('G-P-VERDICTS: verdict history must end at stage F')
    if last_state not in ('PENDING_AUDIT', 'APPROVE', 'REVISE', 'NEED_USER', 'REJECTED', 'STAGE_ADVANCED'):
        fail(f'G-P-VERDICTS: unknown F verdict {last_state}')
    gates['G-P-VERDICTS'] = 'PASS'

    # §9.4 全量可复验：对真实 authoritative 历史执行逐行哈希链复验。
    # anchor 本身被 MANIFEST closed-world 哈希锚定，篡改任一行（即使配平
    # MANIFEST 的行哈希）都会破坏链头/逐行清单。
    anchor = json.loads((pkg / 'public_anchor_manifest.json').read_text())['payload']
    line_sha = [sha(x.encode()) for x in lines]
    prev = '0' * 64
    for _h in line_sha:
        prev = sha((prev + _h).encode())
    if (anchor.get('verdict_records') != len(lines)
            or anchor.get('verdict_line_sha256') != line_sha
            or anchor.get('verdict_chain_head') != prev
            or anchor.get('verdicts_sha256') != sha((pkg / 'verdicts.jsonl').read_bytes())):
        fail('G-P-VERDICTS-CHAIN: per-line hash-chain re-verification of the '
             'authoritative verdict history failed')
    gates['G-P-VERDICTS-CHAIN'] = 'PASS'

    # §9.2 可达性边界覆盖包内全部副本：闭域分类 + annotator 可达面全量
    # 盲态扫描（禁键 + identity token），敏感副本全部哈希锚定于 MANIFEST。
    uni = json.loads((pkg / 'universe/codes.json').read_text())
    p_codes = set(uni['codes'])
    actual = set(on_disk)
    recorded_annot = anchor.get('boundary_annotator_surface')
    derived_annot = sorted(x for x in on_disk
                           if x.startswith(('corpus/', 'analysis/',
                                            'approvals/')))
    if recorded_annot != derived_annot:
        fail('G-P-BOUNDARY: recorded annotator-surface classification drift')
    if set(recorded_annot or []) & (actual - set(recorded_annot or [])):
        fail('G-P-BOUNDARY: classification is not a partition')
    sensitive_missing = sorted(
        x for x in actual - set(recorded_annot or [])
        if x not in {f['path'] for f in manifest['files']}
        and x != 'MANIFEST.json')
    if sensitive_missing:
        fail(f'G-P-BOUNDARY: sensitive copies not hash-anchored: {sensitive_missing[:3]}')
    # §9.2 全可达面扫描——无任何后缀跳过：annotator 可达面内每一个文件
    # （含 .bin/.parquet/.txt/.md 等任意二进制/文本形态）的原始字节都要
    # 过带前缀证券代码正则；可解析的 .json/.jsonl 另加结构化键/值走查。
    n_scanned = 0
    for rel in derived_annot:
        ap = pkg / rel
        raw_text = ap.read_bytes().decode('utf-8', errors='replace')
        n_scanned += 1
        prefixed = sorted({t for t in re.findall(
            r'(?:sz|sh|bj)\.\d{6}', raw_text)} & set(p_codes))
        if prefixed:
            fail(f'G-P-BOUNDARY: identity codes in annotator-surface {rel} '
                 f'(raw byte scan): {prefixed}')
        if ap.suffix not in ('.json', '.jsonl'):
            continue
        text_keys, text_strings = set(), []
        for ln in (ap.read_text().splitlines() if ap.suffix == '.jsonl'
                   else [ap.read_text()]):
            try:
                _walk(json.loads(ln), text_keys, text_strings)
            except (json.JSONDecodeError, ValueError):
                fail(f'G-P-BOUNDARY: annotator-surface file not parseable {rel}')
        hitk = sorted(text_keys & FORBIDDEN_KEYS)
        if hitk:
            fail(f'G-P-BOUNDARY: forbidden keys in annotator-surface {rel}: {hitk}')
        hitc = sorted(t for t in _tokens(text_strings)
                      if t in p_codes or f'sz.{t}' in p_codes or f'sh.{t}' in p_codes)
        if hitc:
            fail(f'G-P-BOUNDARY: identity tokens in annotator-surface {rel}: {hitc}')
    if n_scanned != len(derived_annot):
        fail('G-P-BOUNDARY: full-surface scan did not cover every annotator file')
    gates['G-P-BOUNDARY'] = 'PASS'

    # gates evidence is a closed-world inventory, not a partial allowlist —
    # and every shipped copy must be semantically consistent with THIS
    # package: no self-referential (inherently stale) exporter reports, no
    # foreign-run provenance, no package-summary numbers that contradict the
    # current MANIFEST.
    gate_files = sorted(p.relative_to(pkg / 'gates').as_posix()
                        for p in (pkg / 'gates').rglob('*') if p.is_file())
    if not gate_files or 'f_phase_bridge.json' not in gate_files:
        fail('G-P-GATES: complete evidence inventory missing bridge evidence')
    if 'f_phase_audit_package.json' in gate_files:
        fail('G-P-GATES: self-referential exporter report shipped inside '
             'gates/ (provably stale against current MANIFEST)')
    for rel in gate_files:
        gp = pkg / 'gates' / rel
        text = gp.read_text(errors='replace') if gp.stat().st_size < 2_000_000 else ''
        foreign = sorted({x for x in re.findall(r'audit_\d{6,}', text)
                          if x != RUN_ID})
        if foreign:
            fail(f'G-P-GATES: foreign audit run id in gates/{rel}: {foreign}')
        if gp.suffix == '.json':
            try:
                gd = json.loads(text)
            except json.JSONDecodeError:
                fail(f'G-P-GATES: gates/{rel} is not parseable JSON')
            gkeys, gvals = [], []
            def _pairs(o):
                if isinstance(o, dict):
                    for k, v in o.items():
                        if isinstance(v, (str, int, float)) and not isinstance(v, bool):
                            gvals.append((k, v))
                        _pairs(v)
                elif isinstance(o, list):
                    for v in o:
                        _pairs(v)
            _pairs(gd)
            for k, v in gvals:
                if k in ('fileCount', 'totalBytes') and v not in (
                        manifest['fileCount'], manifest['totalBytes']):
                    fail(f'G-P-GATES: gates/{rel} carries package summary '
                         f'{k}={v} conflicting with current MANIFEST '
                         f'({manifest[k]})')
    gates['G-P-GATES'] = 'PASS'

    # §9.4 envelope 元数据必须真实且可解析：导出 commit、真实时间戳、真实
    # 行数、包内可解析的 source/path —— 占位符与互相矛盾的元数据一律拒绝。
    from datetime import datetime
    mandated = ['infra_manifest.json', 'production_chain_snapshot.json',
                'sealed_pair_manifest.json', 'annotation_corpus_manifest.json',
                'authorization_manifest.json', 'recovery_audit.json',
                'gate_results.json', 'public_anchor_manifest.json']
    envs, commits, stamps = {}, set(), set()
    for name in mandated:
        if not (pkg / name).is_file():
            fail(f'G-P-ENVELOPE: mandated artifact missing {name}')
        env = json.loads((pkg / name).read_text())
        if env.get('schema_version') != 'csr8-f-envelope-v2':
            fail(f'G-P-ENVELOPE: {name} schema_version drift')
        sc, ca = env.get('source_commit'), env.get('created_at')
        if not sc or not re.fullmatch(r'[0-9a-f]{40}', sc):
            fail(f'G-P-ENVELOPE: {name} source_commit unresolved: {sc!r}')
        if not ca or ca in ('phase-f-export',) or not str(ca).endswith('+00:00'):
            fail(f'G-P-ENVELOPE: {name} created_at not a real UTC stamp: {ca!r}')
        try:
            datetime.fromisoformat(str(ca))
        except ValueError:
            fail(f'G-P-ENVELOPE: {name} created_at unparseable: {ca!r}')
        for ref in (env.get('payload', {}).get('path'),
                    env.get('payload', {}).get('source'),
                    env.get('payload', {}).get('canonical_rows')):
            if ref and not (pkg / ref).exists():
                fail(f'G-P-ENVELOPE: {name} payload reference not in package: {ref}')
        envs[name] = env
        commits.add(sc); stamps.add(ca)
    if len(commits) != 1 or len(stamps) != 1:
        fail('G-P-ENVELOPE: envelope metadata disagrees across artifacts')
    n_pairs_pkg = len(pairs)
    corpus_rows_pkg = len([x for x in
                           (pkg / 'corpus/phase_c_annotation_corpus.jsonl')
                           .read_text().splitlines() if x.strip()])
    checks = {
        'sealed_pair_manifest.json': ('sealed_pairs', n_pairs_pkg),
        'annotation_corpus_manifest.json': ('corpus_rows', corpus_rows_pkg),
        'public_anchor_manifest.json': ('verdict_records', len(lines)),
    }
    for name, (key, want) in checks.items():
        got = envs[name]['row_counts'].get(key)
        if got != want:
            fail(f'G-P-ENVELOPE: {name} row_counts.{key}={got!r} '
                 f'contradicts package actuals ({want})')
    gates['G-P-ENVELOPE'] = 'PASS'

    # universe 底册：包内 identity 扫描的权威代码表
    uni = json.loads((pkg / 'universe/codes.json').read_text())
    if (uni['n_codes'] != len(uni['codes']) or uni['n_codes'] < 5000
            or uni['source'] != 'config/universe_frozen.json'):
        fail('G-P-UNIVERSE: packaged universe code list drift')
    codes = set(uni['codes'])
    gates['G-P-UNIVERSE'] = 'PASS'

    def blind_scan(rows, tag, forbidden):
        keys, strings = set(), []
        for r in rows:
            _walk(r, keys, strings)
        hitk = sorted(keys & forbidden)
        if hitk:
            fail(f'G-P-BLIND: forbidden keys in {tag}: {hitk}')
        toks = _tokens(strings)
        hitc = sorted(t for t in toks
                      if t in codes or f'sz.{t}' in codes or f'sh.{t}' in codes)
        if hitc:
            fail(f'G-P-BLIND: identity tokens in {tag}: {hitc}')

    # packaged analysis 行：manifest 锚定 + 行级盲态（键/identity/未来日期）
    arows = [json.loads(x) for x in
             (pkg / 'analysis/analysis_rows.jsonl').read_text().splitlines() if x.strip()]
    aman = json.loads((pkg / 'analysis/analysis_manifest.json').read_text())
    if (aman['corpus_ledger_sha256'] != sha_file(pkg / 'corpus/ledger.json')
            or aman['source_head_hash'] != head['head_hash']
            or aman['n_rows'] != len(arows)):
        fail('G-P-ANALYSIS: packaged manifest no longer anchors packaged corpus')
    for ent, r in zip(aman['rows'], arows):
        if ent['row_sha256'] != sha(canon(r).encode()):
            fail('G-P-ANALYSIS: row/manifest binding drift')
    blind_scan(arows, 'packaged analysis rows', FORBIDDEN_KEYS)
    for r in arows:
        _, ss = set(), []
        _walk(r, set(), ss)
        for s in ss:
            for d in DATE_RE.findall(s):
                if d > r['T']:
                    fail(f'G-P-ANALYSIS: post-T date in packaged rows {d}')
    gates['G-P-ANALYSIS'] = 'PASS'

    # packaged outcomes：schema + 删失语义 + 覆盖
    orows = [json.loads(x) for x in
             (pkg / 'outcomes/outcomes.jsonl').read_text().splitlines() if x.strip()]
    for r in orows:
        if set(r) != OUTCOME_KEYS:
            fail('G-P-BLIND: outcome schema drift in package')
        if r['censored'] != (r['forward_return'] is None):
            fail('G-P-BLIND: censoring semantics violated in package')
    want = {(a['opaque_case_id'], a['packet_id'], h) for a in arows for h in HORIZONS}
    got = {(r['opaque_case_id'], r['packet_id'], r['horizon_days']) for r in orows}
    if got != want or len(orows) != len(want):
        fail('G-P-JOIN: packaged outcome/analysis coverage mismatch')
    blind_scan(orows, 'packaged outcomes', OUTCOME_FORBIDDEN_KEYS)
    gates['G-P-BLIND'] = 'PASS'

    # packaged labeled 域：join 唯一确定性复推导 + manifest 锚定
    lrows = [json.loads(x) for x in
             (pkg / 'analysis_labeled/analysis_labeled.jsonl').read_text().splitlines() if x.strip()]
    jman = json.loads((pkg / 'analysis_labeled/join_manifest.json').read_text())
    by_key = {}
    for o in orows:
        by_key.setdefault((o['opaque_case_id'], o['packet_id']), []).append(o)
    exp = []
    for a in arows:
        outs = sorted(by_key.get((a['opaque_case_id'], a['packet_id']), []),
                      key=lambda x: x['horizon_days'])
        if len(outs) != len(HORIZONS):
            fail('G-P-JOIN: labeled coverage incomplete at re-derivation')
        for o in outs:
            exp.append({**a, 'horizon_days': o['horizon_days'],
                        'outcome_as_of': o['outcome_as_of'],
                        'forward_return': o['forward_return'],
                        'censored': o['censored'],
                        'censor_reason': o['censor_reason']})
    if [canon(r) for r in exp] != [canon(r) for r in lrows]:
        fail('G-P-JOIN: packaged labeled rows are NOT the re-derived join')
    blind_scan(lrows, 'packaged labeled rows', OUTCOME_FORBIDDEN_KEYS)
    if (jman['contract_sha256'] != sha_file(pkg / 'outcomes/outcome_join_contract.json')
            or jman['n_labeled_rows'] != len(lrows)
            or jman['join_keys'] != ['opaque_case_id', 'packet_id']):
        fail('G-P-JOIN: join manifest drift')
    gates['G-P-JOIN'] = 'PASS'
    return {'gates': gates, 'head_hash': head['head_hash'],
            'fileCount': manifest['fileCount'],
            'totalBytes': manifest['totalBytes'],
            'all_pass': all(v == 'PASS' for v in gates.values())}


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--root', type=Path, default=CSR)
    a.add_argument('--pkg', type=Path, default=PKG)
    a.add_argument('--export', action='store_true')
    a.add_argument('--verify', action='store_true')
    a.add_argument('--evidence', action='store_true')
    x = a.parse_args()
    if x.export:
        m = export(x.pkg, x.root)
        print(json.dumps({'fileCount': m['fileCount'],
                          'totalBytes': m['totalBytes'],
                          'head_hash': m['chain_head_hash']},
                         sort_keys=True, separators=(',', ':')))
        return
    if x.verify:
        print(json.dumps(verify(x.pkg), sort_keys=True, separators=(',', ':')))
        return
    if x.evidence:
        m = export(x.pkg, x.root)
        v = verify(x.pkg)
        ev_path = ROOT / 'docs/audit/evidence/f_phase_audit_package.json'
        ev_path.write_text(json.dumps(
            {'export': {'fileCount': m['fileCount'],
                        'totalBytes': m['totalBytes'],
                        'chain_head_hash': m['chain_head_hash']},
             'verify': v}, ensure_ascii=False, sort_keys=True, indent=1))
        print(json.dumps(v, sort_keys=True, separators=(',', ':')))
        return
    print(json.dumps({'phase': 'F.4', 'commands': ['--export', '--verify', '--evidence']},
                     sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
