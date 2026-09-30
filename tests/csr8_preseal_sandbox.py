"""Certified pre-B5 sandbox construction for bridge-executable tests.

The B5 POST_SEAL_FINAL cleanup legitimately removed the live annotator
workspace (its audit trail lives on in the C2 archive +
draft_snapshot.bin + c4d_receipts), so B1/B2/B4 gate tests must NOT
treat the live tree as a pre-SEAL state any more: the live terminal
state is [R1,S1] with an empty/absent annotator domain.

This builder re-derives a complete pre-B5 state in an isolated tmp root
FROM THE LIVE CERTIFIED BYTES, driving the REAL transaction APIs
end-to-end (no fixture snapshots, no synthetic reimplementation):

    production copy (chain truncated to the exact committed R1 line,
    S1 archived bytes removed, head rewound to count=1)
      -> b1.do_handoff(root)            # real annotator domain + registry
      -> b2.create(root)                # real blinded draft
      -> c4d.make_receipt(root, ...)    # real receipt freeze (draft -> 0400)
      -> b4.persist_unattended(root, record)   # real approval artifacts

Every artifact is produced by the frozen transaction code and bound to
the frozen LIVE_R1 anchor + the certified archived packet bytes, so the
result is a certifiable B4 pre-state ("SEAL_AUTHORIZED") from which the
real seal_transaction can be executed and measured.
"""
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import csr8_phase_c_annotation_seal as c4d  # noqa: E402
import csr8_phase_b1_real_handoff as b1     # noqa: E402
import csr8_phase_b2_real_annotation as b2  # noqa: E402
import csr8_phase_b4_human_approval as b4   # noqa: E402

STAGES = ("B1", "B2", "B3", "B4")


class PreSealSandbox:
    """An isolated, transaction-derived pre-B5 state."""

    def __init__(self, root, record_path, through):
        self.root = Path(root)
        self.record_path = Path(record_path)
        self.through = through

    @property
    def receipt_sha256(self):
        return b4.receipt_sha256(self.root)


def _rewind_chain_to_r1(root):
    """Truncate the copied production chain to the exact committed R1
    event and rewind the trusted head (count=1, head=R1 hash).  The S1
    archived bytes are removed: a pre-SEAL state must not contain them."""
    log = c4d.log_path(root, c4d.REAL_SESSION)
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    # C3 live state is [R1,S1,R2].  Rewind must discard the later reveal and
    # its ordinal-2 authorization so the replica is rebuilt from the exact
    # pre-B5 boundary rather than inheriting post-C3 artifacts.
    if len(lines) not in (2, 3):
        raise RuntimeError(
            f"live production chain is not a supported [R1,S1] or "
            f"[R1,S1,R2] shape ({len(lines)} events) — refusing to build a "
            f"pre-SEAL sandbox from it")
    if len(lines) == 3:
        r2 = json.loads(lines[2])
        if r2.get("event_type") != "REVEAL_PACKET":
            raise RuntimeError("post-C3 tail is not an R2 reveal")
        lines = lines[:2]
    r1 = json.loads(lines[0])
    if r1["event_type"] != "REVEAL_PACKET" or \
            r1["event_hash"] != c4d.LIVE_R1_EVENT_HASH:
        raise RuntimeError("live R1 event does not match the frozen anchor")
    log.write_text(lines[0] + "\n")
    c4d.head_path(root, c4d.REAL_SESSION).write_text(
        json.dumps({"count": 1, "head_hash": r1["event_hash"]},
                   sort_keys=True, separators=(",", ":")))
    seal_bytes = (root / "production" / c4d.REAL_SESSION / "sealing" /
                  "bytes" / "seal_annotation")
    if seal_bytes.exists():
        shutil.rmtree(seal_bytes)
    # C2-stage artifact rewind: the ordinal-2 authorization domain
    # (approval+permit for the NEXT reveal) postdates the pre-B5 state
    # this builder reconstructs.  A copied pair would bind the LIVE
    # proposal bytes and break the replica's own transactions.
    authz2 = c4d.next_authz_dir(root, c4d.REAL_SESSION, 2)
    if authz2.exists():
        shutil.rmtree(authz2)


def build_pre_seal_sandbox(tmp_path, through="B4"):
    """Drive the real B1→B4 transaction sequence on an isolated copy.

    ``through`` selects how far the sequence is driven (B1/B2/B3/B4);
    B4 yields a SEAL_AUTHORIZED pre-B5 state.
    """
    if through not in STAGES:
        raise ValueError(f"through must be one of {STAGES}")
    tmp = Path(tmp_path)
    root = tmp / "csr8_phase_c"
    root.mkdir(parents=True)
    shutil.copytree(c4d.REAL_PRODUCTION, root / "production")
    shutil.copytree(c4d.REAL_CSR / "public", root / "public")
    _rewind_chain_to_r1(root)
    if through in STAGES:                       # B1: real handoff
        b1.do_handoff(root)
    if through in ("B2", "B3", "B4"):           # B2: real blinded draft
        b2.create(root)
    if through in ("B3", "B4"):                 # B3: real receipt freeze
        c4d.make_receipt(root, c4d.REAL_SESSION, ordinal=1)
    record = tmp / "b4_unattended_approval.json"
    if through == "B4":                          # B4: real approval artifacts
        b4.persist_unattended(root, record)
    return PreSealSandbox(root, record, through)
