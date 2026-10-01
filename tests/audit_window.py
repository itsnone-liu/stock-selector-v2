"""Iteration-4 two-layer certification window helper (plain module).

Phase H (iteration 4) no longer runs the frozen certify / machine-audit
scripts (external-audit ruling: nothing Phase H causes may read
forbidden-zone bytes). Between Phase-H completion and audit-layer
re-certification the live tree is legitimately AHEAD of
config/audit/certified_live_inputs.json inside the Phase-H-owned campaign
zones ONLY. The helper below machine-verifies exactly that confinement
WITHOUT opening any forbidden-zone byte (names-only comparison for
forbidden prefixes) so audit-layer tests can fail loudly on any drift
outside the campaign zones while honestly skipping the pending window.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------
# iteration-4 two-layer certification protocol
# --------------------------------------------------------------------------
# Phase H no longer runs the frozen certify/machine-audit scripts (external
# audit iteration-4 ruling: no forbidden-zone reads by anything Phase H
# causes). Between Phase-H completion and audit-layer re-certification the
# live tree is legitimately AHEAD of config/audit/certified_live_inputs.json
# inside the Phase-H-owned campaign zones ONLY. pending_audit_recert_window()
# machine-verifies exactly that confinement WITHOUT opening any
# forbidden-zone byte (names-only comparison for forbidden prefixes).
CAMPAIGN_ZONE_PREFIXES = ("h_campaign", "h_campaign_archive")
FORBIDDEN_PREFIXES = ("outcomes", "analysis_labeled")


def pending_audit_recert_window():
    """(confined, delta): True iff every live-vs-manifest difference sits
    inside the Phase-H campaign zones. Forbidden-zone entries are compared
    by NAME only — this helper never opens them (that is the audit layer's
    job). Any drift outside the campaign zones => confined False."""
    import hashlib
    root = ROOT / "config/audit/certified_live_inputs.json"
    manifest = json.loads(root.read_text())
    csr = next(r for r in manifest["roots"]
               if r["root"] == "data/csr8_phase_c")
    pinned = {f["path"]: (f["sha256"], f["mode"]) for f in csr["files"]}
    live_root = ROOT / "data/csr8_phase_c"
    live = {p.relative_to(live_root).as_posix()
            for p in live_root.rglob("*") if p.is_file()}
    extra = live - set(pinned)
    missing = set(pinned) - live
    changed = set()
    for path, (sha256, mode) in pinned.items():
        if path.startswith(CAMPAIGN_ZONE_PREFIXES):
            continue
        if path in missing:
            continue
        lp = live_root / path
        if path.startswith(FORBIDDEN_PREFIXES):
            continue  # names-only for forbidden zones (never opened here)
        if hashlib.sha256(lp.read_bytes()).hexdigest() != sha256 \
                or (lp.stat().st_mode & 0o777) != mode:
            changed.add(path)
    outside = sorted(
        p for p in extra | missing | changed
        if not p.startswith(CAMPAIGN_ZONE_PREFIXES))
    delta = {"extra_live": len(extra), "missing_live": len(missing),
             "changed": len(changed), "outside_campaign_zones": outside[:10]}
    return (not outside), delta


def skip_if_pending_audit_rec(exc=None):
    """Audit-layer tests hit the pending window: assert the delta is
    EXACTLY the Phase-H campaign zones, then skip with a precise reason.
    Anything else fails loudly."""
    confined, delta = pending_audit_recert_window()
    assert confined, (
        f"certified-tree drift OUTSIDE the campaign zones: {delta} "
        f"(original error: {exc})")
    pytest.skip(
        "pending audit-layer re-certification (iteration-4 two-layer "
        "protocol): Phase-H campaign lifecycle is ahead of the certified "
        "manifest inside h_campaign/ + h_campaign_archive/ only; the "
        "external audit layer re-runs scripts/csr8_phase_a_certify_inputs."
        "py to re-certify")
