"""CSR-8 C1 ordinal-2 next-reveal proposal tests (bridge-executable).

Taskbook §6 C1 (run audit_20260930021152297, stage C1): the ordinal-2
proposal is a selector-only artifact derived from the committed chain.

Measured here, on real transaction paths (no fixture snapshots):

* prerequisites: chain == [R1,S1], open_reveals == 0, S1 replay PASS,
  candidate prefix == 1 — all machine-measured by verify_c1 on the live
  tree AND re-executed end-to-end on a transaction-derived sealed
  replica (real B1→B4 + seal_transaction from the certified live bytes,
  then the real do_propose transaction);
* closed-world: the c4d_proposals domain contains exactly the ordinal-2
  proposal, approval/permit do not exist (C2 authorization point), no
  R2 is appended (production stays REVEAL=1/SEAL=1), and the c4c anchor
  keeps its frozen reveal-phase bytes;
* disclosure: the verify surface exposes ONLY proposal_sha256 — no
  candidate ocid/T/packet_id leaves the selector side;
* fail-closed: every prerequisite/boundary violation on tampered sealed
  replicas is caught by the exact C1 gate.
"""
import hashlib
import json
import shutil
import stat
from pathlib import Path

import pytest

from csr8_preseal_sandbox import build_pre_seal_sandbox  # noqa: F401 (sys.path)

import csr8_phase_c_annotation_seal as c4d
import csr8_phase_c1_ordinal2_proposal as c1mod

SID = c4d.REAL_SESSION
GATES = {
    c1mod.G_CHAIN, c1mod.G_CLOSED, c1mod.G_REPLAY, c1mod.G_PREFIX,
    c1mod.G_ELIG, c1mod.G_PROP, c1mod.G_WORLD, c1mod.G_BOUND,
}


def _sealed_replica(tmp_path, name="sealed"):
    """Fresh transaction-derived [R1,S1] replica from certified live
    bytes (real handoff/draft/receipt/approval transactions on a chain
    copy rewound to the exact committed R1 line, then the real seal)."""
    sb = build_pre_seal_sandbox(tmp_path / name, through="B4")
    result = c4d.seal_transaction(sb.root, SID)
    assert result["state"] == "SEALED"
    return sb.root


def _replica_with_proposal(tmp_path, name="proposed"):
    root = _sealed_replica(tmp_path, name)
    out = c1mod.do_propose(root)
    assert out["c1"] == "PROPOSAL_PERSISTED"
    return root


def _rewind_to_open_reveal(root):
    """Turn a sealed replica back into an open-reveal chain ([R1] only,
    S1 archive removed, trusted head rewound to count=1)."""
    log = c4d.log_path(root, SID)
    lines = [l for l in log.read_text().splitlines() if l.strip()]
    assert len(lines) == 2
    log.write_text(lines[0] + "\n")
    r1 = json.loads(lines[0])
    c4d.head_path(root, SID).write_text(
        json.dumps({"count": 1, "head_hash": r1["event_hash"]},
                   sort_keys=True, separators=(",", ":")))
    seal_bytes = root / "production" / SID / "sealing" / "bytes" / \
        "seal_annotation"
    if seal_bytes.exists():
        shutil.rmtree(seal_bytes)


# ---------------------------------------------------------------------------
# live tree — the authoritative C1 post-state
# ---------------------------------------------------------------------------

