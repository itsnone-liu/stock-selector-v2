"""CSR-8 C2 NEXT_REVEAL_ONLY approval tests (bridge-executable).

Taskbook §6 C2 as amended v2-unattended-20260930 (run
audit_20260930021152297, stage C2): the ordinal-2 approval is persisted
under the unattended policy and machine-measured.

Measured here, on real transaction paths (no fixture snapshots):

* three-way exact-bytes consistency: proposal exact bytes == approved
  hash == permit exact bytes (frozen builder re-proof on live tree and
  re-executed end-to-end on a transaction-derived sealed replica);
* unattended-policy record: closed-world schema, canonical bytes, 0600,
  approved_by=UNATTENDED_POLICY, binding=EXACT, scope=NEXT_REVEAL_ONLY,
  wording/field hash character-identical to the approved proposal hash;
* boundary: authorization stays UNUSED (no R2 append — C3 point), the
  authorization domain is closed-world (exactly approval+permit), no
  authorization expansion;
* fail-closed: every binding/closed-world drift on tampered replicas is
  caught by the exact C2 gate.
"""
import hashlib
import json
import stat
from pathlib import Path

import pytest

from csr8_preseal_sandbox import build_pre_seal_sandbox  # noqa: F401 (sys.path)

import csr8_phase_c_annotation_seal as c4d
import csr8_phase_c1_ordinal2_proposal as c1mod
import csr8_phase_c2_next_reveal_approval as c2mod

SID = c4d.REAL_SESSION
GATES = {
    c2mod.G_STATE, c2mod.G_PROP, c2mod.G_APPR, c2mod.G_PERM,
    c2mod.G_THREE, c2mod.G_UNUSED, c2mod.G_REC, c2mod.G_WORLD,
}
AD_LIVE = c4d.next_authz_dir(c4d.REAL_CSR, SID, 2)


def _approved_replica(tmp_path, name="approved"):
    """Sealed [R1,S1] replica -> real C1 proposal -> real C2 approval,
    with the run-side record persisted inside tmp (not the repo)."""
    from csr8_preseal_sandbox import build_pre_seal_sandbox as _bps
    sb = _bps(tmp_path / name, through="B4")
    assert c4d.seal_transaction(sb.root, SID)["state"] == "SEALED"
    out = c1mod.do_propose(sb.root)
    assert out["c1"] == "PROPOSAL_PERSISTED"
    record = tmp_path / f"{name}_record.json"
    out2 = c2mod.do_approve(sb.root, record)
    assert out2["c2"] == "APPROVAL_PERSISTED"
    return sb.root, record


def _tampered(tmp_path, name, tweak):
    root, record = _approved_replica(tmp_path, name)
    tweak(root, record)
    return root, record


# ---------------------------------------------------------------------------
# live tree — the authoritative C2 post-state
# ---------------------------------------------------------------------------

def test_c2_live_gates_all_pass_three_way_exact():
    result = c2mod.verify_c2()
    assert result["root_scope"] == "live"
    assert set(result["gates"]) == GATES
    assert set(result["gates"].values()) == {"PASS"}
    assert result["approved_by"] == "UNATTENDED_POLICY"
    assert result["scope"] == "NEXT_REVEAL_ONLY"
    assert result["reveal_ordinal"] == 2
    assert result["consumption"] == "UNUSED"
    # three-way consistency measured from persisted bytes directly
    pbytes = (Path(c4d.REAL_CSR) / c1mod.PROPOSAL_REL).read_bytes()
    psha = hashlib.sha256(pbytes).hexdigest()
    approval = json.loads((AD_LIVE / "next_reveal.approval.json")
                          .read_bytes())
    permit = (AD_LIVE / "next_reveal.permit.json").read_bytes()
    assert permit == pbytes
    assert approval["approved_authorization_sha256"] == psha
    assert result["approved_proposal_sha256"] == psha
    assert result["authorized_permit_sha256"] == psha
    assert result["authorized_artifact_sha256"] == hashlib.sha256(
        (AD_LIVE / "next_reveal.approval.json").read_bytes()).hexdigest()
    # disclosure: verify surface carries no candidate identity
    blob = json.dumps(result)
    for forbidden in ("opaque_case_id", "packet_id", "case_key"):
        assert forbidden not in blob
    # deterministic re-measurement
    assert c2mod.verify_c2() == result


