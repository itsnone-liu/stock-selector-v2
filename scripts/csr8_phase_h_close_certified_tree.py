#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CSR-8 Phase H H0 — certified-tree campaign-zone closure (iteration 5).

外部审计对 iteration-4 的阻断：「当前精确目标提交的认证树不闭合、H0 验证
失败，无法确认 campaign manifest、review ledger、ordinal-3 proposal 和
reviewer verdict 构成有效且可重放的入口状态」。

修复语义（严格保持 iteration-4 裁定的禁读边界）：

* config/audit/certified_live_inputs.json 的 data/csr8_phase_c root 此前
  只覆盖已归档的 iteration-3 campaign（hc-c88d…）条目；live campaign
  （hc-4619…）与归档域（h_campaign_archive/）不在清单内 → 审计层
  verify_certified_tree() 全树闭世界比对失败。
* 本工具以增量方式闭合清单：仅新增/更新/移除 h_campaign/ 与
  h_campaign_archive/ 前缀的 files[] 与 dirs[] 条目（逐文件
  sha256+bytes+mode，逐非空目录 mode），重算 fileCount/dirCount/totalBytes。
* 禁读边界：全程在 ForbiddenReadGuard 下运行；除两个 campaign 域与清单
  JSON 本身外不打开任何路径。outcomes/ 与 analysis_labeled/ 的既有钉定
  字节原样保留（不重算、不打开、不校验——归审计层复验）。
* 非campaign条目零改动：逐字节断言新旧清单在非 campaign 域完全一致，
  任何意外差异 fail-closed。
