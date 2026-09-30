"""CSR-8 B5 real SEAL transaction tests (bridge-executable, i19 contract).

The B5 Freeze Gate's post-state is measured on the live tree by
scripts/csr8_phase_a_machine_audit.py; these tests additionally execute
the REAL transaction end-to-end from a certified pre-B5 state derived in
isolation from the live certified bytes (tests/csr8_preseal_sandbox.py
drives the real handoff/draft/receipt/approval transactions on a chain
copy rewound to the exact committed R1 line):

* positive: pre-commit state measured (SEAL_AUTHORIZED, locked exact
  draft, exact active packet, approval-receipt binding) -> real
  seal_transaction -> the complete Freeze Gate proof (verify_b5) re-measures
  every gate PASS on the result;
* commit-time fail-closed: every pre-commit precondition refusal;
* post-seal fail-closed: tamper of chain / head / seal archive / receipt /
  approval / attempt history / c4d anchor / c4c anchor / public state /
  outcome domain / uncleared workspace;
* once-only: a second seal_transaction on [R1,S1] is refused and every
  durable artifact stays byte-identical.
"""
import hashlib
import json
import shutil
import stat
from pathlib import Path

import pytest

from csr8_preseal_sandbox import build_pre_seal_sandbox

import csr8_phase_c_annotation_seal as c4d
import csr8_phase_b5_real_seal as b5

SID = c4d.REAL_SESSION
REPLICA_GATES = {  # every Freeze Gate item except the live-only sync record
    'trusted_prefix', 'history_unique', 'receipt_snapshot_exact',
    'approval_exact', 'commit_time_receipt', 'persisted_receipt_reread',
    'seal_append_once', 'c2_full_verify', 'semantic_replay',
    'seal_committed', 'c4d_anchor_durable', 'workspace_cleanup',
    'post_seal_final', 'chain_r1_s1', 'head_s1', 'receipt_triple_exact',
    'approval_consumed', 'attempt_history', 'active_workspace_empty',
    'c4d_anchor_exact', 'c4c_anchor_unchanged', 'outcome_untouched',
}


def canon(obj):
    return c4d.canon(obj)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sealed_copy(tmp_path, name="sealed"):
    """Fresh transaction-derived [R1,S1] replica (real B1->B4 + SEAL)."""
    sb = build_pre_seal_sandbox(tmp_path / name, through="B4")
    result = c4d.seal_transaction(sb.root, SID)
    assert result["state"] == "SEALED"
    return sb.root


def _attempt(root):
    return c4d.attempt_dir(root, SID, 1, 1)


def _sealing(root):
    return c4d.sealing_dir(root, SID)