def test_c2_live_record_binds_exact_hash_and_policy():
    rec = json.loads(c2mod.UNATTENDED_RECORD.read_bytes())
    pbytes = (Path(c4d.REAL_CSR) / c1mod.PROPOSAL_REL).read_bytes()
    psha = hashlib.sha256(pbytes).hexdigest()
    assert set(rec) == c2mod.RECORD_KEYS
    assert c4d.canon(rec).encode() == c2mod.UNATTENDED_RECORD.read_bytes()
    assert stat.S_IMODE(c2mod.UNATTENDED_RECORD.lstat().st_mode) == 0o600
    assert rec["approved_by"] == rec["policy"] == "UNATTENDED_POLICY"
    assert rec["binding"] == ["EXACT"]
    assert rec["scope"] == "NEXT_REVEAL_ONLY"
    assert rec["run_id"] == "audit_20260930021152297"
    assert rec["host_id"] == "RainYun-c438TDGn"
    assert rec["stage"] == "C2" and rec["iteration"] == 1
    assert rec["approved_proposal_sha256"] == psha
    # wording-embedded hash is character-identical
    assert c2mod.parse_wording_hash(rec["taskbook_wording"]) == psha
    assert rec["authorized_permit_sha256"] == psha
    assert rec["sealed_prefix_head"] == c4d._current_prefix_head(
        c4d.REAL_CSR, SID)


def test_c2_do_approve_is_one_shot_on_live():
    """Re-running the real transaction refuses (O_EXCL) before any write
    and the persisted artifacts stay byte-identical."""
    before = [(AD_LIVE / n).read_bytes() for n in
              ("next_reveal.approval.json", "next_reveal.permit.json")]
    rec_before = c2mod.UNATTENDED_RECORD.read_bytes()
    with pytest.raises(RuntimeError, match="immutable O_EXCL artifact"):
        c2mod.do_approve()
    assert [(AD_LIVE / n).read_bytes() for n in
            ("next_reveal.approval.json", "next_reveal.permit.json")] == before
    assert c2mod.UNATTENDED_RECORD.read_bytes() == rec_before
    assert set(c2mod.verify_c2()["gates"].values()) == {"PASS"}


def test_c2_live_boundary_no_r2_no_expansion():
    """C2 stops at approval+permit: no R2 append, chain exactly [R1,S1],
    and the C1 stage gate still verifies its (stage-aware) boundary."""
    events = [json.loads(l) for l in
              (c4d.REAL_PRODUCTION / SID / "sealing" / "sealing_log.jsonl")
              .read_text().splitlines() if l.strip()]
    assert [e["event_type"] for e in events] == \
        ["REVEAL_PACKET", "SEAL_ANNOTATION"]
    assert set(c1mod.verify_c1()["gates"].values()) == {"PASS"}


# ---------------------------------------------------------------------------
# real transaction on a sealed replica — the approval is re-executed
# ---------------------------------------------------------------------------

def test_c2_real_transaction_on_sealed_replica(tmp_path):
    root, record = _approved_replica(tmp_path)
    ad = c4d.next_authz_dir(root, SID, 2)
    # full frozen re-proof of the whole authorization chain
    c4d.verify_next_authorization_chain(root, SID, 2)
    # persisted shapes: canonical, 0600, domain 0700
    for name in ("next_reveal.approval.json", "next_reveal.permit.json"):
        p = ad / name
        assert stat.S_IMODE(p.lstat().st_mode) == 0o600
        obj = json.loads(p.read_bytes())
        assert c4d.canon(obj).encode() == p.read_bytes()
    for d in (c4d.prod_dir(root, SID) / "authorization", ad):
        assert stat.S_IMODE(d.lstat().st_mode) == 0o700
    # replica verify with its own record path stays green
    out = c2mod.verify_c2(root, record)
    assert out["root_scope"] == "replica"
    assert set(out["gates"].values()) == {"PASS"}
    # one-shot: a second transaction on the same state refuses
    with pytest.raises(RuntimeError, match="immutable O_EXCL artifact"):
        c2mod.do_approve(root, record)


# ---------------------------------------------------------------------------
# fail-closed: every binding / closed-world drift is caught
# ---------------------------------------------------------------------------

def test_c2_catches_approval_hash_drift(tmp_path):
    def tweak(root, record):
        p = c4d.next_authz_dir(root, SID, 2) / "next_reveal.approval.json"
        obj = json.loads(p.read_bytes())
        obj["approved_authorization_sha256"] = "e" * 64
        import os
        os.chmod(p, 0o600)
        p.write_bytes(c4d.canon(obj).encode())
    with pytest.raises(RuntimeError,
                       match="does not bind the exact proposal bytes"):
        c2mod.verify_c2(*_tampered(tmp_path, "apprdrift", tweak))


def test_c2_catches_permit_bytes_drift(tmp_path):
    def tweak(root, record):
        p = c4d.next_authz_dir(root, SID, 2) / "next_reveal.permit.json"
        import os
        os.chmod(p, 0o600)
        p.write_bytes(b"{}")
    with pytest.raises(RuntimeError,
                       match="permit bytes != proposal bytes"):
        c2mod.verify_c2(*_tampered(tmp_path, "permitdrift", tweak))


