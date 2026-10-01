#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase G — 最终机器审计（任务书 hash 8525b7008f5f 终局 gate，run audit_20260930021152297）。

执行者只产出机器实测，不产出裁决：

* 全链 replay：冻结 SealingLog 全量重放（含 head 锚 + exact-byte 绑定）
  + C3/C4/C6/D 阶段域复核（复用 phase A machine audit 的冻结校验器）。
* 全 gate 重跑：§9.1–§9.4 全部 live gate（corpus / blinding / outcomes /
  join / manifest anchor）+ audit package 独立复验。
* 认证清单最终态：certified_live_inputs.json 全树 byte/mode/set 逐项比对。
* 生产计数：REVEAL=2 / SEAL=2（事件序列精确形态）。
* anchor 双锚 exact：封链链头哈希在全部表面（live head、corpus ledger、
  bridge evidence、audit package snapshot/public anchor）逐字相等；
  verdict 逐行哈希链头对 packaged 与 durable 两份历史分别重算并逐字相等。
* 前置 gate 裁决态：B5 / C6 / D / E / F 的 authoritative verdict 末态
  如实记录 —— 全部 APPROVE 才是 PREREQUISITES-COMPLETE，否则 PENDING。

PRODUCTION INFRA FINAL FROZEN 属于独立审计的裁决，本脚本永不宣布；
报告只携带 'RESERVED-TO-INDEPENDENT-AUDIT' 标记与机器实测事实。
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_a_machine_audit as ma          # noqa: E402 (frozen audit)
import csr8_phase_f_audit_package as fp          # noqa: E402
import csr8_phase_f_bridge as fb                 # noqa: E402
import csr8_phase_f_outcome_join as fo           # noqa: E402

ROOT = ma.ROOT
RUN_ID = 'audit_20260930021152297'
PREREQ_STAGES = ('B5', 'C6', 'D', 'E', 'F')
EVIDENCE = ROOT / 'docs/audit/evidence/g_final_machine_audit.json'


def _fail(msg):
    raise RuntimeError(msg)