def test_b5_positive_transaction_freeze_gate_all_pass(tmp_path):
    """From the certified pre-state the REAL seal_transaction executes
    once, and the authoritative verify_b5 proof measures every Freeze
    Gate item PASS on the result (live-only public-state sync asserted
    against the real tree below)."""
    sb = build_pre_seal_sandbox(tmp_path, through="B4")
    root = sb.root
    # --- measured pre-commit state (the B5 're-prove before append' set)
    assert c4d.derive_state(root, SID)[0] == "SEAL_AUTHORIZED"
    adir = _attempt(root)
    rbytes = (adir / "receipt.json").read_bytes()
    approval = json.loads((adir / "seal_approval.json").read_bytes())
    assert approval["approved_receipt_sha256"] == sha(rbytes)
    log = c4d.log_path(root, SID)
    r1 = json.loads(log.read_text().splitlines()[0])
    packet = c4d.packet_path(root, SID, r1["payload"]["packet_id"])
    archived_r1 = _sealing(root) / r1["payload"]["bytes_ref"]
    assert packet.read_bytes() == archived_r1.read_bytes()   # active packet exact
    draft = c4d.draft_path(root, SID)
    assert stat.S_IMODE(draft.stat().st_mode) == 0o400       # locked exact draft
    assert draft.read_bytes() == (adir / "draft_snapshot.bin").read_bytes()
    # --- the one allowed SEAL_ANNOTATION append
    result = c4d.seal_transaction(root, SID)
    assert result["state"] == "SEALED"
    # --- complete Freeze Gate proof on the transaction result
    out = b5.verify_b5(root)
    assert out["root_scope"] == "replica"
    assert set(out["gates"]) == REPLICA_GATES
    assert set(out["gates"].values()) == {"PASS"}
    assert out["chain"] == ["REVEAL_PACKET", "SEAL_ANNOTATION"]
    events = [json.loads(l) for l in
              c4d.log_path(root, SID).read_text().splitlines() if l.strip()]
    assert out["head"] == events[1]["event_hash"]
    assert out["receipt_sha256"] == sha((_attempt(root) / "receipt.json").read_bytes())
    # POST_SEAL_FINAL cleaned the active workspace; the audit trail stays
    assert not (c4d.annot_dom(root, SID).exists() and
                any(c4d.annot_dom(root, SID).rglob("*")))
    assert (_attempt(root) / "draft_snapshot.bin").is_file()
    # B5 live proof is superseded once the later C3 append is committed.
    live_events = [json.loads(l) for l in
                   c4d.log_path(c4d.REAL_CSR, SID).read_text().splitlines()
                   if l.strip()]
    if [e["event_type"] for e in live_events] != [
            "REVEAL_PACKET", "SEAL_ANNOTATION"]:
        pytest.skip("B5 live boundary superseded by completed C3")
    # live-tree public production state IS synced (live-only artifact)
    live = b5.verify_b5()
    assert live["gates"]["public_state_synced"] == "PASS"
    assert live["production"] == "REVEAL=1 SEAL=1"


# ---------------------------------------------------------------------------
# commit-time precondition refusals (the transaction re-proves everything
# immediately before the irreversible append)
# ---------------------------------------------------------------------------

def test_b5_refuses_seal_without_approval(tmp_path):
    sb = build_pre_seal_sandbox(tmp_path, through="B3")   # receipt, no approval
    with pytest.raises(RuntimeError, match="SEAL_AUTHORIZED"):
        c4d.seal_transaction(sb.root, SID)


def test_b5_refuses_unlocked_draft(tmp_path):
    sb = build_pre_seal_sandbox(tmp_path, through="B4")
    c4d.draft_path(sb.root, SID).chmod(0o644)
    with pytest.raises(RuntimeError, match="FORENSIC|unlocked draft"):
        c4d.seal_transaction(sb.root, SID)


def test_b5_refuses_drifted_draft_bytes(tmp_path):
    sb = build_pre_seal_sandbox(tmp_path, through="B4")
    p = c4d.draft_path(sb.root, SID)
    p.chmod(0o600)
    p.write_bytes(p.read_bytes() + b"\n")
    p.chmod(0o400)
    with pytest.raises(RuntimeError, match="FORENSIC|draft drift"):
        c4d.seal_transaction(sb.root, SID)


def test_b5_refuses_tampered_active_packet(tmp_path):
    sb = build_pre_seal_sandbox(tmp_path, through="B4")
    log = c4d.log_path(sb.root, SID)
    r1 = json.loads(log.read_text().splitlines()[0])
    packet = c4d.packet_path(sb.root, SID, r1["payload"]["packet_id"])
    packet.chmod(0o600)
    packet.write_bytes(packet.read_bytes() + b" ")
    packet.chmod(0o600)
    with pytest.raises(RuntimeError, match="active packet"):
        c4d.seal_transaction(sb.root, SID)


def test_b5_refuses_receipt_the_approval_does_not_cover(tmp_path):
    """Commit-time exact-byte binding: an approval persisted for OTHER
    receipt bytes must never authorize the append."""
    sb = build_pre_seal_sandbox(tmp_path, through="B4")
    adir = _attempt(sb.root)
    receipt = json.loads((adir / "receipt.json").read_bytes())
    receipt["created_at"] = "2099-01-01T00:00:00Z"      # canonical, different bytes
    (adir / "receipt.json").chmod(0o600)
    (adir / "receipt.json").write_bytes(canon(receipt).encode())
    (adir / "receipt.json").chmod(0o600)
    with pytest.raises(RuntimeError,
                       match="FORENSIC|approved_receipt_sha256 != SHA256|"
                             "does not cover"):
        c4d.seal_transaction(sb.root, SID)


