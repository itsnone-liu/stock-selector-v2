#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase C4-D B1 — Real annotator handoff（真实授权点，仅 B1）。

任务书 §5 B1（run audit_20260929003837254 阶段 B1）。仅允许：

  1. 创建真实 annotator domain（data/csr8_phase_c/annotator/c4-prod-0002/）
  2. 对当前 R1 packet 做 exact-copy handoff（字节级拷贝自 C2 归档）
  3. 创建 annotation session registry（不透明 annotation_session_id）

禁止（本模块物理上不包含对应代码路径）：receipt / approval / SEAL /
R2 proposal / outcome 读取。

用法：
  python3 scripts/csr8_phase_b1_real_handoff.py            # 执行真实 handoff（一次性）
  python3 scripts/csr8_phase_b1_real_handoff.py --verify   # 只读全 gate 实测

Gate（verify_b1 全部机器实测，可对任意 root（含 tmp 副本）运行）：
  G-B1-CHAIN      真实链恰为 [R1]，event_hash == LIVE_R1_EVENT_HASH
  G-B1-ARCHIVE    C2 归档字节存在且 sha == R1.payload.packet_sha256
  G-B1-DOMAIN     annotator domain 存在、closed-world（B1 边界：仅 packet/
                  与 annotation_session_registry.json）、目录 0700/文件 0600
  G-B1-EXACTCOPY  annotator packet bytes == 归档 bytes（逐字节）
  G-B1-REGISTRY   registry canonical、closed-world schema、绑定链字段、
                  annotation_session_id 不透明（32 hex）、时间戳 canonical
  G-B1-LEAK       域内全部 JSON 键经禁止键扫描（identity/future/outcome/
                  secret 均不得出现）；packet 顶层键 ⊆ 冻结盲态键集
  G-B1-BOUNDARY   c4d_receipts / c4d_proposals 域仍不存在；生产计数
                  REVEAL=1/SEAL=0

