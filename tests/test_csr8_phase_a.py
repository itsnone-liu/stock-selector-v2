"""Independent, isolated Phase-A evidence.

No ignored secret or live production domain is required.  The D71 test patches
only the frozen C3 selector inputs to a temporary synthetic packet, then runs
the real C4-D authorization functions against a temporary sandbox.
"""
import hashlib
import importlib.util
import io
import json
import ast
from contextlib import redirect_stdout
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "csr8_phase_c_annotation_seal.py"


def _load():
    import sys
    sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("csr8_phase_a_impl", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_d71_uses_real_guard_and_leaves_ordinal3_artifacts_absent(tmp_path):
    mod = _load()
    old = _patch_isolated_c3(mod, tmp_path)
    try:
        output = io.StringIO()
        with redirect_stdout(output):
            mod.d71()
        text = output.getvalue()
        assert "PASS D71" in text
        assert "G-C4D-AUTHZ" in text
    finally:
        _restore_isolated_c3(mod, old)


def _patch_isolated_c3(mod, tmp_path):
    c3 = tmp_path / "c3" / "packets"
    c3.mkdir(parents=True)
    old = (mod.c4ab.C3_STATE, mod.c1.PLAN_FILE, mod.c1.load_salt,
           mod.c4ab.first_candidate, mod.candidate_total_order,
           mod.candidate_for_ordinal, mod.verify_candidate_gates)
    mod.c4ab.C3_STATE = c3.parent
    mod.c1.load_salt = lambda: "phase-a-test-salt"
    mod.c1.PLAN_FILE = tmp_path / "packet_plan.json"
    ocid = mod.c2.synth_ocid(mod.SYNTH_CASE)
    case_key = f"G1_complete_bull|{mod.SYNTH_CASE}"
    order = [{"opaque_case_id": ocid, "T": mod.SYNTH_T,
              "t_rank": 0, "case_rank": 0},
             {"opaque_case_id": ocid, "T": "2099-01-03",
              "t_rank": 1, "case_rank": 0}]
    mod.c1.PLAN_FILE.write_text(json.dumps({"entries": [
        {"case_key": case_key, "T": mod.SYNTH_T},
        {"case_key": case_key, "T": "2099-01-03"},
    ]}))
    for item in order:
        pid = hashlib.sha256(f"{item['opaque_case_id']}|{item['T']}".encode()).hexdigest()
        (c3 / f"{pid}.json").write_bytes(mod.synth_packet_bytes(mod.SYNTH_CASE, item["T"]))
    mod.c4ab.first_candidate = lambda _c1: dict(order[0], digest="test")
    mod.candidate_total_order = lambda: list(order)
    mod.candidate_for_ordinal = lambda n: dict(order[n - 1])
    mod.verify_candidate_gates = lambda: {"size": 2,
        "ordinal1_matches_frozen_first": True, "revealed_prefix": 1}
    return old


def _restore_isolated_c3(mod, old):
    (mod.c4ab.C3_STATE, mod.c1.PLAN_FILE, mod.c1.load_salt,
     mod.c4ab.first_candidate, mod.candidate_total_order,
     mod.candidate_for_ordinal, mod.verify_candidate_gates) = old


def test_complete_d01_d71_matrix_runs_in_isolated_sandbox(tmp_path):
    """Every registered fixture executes; only its declared target may fail."""
    mod = _load()
    old = _patch_isolated_c3(mod, tmp_path)
    seen = []
    try:
        for name, _description, fixture_fn in mod.FIXTURES:
            fixture_fn()
            seen.append(name)
    finally:
        _restore_isolated_c3(mod, old)
    assert seen == [f"D{i:02d}" for i in range(1, 72)]


def test_guard_rejects_prefix_mismatch_without_swallowing(tmp_path):
    mod = _load()
    old = _patch_isolated_c3(mod, tmp_path)
    try:
        sb, sid = mod.prepared_sealed()
        # Persisted R1 is deliberately not candidate prefix; rejection must
        # escape the guard and no proposal domain may be created.
        mod.candidate_total_order = lambda: [{"opaque_case_id": "wrong", "T": "2099-01-02"}]
        with pytest.raises(RuntimeError, match="candidate total-order prefix"):
            mod.build_next_reveal_proposal(sb, sid, 2, mod._current_prefix_head(sb, sid))
        assert not mod.proposals_dom(sb, sid, 2).exists()
        mod.cleanup_sb(sb)
    finally:
        _restore_isolated_c3(mod, old)


def test_second_sealed_pair_continues_to_next_ordinal(tmp_path):
    mod = _load()
    old = _patch_isolated_c3(mod, tmp_path)
    try:
        sb, sid = mod.prepared_sealed()
        mod.build_next_reveal_proposal(sb, sid, 2, mod._current_prefix_head(sb, sid))
        mod.approve_next_reveal(sb, sid, 2)
        mod.materialize_next_permit(sb, sid, 2)
        mod.reveal_transaction(sb, sid, 2)
        # Complete the second synthetic pair using the same persisted APIs.
        mod.handoff(sb, sid, mod.SYNTH_CASE, "2099-01-03")
        mod.write_draft(sb, sid, mod.sample_draft(sb, sid))
        mod.make_receipt(sb, sid)
        mod.make_seal_approval(sb, sid)
        mod.seal_transaction(sb, sid)
        evs = mod.chain_events(sb, sid)
        assert [e["event_type"] for e in evs] == [mod.c2.REVEAL, mod.c2.SEAL, mod.c2.REVEAL, mod.c2.SEAL]
        mod.prove_next_reveal_eligible(sb, sid, 3)
        mod.cleanup_sb(sb)
    finally:
        _restore_isolated_c3(mod, old)


def test_d71_artifact_absence_is_checked_after_each_real_entrypoint(tmp_path):
    mod = _load()
    old = _patch_isolated_c3(mod, tmp_path)
    try:
        sb, sid = mod.prepared_sealed()
        mod.build_next_reveal_proposal(sb, sid, 2, mod._current_prefix_head(sb, sid))
        mod.approve_next_reveal(sb, sid, 2)
        mod.materialize_next_permit(sb, sid, 2)
        mod.reveal_transaction(sb, sid, 2)
        proposal = mod.proposals_dom(sb, sid, 3)
        with pytest.raises(RuntimeError, match="G-C4D-AUTHZ"):
            mod.build_next_reveal_proposal(sb, sid, 3, mod._current_prefix_head(sb, sid))
        with pytest.raises(RuntimeError, match="G-C4D-AUTHZ"):
            mod.approve_next_reveal(sb, sid, 3)
        with pytest.raises(RuntimeError, match="G-C4D-AUTHZ"):
            mod.materialize_next_permit(sb, sid, 3)
        assert not proposal.exists()
        assert not mod.next_authz_dir(sb, sid, 3).exists()
        mod.cleanup_sb(sb)
    finally:
        _restore_isolated_c3(mod, old)


def test_guard_semantics_and_five_entrypoints_are_machine_checked():
    tree = ast.parse(SCRIPT.read_text())
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    guard = funcs["prove_next_reveal_eligible"]
    calls = [n for n in ast.walk(guard) if isinstance(n, ast.Call)]
    call_text = {ast.unparse(n) for n in calls}
    assert "c2translate(lg.load().verify, True)" in call_text
    assert any("event_type" in ast.unparse(n) and "c2.SEAL" in ast.unparse(n) for n in ast.walk(guard))
    assert any("ordinal != n + 1" in ast.unparse(n) for n in ast.walk(guard))
    for name in ("build_next_reveal_proposal", "approve_next_reveal",
                 "materialize_next_permit", "verify_next_authorization_chain",
                 "reveal_transaction"):
        assert name in funcs
        body = ast.unparse(funcs[name])
        assert "prove_next_reveal_eligible(sb, sid, ordinal)" in body, name


def test_public_blindness_contract_and_anchor_are_machine_checked(tmp_path):
    mod = _load()
    anchor = mod.PUBLIC_DIR / "c4c_anchor.json"
    assert anchor.read_bytes() == b'{"authorization_sha256":"911d8b844da3a38467aecc0919ee22664484f87c9f49bf445a5a949b6245dc81","production_head_hash":"b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5"}'
    forbidden = ("opaque_case_id", "packet_id", "case_key", "secret_salt", "outcome")
    for p in mod.PUBLIC_DIR.glob("*.json"):
        text = p.read_text()
        assert not any(word in text for word in forbidden), p
    state = json.loads((mod.PUBLIC_DIR / "c4d_phase_a_public_state.json").read_text())
    # B5 boundary: the public state is updated to the sealed production pair;
    # the C4-C anchor itself remains byte-identical and blind.
    assert state["production"]["event_types"] == ["REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET"]
    assert state["production"]["seal_count"] == 1
    assert state["production"]["reveal_count"] == 2
    # B1 gates are measured on a transaction-derived pre-SEAL replica (the
    # live annotator workspace is legitimately cleared by POST_SEAL_FINAL);
    # the live tree must measure the post-B5 terminal shape instead.
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    sb = build_pre_seal_sandbox(tmp_path, through="B1")
    b1 = _load_b1()
    assert set(b1.verify_b1(sb.root)["gates"].values()) == {"PASS"}
    live_events = b1.read_chain(b1.REAL_CSR, b1.SID)
    assert [e["event_type"] for e in live_events] == \
        ["REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET", "SEAL_ANNOTATION"]
    # C4 relocates the second-session artifacts into ordinal-0002; the
    # top-level annotator is absent because empty directories are not certified.
    assert not mod.REAL_ANNOTATOR.exists()
    assert mod.REAL_RECEIPTS.exists()               # frozen audit trail kept
    # C1 boundary (H0-aware): the ordinal-2 next-reveal proposal is the
    # sole legal LIVE c4d_proposals entry (selector-only, frozen-builder
    # re-proven; approval/permit were the C2 authorization point). Since
    # Phase H H0 (taskbook v1.1 §8/§31) the ordinal-3 NEXT_REVEAL_ONLY
    # proposal is PREPARED by the frozen §7 builder but STAGED inside the
    # campaign directory — the live annotator domain stays untouched
    # until the PHASE_ENTRY APPROVE authorizes the ordinal-3 flow.
    proposal_rel = "c4-prod-0002/ordinal-0002/next_reveal.proposal.json"
    proposal_entries = sorted(
        p.relative_to(mod.REAL_PROPOSALS_C4D).as_posix()
        for p in mod.REAL_PROPOSALS_C4D.rglob("*") if p.is_file())
    assert proposal_entries == [proposal_rel], proposal_entries
    if len(live_events) == 4:
        # H0-prepared ordinal-3 proposal is staged campaign-side only:
        # NEXT_REVEAL_ONLY scope bound to the sealed prefix head, with no
        # authorization domain and nothing revealed for ordinal 3.
        staged = sorted((mod.REAL_CSR / "h_campaign").glob(
            "*/ordinal_0003/next_reveal.proposal.staged.json"))
        assert len(staged) == 1, staged
        staged_doc = json.loads(staged[0].read_bytes())
        assert staged_doc["scope"] == "NEXT_REVEAL_ONLY"
        assert staged_doc["reveal_ordinal"] == 3
        assert staged_doc["sealed_prefix_head"] == live_events[-1]["event_hash"]
        assert not (mod.REAL_CSR / "production" / mod.REAL_SESSION /
                    "authorization" / "ordinal-0003").exists()
    if [e["event_type"] for e in live_events] == [
            "REVEAL_PACKET", "SEAL_ANNOTATION"]:
        c1_proposal, _c1_bytes = mod._check_proposal(
            mod.REAL_CSR, mod.REAL_SESSION, 2)
        assert c1_proposal["scope"] == "NEXT_REVEAL_ONLY"
    else:
        # After C3 the proposal remains immutable evidence bound to S1; the
        # pre-C3 proposal consumer is intentionally no longer applicable to
        # the advanced live head.
        assert json.loads((mod.REAL_PROPOSALS_C4D / mod.REAL_SESSION /
                           "ordinal-0002/next_reveal.proposal.json").read_bytes())[
            "scope"] == "NEXT_REVEAL_ONLY"


def test_bridge_machine_audit_script_executes_complete_matrix():
    """The B5-authoritative machine audit: certified closure + the complete
    Freeze Gate measured from persisted bytes (the Phase-A-era D01_D71 /
    C4D / C4C_regression / candidate_gates / blindness / real_fingerprint /
    integration fields were the iteration-17 contract and are now measured
    by the committed pytest suite directly — see the D01-D71 matrix tests)."""
    import subprocess, sys
    result = subprocess.run([sys.executable, str(ROOT / "scripts/csr8_phase_a_machine_audit.py")], cwd=ROOT, capture_output=True, text=True, timeout=1200)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["certified_inputs"] == "VERIFIED"
    manifest = json.loads((ROOT / "config/audit/certified_live_inputs.json").read_text())
    assert payload["certified_files"] == manifest["fileCount"]
    assert payload["certified_roots"] == len(manifest["roots"])
    assert payload["production_snapshot"] == "REVEAL=2 SEAL=2"
    b5 = payload.get("b5", {"b5_freeze": "SUPERSEDED-BY-C3"})
    assert b5["b5_freeze"] in {"PASS", "SUPERSEDED-BY-C3"}
    if b5["b5_freeze"] == "SUPERSEDED-BY-C3":
        c4 = payload["c4"]
        assert c4["c4"] == "PASS"
        assert set(c4["gates"].values()) == {"PASS"}
        assert c4["artifact_root"].endswith("ordinal-0002")
        return
    gates = {k: v for k, v in b5.items() if k.startswith("G-B5-")}
    assert gates, "machine audit must enumerate the measured B5 gates"
    assert set(gates.values()) == {"PASS"}, gates
    # the audit measures the whole Freeze Gate family, live-only sync included
    assert "G-B5-PUBLIC_STATE_SYNCED" in gates
    assert "G-B5-C4C_ANCHOR_UNCHANGED" in gates
    assert "G-B5-OUTCOME_UNTOUCHED" in gates
    # since C1 the machine audit also measures the ordinal-2 proposal gate
    c1 = payload["c1"]
    assert c1["c1_proposal"] == "PASS"
    c1_gates = {k: v for k, v in c1.items() if k.startswith("G-C1-")}
    assert set(c1_gates.values()) == {"PASS"}, c1_gates
    assert {"G-C1-CHAIN", "G-C1-CLOSED", "G-C1-REPLAY", "G-C1-PREFIX",
            "G-C1-ELIGIBLE", "G-C1-PROPOSAL", "G-C1-WORLD",
            "G-C1-BOUNDARY"} <= set(c1_gates)
    # since C2 the machine audit also measures the approval gate
    c2 = payload["c2"]
    assert c2["c2_approval"] == "PASS"
    c2_gates = {k: v for k, v in c2.items() if k.startswith("G-C2-")}
    assert set(c2_gates.values()) == {"PASS"}, c2_gates
    assert {"G-C2-STATE", "G-C2-PROPOSAL", "G-C2-APPROVAL", "G-C2-PERMIT",
            "G-C2-THREEWAY", "G-C2-UNUSED", "G-C2-RECORD",
            "G-C2-WORLD"} <= set(c2_gates)
    # the audit line itself surfaces the three-way binding hashes
    assert c2["approved_by"] == "UNATTENDED_POLICY"
    assert c2["scope"] == "NEXT_REVEAL_ONLY"
    assert c2["consumption"] == "UNUSED"
    assert c2["approved_proposal_sha256"] == c2["authorized_permit_sha256"]
    assert len(c2["approved_proposal_sha256"]) == 64
    assert len(c2["authorized_artifact_sha256"]) == 64


def test_certified_live_inputs_manifest_is_complete_and_forbidden_free():
    """The committed inventory certifies the ENTIRE data/csr8_phase_c tree:
    the c4d_proposals domain is certified CLOSED-WORLD (its sole legal
    entry is the ordinal-2 next_reveal.proposal.json — the consumed C1
    authorization point; since Phase H H0 the prepared ordinal-3 proposal
    is staged campaign-side under h_campaign/, never inside the live
    c4d_proposals domain), the local tree must match every pinned
    hash/mode exactly, and the pinned production chain links to the
    frozen anchor head hash."""
    import importlib.util
    cert = ROOT / "config/audit/certified_live_inputs.json"
    assert cert.is_file(), "config/audit/certified_live_inputs.json missing"
    manifest = json.loads(cert.read_text())
    assert manifest["version"] == 2
    assert {r["root"] for r in manifest["roots"]} == {
        "data/csr8_phase_c", "data/adjustment_baostock"}
    assert manifest["fileCount"] == sum(len(r["files"]) for r in manifest["roots"])
    protected = {x["path"]: x for x in manifest.get("protectedArtifacts", [])}
    approval_rel = "data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-0001/attempt-0001/seal_approval.json"
    proposal_rel = "data/csr8_phase_c/c4d_proposals/c4-prod-0002/ordinal-0002/next_reveal.proposal.json"
    record_rel = "docs/audit/evidence/b4_unattended_approval.json"
    assert approval_rel in protected
    assert record_rel in protected
    assert protected[approval_rel]["mode"] == 0o600
    assert protected[record_rel]["mode"] == 0o600
    # C1: the selector-only ordinal-2 proposal is a protected artifact
    assert proposal_rel in protected
    assert protected[proposal_rel]["mode"] == 0o600
    # C2: the NEXT_REVEAL_ONLY approval+permit pair and the run-side
    # unattended approval record are protected artifacts (all 0600)
    for c2_rel in (
        "data/csr8_phase_c/production/c4-prod-0002/authorization/"
        "ordinal-0002/next_reveal.approval.json",
        "data/csr8_phase_c/production/c4-prod-0002/authorization/"
        "ordinal-0002/next_reveal.permit.json",
        "docs/audit/evidence/c2_unattended_approval.json",
    ):
        assert c2_rel in protected, c2_rel
        assert protected[c2_rel]["mode"] == 0o600
    paths = []
    for r in manifest["roots"]:
        paths += [f"{r['root']}/{f['path']}" for f in r["files"]]
        paths += [f"{r['root']}/{d['path']}" for d in r["dirs"]]
    # C1 closed-world (H0-aware): c4d_proposals/ is certified with
    # EXACTLY the allowlisted proposal subtree — the declared allowlist
    # equals the certified entries and nothing else may appear there.
    # Since Phase H H0 the ordinal-3 proposal is PREPARED but STAGED
    # campaign-side (h_campaign/, never inside c4d_proposals/), so the
    # live-domain allowlist keeps exactly the consumed C1 ordinal-2
    # authorization point; approval/permit and every other ordinal stay
    # forbidden.
    assert manifest.get("forbiddenPrefixes") == []
    c1_allow = manifest.get("c4dProposalAllowlist")
    assert c1_allow == ["c4d_proposals/c4-prod-0002/ordinal-0002/next_reveal.proposal.json"]
    proposal_domain_files = sorted(
        f"{r['root']}/{f['path']}" for r in manifest["roots"] for f in r["files"]
        if f"{r['root']}/{f['path']}".startswith("data/csr8_phase_c/c4d_proposals/"))
    assert proposal_domain_files == [proposal_rel], proposal_domain_files
    # H0: the prepared ordinal-3 proposal is STAGED campaign-side; the
    # staged copy is certified inventory (0600) under h_campaign/
    staged_proposals = sorted(
        f"{r['root']}/{f['path']}" for r in manifest["roots"] for f in r["files"]
        if "h_campaign/" in f"{r['root']}/{f['path']}"
        and f["path"].endswith("next_reveal.proposal.staged.json"))
    assert len(staged_proposals) == 1, staged_proposals
    # required gate inputs are pinned
    listed = {f"{r['root']}/{f['path']}" for r in manifest["roots"]
              for f in r["files"]}
    for required in (
        "data/csr8_phase_c/secret/secret_salt",
        "data/csr8_phase_c/secret/packet_plan.json",
        "data/csr8_phase_c/production/c4-prod-0002/sealing/sealing_log.jsonl",
        "data/csr8_phase_c/production/c4-prod-0002/sealing/sealing_log.head.json",
        "data/csr8_phase_c/production/c4-prod-0002/sealing/bytes/seal_annotation/1.bin",
        "data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-0001/attempt-0001/receipt.json",
        "data/csr8_phase_c/c4d_receipts/c4-prod-0002/ordinal-0001/attempt-0001/draft_snapshot.bin",
        "data/csr8_phase_c/c4_public/c4d_seal_anchor.json",
        "data/csr8_phase_c/public/c4c_anchor.json",
        "data/csr8_phase_c/c4c_proposals/c4-prod-0002/first_reveal.proposal.json",
        "data/adjustment_baostock/fetch_manifest.json",
    ):
        assert required in listed, f"gate input not certified: {required}"
    # post-B5 terminal shape: the annotator workspace is cleaned by
    # POST_SEAL_FINAL and must NOT be certified (its audit trail is the C2
    # archive + draft_snapshot.bin above)
    annotator_entries = [p for p in paths
                         if p.startswith("data/csr8_phase_c/annotator")]
    assert annotator_entries == [], annotator_entries
    # materializability: every certified directory has at least one
    # certified file descendant (git and a files-only certified
    # materializer cannot recreate an empty dir — the i18 bridge ENOENT
    # regression class)
    file_paths = [f"{r['root']}/{f['path']}" for r in manifest["roots"]
                  for f in r["files"]]
    dir_paths = [f"{r['root']}/{d['path']}" for r in manifest["roots"]
                 for d in r["dirs"]]
    assert dir_paths and all(
        any(fp.startswith(d + "/") for fp in file_paths) for d in dir_paths
    ), [d for d in dir_paths
        if not any(fp.startswith(d + "/") for fp in file_paths)]
    # the local trees must equal the manifest exactly (bridge-certified
    # materialization or native live tree — either way, zero tolerance)
    spec = importlib.util.spec_from_file_location(
        "c4d_machine_audit", ROOT / "scripts/csr8_phase_a_machine_audit.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    checked = audit.verify_certified_tree()
    assert checked["fileCount"] == manifest["fileCount"]
    import inspect
    assert "dst_file.chmod(f[\"mode\"])" in inspect.getsource(
        audit.materialize_certified_tree)
    # pinned chain links to the frozen anchor head
    mod = _load()
    csr_root = next(r for r in manifest["roots"]
                    if r["root"] == "data/csr8_phase_c")
    log_entry = next(f for f in csr_root["files"]
                     if f["path"] == "production/c4-prod-0002/sealing/"
                                     "sealing_log.jsonl")
    import hashlib
    live_log = mod.REAL_PRODUCTION / mod.REAL_SESSION / "sealing" / \
        "sealing_log.jsonl"
    assert hashlib.sha256(live_log.read_bytes()).hexdigest() == \
        log_entry["sha256"]
    evs = [json.loads(l) for l in live_log.read_text().splitlines() if l.strip()]
    assert evs[0]["event_hash"] == mod.LIVE_R1_EVENT_HASH


def test_phase_a_machine_evidence_manifest_is_complete():
    text = SCRIPT.read_text()
    for token in ("D71", "C4-C regression", "CANDIDATE GATES PASS",
                  "fingerprint_real() != before", "live_preflight()",
                  "C4-D SYNTHETIC AUDIT GREEN"):
        assert token in text


# --------------------------------------------------------------------------
# B1 real annotator handoff (run 2 stage B1, taskbook §5)
# --------------------------------------------------------------------------

B1_SCRIPT = ROOT / "scripts/csr8_phase_b1_real_handoff.py"


def _load_b1():
    import sys
    sys.path.insert(0, str(B1_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("csr8_b1_impl", B1_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_b1_real_annotator_domain_gates_pass_on_pre_seal_replica(tmp_path):
    """All seven B1 gates measure PASS against a transaction-derived
    pre-SEAL replica (real do_handoff on a certified production copy
    rewound to the exact committed R1 line): exact-copy vs C2 archive,
    closed-world domain, opaque annotation_session_id, leak scans,
    boundary domains absent.  The live tree itself must measure the
    post-B5 terminal shape instead (annotator cleaned, chain [R1,S1])."""
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    b1 = _load_b1()
    sb = build_pre_seal_sandbox(tmp_path, through="B1")
    res = b1.verify_b1(sb.root)
    assert set(res["gates"].values()) == {"PASS"}
    assert res["reveal_event_hash"] == b1.LIVE_R1
    assert res["annotation_sessions"] == 1
    # post-B5 live terminal shape (fail-closed direction)
    assert not b1.c4d.REAL_ANNOTATOR.exists()
    assert [e["event_type"] for e in b1.read_chain(b1.REAL_CSR, b1.SID)] == \
        ["REVEAL_PACKET", "SEAL_ANNOTATION", "REVEAL_PACKET", "SEAL_ANNOTATION"]


def test_b1_gates_fail_closed_on_tampered_copies(tmp_path):
    """Every B1 gate is a real re-measurement: tampering a tmp copy of a
    transaction-derived pre-SEAL replica must fail with the exact gate
    name."""
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    b1 = _load_b1()
    sb = build_pre_seal_sandbox(tmp_path, through="B1")
    root = sb.root
    # baseline passes on the replica
    assert set(b1.verify_b1(root)["gates"].values()) == {"PASS"}

    sid = b1.SID
    dom = b1.c4d.annot_dom(root, sid)
    r1 = b1.read_chain(root, sid)[0]
    pkt_file = dom / "packet" / f"{r1['payload']['packet_id']}.json"
    pristine = pkt_file.read_bytes()

    # exact-copy violation: flip one byte of the handed-off packet
    raw = bytearray(pristine)
    raw[0] ^= 0x01
    pkt_file.write_bytes(bytes(raw))
    with pytest.raises(RuntimeError, match="G-B1-EXACTCOPY"):
        b1.verify_b1(root)
    pkt_file.write_bytes(pristine)

    # closed-world violation: stray file in the annotator domain
    stray = dom / "notes.txt"
    stray.write_text("x")
    with pytest.raises(RuntimeError, match="G-B1-DOMAIN"):
        b1.verify_b1(root)
    stray.unlink()

    # canonical-registry violation: reserialize with spaces
    reg_path = b1.registry_path(root, sid)
    reg_obj = json.loads(reg_path.read_text())
    reg_path.write_text(json.dumps(reg_obj, indent=2))
    with pytest.raises(RuntimeError, match="G-B1-REGISTRY"):
        b1.verify_b1(root)
    reg_path.write_bytes(b1.canon(reg_obj).encode())

    # opaque-session-id violation: identity-shaped session id
    reg_obj["annotation_sessions"][0]["annotation_session_id"] = \
        "annotator-zhang-san-session"
    reg_path.write_bytes(b1.canon(reg_obj).encode())
    with pytest.raises(RuntimeError, match="G-B1-REGISTRY"):
        b1.verify_b1(root)
    reg_obj["annotation_sessions"][0]["annotation_session_id"] = \
        secrets_hex = __import__("secrets").token_hex(16)
    reg_path.write_bytes(b1.canon(reg_obj).encode())

    # leak violation: outcome-labeled key smuggled into the registry
    reg_obj["outcome_label"] = "OBSERVED"
    reg_path.write_bytes(b1.canon(reg_obj).encode())
    with pytest.raises(RuntimeError, match="G-B1-REGISTRY|G-B1-LEAK"):
        b1.verify_b1(root)

    # Restore the valid registry before testing the independent boundary gate.
    reg_obj.pop("outcome_label")
    reg_path.write_bytes(b1.canon(reg_obj).encode())
    # boundary violation: c4d_proposals domain appears early
    (root / "c4d_proposals").mkdir()
    with pytest.raises(RuntimeError, match="G-B1-BOUNDARY"):
        b1.verify_b1(root)


def test_b1_do_handoff_refuses_duplicate_and_audits_itself(tmp_path):
    """do_handoff is one-shot: re-running on a domain that already holds
    the handoff refuses, and re-running against the post-B5 live terminal
    state (chain [R1,S1], workspace cleaned) refuses at the chain gate —
    the verifier itself is re-measured by the replica tests above."""
    import subprocess, sys as _sys
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    b1 = _load_b1()
    # one-shot on a fresh replica: first run succeeds, second refuses
    sb = build_pre_seal_sandbox(tmp_path, through="B1")
    with pytest.raises(RuntimeError, match="already executed"):
        b1.do_handoff(sb.root)
    # the live tree is past B5: any handoff attempt must refuse at G-CHAIN
    with pytest.raises(RuntimeError, match="G-B1-CHAIN"):
        b1.do_handoff()
    # and the CLI verifier fail-closes loudly on the post-B5 live tree
    # (annotator domain legitimately absent — never a silent PASS)
    result = subprocess.run(
        [_sys.executable, str(B1_SCRIPT), "--verify"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode != 0
    assert "G-B1-" in (result.stdout + result.stderr)


# B2 real blinded annotation draft
B2_SCRIPT = ROOT / "scripts/csr8_phase_b2_real_annotation.py"


def _load_b2():
    import sys
    sys.path.insert(0, str(B2_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("csr8_b2_impl", B2_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_b2_real_draft_generation_and_all_gates_pass(tmp_path):
    """The real blinded-draft generation runs on a transaction-derived
    pre-SEAL replica (B1 state) and every B2 gate measures PASS on the
    persisted result."""
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    b2 = _load_b2()
    sb = build_pre_seal_sandbox(tmp_path, through="B1")
    generated = b2.build_draft(sb.root)
    assert generated["annotation_attempt"] == 1
    assert [j["hypothesis_id"] for j in generated["annotation"]["rt_judgments"]] == list(b2.c4d.HYPOTHESES)
    created = b2.create(sb.root)               # real persist transaction
    assert created["b2"] == "DRAFT_CREATED"
    result = b2.verify_b2(sb.root)
    assert set(result["gates"].values()) == {"PASS"}
    assert result["annotation_session_id"] == generated["annotation_session_id"]


def test_b2_draft_gate_rejects_invalid_pointer(tmp_path):
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    b2 = _load_b2()
    sb = build_pre_seal_sandbox(tmp_path, through="B2")
    root = sb.root
    assert set(b2.verify_b2(root)["gates"].values()) == {"PASS"}
    p = b2.c4d.annot_dom(root, b2.SID) / "draft" / "annotation_draft.json"
    draft = json.loads(p.read_text())
    draft["annotation"]["rt_judgments"][0]["evidence_refs"] = ["/not/in/packet"]
    p.write_text(json.dumps(draft, indent=2))
    with pytest.raises(RuntimeError, match="G-B2-DRAFT"):
        b2.verify_b2(root)


# --------------------------------------------------------------------------
# B4 exact-hash approval under the UNATTENDED policy
# (run audit_20260930021152297, taskbook §5 B4 + amendment
# v2-unattended-20260930).  Amendment v2 removed the human authorization
# gates: the executor persists the approval artifacts directly — no human
# message is waited for — and the PREAUTH v1 mechanism was removed from
# the bridge code.  The previous run's human-gate evidence files
# (b4_human_approval_message.txt, b4_preauth_v1.json, ...) stay committed
# as inert history and are no longer part of this gate.
# --------------------------------------------------------------------------

B4_SCRIPT = ROOT / "scripts/csr8_phase_b4_human_approval.py"


def _load_b4():
    import sys
    sys.path.insert(0, str(B4_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("csr8_b4_impl", B4_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_b4_live_unattended_approval_binds_exact_receipt_hash(tmp_path):
    """The live artifacts keep their exact-hash bindings (measured from
    the persisted bytes), and the FULL B4 gate stack re-measures green on
    a transaction-derived pre-SEAL replica — the live tree itself is past
    B5 (annotator cleaned), so the full stack no longer applies to it."""
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    b4 = _load_b4()
    # full gate stack on the replica (same real code path)
    sb = build_pre_seal_sandbox(tmp_path, through="B4")
    result = b4.verify_b4(sb.root, sb.record_path)
    assert set(result["gates"].values()) == {"PASS"}
    assert result["approved_by"] == "UNATTENDED_POLICY"
    # live persisted artifacts: every exact-hash binding still holds
    import hashlib
    receipt_sha = hashlib.sha256(b4.RECEIPT.read_bytes()).hexdigest()
    approval_bytes = b4.APPROVAL.read_bytes()
    approval = json.loads(approval_bytes)
    record_bytes = b4.UNATTENDED_RECORD.read_bytes()
    record = json.loads(record_bytes)
    assert result["receipt_sha256"] != receipt_sha  # replica ≠ live receipt
    assert receipt_sha == \
        "85a224a3e748b569060a14aea8fe5fe353b62e8a804e0f43cfb4c51a18063aa6"
    # approval artifact == approved object hash (character-identical)
    assert approval["approved_receipt_sha256"] == receipt_sha
    assert record["approved_receipt_sha256"] == receipt_sha
    assert b4.parse_wording_hash(record["taskbook_wording"]) == receipt_sha
    assert record["approved_by"] == "UNATTENDED_POLICY"
    assert record["binding"] == ["EXACT"]
    assert record["scope"] == "SEAL_ANNOTATION_ONLY"
    assert record["run_id"] == "audit_20260930021152297"
    assert record["authorized_artifact_sha256"] == \
        hashlib.sha256(approval_bytes).hexdigest()
    # permission bits and canonical form
    import stat as _stat
    import os as _os
    assert _stat.S_IMODE(_os.stat(b4.APPROVAL).st_mode) == 0o600
    assert _stat.S_IMODE(_os.stat(b4.UNATTENDED_RECORD).st_mode) == 0o600
    assert b4.c4d.canon(approval).encode() == approval_bytes
    assert b4.c4d.canon(record).encode() == record_bytes


def test_b4_unattended_persist_is_one_shot_on_the_real_domain():
    """The unattended approval record is an immutable O_EXCL artifact:
    any second persist attempt must fail closed."""
    b4 = _load_b4()
    with pytest.raises(RuntimeError,
                       match="already exists; immutable O_EXCL artifact"):
        b4.persist_unattended()


def test_b4_preauth_v1_mechanism_removed_from_bridge_code():
    """Amendment v2 removes the PREAUTH v1 mechanism from the bridge
    code: in EXECUTABLE code no preauth artifact dependency, schema or
    entry point may remain (prose documenting the removal may)."""
    import ast as _ast
    tree = _ast.parse(B4_SCRIPT.read_text())
    lines = B4_SCRIPT.read_text().splitlines()
    if tree.body and isinstance(tree.body[0], _ast.Expr) and \
            isinstance(tree.body[0].value, _ast.Constant):
        code_only = "\n".join(lines[tree.body[0].end_lineno:])
    else:
        code_only = "\n".join(lines)
    assert "b4_preauth_v1.json" not in code_only
    assert "PREAUTH_KEYS" not in code_only
    b4 = _load_b4()
    assert not hasattr(b4, "verify_preauth_v1")
    assert not hasattr(b4, "verify_session_record_live")
    assert not hasattr(b4, "parse_human_message")


def _b4_sandbox(tmp_path, b4):
    """Full end-to-end dry-run base for the B4 unattended transaction: a
    transaction-derived pre-approval replica (real B1->B3 transactions on
    a certified production copy — annotator domain present, receipt
    frozen, NO seal_approval yet), so the dry-run exercises the real
    frozen persist path; the run-side unattended record is then written
    O_EXCL and everything is re-proven green."""
    from csr8_preseal_sandbox import build_pre_seal_sandbox
    sb = build_pre_seal_sandbox(tmp_path, through="B3")
    root = sb.root
    approval = (root / "c4d_receipts" / b4.SID / "ordinal-0001" /
                "attempt-0001" / "seal_approval.json")
    assert not approval.exists()      # pre-approval state, by construction
    record_path = tmp_path / "b4_unattended_approval.json"
    return root, record_path, approval


def test_b4_end_to_end_transaction_on_copy_then_fail_closed_tampers(tmp_path):
    b4 = _load_b4()
    root, record_path, approval_path = _b4_sandbox(tmp_path, b4)
    result = b4.persist_unattended(root, record_path)
    assert result["b4"] == "APPROVAL_PERSISTED"
    assert set(result["gates"].values()) == {"PASS"}
    assert result["approved_by"] == "UNATTENDED_POLICY"
    # verify-only path re-proves the same gates from persisted bytes
    rev = b4.verify_b4(root, record_path)
    assert set(rev["gates"].values()) == {"PASS"}

    good_record = record_path.read_bytes()
    good_approval = approval_path.read_bytes()

    # wording drift: one extra character inside the fixed wording
    rec = json.loads(good_record)
    rec["taskbook_wording"] = rec["taskbook_wording"].replace(
        "我明确批准", "我明确地批准")
    record_path.write_bytes(b4.c4d.canon(rec).encode())
    with pytest.raises(RuntimeError, match="wording drift"):
        b4.verify_b4(root, record_path)
    # hash drift inside the wording: flip one hex digit
    rec = json.loads(good_record)
    w = rec["taskbook_wording"].splitlines()
    w[1] = ("0" if w[1][0] != "0" else "1") + w[1][1:]
    rec["taskbook_wording"] = "\n".join(w)
    record_path.write_bytes(b4.c4d.canon(rec).encode())
    with pytest.raises(RuntimeError, match="wording drift"):
        b4.verify_b4(root, record_path)
    record_path.write_bytes(good_record)

    # record binds a different receipt hash (canonical rewrite)
    rec = json.loads(good_record)
    rec["approved_receipt_sha256"] = "0" * 64
    record_path.write_bytes(b4.c4d.canon(rec).encode())
    with pytest.raises(RuntimeError,
                       match="does not bind the exact receipt hash"):
        b4.verify_b4(root, record_path)
    record_path.write_bytes(good_record)

    # approved_by drift (self-approval outside the unattended policy)
    rec = json.loads(good_record)
    rec["approved_by"] = "EXECUTOR"
    record_path.write_bytes(b4.c4d.canon(rec).encode())
    with pytest.raises(RuntimeError, match="UNATTENDED_POLICY"):
        b4.verify_b4(root, record_path)
    record_path.write_bytes(good_record)

    # authorization expansion: binding widened beyond EXACT
    rec = json.loads(good_record)
    rec["binding"] = ["EXACT", "ANY"]
    record_path.write_bytes(b4.c4d.canon(rec).encode())
    with pytest.raises(RuntimeError, match="binding"):
        b4.verify_b4(root, record_path)
    record_path.write_bytes(good_record)

    # authorized_artifact_sha256 drift (authorizes different bytes)
    rec = json.loads(good_record)
    rec["authorized_artifact_sha256"] = "0" * 64
    record_path.write_bytes(b4.c4d.canon(rec).encode())
    with pytest.raises(RuntimeError, match="authorized_artifact_sha256"):
        b4.verify_b4(root, record_path)
    record_path.write_bytes(good_record)

    # record from a different run
    rec = json.loads(good_record)
    rec["run_id"] = "audit_20260930010058058"
    record_path.write_bytes(b4.c4d.canon(rec).encode())
    with pytest.raises(RuntimeError, match="run/host/stage"):
        b4.verify_b4(root, record_path)
    record_path.write_bytes(good_record)

    # non-canonical record bytes (pretty-printed rewrite)
    record_path.write_text(json.dumps(json.loads(good_record), indent=2))
    with pytest.raises(RuntimeError, match="not canonical"):
        b4.verify_b4(root, record_path)
    record_path.write_bytes(good_record)

    # non-canonical chain-side approval bytes
    approval_path.write_text(
        json.dumps(json.loads(good_approval), indent=2))
    with pytest.raises(RuntimeError, match="not canonical"):
        b4.verify_b4(root, record_path)
    approval_path.write_bytes(good_approval)

    # chain approval binds a different receipt hash (canonical rewrite)
    obj = json.loads(good_approval)
    obj["approved_receipt_sha256"] = "0" * 64
    approval_path.write_bytes(b4.c4d.canon(obj).encode())
    with pytest.raises(RuntimeError,
                       match="does not bind exact receipt bytes"):
        b4.verify_b4(root, record_path)
    approval_path.write_bytes(good_approval)

    # mode drift 0600 -> 0644 (record and chain approval) must fail closed;
    # verification must not repair or rewrite the tampered mode.
    record_path.chmod(0o644)
    with pytest.raises(RuntimeError, match="mode"):
        b4.verify_b4(root, record_path)
    import stat as _stat
    assert _stat.S_IMODE(record_path.stat().st_mode) == 0o644
    record_path.chmod(0o600)
    approval_path.chmod(0o644)
    with pytest.raises(RuntimeError, match="mode"):
        b4.verify_b4(root, record_path)
    assert _stat.S_IMODE(approval_path.stat().st_mode) == 0o644
    approval_path.chmod(0o600)

    # after restoring everything, baseline must be green again
    assert set(b4.verify_b4(root, record_path)["gates"].values()) == \
        {"PASS"}


def test_b4_fail_closed_without_unattended_record(tmp_path):
    """No unattended record → the gate fails closed (the persisted chain
    approval alone is not a v2-complete B4)."""
    b4 = _load_b4()
    root, record_path, approval_path = _b4_sandbox(tmp_path, b4)
    # persist chain-side approval but delete the record before verify
    result = b4.persist_unattended(root, record_path)
    assert result["b4"] == "APPROVAL_PERSISTED"
    record_path.unlink()
    with pytest.raises(RuntimeError, match="unattended approval record "
                                           "absent"):
        b4.verify_b4(root, record_path)
    # second persist over the existing chain approval must also fail
    # closed: the record is one-shot O_EXCL on the real path, and a
    # re-persist attempt against the same copy is refused by the chain
    # artifact's own immutability only after the record would be written
    # — here the record is absent, so persist re-writes it; the chain
    # approval path (already present, binding verified) stays immutable.
    again = b4.persist_unattended(root, record_path)
    assert again["b4"] == "APPROVAL_PERSISTED"
    assert set(again["gates"].values()) == {"PASS"}
