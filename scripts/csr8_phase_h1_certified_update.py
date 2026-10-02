#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase H1 — certified-tree incremental closure (ordinal 3).

H0 先例（csr8_phase_h_close_certified_tree.py）的 H1 版：H1 生产阶段合法
改变了 data/csr8_phase_c 下五个 zone 的字节（production/ 链与授权、
c4d_proposals/ordinal-0003、c4d_receipts/ordinal-0003、c4_public/ 锚、
h_campaign/ 审查面），认证清单 config/audit/certified_live_inputs.json
必须重新闭合，否则审计层 verify_certified_tree() 闭世界比对失败。

纪律（与 H0 闭合工具一致，严格 fail-closed）：

* 仅重扫五个 zone 的 files[]/dirs[]（逐文件 sha256+bytes+mode，逐非空
  目录 mode）；其余前缀的既有钉定条目逐字节原样保留——secret/、
  outcomes/、analysis_labeled/ 等禁读域从不打开、从不重算。
* 非本次 zone 的条目在新旧清单之间必须完全一致；顶层受保护字段
  （version/generator/forbiddenPrefixes/c4dProposalAllowlist/
  protectedArtifacts/roots 结构）零改动断言。
* 清单顶部新增 h1Closure 披露块（范围、工具、时间、计数）。
* 原子替换写入（mkstemp + os.replace），写后 zone 自检重扫闭世界一致。

本工具不触碰任何生产字节：只重写认证清单 JSON 本身。
"""

import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

MANIFEST = ROOT / 'config/audit/certified_live_inputs.json'
CSR_ROOT_NAME = 'data/csr8_phase_c'
CSR = ROOT / CSR_ROOT_NAME

# H1-legitimate mutation zones (everything else is carried byte-identically)
ZONES = ('production/', 'c4d_proposals/', 'c4d_receipts/', 'c4_public/',
         'h_campaign/')
ZONE_ROOTS = ('production', 'c4d_proposals', 'c4d_receipts', 'c4_public',
              'h_campaign')


def fail(msg):
    raise SystemExit(msg)


def now_utc():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).strftime(
        '%Y-%m-%dT%H:%M:%SZ')


def _in_zone(rel):
    return rel in ZONE_ROOTS or any(rel.startswith(z) for z in ZONES)


def _scan_zones():
    files, dirs = [], []
    for zone in ZONE_ROOTS:
        base = CSR / zone
        if not base.is_dir():
            fail(f'zone root missing on disk: {zone}')
        dirs.append({'path': zone, 'mode': _mode(base)})
        for p in sorted(base.rglob('*')):
            rel = p.relative_to(CSR).as_posix()
            if p.is_dir():
                dirs.append({'path': rel, 'mode': _mode(p)})
            elif p.is_file():
                b = p.read_bytes()
                files.append({'path': rel,
                              'sha256': hashlib.sha256(b).hexdigest(),
                              'bytes': len(b),
                              'mode': _mode(p)})
            else:
                fail(f'non-regular entry in zone: {rel}')
    return files, dirs


def _mode(p):
    return int(oct(os.stat(p).st_mode)[-3:], 8)


def main():
    old_bytes = MANIFEST.read_bytes()
    manifest = json.loads(old_bytes)
    roots = [r for r in manifest['roots'] if r.get('root') == CSR_ROOT_NAME]
    if len(roots) != 1:
        fail('csr root missing from certified manifest')
    csr = roots[0]

    new_files, new_dirs = _scan_zones()

    kept_files = [f for f in csr['files'] if not _in_zone(f['path'])]
    kept_dirs = [d for d in csr['dirs'] if not _in_zone(d['path'])]
    scan_dir_by_path = {d['path']: d for d in new_dirs}
    kept_dirs = [d for d in kept_dirs if d['path'] not in scan_dir_by_path]
    old_kept_files = sorted(kept_files, key=lambda x: x['path'])
    old_kept_dirs = sorted(kept_dirs, key=lambda x: x['path'])

    csr['files'] = sorted(kept_files + new_files, key=lambda x: x['path'])
    csr['dirs'] = sorted(kept_dirs + new_dirs, key=lambda x: x['path'])
    csr['fileCount'] = len(csr['files'])
    csr['dirCount'] = len(csr['dirs'])
    csr['totalBytes'] = sum(f['bytes'] for f in csr['files'])
    manifest['fileCount'] = sum(r['fileCount'] for r in manifest['roots'])
    manifest['totalBytes'] = sum(r['totalBytes'] for r in manifest['roots'])
    manifest['h1Closure'] = {
        'closed_by': 'scripts/csr8_phase_h1_certified_update.py',
        'scope': 'production/ + c4d_proposals/ + c4d_receipts/ + '
                 'c4_public/ + h_campaign/ entries only; forbidden-read '
                 'zones (secret/, outcomes/, analysis_labeled/, corpus/) '
                 'carried byte-identically from the last audit-layer '
                 'certification, never opened, never re-hashed',
        'closed_at': now_utc(),
        'zone_files': len(new_files),
        'zone_dirs': len(new_dirs)}

    # fail-closed self-checks before write
    for f in csr['files']:
        if _in_zone(f['path']):
            continue
        if not (CSR / f['path']).is_file():
            fail(f'non-zone entry lost its live file: {f["path"]}')
    for key in ('c4dProposalAllowlist', 'forbiddenPrefixes',
                'protectedArtifacts', 'generator', 'version'):
        if json.loads(old_bytes).get(key) != manifest.get(key):
            fail(f'manifest field mutated outside H1 closure: {key}')
    new_kept_files = sorted([f for f in csr['files']
                             if not _in_zone(f['path'])],
                            key=lambda x: x['path'])
    new_kept_dirs = sorted([d for d in csr['dirs']
                            if not _in_zone(d['path'])],
                           key=lambda x: x['path'])
    if new_kept_files != old_kept_files or new_kept_dirs != old_kept_dirs:
        fail('non-zone manifest entries mutated')

    fd, tmp = tempfile.mkstemp(dir=str(MANIFEST.parent),
                               prefix='.certified_live_inputs.')
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, sort_keys=True, indent=2)
        fh.write('\n')
    os.replace(tmp, MANIFEST)

    # post-write zone closure self-check
    recheck = json.loads(MANIFEST.read_bytes())
    rc = [r for r in recheck['roots']
          if r.get('root') == CSR_ROOT_NAME][0]
    pinned = {(f['path'], f['sha256'], f['bytes'], f['mode'])
              for f in rc['files'] if _in_zone(f['path'])}
    live = {(f['path'], f['sha256'], f['bytes'], f['mode'])
            for f in _scan_zones()[0]}
    if pinned != live:
        fail('zone closure self-check failed')
    print(json.dumps({
        'state': 'CLOSED', 'zone_files': len(new_files),
        'zone_dirs': len(new_dirs),
        'manifest_fileCount': manifest['fileCount'],
    }, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
