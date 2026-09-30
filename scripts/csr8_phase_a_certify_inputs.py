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
* it refuses to certify any C4-D domain entry that violates the stage
  boundary (stage-boundary aware as of run 2: annotator/ became legal
  at B1 and was cleaned by the B5 POST_SEAL_FINAL; c4d_receipts/ is the
  legal frozen evidence domain since B3; c4d_proposals/ became legal at
  C1 as a CLOSED-WORLD domain whose sole allowlisted entry is the
  ordinal-2 next_reveal.proposal.json — approval/permit are the C2
  authorization point) — so the committed manifest itself is
  machine-checkable proof of the stage boundary;
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
# The C1 ordinal-2 proposal and the C2 approval+permit pair are selector-only
# 0600 artifacts INSIDE the data root (already inventory-pinned); listing
# them here additionally enforces their 0600 mode through the bridge's
# protected-artifact materialization path.
PROTECTED_ARTIFACTS = (
    'data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-0001/attempt-0001/seal_approval.json',
    'data/csr8_phase_c/c4d_proposals/c4-prod-0002/ordinal-0002/next_reveal.proposal.json',
    'data/csr8_phase_c/production/c4-prod-0002/authorization/ordinal-0002/next_reveal.approval.json',
    'data/csr8_phase_c/production/c4-prod-0002/authorization/ordinal-0002/next_reveal.permit.json',
    'docs/audit/evidence/b4_unattended_approval.json',
    'docs/audit/evidence/c2_unattended_approval.json',
)

# C4-D 域阶段边界（C1 终态感知）：annotator/ 工作区在 B5 POST_SEAL_FINAL
# 后已按协议清理；c4d_receipts/ 自 B3 起为合法冻结证据域；c4d_proposals/
# 自 C1 起合法，但 closed-world：域内唯一允许文件是 ordinal-2
# next_reveal.proposal.json（approval/permit 是 C2 授权点、其余 ordinal
# 域是后续阶段，均仍禁止）。
C4D_PROPOSAL_ALLOWLIST = (
    'c4d_proposals/c4-prod-0002/ordinal-0002/next_reveal.proposal.json',
)


def _c4d_proposal_forbidden(rel):
    """rel is relative to data/csr8_phase_c (posix).

    Legal inside c4d_proposals/ at the C1 boundary: exactly the
    allowlisted file and the ancestor directories leading to it (the
    closed-world DOMAIN structure).  Everything else — approval/permit
    files, other ordinals, foreign subtrees — fails closed.
    """
    if not rel.startswith('c4d_proposals/'):
        return False
    if rel in C4D_PROPOSAL_ALLOWLIST:
        return False
    return not any(a.startswith(rel + '/')
                   for a in C4D_PROPOSAL_ALLOWLIST)


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
    dirs, files, skipped_empty = [], [], []
    for p in sorted(root.rglob('*')):
        rel = p.relative_to(root).as_posix()
        st = p.lstat()
        if stat.S_ISLNK(st.st_mode):
            print(f'FAIL: symlink refused in certified tree: '
                  f'{root_rel}/{rel}')
            sys.exit(1)
        if p.is_dir():
            if _c4d_proposal_forbidden(rel):
                print(f'FAIL: forbidden C4-D proposal entry present: '
                      f'{root_rel}/{rel}')
                sys.exit(1)
            # Empty directories are NOT certifiable: the bridge
            # materializes certified inputs file-by-file into a detached
            # git worktree (git cannot represent an empty directory), so
            # a pinned empty dir would ENOENT at materialization time
            # (audit_20260930021152297 i18 bridge record).  They are
            # skipped explicitly and reported — never silently pinned.
            if not any(p.iterdir()):
                skipped_empty.append(rel)
                continue
            dirs.append({'path': rel, 'mode': stat.S_IMODE(st.st_mode)})
        elif p.is_file():
            if _c4d_proposal_forbidden(rel):
                print(f'FAIL: forbidden C4-D proposal file present: '
                      f'{root_rel}/{rel}')
                sys.exit(1)
            files.append({'path': rel, 'sha256': sha256_file(p),
                          'bytes': st.st_size,
                          'mode': stat.S_IMODE(st.st_mode)})
        else:
            print(f'FAIL: non-regular entry refused: {root_rel}/{rel}')
            sys.exit(1)
    for rel in skipped_empty:
        print(f'note: skipping empty (non-materializable) directory: '
              f'{root_rel}/{rel}')
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
        # C1 stage boundary: no blanket-forbidden C4-D prefix remains;
        # c4d_proposals/ is closed-world with exactly the allowlisted
        # ordinal-2 proposal (approval/permit stay forbidden — C2 point).
        'forbiddenPrefixes': [],
        'c4dProposalAllowlist': list(C4D_PROPOSAL_ALLOWLIST),
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
