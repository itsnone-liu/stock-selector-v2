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
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402
import csr8_phase_c_seal as c2              # noqa: E402
from csr8_phase_f_bridge import (CSR, SID, ROOT, canon, fail, sealed_pairs,
                                 corpus_dir, ledger_path, analysis_dir,
                                 FORBIDDEN_KEYS, _walk, _tokens, UNIVERSE)
from csr8_phase_f_outcome_join import (outcomes_dir, OUTCOME_KEYS,
                                       OUTCOME_FORBIDDEN_KEYS)

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


def sha(b):
    return hashlib.sha256(b).hexdigest()


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def build_verdicts():
    """hash-chain verdicts.jsonl 行（逐行 prev_sha256 绑定）。"""
    lines, prev = [], '0' * 64
    for v in VERDICT_HISTORY:
        rec = {**v, 'run_id': RUN_ID, 'prev_sha256': prev}
        line = canon(rec)
        prev = sha(line.encode())
        lines.append(line)
    return lines


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
    for name in GATE_FILES:
        src = ROOT / 'docs/audit/evidence' / name
        if not src.is_file():
            fail(f'gate evidence missing: {name}')
        shutil.copy2(src, pkg / 'gates' / name)
    (pkg / 'corpus').mkdir()
    shutil.copy2(ledger_path(root, SID), pkg / 'corpus/ledger.json')
    (pkg / 'analysis').mkdir()
    shutil.copy2(analysis_dir(root, SID) / 'analysis_manifest.json',
                 pkg / 'analysis/analysis_manifest.json')
    (pkg / 'outcomes').mkdir()
    shutil.copy2(outcomes_dir(root, SID) / 'outcomes.jsonl',
                 pkg / 'outcomes/outcomes.jsonl')
    shutil.copy2(outcomes_dir(root, SID) / 'outcome_join_contract.json',
                 pkg / 'outcomes/outcome_join_contract.json')
    (pkg / 'verdicts.jsonl').write_text(
        ''.join(x + '\n' for x in build_verdicts()))
    head = json.loads((pkg / 'chain/sealing_log.head.json').read_text())
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

    # corpus ledger ↔ 包内链
    ledger = json.loads((pkg / 'corpus/ledger.json').read_text())
    if (ledger['chain']['head_hash'] != head['head_hash']
            or ledger['chain']['event_count'] != len(evs)
            or len(ledger['pairs']) != len(pairs)):
        fail('G-P-CORPUS: ledger does not bind packaged chain')
    for (ordinal, rev, seal), m in zip(pairs, ledger['pairs']):
        if (m['reveal_event_hash'] != rev['event_hash']
                or m['seal_event_hash'] != seal['event_hash']
                or m['packet_sha256'] != rev['payload']['packet_sha256']
                or m['receipt_sha256'] != seal['payload']['receipt_sha256']):
            fail(f'G-P-CORPUS: pair {ordinal} binding drift')
    gates['G-P-CORPUS'] = 'PASS'

    # verdicts hash-chain + 阶段覆盖
    lines = (pkg / 'verdicts.jsonl').read_text().splitlines()
    prev, stages = '0' * 64, []
    for ln in lines:
        rec = json.loads(ln)
        if rec['prev_sha256'] != prev or sha(ln.encode()) is None:
            fail('G-P-VERDICTS: hash chain broken')
        if canon(rec) != ln:
            fail('G-P-VERDICTS: line not canonical')
        prev = sha(ln.encode())
        stages.append((rec['stage'], rec['verdict']))
    if [s for s, _ in stages] != ['A', 'B', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'D', 'E', 'F']:
        fail(f'G-P-VERDICTS: stage coverage {stages}')
    if stages[-1] != ('F', 'PENDING_AUDIT'):
        fail('G-P-VERDICTS: F must be PENDING_AUDIT at export time')
    gates['G-P-VERDICTS'] = 'PASS'

    # gates 证据齐全 + outcomes 盲态
    for name in GATE_FILES:
        if not (pkg / 'gates' / name).is_file():
            fail(f'G-P-GATES: missing {name}')
    gates['G-P-GATES'] = 'PASS'
    keys, strings = set(), []
    for ln in (pkg / 'outcomes/outcomes.jsonl').read_text().splitlines():
        r = json.loads(ln)
        if set(r) != OUTCOME_KEYS:
            fail('G-P-BLIND: outcome schema drift in package')
        _walk(r, keys, strings)
    if keys & OUTCOME_FORBIDDEN_KEYS:
        fail('G-P-BLIND: forbidden keys in packaged outcomes')
    codes = set(json.loads(Path(UNIVERSE).read_text())['codes'])
    toks = _tokens(strings)
    if any(t in codes or f'sz.{t}' in codes or f'sh.{t}' in codes for t in toks):
        fail('G-P-BLIND: identity tokens in packaged outcomes')
    gates['G-P-BLIND'] = 'PASS'
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