冻结模块（c1/c2/c4ab/c4c 与 C4-D synthetic executor）只读导入，不修改。
"""

import argparse
import datetime as _dt
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402 (read-only reuse)

ROOT = c4d.ROOT
REAL_CSR = c4d.REAL_CSR
SID = c4d.REAL_SESSION
LIVE_R1 = c4d.LIVE_R1_EVENT_HASH

G_CHAIN = 'G-B1-CHAIN'
G_ARCH = 'G-B1-ARCHIVE'
G_DOM = 'G-B1-DOMAIN'
G_COPY = 'G-B1-EXACTCOPY'
G_REG = 'G-B1-REGISTRY'
G_LEAK = 'G-B1-LEAK'
G_BOUND = 'G-B1-BOUNDARY'

REGISTRY_NAME = 'annotation_session_registry.json'
REGISTRY_VERSION = 'c4d-annotation-session-registry-v1'
REGISTRY_TOP = {'registry_version', 'session_id', 'reveal_event_hash',
                'packet_id', 'packet_sha256',
                'annotation_contract_sha256', 'annotation_sessions'}
SESSION_KEYS = {'annotation_session_id', 'created_at', 'status',
                'packet_id', 'packet_sha256', 'reveal_event_hash'}
SESSION_STATUSES = {'OPEN', 'SUPERSEDED', 'CLOSED'}
# 冻结盲态 packet 顶层键（真实 R1 归档实测键集，封闭世界）
PACKET_TOP_ALLOWED = {'as_of', 'evidence', 'opaque_case_id', 'packet_id',
                      'price_panel'}
# 禁止出现在 annotator 域任何 JSON 键中（identity / future / outcome /
# secret 四类泄漏）；opaque_case_id 合法，case_key/identity 类不合法
LEAK_FORBIDDEN_KEYS = {
    'case_key', 'case_id', 'identity', 'symbol', 'ticker', 'code',
    'stock_code', 'name', 'person', 'user',
    'outcome', 'outcome_label', 'label', 'y_label', 'forward_return',
    'future_return', 'future', 'horizon_return', 'return_label',
    'secret', 'secret_salt', 'salt', 'api_key', 'token',
}
HEX64 = re.compile(r'^[0-9a-f]{64}$')
HEX32 = re.compile(r'^[0-9a-f]{32}$')
TS_FMT = '%Y-%m-%dT%H:%M:%SZ'


def canon(x):
    return c4d.canon(x)


def sha(b):
    return c4d.sha(b)


def fail(msg):
    raise RuntimeError(msg)


def mode_of(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def registry_path(root, sid=SID):
    return root / 'annotator' / sid / REGISTRY_NAME


def read_chain(root, sid=SID):
    """完整行解析真实链事件（沿用 C4-D 的 committed-prefix 语义）。"""
    log = c4d.sealing_dir(root, sid) / 'sealing_log.jsonl'
    evs = []
    for ln in log.read_text().splitlines():
        if not ln.strip():
            continue
        try:
            evs.append(json.loads(ln))
        except json.JSONDecodeError:
            break
    return evs


def _walk_keys(obj, acc):
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            _walk_keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _walk_keys(v, acc)


def verify_b1(root=None, sid=SID):
    """B1 全 gate 只读实测。返回 gate 明细 dict；任何违反 → RuntimeError。"""
    root = Path(root) if root is not None else REAL_CSR
    gates = {}

    # G-B1-CHAIN：链恰为 [R1]
    evs = read_chain(root, sid)
    reveals = [e for e in evs if e.get('event_type') == 'REVEAL_PACKET']
    seals = [e for e in evs if e.get('event_type') == 'SEAL_ANNOTATION']
    if len(reveals) != 1 or seals:
        fail(f'{G_CHAIN}: chain must be exactly [R1] at stage B1 '
             f'(reveals={len(reveals)} seals={len(seals)})')
    r1 = reveals[0]
    if r1.get('event_hash') != LIVE_R1:
        fail(f'{G_CHAIN}: R1 event_hash != frozen LIVE_R1 anchor')
    if r1['payload'].get('session_id') != sid:
        fail(f'{G_CHAIN}: R1 session binding violated')
    gates[G_CHAIN] = 'PASS'

    # G-B1-ARCHIVE：归档字节可读且哈希绑定
    arch = c4d.sealing_dir(root, sid) / r1['payload']['bytes_ref']
    if not arch.is_file():
        fail(f'{G_ARCH}: C2 archived REVEAL bytes missing: {arch}')
    ab = arch.read_bytes()
    pid = r1['payload']['packet_id']
    psha = r1['payload']['packet_sha256']
    if sha(ab) != psha or not HEX64.match(pid):
        fail(f'{G_ARCH}: archive binding broken (sha/packet_id)')
    gates[G_ARCH] = 'PASS'

    # G-B1-DOMAIN：closed-world 形态
    dom = c4d.annot_dom(root, sid)
    if not dom.is_dir():
        fail(f'{G_DOM}: annotator domain absent (stage B1 requires it)')
    if mode_of(dom) != 0o700:
        fail(f'{G_DOM}: annotator domain mode drift ({oct(mode_of(dom))})')
    # annotator/ 顶层只允许本会话目录（closed-world）
    top = root / 'annotator'
    for e in top.iterdir():
        if e.name != sid:
            fail(f'{G_DOM}: unexpected entry in annotator/ top: {e.name}')
    entries = sorted(p.name for p in dom.iterdir())
    allowed_entries = sorted(['packet', REGISTRY_NAME])
    # B2 legitimately adds the blinded annotation draft/; B1 artifacts
    # remain closed-world and no receipt/approval domain is admitted here.
    if set(entries) - set(allowed_entries) - {'draft'}:
        fail(f'{G_DOM}: closed-world violation — unexpected entries '
             f'{sorted(set(entries) - set(allowed_entries) - {"draft"})}')
    if not set(allowed_entries).issubset(entries):
        fail(f'{G_DOM}: B1 artifacts missing from annotator domain: {entries}')
    if 'draft' in entries:
        if not (dom / 'draft').is_dir() or mode_of(dom / 'draft') != 0o700:
            fail(f'{G_DOM}: draft/ mode drift')
        draft_files = list((dom / 'draft').iterdir())
        if (len(draft_files) != 1 or
                draft_files[0].name != 'annotation_draft.json' or
                mode_of(draft_files[0]) != 0o600):
            fail(f'{G_DOM}: draft/ must contain exactly annotation_draft.json')
    if mode_of(dom / 'packet') != 0o700:
        fail(f'{G_DOM}: packet/ mode drift')
    pkts = list((dom / 'packet').iterdir())
    if len(pkts) != 1 or pkts[0].name != f'{pid}.json':
        fail(f'{G_DOM}: packet/ must hold exactly <packet_id>.json')
    if mode_of(pkts[0]) != 0o600:
        fail(f'{G_DOM}: packet file mode drift ({oct(mode_of(pkts[0]))})')
    if mode_of(registry_path(root, sid)) != 0o600:
        fail(f'{G_DOM}: registry mode drift '
             f'({oct(mode_of(registry_path(root, sid)))})')
    gates[G_DOM] = 'PASS'

    # G-B1-EXACTCOPY：逐字节等于归档
    hb = pkts[0].read_bytes()
    if hb != ab:
        fail(f'{G_COPY}: annotator packet bytes != C2 archived bytes '
             f'(exact-copy contract violated)')
    gates[G_COPY] = 'PASS'

    # G-B1-REGISTRY：canonical closed-world + 绑定 + 不透明 id
    rp = registry_path(root, sid)
    rb = rp.read_bytes()
    try:
        reg = json.loads(rb)
    except json.JSONDecodeError:
        fail(f'{G_REG}: registry is not JSON')
    if not isinstance(reg, dict) or set(reg.keys()) != REGISTRY_TOP:
        ks = set(reg.keys()) if isinstance(reg, dict) else set()
        fail(f'{G_REG}: registry closed-world violation '
             f'(extra={sorted(ks - REGISTRY_TOP)} '
             f'missing={sorted(REGISTRY_TOP - ks)})')
    if canon(reg).encode() != rb:
        fail(f'{G_REG}: registry bytes noncanonical')
    if reg['registry_version'] != REGISTRY_VERSION:
        fail(f'{G_REG}: unknown registry_version')
    if reg['session_id'] != sid or reg['reveal_event_hash'] != LIVE_R1 \
            or reg['packet_id'] != pid or reg['packet_sha256'] != psha:
        fail(f'{G_REG}: registry chain-binding violated')
    if reg['annotation_contract_sha256'] != c4d.ANNOTATION_CONTRACT_SHA256:
        fail(f'{G_REG}: registry annotation-contract binding violated')
    sessions = reg['annotation_sessions']
    if not isinstance(sessions, list) or not sessions:
        fail(f'{G_REG}: annotation_sessions must be a non-empty list')
    seen_ids = set()
    for i, s in enumerate(sessions):
        if not isinstance(s, dict) or set(s.keys()) != SESSION_KEYS:
            fail(f'{G_REG}: session[{i}] closed-world violation')
        if not HEX32.match(s['annotation_session_id'] or ''):
            fail(f'{G_REG}: session[{i}] annotation_session_id not an '
                 f'opaque 32-hex token')
        if s['annotation_session_id'] in seen_ids:
            fail(f'{G_REG}: duplicate annotation_session_id')
        seen_ids.add(s['annotation_session_id'])
        if s['packet_id'] != pid or s['packet_sha256'] != psha \
                or s['reveal_event_hash'] != LIVE_R1:
            fail(f'{G_REG}: session[{i}] chain-binding violated')
        if s['status'] not in SESSION_STATUSES:
            fail(f'{G_REG}: session[{i}] status outside closed set')
        try:  # canonical timestamp round-trip（F5 语义）
            if _dt.datetime.strptime(s['created_at'], TS_FMT).strftime(
                    TS_FMT) != s['created_at']:
                raise ValueError
        except ValueError:
            fail(f'{G_REG}: session[{i}] created_at not canonical UTC Z')
    if sessions[-1]['status'] != 'OPEN':
        fail(f'{G_REG}: latest annotation session must be OPEN at B1')
    gates[G_REG] = 'PASS'

    # G-B1-LEAK：域内全部文件的 JSON 键禁止键扫描 + packet 顶层键集
    for f in sorted(dom.rglob('*')):
        if not f.is_file():
            continue
        raw = f.read_bytes()
        if b'secret_salt' in raw or b'api_key' in raw:
            fail(f'{G_LEAK}: secret material in annotator domain: {f.name}')
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            fail(f'{G_LEAK}: non-JSON file in annotator domain: {f.name}')
        keys = set()
        _walk_keys(obj, keys)
        bad = keys & LEAK_FORBIDDEN_KEYS
        if bad:
            fail(f'{G_LEAK}: forbidden key(s) {sorted(bad)} leaked into '
                 f'annotator domain file {f.name}')
    pkt_obj = json.loads(hb)
    if not isinstance(pkt_obj, dict) or \
            not set(pkt_obj.keys()) <= PACKET_TOP_ALLOWED:
        fail(f'{G_LEAK}: handed-off packet top-level keys outside the '
             f'frozen blinded schema: {sorted(set(pkt_obj.keys()))}')
    gates[G_LEAK] = 'PASS'

    # G-B1-BOUNDARY：后续域仍不存在 + 生产计数不变
    for d in ('c4d_receipts', 'c4d_proposals'):
        if (root / d).exists():
            fail(f'{G_BOUND}: forbidden domain exists at stage B1: {d}/')
    n_rev = len([e for e in evs if e.get('event_type') == 'REVEAL_PACKET'])
    if n_rev != 1 or seals:
        fail(f'{G_BOUND}: production counts must stay REVEAL=1/SEAL=0')
    gates[G_BOUND] = 'PASS'

    return {'gates': gates, 'packet_id': pid, 'packet_sha256': psha,
            'reveal_event_hash': LIVE_R1,
            'annotation_sessions': len(sessions),
            'annotation_session_id': sessions[-1]['annotation_session_id']}


def do_handoff():
    """真实执行 B1（一次性）。任何 gate 前置不过 → 不写任何字节。"""
    evs = read_chain(REAL_CSR, SID)
    reveals = [e for e in evs if e.get('event_type') == 'REVEAL_PACKET']
    if len(reveals) != 1 or any(
            e.get('event_type') == 'SEAL_ANNOTATION' for e in evs):
        fail(f'{G_CHAIN}: real chain is not exactly [R1] — refusing')
    r1 = reveals[0]
    if r1['event_hash'] != LIVE_R1:
        fail(f'{G_CHAIN}: real R1 head != frozen anchor — refusing')
    dom = c4d.annot_dom(REAL_CSR, SID)
    if dom.exists():
        fail('B1 already executed (annotator domain exists) — '
             'use --verify')
    arch = c4d.sealing_dir(REAL_CSR, SID) / r1['payload']['bytes_ref']
    ab = arch.read_bytes()
    if sha(ab) != r1['payload']['packet_sha256']:
        fail(f'{G_ARCH}: archive binding broken — refusing to hand off')

    sid_dir = REAL_CSR / 'annotator'
    sid_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if mode_of(sid_dir) != 0o700:
        os.chmod(sid_dir, 0o700)
    dom.mkdir(mode=0o700)
    c4d.fsync_dir(sid_dir)
    (dom / 'packet').mkdir(mode=0o700)
    c4d.fsync_dir(dom)
    target = c4d.packet_path(REAL_CSR, SID, r1['payload']['packet_id'])
    c4d.excl_write(target, ab)          # O_EXCL 0600 + fsync(file, parent)
    c4d.fsync_dir(dom / 'packet')
    now = _dt.datetime.now(_dt.timezone.utc).strftime(TS_FMT)
    reg = {
        'registry_version': REGISTRY_VERSION,
        'session_id': SID,
        'reveal_event_hash': LIVE_R1,
        'packet_id': r1['payload']['packet_id'],
        'packet_sha256': r1['payload']['packet_sha256'],
        'annotation_contract_sha256': c4d.ANNOTATION_CONTRACT_SHA256,
        'annotation_sessions': [{
            'annotation_session_id': secrets.token_hex(16),
            'created_at': now,
            'status': 'OPEN',
            'packet_id': r1['payload']['packet_id'],
            'packet_sha256': r1['payload']['packet_sha256'],
            'reveal_event_hash': LIVE_R1,
        }],
    }
    c4d.excl_write(registry_path(REAL_CSR, SID), canon(reg).encode())
    c4d.fsync_dir(dom)
    result = verify_b1()
    result['b1'] = 'HANDOFF_DONE'
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--verify', action='store_true',
                    help='read-only full gate verification (no writes)')
    args = ap.parse_args(argv)
    if args.verify:
        result = verify_b1()
        result['b1'] = 'VERIFIED'
    else:
        result = do_handoff()
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':'),
                     sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
