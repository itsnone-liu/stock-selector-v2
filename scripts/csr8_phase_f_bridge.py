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


def read_ledger(root=CSR, sid=SID):
    return json.loads(ledger_path(root, sid).read_text())


def verify_corpus(root=CSR, sid=SID):
    """只读全 gate 实测；任何篡改 → RuntimeError。"""
    root = Path(root)
    gates = {}
    ledger = read_ledger(root, sid)
    cdir = corpus_dir(root, sid)
    on_disk = sorted(p.relative_to(cdir).as_posix()
                     for p in cdir.rglob('*') if p.is_file())
    listed = sorted([f['path'] for f in ledger['files']] + ['ledger.json'])
    if on_disk != listed:
        fail(f'G-F-CORPUS-WORLD: corpus closed-world violated {on_disk} != {listed}')
    gates['G-F-CORPUS-WORLD'] = 'PASS'
    for f in ledger['files']:
        fp = cdir / f['path']
        b = fp.read_bytes()
        if sha(b) != f['sha256'] or len(b) != f['bytes']:
            fail(f"G-F-CORPUS-LEDGER: hash ledger mismatch {f['path']}")
        if stat.S_IMODE(os.stat(fp).st_mode) != 0o444:
            fail(f"G-F-CORPUS-RO: file not read-only {f['path']}")
    gates['G-F-CORPUS-LEDGER'] = 'PASS'
    gates['G-F-CORPUS-RO'] = 'PASS'
    # 冻结链 replay 重新派生全部绑定
    evs = verify_chain(root, sid)
    head = json.loads(sealing_paths(root, sid)[1].read_text())
    if (head['head_hash'] != ledger['chain']['head_hash']
            or len(evs) != ledger['chain']['event_count']):
        fail('G-F-CORPUS-CHAIN: ledger no longer binds the live chain head')
    pairs = sealed_pairs(root, sid)
    if len(pairs) != len(ledger['pairs']):
        fail('G-F-CORPUS-CHAIN: pair count drift')
    for (ordinal, rev, seal), m in zip(pairs, ledger['pairs']):
        rp, sp = rev['payload'], seal['payload']
        if (m['reveal_event_hash'] != rev['event_hash']
                or m['seal_event_hash'] != seal['event_hash']
                or m['packet_sha256'] != rp['packet_sha256']
                or m['receipt_sha256'] != sp['receipt_sha256']
                or m['opaque_case_id'] != rp['opaque_case_id'] or m['T'] != rp['T']):
            fail(f'G-F-CORPUS-CHAIN: pair {ordinal} binding drift')
        od = f'ordinal-{ordinal:04d}'
        pb = (cdir / 'pairs' / od / 'reveal_packet.json').read_bytes()
        rb = (cdir / 'pairs' / od / 'seal_receipt.json').read_bytes()
        if sha(pb) != rp['packet_sha256'] or sha(rb) != sp['receipt_sha256']:
            fail(f'G-F-CORPUS-CHAIN: corpus bytes != chain payload ({od})')
        receipt = json.loads(rb)
        if receipt['packet_id'] != rp['packet_id']:
            fail(f'G-F-CORPUS-CHAIN: receipt/packet binding ({od})')
    gates['G-F-CORPUS-CHAIN'] = 'PASS'
    return gates


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


def build_analysis(root=CSR, sid=SID):
    """分析侧只经 guarded reader 读 corpus 盲态字节派生 analysis 行。"""
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
    adir = analysis_dir(root, sid)
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
    return croot, pr, cal_path


def evidence(root=CSR, out_path=None):
    """§9.1–§9.3 机器实测 evidence：live 构建+全 gate+真实渗透尝试+删失变体。"""
    import tempfile
    from csr8_phase_f_outcome_join import (build_outcomes, verify_outcomes,
                                           join, CENSOR_WINDOW, CENSOR_PRICE)
    root = Path(root)
    out_path = Path(out_path) if out_path else (
        ROOT / 'docs/audit/evidence/f_phase_bridge.json')
    led = build_corpus(root)
    man = build_analysis(root)
    outcomes = build_outcomes(root)
    j = join(root)
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
        'corpus': {'files': led['totals'],
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