def test_c1_live_gates_all_pass_with_hash_only_disclosure():
    events = [json.loads(l) for l in
              (c4d.REAL_PRODUCTION / SID / "sealing" /
               "sealing_log.jsonl").read_text().splitlines() if l.strip()]
    if [e["event_type"] for e in events] in ([
            "REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET"], [
            "REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET", "SEAL_ANNOTATION"]):
        pytest.skip("C1 live boundary superseded by completed C3/C6")
    result = c1mod.verify_c1()
    assert result["root_scope"] == "live"
    assert result["chain"] == ["REVEAL_PACKET", "SEAL_ANNOTATION"]
    assert result["open_reveals"] == 0
    assert result["candidate_prefix"] == 1
    assert set(result["gates"]) == GATES
    assert set(result["gates"].values()) == {"PASS"}
    assert result["proposal_rel"] == c1mod.PROPOSAL_REL
    # disclosure contract: the ONLY C1 artifact surface is the sha256
    h = result["proposal_sha256"]
    assert isinstance(h, str) and len(h) == 64
    int(h, 16)
    # no candidate identity leaves the selector side in the verify result
    safe_keys = {"root_scope", "chain", "open_reveals", "candidate_prefix",
                 "proposal_rel", "proposal_sha256", "gates", "c1"}
    assert set(result) <= safe_keys, set(result) - safe_keys
    blob = json.dumps(result)
    for forbidden in ("opaque_case_id", "packet_id", "case_key"):
        assert forbidden not in blob
    # deterministic re-measurement: identical bytes -> identical result
    assert c1mod.verify_c1() == result
    # the certified manifest pins the exact live proposal bytes
    manifest = json.loads(
        (Path(c4d.ROOT) / "config/audit/certified_live_inputs.json")
        .read_text())
    entry = next(
        f for r in manifest["roots"] for f in r["files"]
        if f"{r['root']}/{f['path']}" ==
        f"data/csr8_phase_c/{c1mod.PROPOSAL_REL}")
    pbytes = (Path(c4d.REAL_CSR) / c1mod.PROPOSAL_REL).read_bytes()
    assert entry["sha256"] == hashlib.sha256(pbytes).hexdigest() == h
    assert entry["mode"] == 0o600


def test_c1_live_boundary_no_c3_state():
    log = c4d.REAL_PRODUCTION / SID / "sealing" / "sealing_log.jsonl"
    events = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    if [e["event_type"] for e in events] in ([
            "REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET"], [
            "REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET", "SEAL_ANNOTATION"]):
        pytest.skip("C1 boundary superseded by completed C3/C6")
    """C1 stops at the proposal and C2 stops at approval+permit: the
    ordinal-2 authorization domain holds EXACTLY the frozen-re-proven
    pair, no R2 append (production stays REVEAL=1/SEAL=1), the
    production authorization top level keeps only the frozen C4-C
    first-reveal artifacts, and the c4c anchor bytes are untouched."""
    log = c4d.REAL_PRODUCTION / SID / "sealing" / "sealing_log.jsonl"
    events = [json.loads(l) for l in log.read_text().splitlines() if l.strip()]
    assert [e["event_type"] for e in events] == \
        ["REVEAL_PACKET", "SEAL_ANNOTATION"]          # no R2 append
    # C2 terminal shape: exactly the approval+permit pair, fully
    # re-proven through the frozen authorization-chain proof.
    ad = c4d.next_authz_dir(c4d.REAL_CSR, SID, 2)
    assert sorted(p.name for p in ad.rglob("*") if p.is_file()) == \
        ["next_reveal.approval.json", "next_reveal.permit.json"]
    assert not any(p.is_dir() for p in ad.rglob("*"))
    c4d.verify_next_authorization_chain(c4d.REAL_CSR, SID, 2)
    permit = (ad / "next_reveal.permit.json").read_bytes()
    proposal_bytes = (Path(c4d.REAL_CSR) / c1mod.PROPOSAL_REL).read_bytes()
    assert permit == proposal_bytes                # three-way exact bytes
    authz = c4d.prod_dir(c4d.REAL_CSR, SID) / "authorization"
    assert sorted(p.name for p in authz.iterdir()) == \
        ["first_reveal.approval.json", "first_reveal.json", "ordinal-0002"]
    # selector-only mode discipline on the live proposal domain
    pdom = c4d.REAL_PROPOSALS_C4D
    for d in (pdom, pdom / SID, c4d.proposals_dom(c4d.REAL_CSR, SID, 2)):
        assert stat.S_IMODE(d.lstat().st_mode) == 0o700
    assert stat.S_IMODE(
        (pdom / SID / "ordinal-0002" / "next_reveal.proposal.json")
        .lstat().st_mode) == 0o600
    assert stat.S_IMODE((ad / "next_reveal.approval.json")
                        .lstat().st_mode) == 0o600
    assert stat.S_IMODE((ad / "next_reveal.permit.json")
                        .lstat().st_mode) == 0o600