def _load_module(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def b5_freeze_gate_rerun():
    """B5 Freeze Gate 机器重跑。

    在认证字节的 B5 时期视图（封链前两事件 R1/S1 + count=2 head 锚）上
    完整重放冻结的 B5 校验器：R1/S1 事件哈希、receipt 三联 exact-byte、
    canonical bytes、attempt 域权限全部原样复验。视图在临时目录构造，
    不触碰任何 live 工件；两行事件字节与 certified manifest 逐字一致。
    """
    import shutil
    import tempfile
    b5 = _load_module('scripts/csr8_phase_b5_real_seal.py', 'g_b5_audit')
    events = fb.verify_chain(fb.CSR)
    r1, s1 = events[0], events[1]
    with tempfile.TemporaryDirectory(prefix='csr8-g-b5-') as td:
        root = Path(td) / 'csr8_phase_c'
        for sub in ('production', 'c4d_receipts', 'public', 'c4_public'):
            shutil.copytree(fb.CSR / sub, root / sub)
        sdir = root / 'production' / fb.SID / 'sealing'
        lines = (sdir / 'sealing_log.jsonl').read_text().splitlines()
        (sdir / 'sealing_log.jsonl').write_text('\n'.join(lines[:2]) + '\n')
        head = json.loads((sdir / 'sealing_log.head.json').read_text())
        head['count'] = 2
        head['head_hash'] = s1['event_hash']
        (sdir / 'sealing_log.head.json').write_text(json.dumps(head))
        # B5-era anchor view: the durable c4d anchor has since been advanced by
        # C6 (final head + ordinal-0002 receipt); its B5-era content is
        # reconstructed from certified facts only (S1 event hash from the
        # immutable chain + ordinal-0001 receipt sha from the frozen attempt
        # bytes + the structural sealed_count=1 the frozen gate itself
        # demands).  Every other binding is re-proved against immutable bytes
        # by the replay.
        import csr8_phase_c_annotation_seal as c4d
        apath = root / 'c4_public' / 'c4d_seal_anchor.json'
        ap = json.loads(apath.read_text())
        ap['production_head_hash'] = s1['event_hash']
        ap['sealed_count'] = 1
        r1bytes = ((root / 'c4d_receipts' / fb.SID / 'ordinal-0001' /
                    'attempt-0001' / 'receipt.json').read_bytes())
        ap['seal_receipt_sha256'] = __import__('hashlib').sha256(r1bytes).hexdigest()
        apath.write_bytes(c4d.canon(ap).encode())
        result = b5.verify_b5(root=root)
    return {'b5_freeze': 'PASS', **{'G-B5-' + k.upper(): v
                                    for k, v in result['gates'].items()}}


def stage_e_rerun():
    """Stage E 实际重跑：完整重放冻结的 E runner 证据矩阵。

    evidence() 在独立沙盒中重建全部 crash/resume 边界（checkpoint 矩阵、
    journal 丢失后仅凭树恢复、between-boundary kill、kill race、timeout
    degradation+repair）。沙盒 seal 的 receipt id（uuid4）与事件 ts（墙钟）
    是每 run 新鲜熵 —— head hash 逐字节复现在构造上不可能；本重跑的
    判定是结构逐字相等：全部键、边界序、SEALED/idempotent 语义与已固化
    提交的 E 证据完全一致（64-hex 哈希值归一后比较）。重跑在全新解释器
    子进程中进行，避免本进程先前 B5/C4/C6/D 校验器对共享 c4d 模块状态
    的扰动影响沙盒行为；重跑后恢复已提交工件以保持工作树与认证清单一致。
    """
    import re
    import subprocess
    epath = ROOT / 'docs/audit/evidence/e_phase_runner_matrix.json'
    committed = epath.read_bytes()
    r = subprocess.run([sys.executable,
                        str(ROOT / 'scripts/csr8_phase_e_runner.py'),
                        '--evidence'], cwd=str(ROOT),
                       capture_output=True, text=True)
    if r.returncode != 0:
        epath.write_bytes(committed)
        _fail('G-CHAIN: stage E rerun subprocess failed: '
              f'{r.stderr.strip()[-400:]}')
    fresh = epath.read_bytes()

    def _norm(obj):
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                # watchdog_checks 是墙钟轮询计数（依赖机器时序），只归一为
                # 标记并在下方断言其为正整数；其余字段要求结构逐字相等。
                if k == 'watchdog_checks':
                    if not isinstance(v, int) or v <= 0:
                        _fail('G-CHAIN: stage E watchdog_checks must be a '
                              f'positive int, got {v!r}')
                    out[k] = '<watchdog_checks>'
                else:
                    out[k] = _norm(v)
            return out
        if isinstance(obj, list):
            return [_norm(v) for v in obj]
        if isinstance(obj, str):
            return re.sub(r'[0-9a-f]{64}', '<hash>', obj)
        return obj
    if _norm(json.loads(fresh)) != _norm(json.loads(committed)):
        epath.write_bytes(committed)
        _fail('G-CHAIN: stage E rerun does not structurally reproduce the '
              'committed evidence matrix')
    epath.write_bytes(committed)
    art = json.loads(committed)
    return {'e_runner': 'PASS',
            'checkpoints': len(art['checkpoints']),
            'boundary_state_recovery': len(art['boundary_state_recovery']),
            'between_boundary_kills': len(art['between_boundary_kills']),
            'kill_race': len(art['kill_race']),
            'rerun_structurally_exact': True}


def chain_replay():
    """全链 replay：SealingLog 重放 + 各冻结阶段域复核。"""
    events = fb.verify_chain(fb.CSR)
    types = [e.get('event_type') for e in events]
    if types != ['REVEAL_PACKET', 'SEAL_ANNOTATION',
                 'REVEAL_PACKET', 'SEAL_ANNOTATION']:
        _fail(f'G-CHAIN: exact persisted chain required, got {types}')
    manifest = ma.verify_certified_tree()
    b5 = b5_freeze_gate_rerun()
    if b5.get('b5_freeze') != 'PASS':
        _fail(f'G-CHAIN: B5 freeze gate failed: {b5}')
    c3 = (ma.verify_c3_append_domain() if types ==
          ['REVEAL_PACKET', 'SEAL_ANNOTATION', 'REVEAL_PACKET']
          else {'c3_append': 'SUPERSEDED-BY-C6'})
    c4 = ma.verify_c4_annotation_domain(manifest)
    c6mod = _load_module('scripts/csr8_phase_c6_seal_s2.py', 'g_c6_audit')
    c6 = c6mod.verify()
    if c6.get('c6') != 'PASS' or c6.get('production') != 'REVEAL=2 SEAL=2':
        _fail(f'G-CHAIN: C6 dual-cycle verification failed: {c6}')
    dmod = _load_module('scripts/csr8_phase_d_progressive_loop.py', 'g_d_audit')
    d = dmod.verify()
    if d.get('d') != 'PASS':
        _fail(f'G-CHAIN: stage D verification failed: {d}')
    e = stage_e_rerun()
    if e.get('e_runner') != 'PASS':
        _fail(f'G-CHAIN: stage E rerun failed: {e}')
    return {'events': types, 'b5_freeze': b5, 'c3': c3, 'c4': c4, 'c6': c6,
            'd': d, 'e': e,
            'certified_files': manifest['fileCount'],
            'certified_roots': len(manifest['roots']),
            'protected_artifacts': len(manifest.get('protectedArtifacts', [])),
            'certified_total_bytes': manifest['totalBytes']}


def gates_rerun():
    """全 gate 重跑：live §9.1–§9.4 + manifest anchor + package 复验。

    只读：join 一致性读已固化的 join_manifest 并与 labeled 行数/删失计数
    重算对账，绝不重写任何 live 工件。
    """
    corpus = fb.verify_corpus(fb.CSR)
    blinding = fb.verify_blinding(fb.CSR)
    outcomes = fo.verify_outcomes(fb.CSR)
    anchor = fb.verify_manifest_anchor()
    labeled_manifest = json.loads(
        (fo.labeled_dir(fb.CSR) / 'join_manifest.json').read_text())
    n_labeled = sum(1 for x in
                    (fo.labeled_dir(fb.CSR) / 'analysis_labeled.jsonl')
                    .read_text().splitlines() if x.strip())
    n_censored = sum(1 for x in
                     (fo.labeled_dir(fb.CSR) / 'analysis_labeled.jsonl')
                     .read_text().splitlines()
                     if json.loads(x)['censored'])
    if (labeled_manifest['n_labeled_rows'] != n_labeled
            or labeled_manifest['censored'] != n_censored):
        _fail('G-GATES: persisted join manifest does not match labeled rows')
    pkg = fp.verify(fp.PKG)
    if not pkg['all_pass']:
        _fail('G-GATES: audit package re-verification failed')
    return {'corpus': sorted(corpus), 'blinding': sorted(blinding['gates']),
            'outcomes': sorted(outcomes),
            'join_manifest_sha256': labeled_manifest['contract_sha256'],
            'join_rows_recount': n_labeled, 'join_censored_recount': n_censored,
            'manifest_anchor': anchor, 'package_gates': sorted(pkg['gates']),
            'package_gate_count': len(pkg['gates'])}


def production_counts():
    events = fb.verify_chain(fb.CSR)
    counts = {}
    for e in events:
        counts[e['event_type']] = counts.get(e['event_type'], 0) + 1
    if counts.get('REVEAL_PACKET') != 2 or counts.get('SEAL_ANNOTATION') != 2:
        _fail(f'G-COUNTS: production counts must be REVEAL=2/SEAL=2, got {counts}')
    return {'REVEAL': counts['REVEAL_PACKET'], 'SEAL': counts['SEAL_ANNOTATION'],
            'form': 'REVEAL=2 SEAL=2'}


def dual_anchor_exact():
    """双锚 exact：封链链头 + verdict 链头在全部表面逐字相等。"""
    head = json.loads((fb.CSR / 'production' / fb.SID / 'sealing' /
                       'sealing_log.head.json').read_text())
    ledger = fb.read_ledger(fb.CSR)
    ev = json.loads((ROOT / 'docs/audit/evidence/f_phase_bridge.json').read_text())
    snapshot = json.loads((fp.PKG / 'production_chain_snapshot.json').read_text())
    pub = json.loads((fp.PKG / 'public_anchor_manifest.json').read_text())
    surfaces = {
        'live_sealing_head': head['head_hash'],
        'corpus_ledger_head': ledger['chain']['head_hash'],
        'bridge_evidence_head': ev['corpus']['chain_head_hash'],
        'package_snapshot_head': snapshot['payload']['head']['head_hash'],
        'package_public_anchor_head': pub['payload']['chain_head'],
    }
    if len(set(surfaces.values())) != 1:
        _fail(f'G-ANCHOR: sealing chain head not exact across surfaces: '
              f'{surfaces}')
    chain_head = next(iter(surfaces.values()))

    pkg_lines = [x for x in (fp.PKG / 'verdicts.jsonl').read_text().splitlines()
                 if x.strip()]
    durable_lines = [x for x in fp.DURABLE_VERDICTS.read_text().splitlines()
                     if x.strip()]

    def _vchain(lines):
        prev = '0' * 64
        for ln in lines:
            prev = hashlib.sha256((prev + hashlib.sha256(
                ln.encode()).hexdigest()).encode()).hexdigest()
        return prev
    if pkg_lines != durable_lines:
        _fail('G-ANCHOR: durable verdict history is not byte-exact with the '
              'packaged snapshot (durable has grown or diverged — the final '
              'audit requires the package re-exported against the final '
              f'durable history: packaged={len(pkg_lines)} '
              f'durable={len(durable_lines)})')
    pkg_head = _vchain(pkg_lines)
    durable_full_head = _vchain(durable_lines)
    anchored = pub['payload']['verdict_chain_head']
    if pkg_head != anchored or durable_full_head != anchored:
        _fail('G-ANCHOR: verdict chain head not exact across surfaces '
              f'(packaged={pkg_head[:12]} durable-full={durable_full_head[:12]}'
              f' anchored={anchored[:12]})')
    return {'sealing_chain_head': chain_head, 'surfaces': sorted(surfaces),
            'verdict_chain_head': anchored, 'verdict_records': len(pkg_lines),
            'durable_records': len(durable_lines),
            'verdict_head_recomputed': {'packaged': pkg_head,
                                        'durable_full': durable_full_head,
                                        'anchored': anchored}}


def verdict_prerequisites():
    """前置 gate 裁决态如实记录（独立审计所有，执行者只读）。"""
    last = {}
    for ln in fp.DURABLE_VERDICTS.read_text().splitlines():
        if not ln.strip():
            continue
        r = json.loads(ln)
        last[r['stage']] = r['verdict']['state']
    detail = {s: last.get(s) for s in PREREQ_STAGES}
    complete = all(detail[s] == 'APPROVE' for s in PREREQ_STAGES)
    return {'stages': detail,
            'status': 'PREREQUISITES-COMPLETE' if complete else 'PENDING',
            'owner': 'INDEPENDENT-AUDIT'}


def final_report(out_path=EVIDENCE):
    report = {
        'run_id': RUN_ID, 'stage': 'G',
        'production_infra_final_frozen': 'RESERVED-TO-INDEPENDENT-AUDIT',
        'declared_by_executor': False,
        'declaration_note': 'PRODUCTION INFRA FINAL FROZEN 只能由独立审计宣布；'
                            '本报告仅承载机器实测事实。',
        'chain_replay': chain_replay(),
        'gates_rerun': gates_rerun(),
        'production_counts': production_counts(),
        'dual_anchor': dual_anchor_exact(),
        'verdict_prerequisites': verdict_prerequisites(),
    }
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True,
                                   indent=1))
    return report


def main():
    import argparse
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--evidence', action='store_true')
    x = a.parse_args()
    rep = final_report()
    # Library verifiers may print informational FAIL-CLOSED state lines to
    # stdout during evaluation; the machine-readable report is the evidence
    # FILE — stdout only carries a compact summary line.
    print(json.dumps({'written': str(EVIDENCE),
                      'prerequisites': rep['verdict_prerequisites']['status'],
                      'production_counts': rep['production_counts']['form'],
                      'declaration': rep['production_infra_final_frozen']},
                     sort_keys=True))


if __name__ == '__main__':
    main()
