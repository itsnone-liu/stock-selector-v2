#!/usr/bin/env python3
"""Certified live-input inventory for bridge-executed audits (Phase A i17).

The audit bridge executes post-commit pytest in an isolated detached
worktree that intentionally has NO access to gitignored ``data/`` state.
The Phase-A freeze nevertheless requires the REAL production gates
(C4-C regression, live preflight, candidate gates, blindness scan,
production REVEAL=1/SEAL=0, forbidden-domain absence, real fingerprint
before==after) to run there.

The audit verdict for iteration 16 states the sanctioned resolution:
committed tests must not *necessarily* fail; gates that depend on
non-committed live inputs need CERTIFIED inputs provided through the
audit infrastructure.

This script produces that certification, pinned inside the repo:

* it walks the COMPLETE trees the frozen C4-C/C4-D chain reads
  (every dir and file, with mode / size / sha256 — full inventory,
  not a cherry-pick): ``data/csr8_phase_c`` (production chain, C3
  preflight, secret) and ``data/adjustment_baostock`` (frozen price
  authority verified by the C4-C regression);
* it refuses to certify if any forbidden C4-D domain exists under
  ``data/csr8_phase_c`` (c4d_receipts/, c4d_proposals/ — stage-boundary
  aware as of run 2 B1: the annotator/ domain became a legal real
  domain at B1 and its closed-world/leak gates are machine-verified by
  scripts/csr8_phase_b1_real_handoff.py) — so the committed manifest
  itself is machine-checkable proof of the stage boundary;
* it writes ``config/audit/certified_live_inputs.json`` (version 2,
  multi-root).

The bridge then reads this manifest FROM THE TARGET COMMIT (git object
db, never the working tree), verifies the executor's live trees match
every pinned hash exactly, and only then materializes them into the
detached worktree.  Any drift (modified / missing / extra entry) is
recorded and nothing is copied — fail-closed.

Run (read-only w.r.t. data/, writes one config file):

    python3 scripts/csr8_phase_a_certify_inputs.py
"""

import hashlib
import json
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'config/audit/certified_live_inputs.json'

# 冻结 C4-C/C4-D 链读取的全部 data/ 根（grep 全量枚举过）。
ROOTS = (
    'data/csr8_phase_c',
    'data/adjustment_baostock',
)

# Security-sensitive approval evidence is outside the live data roots, so it
# must be pinned explicitly rather than silently omitted from certification.
PROTECTED_ARTIFACTS = (
    'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-0001/attempt-0001/seal_approval.json',
    'docs/audit/evidence/b4_unattended_approval.json',
)

# C4-D 禁止域（阶段边界感知，run 2 / B1+）：annotator/ 自 B1 起为合法
# 真实域（其 closed-world 与泄漏 gate 由 csr8_phase_b1_real_handoff.py
# 机器实测）；c4d_receipts/ 与 c4d_proposals/ 在 B3/B5 前仍属禁止。
FORBIDDEN_PREFIXES = (
    'c4d_proposals/',
)


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def inventory(root_rel):
    root = ROOT / root_rel
    if not root.is_dir():
        print(f'FAIL: live root missing: {root}')
        sys.exit(1)
    dirs, files = [], []
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root).as_posix()
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode):
            print(f'FAIL: symlink refused in certified tree: '
                  f'{root_rel}/{rel}')
            sys.exit(1)
        if p.is_dir():
            if any(rel.startswith(fp) for fp in FORBIDDEN_PREFIXES):
                print(f'FAIL: forbidden C4-D domain present: '
                      f'{root_rel}/{rel}')
                sys.exit(1)
            dirs.append({'path': rel, 'mode': stat.S_IMODE(st.st_mode)})
        elif p.is_file():
            if any(rel.startswith(fp) for fp in FORBIDDEN_PREFIXES):
                print(f'FAIL: forbidden C4-D file present: '
                      f'{root_rel}/{rel}')
                sys.exit(1)
            files.append({'path': rel, 'sha256': sha256_file(p),
                          'bytes': st.st_size,
                          'mode': stat.S_IMODE(st.st_mode)})
        else:
            print(f'FAIL: non-regular entry refused: {root_rel}/{rel}')
            sys.exit(1)
    return {'root': root_rel, 'dirCount': len(dirs),
            'fileCount': len(files),
            'totalBytes': sum(f['bytes'] for f in files),
            'dirs': dirs, 'files': files}


def protected_inventory():
    entries = []
    for rel in PROTECTED_ARTIFACTS:
        path = ROOT / rel
        if not path.is_file():
            print(f'FAIL: protected artifact missing: {rel}')
            sys.exit(1)
        st = path.lstat()
        mode = stat.S_IMODE(st.st_mode)
        if mode != 0o600:
            print(f'FAIL: protected artifact must be 0600: {rel} (got {oct(mode)})')
            sys.exit(1)
        entries.append({'path': rel, 'sha256': sha256_file(path),
                        'bytes': st.st_size, 'mode': mode})
    return entries


def main():
    roots = [inventory(r) for r in ROOTS]
    protected = protected_inventory()
    manifest = {
        'version': 2,
        'generator': 'scripts/csr8_phase_a_certify_inputs.py',
        'forbiddenPrefixes': list(FORBIDDEN_PREFIXES),
        'roots': roots,
        'protectedArtifacts': protected,
        'fileCount': sum(r['fileCount'] for r in roots),
        'totalBytes': sum(r['totalBytes'] for r in roots),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, sort_keys=True, indent=1),
                   encoding='utf-8')
    print(f'certified {len(roots)} roots / '
          f'{manifest["fileCount"]} files / '
          f'{manifest["totalBytes"]} bytes -> {OUT.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