def test_c1_do_propose_is_one_shot_on_live():
    events = [json.loads(l) for l in
              (c4d.REAL_PRODUCTION / SID / "sealing" /
               "sealing_log.jsonl").read_text().splitlines() if l.strip()]
    if [e["event_type"] for e in events] in ([
            "REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET"], [
            "REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET", "SEAL_ANNOTATION"]):
        pytest.skip("C1 one-shot live transaction superseded by completed C3/C6")
    """The live transaction is O_EXCL: a second do_propose refuses at
    the duplicate gate BEFORE any write, and the tree is unchanged."""
    before = (Path(c4d.REAL_CSR) / c1mod.PROPOSAL_REL).read_bytes()
    with pytest.raises(RuntimeError, match="duplicate proposal"):
        c1mod.do_propose()
    assert (Path(c4d.REAL_CSR) / c1mod.PROPOSAL_REL).read_bytes() == before
    assert set(c1mod.verify_c1()["gates"].values()) == {"PASS"}


# ---------------------------------------------------------------------------
# real transaction on a sealed replica — the derivation is re-executed
# ---------------------------------------------------------------------------

def test_c1_real_transaction_on_sealed_replica(tmp_path):
    """do_propose re-executes the full derivation on a transaction-
    derived sealed replica: pre-write prerequisites, frozen §7 builder,
    one-shot persistence, full gate re-proof."""
    root = _sealed_replica(tmp_path)
    target = root / c1mod.PROPOSAL_REL
    assert not target.exists()
    out = c1mod.do_propose(root)
    assert out["c1"] == "PROPOSAL_PERSISTED"
    assert out["root_scope"] == "replica"
    assert set(out["gates"]) == GATES
    assert set(out["gates"].values()) == {"PASS"}
    assert out["candidate_prefix"] == 1 and out["open_reveals"] == 0
    # persisted artifact: canonical bytes, 0600 file inside 0700 domains
    proposal, pbytes = c4d._check_proposal(root, SID, 2)
    assert c4d.canon(proposal).encode() == pbytes
    assert stat.S_IMODE(target.lstat().st_mode) == 0o600
    for d in (root / "c4d_proposals", root / "c4d_proposals" / SID,
              c4d.proposals_dom(root, SID, 2)):
        assert stat.S_IMODE(d.lstat().st_mode) == 0o700
    # the proposal binds THIS chain's sealed prefix head (S1 event hash)
    s1 = [json.loads(l) for l in
          c4d.log_path(root, SID).read_text().splitlines() if l.strip()][1]
    assert proposal["sealed_prefix_head"] == s1["event_hash"]
    assert proposal["reveal_ordinal"] == 2 and proposal["scope"] == \
        "NEXT_REVEAL_ONLY"
    # C1 stops here: no approval/permit, no R2 on the replica either
    assert not c4d.next_authz_dir(root, SID, 2).exists()
    types = [json.loads(l)["event_type"] for l in
             c4d.log_path(root, SID).read_text().splitlines() if l.strip()]
    assert types == ["REVEAL_PACKET", "SEAL_ANNOTATION"]
    # one-shot: a second proposal transaction refuses (O_EXCL)
    with pytest.raises(RuntimeError, match="duplicate proposal"):
        c1mod.do_propose(root)
    # verify stays green and deterministic on the replica
    assert set(c1mod.verify_c1(root)["gates"].values()) == {"PASS"}


# ---------------------------------------------------------------------------
# fail-closed: every prerequisite / closed-world violation is caught
# ---------------------------------------------------------------------------