def test_c2_catches_approval_mode_drift(tmp_path):
    def tweak(root, record):
        (c4d.next_authz_dir(root, SID, 2) /
         "next_reveal.approval.json").chmod(0o644)
    with pytest.raises(RuntimeError,
                       match="authorization file mode drift"):
        c2mod.verify_c2(*_tampered(tmp_path, "apprmode", tweak))


def test_c2_catches_record_wording_hash_drift(tmp_path):
    def tweak(root, record):
        rb = json.loads(record.read_bytes())
        rb["taskbook_wording"] = c2mod.fixed_wording("f" * 64)
        import os
        os.chmod(record, 0o600)
        record.write_bytes(c4d.canon(rb).encode())
    with pytest.raises(RuntimeError, match=c2mod.G_REC):
        c2mod.verify_c2(*_tampered(tmp_path, "worddrift", tweak))


def test_c2_catches_record_policy_drift(tmp_path):
    def tweak(root, record):
        rb = json.loads(record.read_bytes())
        rb["approved_by"] = rb["policy"] = "HUMAN_INLINE"
        import os
        os.chmod(record, 0o600)
        record.write_bytes(c4d.canon(rb).encode())
    with pytest.raises(RuntimeError,
                       match="approved_by/policy must be UNATTENDED_POLICY"):
        c2mod.verify_c2(*_tampered(tmp_path, "policydrift", tweak))


def test_c2_catches_record_scope_expansion(tmp_path):
    def tweak(root, record):
        rb = json.loads(record.read_bytes())
        rb["scope"] = "SEAL_AND_REVEAL"          # authorization expansion
        import os
        os.chmod(record, 0o600)
        record.write_bytes(c4d.canon(rb).encode())
    with pytest.raises(RuntimeError,
                       match="scope must be NEXT_REVEAL_ONLY"):
        c2mod.verify_c2(*_tampered(tmp_path, "scopedrift", tweak))


def test_c2_catches_missing_record(tmp_path):
    def tweak(root, record):
        record.unlink()
    with pytest.raises(RuntimeError, match="record absent"):
        c2mod.verify_c2(*_tampered(tmp_path, "norecord", tweak))


def test_c2_catches_authorization_domain_extra_entry(tmp_path):
    def tweak(root, record):
        (c4d.next_authz_dir(root, SID, 2) / "extra.txt").write_bytes(b"x")
    # caught defense-in-depth: the C1 boundary re-proof wraps the frozen
    # authorization-chain check, then C2's own closed-world gate
    with pytest.raises(RuntimeError,
                       match="not the exact C2 pair"):
        c2mod.verify_c2(*_tampered(tmp_path, "extra", tweak))


def test_c2_bound_object_is_proposal_not_receipt():
    """Iteration-2 interpretation ruling, pinned machine-side: the v2
    amendment's 'session / reveal / attempt exact receipt bytes' /
    'receipt_sha256' wording is a §5-B4 template carryover. C2 binds the
    ordinal-2 PROPOSAL exact bytes (approved_proposal_sha256); a
    receipt/attempt binding is semantically impossible at C2 because the
    cycle-2 receipt/attempt artifacts are created at the C4 stage."""
    # (1) no cycle-2 receipt/attempt domain exists at the C2 boundary
    receipts = c4d.REAL_CSR / "c4d_receipts" / SID
    assert sorted(p.name for p in receipts.iterdir()) == ["ordinal-0001"]
    assert not (receipts / "ordinal-0002").exists()
    # (2) neither persisted schema carries any receipt/attempt field
    assert not (c4d.REVEAL_APPROVAL_KEYS &
                {"receipt_sha256", "attempt", "attempt_id",
                 "approved_receipt_sha256"})
    assert not (c2mod.RECORD_KEYS &
                {"receipt_sha256", "attempt", "attempt_id",
                 "approved_receipt_sha256"})
    rec = json.loads(c2mod.UNATTENDED_RECORD.read_bytes())
    blob = json.dumps(rec)
    assert "receipt" not in blob and "attempt" not in blob
    # (3) the single bound object is the proposal exact bytes, and the
    # chain-side approval binds the same hash
    pbytes = (Path(c4d.REAL_CSR) / c1mod.PROPOSAL_REL).read_bytes()
    psha = hashlib.sha256(pbytes).hexdigest()
    approval = json.loads((AD_LIVE / "next_reveal.approval.json")
                          .read_bytes())
    permit = (AD_LIVE / "next_reveal.permit.json").read_bytes()
    assert rec["approved_proposal_sha256"] == psha
    assert approval["approved_authorization_sha256"] == psha
    assert permit == pbytes
    assert c2mod.parse_wording_hash(rec["taskbook_wording"]) == psha