# ---------------------------------------------------------------------------
# post-seal Freeze Gate fail-closed (each tamper must be caught)
# ---------------------------------------------------------------------------

def _tamper_copy(tmp_path, name):
    src = sealed_copy(tmp_path, name + "_src")
    dst = tmp_path / (name + "_t")
    shutil.copytree(src, dst)
    return dst


def test_b5_gate_catches_chain_shape_tamper(tmp_path):
    root = _tamper_copy(tmp_path, "chain")
    log = c4d.log_path(root, SID)
    lines = log.read_text().splitlines()
    ev = json.loads(lines[1])
    ev["event_type"] = "REVEAL_PACKET"                # illegal chain shape
    lines[1] = canon(ev)
    log.write_text("\n".join(lines) + "\n")
    with pytest.raises(RuntimeError, match="chain must be exactly"):
        b5.verify_b5(root)


def test_b5_gate_catches_event_hash_tamper(tmp_path):
    root = _tamper_copy(tmp_path, "evhash")
    log = c4d.log_path(root, SID)
    lines = log.read_text().splitlines()
    ev = json.loads(lines[1])
    ev["payload"]["receipt_sha256"] = ("0" if ev["payload"]["receipt_sha256"][0] != "0"
                                       else "1") + ev["payload"]["receipt_sha256"][1:]
    lines[1] = canon(ev)
    log.write_text("\n".join(lines) + "\n")
    # C2's own hash-chain verify fail-closes (frozen c2 fail -> SystemExit)
    with pytest.raises((RuntimeError, SystemExit)):
        b5.verify_b5(root)


def test_b5_gate_catches_head_tamper(tmp_path):
    root = _tamper_copy(tmp_path, "head")
    head = c4d.head_path(root, SID)
    obj = json.loads(head.read_text())
    obj["head_hash"] = "0" * 64
    head.write_text(canon(obj))
    with pytest.raises((RuntimeError, SystemExit)):  # trusted-head verify
        b5.verify_b5(root)


def test_b5_gate_catches_seal_archive_tamper(tmp_path):
    root = _tamper_copy(tmp_path, "archive")
    lines = c4d.log_path(root, SID).read_text().splitlines()
    s1 = json.loads(lines[1])
    archived = _sealing(root) / s1["payload"]["bytes_ref"]
    archived.write_bytes(archived.read_bytes() + b" ")
    # C2 itself binds the archived bytes into the event hash, so the frozen
    # C2 verify fail-closes first (SystemExit; message on stdout).
    with pytest.raises((RuntimeError, SystemExit)):
        b5.verify_b5(root)


def test_b5_gate_catches_receipt_tamper(tmp_path):
    root = _tamper_copy(tmp_path, "receipt")
    adir = _attempt(root)
    receipt = json.loads((adir / "receipt.json").read_bytes())
    receipt["created_at"] = "2099-01-01T00:00:00Z"
    adir.joinpath("receipt.json").chmod(0o600)
    adir.joinpath("receipt.json").write_bytes(canon(receipt).encode())
    with pytest.raises(RuntimeError,
                       match="receipt triple exact-byte equality|"
                             "not canonical|receipt hash drift"):
        b5.verify_b5(root)


def test_b5_gate_catches_approval_tamper(tmp_path):
    root = _tamper_copy(tmp_path, "approval")
    adir = _attempt(root)
    approval = json.loads((adir / "seal_approval.json").read_bytes())
    approval["approved_receipt_sha256"] = "0" * 64
    adir.joinpath("seal_approval.json").chmod(0o600)
    adir.joinpath("seal_approval.json").write_bytes(canon(approval).encode())
    with pytest.raises(RuntimeError, match="receipt hash drift"):
        b5.verify_b5(root)


