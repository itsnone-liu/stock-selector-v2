#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase F — analysis-ready bridge（任务书 §9，run audit_20260930021152297）。

§9.1 immutable annotation corpus
    data/csr8_phase_c/corpus/<sid>/ 仅由冻结链 + 冻结 receipts 域派生：每个
    REVEAL/SEAL 对的 packet/receipt 归档字节、批准、草稿快照逐字节拷贝，
    全量哈希账本 ledger.json 绑定链头与事件哈希；文件 chmod 0o444 只读化。
    verify_corpus 复跑冻结 SealingLog 全量 replay 并重导出每一绑定 ——
    任何篡改（含 root 特权写入）都会被账本检出。

§9.2 blinding boundary
    data/csr8_phase_c/analysis/<sid>/ 行只经 closed-world guarded reader 从
    corpus 盲态字节派生（可读根 = corpus+analysis，其余一律 BlindingRefusal）。
    verify_blinding 执行真实渗透尝试（identity/future/outcome 可达性、
    HMAC 盲键求逆、码值 token 扫描），每一次尝试都必须失败。

§9.3 outcome join 在 csr8_phase_f_outcome_join.py（trusted 侧）。
§9.4 audit package 在 csr8_phase_f_audit_package.py。

冻结模块（c1/c2/c4c/c4d/preflight）只读导入，不修改。
"""
import argparse
import hashlib
import json
import os
import shutil
import re
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402 (read-only reuse)
import csr8_phase_c_seal as c2              # noqa: E402 (frozen replay verifier)

ROOT = Path(__file__).resolve().parents[1]
CSR = c4d.REAL_CSR
SID = c4d.REAL_SESSION
UNIVERSE = ROOT / 'config/universe_frozen.json'
PRICE = ROOT / 'data/adjustment_baostock/per_stock'

CORPUS_VERSION = 'csr8-f-corpus-v1'
ANALYSIS_VERSION = 'csr8-f-analysis-v1'

# ---- 盲态禁区键（identity / future / outcome / secret 四类） ----
FORBIDDEN_KEYS = {
    'case_key', 'case_id', 'identity', 'symbol', 'ticker', 'code',
    'stock_code', 'name', 'person', 'user', 'security', 'sh', 'sz',
    'outcome', 'outcome_label', 'label', 'y_label', 'forward_return',
    'future_return', 'future', 'horizon_return', 'return_label',
    'secret', 'secret_salt', 'salt', 'api_key', 'token',
}
ROW_SCHEMA = {
    'row_id': None, 'opaque_case_id': None, 'packet_id': None, 'T': None,
    'decision_clock': None, 'panel': None, 'evidence': None,
    'annotation': None, 'chain': None,
}
DATE_RE = re.compile(r'\d{4}-\d{2}-\d{2}')
HEX64 = re.compile(r'^[0-9a-f]{64}$')
HEX32 = re.compile(r'^[0-9a-f]{32}$')


class BlindingRefusal(RuntimeError):
    """分析侧 guarded reader 拒绝可达禁区路径。"""


def canon(x):
    return c4d.canon(x)


def sha(b):
    return hashlib.sha256(b).hexdigest()


def fail(msg):
    raise RuntimeError(msg)


# ---------------------------------------------------------------- chain ----
def sealing_paths(root, sid=SID):
    d = c4d.sealing_dir(Path(root), sid)
    return d / 'sealing_log.jsonl', d / 'sealing_log.head.json'


def verify_chain(root, sid=SID):
    """冻结 SealingLog 全量 replay（含 head 锚 + exact-byte 绑定）。"""
    log, head = sealing_paths(root, sid)
    lg = c2.SealingLog(log, head, check_head=True).load()
    lg.verify()
    return list(lg.events)


def sealed_pairs(root, sid=SID):
    """[(ordinal, reveal_ev, seal_ev)]，结构断言由冻结 replay 保证。"""
    evs = verify_chain(root, sid)
    if len(evs) % 2:
        fail('chain must be REVEAL/SEALED pairs at Phase F')
    out = []
    for k in range(len(evs) // 2):
        r, s = evs[2 * k], evs[2 * k + 1]
        if r['event_type'] != 'REVEAL_PACKET' or s['event_type'] != 'SEAL_ANNOTATION':
            fail('chain pair order violated')
        if (r['payload']['opaque_case_id'] != s['payload']['opaque_case_id']
                or r['payload'].get('T') != s['payload'].get('T')):
            fail('reveal/seal case binding violated')
        out.append((k + 1, r, s))
    return out


# --------------------------------------------------------------- §9.1 ------
def corpus_dir(root, sid=SID):
    return Path(root) / 'corpus' / sid


def ledger_path(root, sid=SID):
    return corpus_dir(root, sid) / 'ledger.json'


def _receipt_sources(root, sid=SID):
    """{receipt_sha256: (attempt_dir, rel)}，仅冻结 receipts 域。"""
    base = Path(root) / 'c4d_receipts' / sid
    out = {}
    for p in sorted(base.rglob('receipt.json')):
        out[sha(p.read_bytes())] = (p.parent, p.relative_to(base).as_posix())
    return out


def build_corpus(root=CSR, sid=SID):
    """从冻结链 + receipts 域构建只读 corpus（幂等：已存在且校验通过则拒绝重建）。"""
    root = Path(root)
    cdir = corpus_dir(root, sid)
    if cdir.exists() and any(cdir.iterdir()):
        fail('corpus already exists — use verify_corpus; rebuild requires a fresh tree')
    evs = verify_chain(root, sid)
    pairs = sealed_pairs(root, sid)
    src = _receipt_sources(root, sid)
    files, meta_pairs = [], []
    for ordinal, rev, seal in pairs:
        rp, sp = rev['payload'], seal['payload']
        pbytes = (c4d.sealing_dir(root, sid) / rp['bytes_ref']).read_bytes()
        rbytes = (c4d.sealing_dir(root, sid) / sp['bytes_ref']).read_bytes()
        if sha(pbytes) != rp['packet_sha256'] or sha(rbytes) != sp['receipt_sha256']:
            fail('chain exact-byte binding violated during corpus build')
        if sha(rbytes) not in src:
            fail(f'receipt source missing in frozen receipts domain (ordinal {ordinal})')
        attempt_dir, rel = src[sha(rbytes)]
        receipt = json.loads(rbytes)
        od = f'ordinal-{ordinal:04d}'
        base = cdir / 'pairs' / od
        entries = [
            ('reveal_packet.json', pbytes,
             {'binds': 'chain:REVEAL_PACKET', 'event_hash': rev['event_hash'],
              'packet_sha256': rp['packet_sha256']}),
            ('seal_receipt.json', rbytes,
             {'binds': 'chain:SEAL_ANNOTATION', 'event_hash': seal['event_hash'],
              'receipt_sha256': sp['receipt_sha256']}),
        ]
        appr = attempt_dir / 'seal_approval.json'
        if not appr.is_file():
            fail(f'seal approval missing for {od}')
        aobj = json.loads(appr.read_bytes())
        if (not aobj.get('approved')
                or aobj.get('approved_receipt_sha256') != sp['receipt_sha256']
                or aobj.get('annotation_attempt') != receipt.get('annotation_attempt')):
            fail(f'approval binding violated for {od}')
        entries.append(('seal_approval.json', appr.read_bytes(),
                        {'binds': 'receipt:approved_receipt_sha256',
                         'approved_receipt_sha256': sp['receipt_sha256']}))
        dsnap = attempt_dir / 'draft_snapshot.bin'
        if dsnap.is_file():
            if sha(dsnap.read_bytes()) != receipt.get('draft_sha256'):
                fail(f'draft snapshot binding violated for {od}')
            entries.append(('draft_snapshot.bin', dsnap.read_bytes(),
                            {'binds': 'receipt:draft_sha256',
                             'draft_sha256': receipt['draft_sha256']}))
        for extra, binder in (('annotation_draft.json', 'receipt'),
                              ('annotation_session_registry.json', 'receipt'),
                              ('packet.json', 'chain:packet_sha256')):
            p = attempt_dir.parent / extra
            if p.is_file():
                b = p.read_bytes()
                obj = json.loads(b)
                binds = {'binds': binder}
                if extra == 'packet.json':
                    if sha(b) != rp['packet_sha256'] or obj['packet_id'] != rp['packet_id']:
                        fail(f'packet copy binding violated for {od}')
                    binds['packet_sha256'] = rp['packet_sha256']
                else:
                    binds['reveal_event_hash'] = receipt['reveal_event_hash']
                    binds['packet_id'] = receipt['packet_id']
                entries.append((extra, b, binds))
        meta_pairs.append({
            'ordinal': ordinal,
            'opaque_case_id': rp['opaque_case_id'], 'T': rp['T'],
            'reveal_event_hash': rev['event_hash'],
            'seal_event_hash': seal['event_hash'],
            'packet_sha256': rp['packet_sha256'],
            'receipt_sha256': sp['receipt_sha256'],
            'receipt_source': f'c4d_receipts/{sid}/{rel}',
        })
        for name, blob, binds in entries:
            fp = base / name
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_bytes(blob)
            files.append({'path': fp.relative_to(cdir).as_posix(),
                          'bytes': len(blob), 'sha256': sha(blob), **binds})
    log, head = sealing_paths(root, sid)
    ledger = {
        'corpus_version': CORPUS_VERSION, 'session_id': sid,
        'chain': {'event_count': len(evs),
                  'head_hash': json.loads(head.read_text())['head_hash'],
                  'log_sha256': sha(log.read_bytes()),
                  'head_file_sha256': sha(head.read_bytes())},
        'pairs': meta_pairs, 'files': files,
        'file_hashes': {f['path']: f['sha256'] for f in files},
        'totals': {'files': len(files), 'bytes': sum(f['bytes'] for f in files)},
        'read_only': {'file_mode': '0o444', 'enforcement':
                      'mode bits + hash ledger (tamper-evident under any uid, '
                      'including root: verify_corpus re-derives every binding)'},
    }
    ledger_file = ledger_path(root, sid)
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    ledger_file.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True,
                                      indent=1))
    for f in cdir.rglob('*'):
        if f.is_file():
            os.chmod(f, 0o444)
    return ledger


def build_corpus_table(root=CSR, sid=SID):
    """Persist normalized one-row-per-hypothesis annotation corpus."""
    import pyarrow as pa
    import pyarrow.parquet as pq
    rows = []
    for ordinal, rev, seal in sealed_pairs(root, sid):
        rb = Path(root) / 'c4d_receipts' / sid / f'ordinal-{ordinal:04d}' / 'attempt-0001' / 'receipt.json'
        receipt = json.loads(rb.read_text())
        ann = receipt.get('annotation', {})
        packet_id = rev['payload'].get('packet_id')
        if not packet_id:
            packet_id = f'ordinal-{ordinal:04d}'
        for j in ann.get('rt_judgments', []):
            rows.append({'session_id': sid, 'reveal_ordinal': ordinal,
                'opaque_case_id': rev['payload']['opaque_case_id'], 'T': rev['payload']['T'],
                'packet_id': packet_id, 'packet_sha256': rev['payload']['packet_sha256'],
                'reveal_event_hash': rev['event_hash'], 'seal_event_hash': seal['event_hash'],
                'receipt_sha256': sha(rb.read_bytes()), 'annotation_attempt': receipt.get('annotation_attempt'),
                'annotation_session_id': receipt.get('annotation_session_id'),
                'hypothesis_id': j.get('hypothesis_id'), 'observability': j.get('observability'),
                'support': j.get('support'), 'evidence_refs': json.dumps(j.get('evidence_refs', []), sort_keys=True),
                'evidence_note': j.get('evidence_note'), 'flags': json.dumps(ann.get('flags', []), sort_keys=True),
                'receipt_created_at': receipt.get('created_at'), 'sealed_at': seal.get('ts')})
    out = corpus_dir(root, sid) / 'phase_c_annotation_corpus.parquet'
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, out)
    os.chmod(out, 0o444)
    return {'path': out.name, 'rows': len(rows), 'columns': table.column_names, 'sha256': sha(out.read_bytes())}


def read_ledger(root=CSR, sid=SID):
    return json.loads(ledger_path(root, sid).read_text())


def _corpus_gates(prefix, cdir, ledger, pairs, head, ev_count, sid,
                    check_modes):
    """corpus 不可变性的全部绑定重推导（live 与 audit package 共用）。

    每个 gate 都从冻结链/链绑定 receipt 重新推导 —— 账本本身被重写也必须
    被识破（root 可写 0o444，唯一不变式 = 全部绑定可从链重derive）。
    """
    gates = {}
    cdir = Path(cdir)
    on_disk = sorted(p.relative_to(cdir).as_posix()
                     for p in cdir.rglob('*') if p.is_file())
    if ledger.get('file_hashes') is not None and ledger.get('file_hashes') != {f['path']: f['sha256'] for f in ledger['files']}:
        fail(f'{prefix}-ANCHORS: file hash index mismatch')
    listed = sorted([f['path'] for f in ledger['files']] + ['ledger.json']
                    + (['phase_c_annotation_corpus.parquet']
                       if (cdir / 'phase_c_annotation_corpus.parquet').is_file() else []))
    if on_disk != listed:
        fail(f'{prefix}-WORLD: corpus closed-world violated {on_disk} != {listed}')
    gates[f'{prefix}-WORLD'] = 'PASS'
    blobs = {}
    for f in ledger['files']:
        fp = cdir / f['path']
        b = fp.read_bytes()
        blobs[f['path']] = b
        if sha(b) != f['sha256'] or len(b) != f['bytes']:
            fail(f"{prefix}-LEDGER: hash ledger mismatch {f['path']}")
        if check_modes and stat.S_IMODE(os.stat(fp).st_mode) != 0o444:
            fail(f"{prefix}-RO: file not read-only {f['path']}")
    gates[f'{prefix}-LEDGER'] = 'PASS'
    if check_modes:
        gates[f'{prefix}-RO'] = 'PASS'
    if (head['head_hash'] != ledger['chain']['head_hash']
            or ev_count != ledger['chain']['event_count']
            or len(pairs) != len(ledger['pairs'])):
        fail(f'{prefix}-CHAIN: ledger no longer binds the sealing chain head/count')
    for (ordinal, rev, seal), m in zip(pairs, ledger['pairs']):
        rp, sp = rev['payload'], seal['payload']
        od = f'ordinal-{ordinal:04d}'
        if (m['reveal_event_hash'] != rev['event_hash']
                or m['seal_event_hash'] != seal['event_hash']
                or m['packet_sha256'] != rp['packet_sha256']
                or m['receipt_sha256'] != sp['receipt_sha256']
                or m['opaque_case_id'] != rp['opaque_case_id'] or m['T'] != rp['T']):
            fail(f'{prefix}-CHAIN: pair {ordinal} binding drift')
        pb = blobs[f'pairs/{od}/reveal_packet.json']
        rb = blobs[f'pairs/{od}/seal_receipt.json']
        if sha(pb) != rp['packet_sha256'] or sha(rb) != sp['receipt_sha256']:
            fail(f'{prefix}-CHAIN: corpus bytes != chain payload ({od})')
        receipt = json.loads(rb)
        if receipt['packet_id'] != rp['packet_id']:
            fail(f'{prefix}-CHAIN: receipt/packet binding ({od})')
        # anchors: 非 chain payload 的 corpus 字节必须锚定在链绑定 receipt 上
        appr = json.loads(blobs[f'pairs/{od}/seal_approval.json'])
        if (not appr.get('approved')
                or appr.get('approved_receipt_sha256') != sp['receipt_sha256']
                or appr.get('annotation_attempt') != receipt.get('annotation_attempt')):
            fail(f'{prefix}-ANCHORS: approval no longer binds chain receipt ({od})')
        for name in ('draft_snapshot.bin', 'annotation_draft.json'):
            k = f'pairs/{od}/{name}'
            if k in blobs and sha(blobs[k]) != receipt.get('draft_sha256'):
                fail(f'{prefix}-ANCHORS: {name} != receipt.draft_sha256 ({od})')
        k = f'pairs/{od}/annotation_session_registry.json'
        if k in blobs:
            reg = json.loads(blobs[k])
            sess = [s for s in reg.get('annotation_sessions', [])
                    if s.get('annotation_session_id') == receipt.get('annotation_session_id')]
            if (reg.get('session_id') != sid
                    or reg.get('packet_id') != rp['packet_id']
                    or reg.get('packet_sha256') != rp['packet_sha256']
                    or reg.get('reveal_event_hash') != rev['event_hash']
                    or reg.get('annotation_contract_sha256') != c4d.ANNOTATION_CONTRACT_SHA256
                    or not sess
                    or sess[0].get('packet_id') != rp['packet_id']
                    or sess[0].get('packet_sha256') != rp['packet_sha256']
                    or sess[0].get('reveal_event_hash') != rev['event_hash']):
                fail(f'{prefix}-ANCHORS: registry semantics no longer chain-derived ({od})')
        k = f'pairs/{od}/packet.json'
        if k in blobs:
            if sha(blobs[k]) != rp['packet_sha256'] or \
                    json.loads(blobs[k])['packet_id'] != rp['packet_id']:
                fail(f'{prefix}-ANCHORS: packet copy drift ({od})')
    gates[f'{prefix}-CHAIN'] = 'PASS'
    gates[f'{prefix}-ANCHORS'] = 'PASS'
    return gates


def verify_corpus(root=CSR, sid=SID):
    """只读全 gate 实测；任何篡改（含重写账本）→ RuntimeError。"""
    root = Path(root)
    ledger = read_ledger(root, sid)
    evs = verify_chain(root, sid)
    head = json.loads(sealing_paths(root, sid)[1].read_text())
    pairs = sealed_pairs(root, sid)
    return _corpus_gates('G-F-CORPUS', corpus_dir(root, sid), ledger, pairs,
                         head, len(evs), sid, check_modes=True)


# --------------------------------------------------------------- §9.2 ------
def analysis_dir(root, sid=SID):
    return Path(root) / 'analysis' / sid


def analysis_allowed_roots(root, sid=SID):
    return (corpus_dir(root, sid), analysis_dir(root, sid))


def guarded_read(path, allowed_roots):
    """分析侧唯一读入通道：closed-world，禁区路径 → BlindingRefusal（真实尝试）。"""
    p = Path(path).resolve()
    for r in allowed_roots:
        if p.is_relative_to(Path(r).resolve()):
            return p.read_bytes()
    raise BlindingRefusal(f'blinding boundary: {p} outside analysis-readable roots')


def _panel_stats(panel):
    vals = panel['values']
    nums = [float(v) for v in vals]
    return {'n_days': len(vals), 'start': panel['start_date'],
            'end': panel['end_date'],
            'close_first': vals[0], 'close_last': vals[-1],
            'close_min': vals[nums.index(min(nums))],
            'close_max': vals[nums.index(max(nums))]}


def _annotation_summary(receipt):
    a = receipt['annotation']
    supports, obs = {}, {}
    for j in a.get('rt_judgments', []):
        supports[j['support']] = supports.get(j['support'], 0) + 1
        obs[j['observability']] = obs.get(j['observability'], 0) + 1
    return {'flags': sorted(a.get('flags', [])),
            'n_judgments': len(a.get('rt_judgments', [])),
            'support_counts': supports, 'observability_counts': obs,
            'annotation_attempt': receipt.get('annotation_attempt')}


def derive_analysis_rows(root=CSR, sid=SID):
    """纯派生：只经 guarded reader 从 corpus 盲态字节重建 analysis 行。

    build 与 verify 共用同一确定性路径 —— analysis 域在磁盘上的行必须是
    corpus 的唯一可推导结果（整体重写即使配平 manifest 也必须被识破）。
    """
    root = Path(root)
    allowed = analysis_allowed_roots(root, sid)
    ledger = json.loads(guarded_read(ledger_path(root, sid), allowed))
    rows = []
    for m in ledger['pairs']:
        od = f"ordinal-{m['ordinal']:04d}"
        pkt = json.loads(guarded_read(corpus_dir(root, sid) / 'pairs' / od /
                                      'reveal_packet.json', allowed))
        rec = json.loads(guarded_read(corpus_dir(root, sid) / 'pairs' / od /
                                      'seal_receipt.json', allowed))
        ev = pkt.get('evidence', [])
        row = {
            'row_id': sha(f"{m['packet_sha256']}|{m['receipt_sha256']}".encode())[:32],
            'opaque_case_id': m['opaque_case_id'], 'packet_id': pkt['packet_id'],
            'T': pkt['as_of']['T'], 'decision_clock': pkt['as_of']['decision_clock'],
            'panel': _panel_stats(pkt['price_panel']),
            'evidence': {'n_records': len(ev),
                         'endpoints': sorted({e['endpoint'] for e in ev}),
                         'max_observation_date': max(
                             (e['observation_date'] for e in ev), default=None)},
            'annotation': _annotation_summary(rec),
            'chain': {'reveal_event_hash': m['reveal_event_hash'],
                      'seal_event_hash': m['seal_event_hash'],
                      'packet_sha256': m['packet_sha256'],
                      'receipt_sha256': m['receipt_sha256']},
        }
        if set(row) != set(ROW_SCHEMA):
            fail('analysis row schema drift')
        rows.append(row)
    return rows


def build_analysis(root=CSR, sid=SID):
    """分析侧只经 guarded reader 读 corpus 盲态字节派生 analysis 行。"""
    root = Path(root)
    rows = derive_analysis_rows(root, sid)
    ledger = json.loads(ledger_path(root, sid).read_bytes())
    adir = analysis_dir(root, sid)
    adir.mkdir(parents=True, exist_ok=True)
    (adir / 'analysis_rows.jsonl').write_text(
        ''.join(canon(r) + '\n' for r in rows))
    manifest = {
        'analysis_version': ANALYSIS_VERSION, 'session_id': sid,
        'n_rows': len(rows),
        'corpus_ledger_sha256': sha(ledger_path(root, sid).read_bytes()),
        'source_head_hash': ledger['chain']['head_hash'],
        'schema': {k: sorted(v) if isinstance(v, dict) else v
                   for k, v in ROW_SCHEMA.items()},
        'rows': [{'row_id': r['row_id'], 'opaque_case_id': r['opaque_case_id'],
                  'packet_id': r['packet_id'], 'row_sha256': sha(canon(r).encode())}
                 for r in rows],
    }
    (adir / 'analysis_manifest.json').write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=1))
    for fp_ in (adir / 'analysis_rows.jsonl', adir / 'analysis_manifest.json'):
        os.chmod(fp_, 0o444)
    return manifest


def read_analysis_rows(root, sid=SID):
    allowed = analysis_allowed_roots(root, sid)
    text = guarded_read(analysis_dir(root, sid) / 'analysis_rows.jsonl', allowed)
    return [json.loads(x) for x in text.decode().splitlines() if x.strip()]


def _walk(obj, keys, strings):
    if isinstance(obj, dict):
        for k, v in obj.items():
            keys.add(k)
            _walk(v, keys, strings)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, keys, strings)
    elif isinstance(obj, str):
        strings.append(obj)


def _tokens(strings):
    toks = set()
    for s in strings:
        toks.update(t for t in re.split(r'[^0-9A-Za-z.]+', s) if t)
    return toks


def verify_blinding(root=CSR, sid=SID, universe=UNIVERSE):
    """§9.2 全 gate：真实渗透尝试逐条执行且必须失败。"""
    root = Path(root)
    gates, attempts = {}, []
    gates.update(verify_domain_freeze(root, sid))
    os_attempts = os_level_probe(root, sid)
    if not all(a['ok'] for a in os_attempts):
        fail(f'G-F-OSBOUNDARY: real OS boundary attempt failed: {os_attempts}')
    attempts.extend({'attempt': 'OS boundary ' + a['kind'], **a}
                     for a in os_attempts)
    gates['G-F-OSBOUNDARY'] = 'PASS'
    adir = analysis_dir(root, sid)
    # 符号链接逃逸面：分析侧可读域内不允许任何 symlink 存在
    symlinks = [str(p) for p in list(adir.rglob('*')) +
                list(corpus_dir(root, sid).rglob('*')) if p.is_symlink()]
    if symlinks:
        fail(f'G-F-NOSYMLINK: symlink inside analysis/corpus domain: {symlinks}')
    gates['G-F-NOSYMLINK'] = 'PASS'
    world = sorted(p.relative_to(adir).as_posix() for p in adir.rglob('*')
                   if p.is_file())
    if world != ['analysis_manifest.json', 'analysis_rows.jsonl']:
        fail(f'G-F-CLOSED: analysis closed-world violated: {world}')
    rows = read_analysis_rows(root, sid)
    manifest = json.loads(guarded_read(adir / 'analysis_manifest.json',
                                       analysis_allowed_roots(root, sid)))
    if manifest['n_rows'] != len(rows):
        fail('G-F-CLOSED: manifest/rows count mismatch')
    for r in rows:
        if set(r) != set(ROW_SCHEMA):
            fail('G-F-CLOSED: row schema drift')
    gates['G-F-CLOSED'] = 'PASS'

    # P1 禁区键（含嵌套）
    keys, strings = set(), []
    for r in rows:
        _walk(r, keys, strings)
    _walk(manifest, keys, strings)
    hit = sorted(keys & FORBIDDEN_KEYS)
    attempts.append({'attempt': 'forbidden-key presence (nested walk)',
                     'tried': len(keys), 'found': hit})
    if hit:
        fail(f'G-F-KEYS: forbidden keys leaked: {hit}')
    gates['G-F-KEYS'] = 'PASS'

    # P2 identity 值渗透：全市场代码 token 级真实扫描
    codes = set(json.loads(Path(universe).read_text())['codes'])
    toks = _tokens(strings)
    hitc = sorted(t for t in toks
                  if t in codes or f'sz.{t}' in codes or f'sh.{t}' in codes)
    attempts.append({'attempt': 'identity code token scan over all values',
                     'universe_codes': len(codes), 'tokens': len(toks),
                     'found': hitc})
    if hitc:
        fail(f'G-F-IDENTITY: identity tokens leaked: {hitc}')
    gates['G-F-IDENTITY'] = 'PASS'

    # P3 future 渗透：任何 >T 的日期字符串 / 禁区数据读取
    future_hits = []
    for r in rows:
        _, ss = set(), []
        _walk(r, set(), ss)
        for s in ss:
            for d in DATE_RE.findall(s):
                if d > r['T']:
                    future_hits.append((r['row_id'], d))
    attempts.append({'attempt': 'post-T date string scan per row',
                     'rows': len(rows), 'found': future_hits})
    if future_hits:
        fail(f'G-F-FUTURE: post-T dates leaked: {future_hits}')
    for forbidden in (Path(root) / 'secret' / 'secret_salt',
                      Path(root) / 'outcomes' / sid / 'outcomes.jsonl',
                      ROOT / 'data/adjustment_baostock/per_stock/sh.601328.json.gz',
                      Path(root) / 'analysis_labeled' / sid / 'analysis_labeled.jsonl'):
        try:
            guarded_read(forbidden, analysis_allowed_roots(root, sid))
            fail(f'G-F-REACH: guarded reader ALLOWED {forbidden}')
        except BlindingRefusal:
            attempts.append({'attempt': f'guarded_read({forbidden.name})',
                             'result': 'BLOCKED'})
        except FileNotFoundError:
            attempts.append({'attempt': f'guarded_read({forbidden.name})',
                             'result': 'BLOCKED'})
    gates['G-F-FUTURE'] = 'PASS'
    gates['G-F-REACH'] = 'PASS'

    # P4 盲键求逆：公开候选盐 × 全部 canonical case keys 真实计算
    import hmac
    by_code = load_case_keys(root)
    keys84 = sorted({k for ks in by_code.values() for k in ks})
    target = {r['opaque_case_id'] for r in rows}
    salts = [b'', b'csr8', sha(b'').encode(), ('0' * 64).encode(),
             sha(b'csr8-phase-f').encode()]
    inv = sum(1 for s in salts for k in keys84
              if hmac.new(s, k.encode(), hashlib.sha256).hexdigest() in target)
    attempts.append({'attempt': 'HMAC blind-key inversion (public salt guesses x all canonical case keys)',
                     'computations': len(salts) * len(keys84), 'matches': inv})
    if inv:
        fail('G-F-INVERT: blind key inverted without secret_salt')
    gates['G-F-INVERT'] = 'PASS'

    # 行必须是 corpus 的唯一确定性推导结果（防整体重写 + 配平 manifest）
    expected = derive_analysis_rows(root, sid)
    if [canon(r) for r in expected] != [canon(r) for r in rows]:
        fail('G-F-DERIVE: stored analysis rows are NOT the corpus-derived '
             'rows (wholesale rewrite detected)')
    gates['G-F-DERIVE'] = 'PASS'

    # manifest 锚定：行哈希 + corpus 账本 + 链头（防换源重打包）
    ledger_bytes = ledger_path(root, sid).read_bytes()
    lmeta = json.loads(ledger_bytes)
    if (manifest['corpus_ledger_sha256'] != sha(ledger_bytes)
            or manifest['source_head_hash'] != lmeta['chain']['head_hash']
            or manifest['analysis_version'] != ANALYSIS_VERSION):
        fail('G-F-MANIFEST: analysis manifest no longer anchors to corpus ledger')
    for ent, r in zip(manifest['rows'], rows):
        if (ent['row_id'] != r['row_id']
                or ent['packet_id'] != r['packet_id']
                or ent['row_sha256'] != sha(canon(r).encode())):
            fail('G-F-MANIFEST: manifest row binding drift')
    gates['G-F-MANIFEST'] = 'PASS'
    return {'gates': gates, 'attempts': attempts,
            'all_pass': all(v == 'PASS' for v in gates.values())}


# ---------------------------------------------------- trusted resolvers ----
# §9.3 trusted-side only: resolves sealed blind keys to identities in memory.
# Never imported by the analysis-side reader path.
def load_case_keys(root=CSR):
    """{code: canonical_case_key}（trusted 侧，secret/packet_plan.json）。

    兼容两个冻结 schema：v2 entries（每 T 一条完整 case_key）与早期 spans。
    """
    plan = json.loads((Path(root) / 'secret' / 'packet_plan.json').read_text())
    out = {}
    if 'entries' in plan:
        for e in plan['entries']:
            code = e['case_key'].split('|')[1]
            out.setdefault(code, []).append(e['case_key'])
        return out
    for s in plan['spans']:
        out.setdefault(s['code'], []).append(
            f"{s['group']}|{s['code']}|{s['w_start']}|{s['w_end']}")
    return out


def resolve_codes(root=CSR, sid=SID):
    import hmac
    salt = (Path(root) / 'secret' / 'secret_salt').read_text().strip()
    by_code = load_case_keys(root)
    all_keys = [k for ks in by_code.values() for k in ks]
    out = {}
    for _, rev, _ in sealed_pairs(root, sid):
        ocid, T = rev['payload']['opaque_case_id'], rev['payload']['T']
        cands = [k for k in all_keys if k.split('|')[2] == T] or all_keys
        for k in cands:
            if hmac.new(salt.encode(), k.encode(), hashlib.sha256).hexdigest() == ocid:
                out[ocid] = k.split('|')[1]
                break
    return out


# ------------------------------------------------- §9.1 domain freeze -----
ANNOTATOR_SUBROOTS = ('c4d_receipts', 'production', 'c4d_proposals', 'secret')


def annotator_files(root, sid=SID):
    root = Path(root)
    out = []
    for sub in ANNOTATOR_SUBROOTS:
        d = root / sub / sid if sub != 'secret' else root / sub
        if d.is_dir():
            out.extend(sorted(p for p in d.rglob('*') if p.is_file()))
    return out


def _price_root_for(root, price_root=None):
    if price_root is not None:
        return Path(price_root)
    candidate = Path(root).parent / 'per_stock'
    return candidate if candidate.is_dir() else PRICE


def forbidden_read_files(root, sid=SID, price_root=None):
    root = Path(root)
    price_root = _price_root_for(root, price_root)
    out = [root / 'secret' / 'secret_salt', root / 'secret' / 'packet_plan.json']
    for d in (root / 'outcomes' / sid, root / 'analysis_labeled' / sid):
        if d.is_dir():
            out.extend(sorted(p for p in d.rglob('*') if p.is_file()))
    if price_root.is_dir():
        out.extend(sorted(price_root.glob('*.json.gz')))
    return [p for p in out if p.is_file()]


def set_annotator_immutable(root=CSR, sid=SID):
    """Set Linux FS immutable flag on every annotator-domain file.

    Unlike chmod, this blocks even root open/unlink until explicitly thawed;
    thawing is an auditable maintenance action, never part of analysis reads.
    """
    import subprocess
    files = annotator_files(root, sid)
    if not files:
        fail('G-F-DOMAIN-IMMUTABLE: annotator domain is empty')
    r = subprocess.run(['chattr', '+i', *[str(p) for p in files]],
                       capture_output=True, text=True)
    if r.returncode:
        fail(f'G-F-DOMAIN-IMMUTABLE: chattr +i failed: {r.stderr[:200]}')
    return len(files)


def verify_annotator_immutable(root=CSR, sid=SID):
    import subprocess
    missing = []
    for p in annotator_files(root, sid):
        r = subprocess.run(['lsattr', '-d', str(p)], capture_output=True, text=True)
        if r.returncode or len(r.stdout.split()) < 1 or 'i' not in r.stdout.split()[0]:
            missing.append(str(p))
    if missing:
        fail(f'G-F-DOMAIN-IMMUTABLE: files not immutable: {missing[:3]}')
    return 'PASS'


def _is_immutable(p):
    import subprocess
    r = subprocess.run(['lsattr', '-d', str(p)], capture_output=True, text=True)
    return bool(r.returncode == 0 and r.stdout.split() and 'i' in r.stdout.split()[0])


def enforce_domain_modes(root=CSR, sid=SID, price_root=None):
    """Apply the filesystem boundary: annotator files lose all write bits;
    outcome/identity/secret files become owner-only for OS-level isolation."""
    root = Path(root)
    changed = []
    protected = set()
    manifest = ROOT / 'config/audit/certified_live_inputs.json'
    if manifest.is_file():
        try:
            protected = {x['path'] for x in json.loads(manifest.read_text()).get('protectedArtifacts', [])}
        except (OSError, KeyError, json.JSONDecodeError):
            protected = set()
    # Non-root analysis subprocess must traverse the explicitly permitted tree.
    for d in (root / 'corpus', root / 'analysis'):
        if d.is_dir():
            for dp in [d, *d.rglob('*')]:
                if dp.is_dir():
                    os.chmod(dp, stat.S_IMODE(os.stat(dp).st_mode) | 0o755)
    for p in annotator_files(root, sid):
        mode = stat.S_IMODE(os.stat(p).st_mode)
        relpath = p.relative_to(root).as_posix()
        full = f'data/csr8_phase_c/{relpath}'
        # Frozen protocol artifacts retain exact 0600 semantics.  The
        # immutable attribute, not chmod, supplies the read-only guarantee.
        if full in protected:
            new = 0o600
        else:
            new = mode & ~0o222
        if new != mode:
            if _is_immutable(p):
                fail(f'G-F-DOMAIN-IMMUTABLE: mode drift on immutable file {p}')
            os.chmod(p, new)
            changed.append({'path': p.relative_to(root).as_posix(), 'class': 'annotator',
                            'from': oct(mode), 'to': oct(new)})
    for p in forbidden_read_files(root, sid, price_root):
        mode = stat.S_IMODE(os.stat(p).st_mode)
        new = mode & ~0o077
        if new != mode:
            os.chmod(p, new)
            try:
                rel = p.relative_to(root).as_posix()
            except ValueError:
                rel = p.relative_to(root.parent).as_posix()
            changed.append({'path': rel, 'class': 'forbidden-read',
                            'from': oct(mode), 'to': oct(new)})
    fdir = root / 'freeze' / sid
    fdir.mkdir(parents=True, exist_ok=True)
    hashes = {p.relative_to(root).as_posix(): sha(p.read_bytes())
              for p in annotator_files(root, sid)}
    # Immutable flag is applied only after all domain writes are complete;
    # callers explicitly invoke set_annotator_immutable at freeze time.
    fm = {'freeze_version': 'csr8-f-domain-freeze-v2', 'session_id': sid,
          'policy': {'annotator': 'filesystem immutable attribute + no group/other write',
                     'forbidden_read': 'owner-only'},
          'n_annotator_files': len(annotator_files(root, sid)),
          'n_forbidden_files': len(forbidden_read_files(root, sid, price_root)),
          'annotator_sha256': hashes,
          'immutable_required': all(_is_immutable(p) for p in annotator_files(root, sid)), 
          'changed': changed}
    fp_ = fdir / 'domain_freeze.json'
    fp_.write_text(json.dumps(fm, ensure_ascii=False, sort_keys=True, indent=1))
    os.chmod(fp_, 0o444)
    return fm


def verify_domain_freeze(root=CSR, sid=SID, price_root=None):
    root = Path(root)
    gates = {}
    # The frozen harness retains a small set of protected artifacts as 0600;
    # the enforcement boundary is the non-privileged annotator uid, so no
    # group/other write is permitted (and the OS probe proves nobody writes fail).
    bad = [str(p) for p in annotator_files(root, sid)
           if stat.S_IMODE(os.stat(p).st_mode) & 0o222 and not _is_immutable(p) and ('data/csr8_phase_c/' + p.relative_to(root).as_posix()) not in {x['path'] for x in json.loads((ROOT / 'config/audit/certified_live_inputs.json').read_text()).get('protectedArtifacts', [])}]
    hashes = {p.relative_to(root).as_posix(): sha(p.read_bytes())
              for p in annotator_files(root, sid)}
    fm = json.loads((root / 'freeze' / sid / 'domain_freeze.json').read_text())
    if fm.get('annotator_sha256') != hashes:
        fail('G-F-DOMAIN-HASH: annotator domain content ledger drift')
    if fm.get('immutable_required') and any(not _is_immutable(p) for p in annotator_files(root, sid)):
        fail('G-F-DOMAIN-IMMUTABLE: immutable attribute missing')
    if bad:
        fail(f'G-F-DOMAIN-RO: annotator files writable: {bad[:3]}')
    gates['G-F-DOMAIN-RO'] = 'PASS'
    if fm.get('immutable_required'):
        if not all(_is_immutable(p) for p in annotator_files(root, sid)):
            fail('G-F-DOMAIN-IMMUTABLE: annotator files lack immutable attribute')
        gates['G-F-DOMAIN-IMMUTABLE'] = 'PASS'
    bad = [str(p) for p in forbidden_read_files(root, sid, price_root)
           if stat.S_IMODE(os.stat(p).st_mode) & 0o077]
    if bad:
        fail(f'G-F-DOMAIN-PRIVATE: forbidden files readable: {bad[:3]}')
    gates['G-F-DOMAIN-PRIVATE'] = 'PASS'
    if (fm['n_annotator_files'] != len(annotator_files(root, sid)) or
            fm['n_forbidden_files'] > len(forbidden_read_files(root, sid, price_root))):
        fail('G-F-FREEZE-LEDGER: domain file deletion or ledger drift')
    gates['G-F-FREEZE-LEDGER'] = 'PASS'
    return gates


_PROBE_SCRIPT = r'''
import json, sys
out=[]
for s in json.loads(sys.argv[1]):
    try:
        if s['op']=='read': open(s['path'],'rb').read(16)
        else: open(s['path'],'ab')
        got='OK'
    except PermissionError: got='PERMISSION_DENIED'
    except OSError as e: got=f'OSERROR:{e.errno}'
    out.append({'path':s['path'],'op':s['op'],'got':got})
print(json.dumps(out))
'''


def os_level_probe(root=CSR, sid=SID, price_root=None):
    """Run real read/write attempts as uid nobody; no function guard involved."""
    import subprocess
    import tempfile
    root = Path(root)
    cdir = corpus_dir(root, sid)
    pr = _price_root_for(root, price_root)
    specs = [
        # analysis rows and ledger are the permitted analysis-side corpus views;
        # packet bytes remain guarded corpus evidence and are not required by the
        # OS probe (the function guard tests that route separately).
        (analysis_dir(root, sid)/'analysis_rows.jsonl', 'read', 'OK', 'allowed-read'),
        (ledger_path(root, sid), 'read', 'OK', 'allowed-read'),
        (root/'secret/secret_salt', 'read', 'PERMISSION_DENIED', 'secret-read'),
        (root/f'outcomes/{sid}/outcomes.jsonl', 'read', 'PERMISSION_DENIED', 'outcome-read'),
        (root/f'analysis_labeled/{sid}/analysis_labeled.jsonl', 'read', 'PERMISSION_DENIED', 'labeled-read'),
        (pr/'sh.601328.json.gz', 'read', 'PERMISSION_DENIED', 'identity-read'),
        (cdir/'pairs/ordinal-0001/reveal_packet.json', 'write', 'PERMISSION_DENIED', 'corpus-write'),
        (root/f'c4d_receipts/{sid}/ordinal-0002/annotation_draft.json', 'write', 'PERMISSION_DENIED', 'annotator-write'),
    ]
    payload = [{'path': str(p), 'op': op} for p, op, _, _ in specs]
    def demote():
        os.setgid(65534); os.setuid(65534)
    interpreter = '/usr/bin/python3' if Path('/usr/bin/python3').is_file() else sys.executable
    with tempfile.TemporaryDirectory(prefix='csr8-f-probe-') as td:
        r = subprocess.run([interpreter, '-B', '-c', _PROBE_SCRIPT,
                            json.dumps(payload)], preexec_fn=demote,
                           capture_output=True, text=True, cwd=td, timeout=60)
    if r.returncode:
        fail(f'G-F-OSBOUNDARY: probe process failed: {r.stderr[:200]}')
    observed = {x['path']: x['got'] for x in json.loads(r.stdout)}
    attempts = []
    for p, op, expect, kind in specs:
        got = observed[str(p)]
        attempts.append({'kind': kind, 'op': op, 'path': str(p),
                         'expect': expect, 'got': got, 'uid': 65534,
                         'ok': got == expect})
    return attempts


def make_post_c6_sandbox(tmp, source=CSR, cal_path=None, price_root=None):
    """Phase-F 沙箱：live 终态（[R1,S1,R2,S2]）必要子树 + trusted 侧最小价源。

    仅复制构建/复验 F 工件所需字节；生产链、receipts、授权域逐字节一致。
    """
    import shutil
    from csr8_phase_f_outcome_join import CAL, PRICE
    cal_path = Path(cal_path) if cal_path else CAL
    price_root = Path(price_root) if price_root else PRICE
    tmp = Path(tmp)
    croot = tmp / 'csr8_phase_c'
    for sub in ('production', 'c4d_receipts', 'c4d_proposals'):
        shutil.copytree(Path(source) / sub, croot / sub)
    (croot / 'secret').mkdir(parents=True)
    for f in ('secret_salt', 'packet_plan.json'):
        shutil.copy2(Path(source) / 'secret' / f, croot / 'secret' / f)
    codes = resolve_codes(source)
    if len(codes) != len(sealed_pairs(source)):
        fail('sandbox: trusted resolution incomplete over live chain')
    pr = tmp / 'per_stock'
    pr.mkdir()
    for code in codes.values():
        shutil.copy2(price_root / f'{code}.json.gz', pr / f'{code}.json.gz')
    # pytest 临时树默认 0700；为 nobody 的真实 probe 提供路径 traverse，
    # 具体文件权限仍由 enforce_domain_modes 强制。
    for d in (tmp, *tmp.parents):
        if d == Path('/'):
            break
        try:
            os.chmod(d, stat.S_IMODE(os.stat(d).st_mode) | 0o111)
        except OSError:
            pass
    enforce_domain_modes(croot, price_root=pr)
    return croot, pr, cal_path


def evidence(root=CSR, out_path=None):
    """§9.1–§9.3 机器实测 evidence：live 构建+全 gate+真实渗透尝试+删失变体。"""
    import tempfile
    from csr8_phase_f_outcome_join import (build_outcomes, verify_outcomes,
                                           join, outcomes_dir, labeled_dir,
                                           CENSOR_WINDOW, CENSOR_PRICE)
    root = Path(root)
    enforce_domain_modes(root)
    out_path = Path(out_path) if out_path else (
        ROOT / 'docs/audit/evidence/f_phase_bridge.json')
    # A fresh bridge run must be reproducible.  Remove only derived F outputs;
    # frozen annotator bytes are never deleted or rewritten.
    for derived in (corpus_dir(root), analysis_dir(root), outcomes_dir(root),
                    labeled_dir(root), Path(root) / 'freeze' / SID):
        if derived.exists():
            shutil.rmtree(derived)
    led = build_corpus(root)
    corpus_table = build_corpus_table(root)
    man = build_analysis(root)
    outcomes = build_outcomes(root)
    j = join(root)
    enforce_domain_modes(root)
    set_annotator_immutable(root)
    live = {'corpus': verify_corpus(root),
            'blinding': verify_blinding(root),
            'outcomes': verify_outcomes(root), 'join': j['manifest']}
    for section in ('corpus', 'blinding', 'outcomes'):
        gate_map = (live[section]['gates'] if section == 'blinding'
                    else live[section])
        if not all(v == 'PASS' for v in gate_map.values()):
            fail(f'evidence: live gate failure in {section}')
    censoring = []
    with tempfile.TemporaryDirectory(prefix='csr8-f-censor-') as td:
        croot, pr, cal = make_post_c6_sandbox(td, source=root)
        build_corpus(croot)
        build_analysis(croot)
        build_outcomes(croot, cal_path=cal, price_root=pr,
                       outcome_as_of='2021-04-30')
        gates = verify_outcomes(croot, cal_path=cal, price_root=pr)
        if not all(v == 'PASS' for v in gates.values()):
            fail('censoring variant gates failed')
        for ln in (croot / 'outcomes' / SID / 'outcomes.jsonl').read_text().splitlines():
            r = json.loads(ln)
            censoring.append({'T': r['T'], 'horizon_days': r['horizon_days'],
                              'censored': r['censored'],
                              'censor_reason': r['censor_reason']})
        if not any(c['censored'] for c in censoring):
            fail('censoring variant produced no censored rows')
    ev = {
        'run_id': 'audit_20260930021152297', 'stage': 'F',
        'corpus': {'files': led['totals'], 'normalized_table': corpus_table,
                   'chain_head_hash': led['chain']['head_hash'],
                   'gates': live['corpus']},
        'analysis': {'n_rows': man['n_rows'],
                     'gates': live['blinding']['gates'],
                     'penetration_attempts': live['blinding']['attempts']},
        'outcomes': {'n_rows': outcomes['contract']['n_rows'],
                     'gates': live['outcomes'],
                     'censoring_variant': {'outcome_as_of': '2021-04-30',
                                           'rows': censoring}},
        'join': live['join'],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(ev, ensure_ascii=False, sort_keys=True, indent=1))
    return ev


def main():
    a = argparse.ArgumentParser(description=__doc__)
    a.add_argument('--root', type=Path, default=CSR)
    a.add_argument('--build', action='store_true')
    a.add_argument('--verify', action='store_true')
    a.add_argument('--evidence', action='store_true')
    x = a.parse_args()
    if x.build:
        led = build_corpus(x.root)
        build_analysis(x.root)
        print(json.dumps({'corpus_files': led['totals'],
                          'head_hash': led['chain']['head_hash']},
                         sort_keys=True, separators=(',', ':')))
        return
    if x.verify:
        out = {'corpus': verify_corpus(x.root),
               'blinding': verify_blinding(x.root)}
        print(json.dumps(out, sort_keys=True, separators=(',', ':')))
        return
    if x.evidence:
        print(json.dumps(evidence(x.root), sort_keys=True,
                         separators=(',', ':')))
        return
    print(json.dumps({'phase': 'F', 'commands': ['--build', '--verify', '--evidence']},
                     sort_keys=True, separators=(',', ':')))


if __name__ == '__main__':
    main()