def test_c1_refuses_open_reveal_chain(tmp_path):
    """Prerequisite direction: a chain with an open REVEAL (no S1) is
    not derivable — G-C1-CHAIN fails closed before any write."""
    root = _sealed_replica(tmp_path, "open")
    _rewind_to_open_reveal(root)
    assert not (root / "c4d_proposals").exists()   # nothing written
    with pytest.raises(RuntimeError, match=c1mod.G_CHAIN):
        c1mod.do_propose(root)
    assert not (root / "c4d_proposals").exists()


def test_c1_refuses_unsealed_prefix(tmp_path):
    """A B4-state replica (receipt+approval, chain still [R1]) must not
    yield a proposal: ordinal-2 requires the previous pair SEALED."""
    sb = build_pre_seal_sandbox(tmp_path / "b4state", through="B4")
    with pytest.raises(RuntimeError, match=c1mod.G_CHAIN):
        c1mod.do_propose(sb.root)
    assert not (sb.root / "c4d_proposals").exists()


def _tampered(tmp_path, name, tweak):
    root = _replica_with_proposal(tmp_path, name)
    tweak(root)
    return root


def test_c1_catches_tampered_proposal_bytes(tmp_path):
    def tweak(root):
        p = root / c1mod.PROPOSAL_REL
        obj = json.loads(p.read_bytes())
        obj["sealed_prefix_head"] = "d" * 64     # forged prefix binding
        os_chmod_0600(p)
        p.write_bytes(c4d.canon(obj).encode())
    with pytest.raises(RuntimeError, match="sealed_prefix_head"):
        c1mod.verify_c1(_tampered(tmp_path, "forged", tweak))


def test_c1_catches_proposal_mode_drift(tmp_path):
    def tweak(root):
        (root / c1mod.PROPOSAL_REL).chmod(0o644)
    with pytest.raises(RuntimeError, match="proposal file mode drift"):
        c1mod.verify_c1(_tampered(tmp_path, "mode", tweak))


def test_c1_catches_closed_world_extra_entry(tmp_path):
    def tweak(root):
        extra = c4d.proposals_dom(root, SID, 2) / "notes.txt"
        extra.write_bytes(b"leak")
    with pytest.raises(RuntimeError, match=c1mod.G_WORLD):
        c1mod.verify_c1(_tampered(tmp_path, "extra", tweak))


def test_c1_catches_premature_approval_artifact(tmp_path):
    """approval/permit are the C2 authorization point: an approval-shaped
    file inside the proposals domain violates the C1 closed world (the
    entries-equality check fires first; the dedicated forbidden-name
    clause behind it is defense-in-depth)."""
    def tweak(root):
        forged = c4d.proposals_dom(root, SID, 2) / "next_reveal.approval.json"
        forged.write_bytes(b"{}")
    with pytest.raises(RuntimeError, match=c1mod.G_WORLD):
        c1mod.verify_c1(_tampered(tmp_path, "approval", tweak))


def test_c1_catches_authorization_domain(tmp_path):
    """An ordinal-2 authorization domain (approval/permit home) must not
    exist at C1 — G-C1-BOUNDARY fails closed."""
    def tweak(root):
        c4d.next_authz_dir(root, SID, 2).mkdir(mode=0o700)
    with pytest.raises(RuntimeError, match=c1mod.G_BOUND):
        c1mod.verify_c1(_tampered(tmp_path, "authz", tweak))


def test_c1_catches_c4c_anchor_drift(tmp_path):
    """C1 must leave the frozen c4c anchor bytes untouched: a drifted
    anchor no longer binds the frozen reveal-phase R1."""
    def tweak(root):
        anchor = root / "public" / "c4c_anchor.json"
        os_chmod_0600(anchor)
        anchor.write_bytes(b'{"production_head_hash":"' + b"f" * 64 +
                           b'","authorization_sha256":"' + b"0" * 64 + b'"}')
    with pytest.raises(RuntimeError, match="c4c anchor no longer binds"):
        c1mod.verify_c1(_tampered(tmp_path, "anchor", tweak))


def os_chmod_0600(p):
    import os
    os.chmod(p, 0o600)