def test_b5_gate_catches_attempt_history_hole(tmp_path):
    root = _tamper_copy(tmp_path, "history")
    c4d.attempt_dir(root, SID, 1, 2).mkdir(parents=True)   # stray empty attempt
    with pytest.raises((RuntimeError, FileNotFoundError, SystemExit)):
        b5.verify_b5(root)


def test_b5_gate_catches_c4d_anchor_tamper(tmp_path):
    root = _tamper_copy(tmp_path, "c4danchor")
    anchor = c4d.anchor_path_in(root)
    obj = json.loads(anchor.read_bytes())
    obj["production_head_hash"] = "0" * 64
    anchor.write_bytes(canon(obj).encode())
    with pytest.raises(RuntimeError, match="c4d seal anchor exact binding"):
        b5.verify_b5(root)


def test_b5_gate_catches_c4c_anchor_tamper(tmp_path):
    root = _tamper_copy(tmp_path, "c4canchor")
    anchor = root / "public" / "c4c_anchor.json"
    obj = json.loads(anchor.read_bytes())
    obj["production_head_hash"] = "0" * 64
    anchor.write_bytes(canon(obj).encode())
    with pytest.raises(RuntimeError, match="c4c anchor bytes changed"):
        b5.verify_b5(root)


def test_b5_gate_catches_public_state_desync(tmp_path, monkeypatch):
    live_events = [json.loads(l) for l in
                   c4d.log_path(c4d.REAL_CSR, SID).read_text().splitlines()
                   if l.strip()]
    if [e["event_type"] for e in live_events] != [
            "REVEAL_PACKET", "SEAL_ANNOTATION"]:
        pytest.skip("B5 live boundary superseded by completed C3")
    """The public production-state sync check fail-closes on a drifted
    record.  Measured against a tampered COPY of the public record (the
    live artifact itself is never modified)."""
    pub = Path(c4d.PUBLIC_DIR)
    fake = tmp_path / "c4_public"
    shutil.copytree(pub, fake)
    state_path = fake / "c4d_phase_a_public_state.json"
    state = json.loads(state_path.read_bytes())
    state["production"]["production_head_hash"] = "0" * 64
    state_path.write_bytes(canon(state).encode())
    monkeypatch.setattr(c4d, "PUBLIC_DIR", fake)
    with pytest.raises(RuntimeError,
                       match="public production state is not synced"):
        b5.verify_b5()


def test_b5_gate_catches_outcome_domain_presence(tmp_path):
    root = _tamper_copy(tmp_path, "outcome")
    (root / "production" / SID / "outcome_labels.json").write_text("{}")
    with pytest.raises(RuntimeError, match="outcome domain"):
        b5.verify_b5(root)


def test_b5_gate_catches_uncleaned_workspace(tmp_path):
    root = _tamper_copy(tmp_path, "workspace")
    dom = c4d.annot_dom(root, SID)
    (dom / "packet").mkdir(parents=True)
    (dom / "packet" / "stray.json").write_text("{}")
    with pytest.raises(RuntimeError,
                       match="active annotator workspace not empty"):
        b5.verify_b5(root)


# ---------------------------------------------------------------------------
# once-only / idempotency
# ---------------------------------------------------------------------------

def test_b5_second_seal_refused_and_artifacts_byte_stable(tmp_path):
    root = sealed_copy(tmp_path, "once")
    lines = c4d.log_path(root, SID)
    head = c4d.head_path(root, SID)
    s1 = json.loads(lines.read_text().splitlines()[1])
    archived = _sealing(root) / s1["payload"]["bytes_ref"]
    anchor = c4d.anchor_path_in(root)

    def fingerprint():
        paths = [lines, head, archived, anchor] + \
            sorted(_attempt(root).rglob("*"))
        return [sha(p.read_bytes()) for p in paths]

    before = fingerprint()
    with pytest.raises(RuntimeError, match="chain must end in an open"):
        c4d.seal_transaction(root, SID)
    assert fingerprint() == before
    # the refusal left the state SEALED and the proof still green
    assert c4d.derive_state(root, SID)[0] == "SEALED"
    assert set(b5.verify_b5(root)["gates"].values()) == {"PASS"}