* 清单顶部新增 campaignClosure 披露块，如实记录闭合范围、工具与时间。
"""

import importlib.util
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

_spec = importlib.util.spec_from_file_location(
    'h0_gate', ROOT / 'scripts/csr8_phase_h_entry_gate.py')
h0 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h0)

CAMPAIGN_PREFIXES = ('h_campaign/', 'h_campaign_archive/')
CAMPAIGN_ZONE_ROOTS = ('h_campaign', 'h_campaign_archive')
MANIFEST = ROOT / 'config/audit/certified_live_inputs.json'
CSR_ROOT_NAME = 'data/csr8_phase_c'


def _is_campaign(rel):
    return (rel in CAMPAIGN_ZONE_ROOTS
            or rel.startswith(CAMPAIGN_PREFIXES))


def _scan_campaign_zones():
    """仅遍历两个 campaign 域，返回 files/dirs 条目（相对 CSR root）。"""
    files, dirs = [], []
    for zone in ('h_campaign', 'h_campaign_archive'):
        base = h0.CSR / zone
        if not base.is_dir():
            continue
        # the zone root itself is a manifest dir entry (rglob('*') does
        # not include the base)
        dirs.append({'mode': stat.S_IMODE(base.lstat().st_mode),
                     'path': zone})
        for p in sorted(base.rglob('*')):
            rel = p.relative_to(h0.CSR).as_posix()
            st = p.lstat()
            if p.is_dir():
                if not any(p.iterdir()):
                    continue  # 与冻结 verify_certified_tree 语义一致：空目录不进清单
                dirs.append({'mode': stat.S_IMODE(st.st_mode), 'path': rel})
            elif p.is_file():
                data = p.read_bytes()
                files.append({'bytes': len(data),
                              'mode': stat.S_IMODE(st.st_mode),
                              'path': rel,
                              'sha256': h0.sha(data)})
            else:
                raise SystemExit(f'non-regular campaign entry: {rel}')
    return files, dirs


def main():
    guard = h0.ForbiddenReadGuard()
    h0.GUARD = guard
    with guard:
        old_bytes = MANIFEST.read_bytes()
        manifest = json.loads(old_bytes)
        if manifest.get('version') != 2:
            raise SystemExit('unexpected manifest version')
        roots = [r for r in manifest['roots']
                 if r.get('root') == CSR_ROOT_NAME]
        if len(roots) != 1:
            raise SystemExit('csr root missing')
        csr = roots[0]

        new_files, new_dirs = _scan_campaign_zones()

        kept_files = [f for f in csr['files'] if not _is_campaign(f['path'])]
        kept_dirs = [d for d in csr['dirs'] if not _is_campaign(d['path'])]
        # campaign scan owns the zone roots and everything under them;
        # dedupe by path with the fresh measurement winning
        scan_dir_by_path = {d['path']: d for d in new_dirs}
        kept_dirs = [d for d in kept_dirs
                     if d['path'] not in scan_dir_by_path]
        # non-campaign invariants: byte-identical preservation
        old_kept_files = sorted(kept_files, key=lambda x: x['path'])
        old_kept_dirs = sorted(kept_dirs, key=lambda x: x['path'])

        csr['files'] = sorted(kept_files + new_files,
                              key=lambda x: x['path'])
        csr['dirs'] = sorted(kept_dirs + new_dirs,
                             key=lambda x: x['path'])
        csr['fileCount'] = len(csr['files'])
        csr['dirCount'] = len(csr['dirs'])
        csr['totalBytes'] = sum(f['bytes'] for f in csr['files'])
        manifest['fileCount'] = sum(r['fileCount'] for r in manifest['roots'])
        manifest['totalBytes'] = sum(r['totalBytes'] for r in manifest['roots'])
        manifest['campaignClosure'] = {
            'closed_by': 'scripts/csr8_phase_h_close_certified_tree.py',
            'scope': 'h_campaign/ + h_campaign_archive/ entries only '
                     '(review-surface reads under the ForbiddenReadGuard; '
                     'forbidden-zone pins carried byte-identically from the '
                     'last audit-layer certification, never opened)',
            'closed_at': h0.now_utc(),
            'campaign_files': len(new_files),
            'campaign_dirs': len(new_dirs)}

        # fail-closed self-checks before write
        for f in csr['files']:
            if _is_campaign(f['path']):
                continue
            if not (h0.CSR / f['path']).is_file():
                raise SystemExit(f'non-campaign entry lost live file: '
                                 f'{f["path"]}')
        for key in ('c4dProposalAllowlist', 'forbiddenPrefixes',
                    'protectedArtifacts', 'generator', 'version'):
            if json.loads(old_bytes).get(key) != manifest.get(key):
                raise SystemExit(f'manifest field mutated outside campaign '
                                 f'closure: {key}')
        new_kept_files = sorted(
            [f for f in manifest['roots'][manifest['roots'].index(csr)]
             ['files'] if not _is_campaign(f['path'])],
            key=lambda x: x['path'])
        new_kept_dirs = sorted(
            [d for d in manifest['roots'][manifest['roots'].index(csr)]
             ['dirs'] if not _is_campaign(d['path'])],
            key=lambda x: x['path'])
        if new_kept_files != old_kept_files or new_kept_dirs != old_kept_dirs:
            raise SystemExit('non-campaign manifest entries mutated')

        fd, tmp = tempfile.mkstemp(dir=str(MANIFEST.parent),
                                   prefix='.certified_live_inputs.')
        with os.fdopen(fd, 'w', encoding='utf-8') as fh:
            json.dump(manifest, fh, ensure_ascii=False, sort_keys=True,
                      indent=2)
            fh.write('\n')
        os.replace(tmp, MANIFEST)

        # post-write campaign-zone closure self-check (campaign zones only)
        recheck = json.loads(MANIFEST.read_bytes())
        rc = [r for r in recheck['roots'] if r.get('root') == CSR_ROOT_NAME][0]
        pinned = {(f['path'], f['sha256'], f['bytes'], f['mode'])
                  for f in rc['files'] if _is_campaign(f['path'])}
        live = {(f['path'], f['sha256'], f['bytes'], f['mode'])
                for f in _scan_campaign_zones()[0]}
        if pinned != live:
            raise SystemExit('campaign-zone closure self-check failed')
    print(json.dumps({
        'state': 'CLOSED',
        'campaign_files': len(new_files),
        'campaign_dirs': len(new_dirs),
        'manifest_fileCount': manifest['fileCount'],
        'guard_violations': guard.violations},
        ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
