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
    for name in GATE_FILES:
        src = ROOT / 'docs/audit/evidence' / name
        if not src.is_file():
            fail(f'gate evidence missing: {name}')
        shutil.copy2(src, pkg / 'gates' / name)
    # corpus 全量字节（非仅账本）→ 包内可独立复验不可变性
    shutil.copytree(corpus_dir(root, SID), pkg / 'corpus')
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

    # gates 证据齐全
    for name in GATE_FILES:
        if not (pkg / 'gates' / name).is_file():
            fail(f'G-P-GATES: missing {name}')
    gates['G-P-GATES'] = 'PASS'

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
