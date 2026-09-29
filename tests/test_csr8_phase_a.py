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


def test_public_blindness_contract_and_anchor_are_machine_checked():
    mod = _load()
    anchor = mod.PUBLIC_DIR / "c4c_anchor.json"
    assert anchor.read_bytes() == b'{"authorization_sha256":"911d8b844da3a38467aecc0919ee22664484f87c9f49bf445a5a949b6245dc81","production_head_hash":"b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5"}'
    forbidden = ("opaque_case_id", "packet_id", "case_key", "secret_salt", "outcome")
    for p in mod.PUBLIC_DIR.glob("*.json"):
        text = p.read_text()
        assert not any(word in text for word in forbidden), p
    state = json.loads((mod.PUBLIC_DIR / "c4d_phase_a_public_state.json").read_text())
    assert state["production"] == {"event_types": ["REVEAL_PACKET"], "production_head_hash": "b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5", "seal_count": 0, "reveal_count": 1}
    # Stage-boundary aware: B1 creates and verifies annotator; later domains
    # remain absent and must never be manufactured by the Phase-A audit.
    b1 = _load_b1()
    assert set(b1.verify_b1()["gates"].values()) == {"PASS"}
    assert not mod.REAL_RECEIPTS.exists()
    assert not mod.REAL_PROPOSALS_C4D.exists()


def test_bridge_machine_audit_script_executes_complete_matrix():
    import subprocess, sys
    result = subprocess.run([sys.executable, str(ROOT / "scripts/csr8_phase_a_machine_audit.py")], cwd=ROOT, capture_output=True, text=True, timeout=1200)
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    assert '"certified_inputs":"VERIFIED"' in result.stdout
    assert '"D01_D71":"PASS"' in result.stdout
    assert '"C4D":"PASS"' in result.stdout
    assert '"C4C_regression":"PASS"' in result.stdout
    assert '"candidate_gates":"PASS"' in result.stdout
    assert '"blindness":"PASS"' in result.stdout
    assert '"real_fingerprint":"UNCHANGED"' in result.stdout
    assert '"production_snapshot":"REVEAL=1 SEAL=0"' in result.stdout
    assert '"integration":"PASS"' in result.stdout
    # stage-boundary aware (run 2 / B1): real annotator domain gates are
    # measured by the machine audit itself
    assert '"b1_annotator_domain":"PRESENT"' in result.stdout
    for gate in ("G-B1-CHAIN", "G-B1-ARCHIVE", "G-B1-DOMAIN",
                 "G-B1-EXACTCOPY", "G-B1-REGISTRY", "G-B1-LEAK",
                 "G-B1-BOUNDARY"):
        assert f'"{gate}":"PASS"' in result.stdout, gate


def test_certified_live_inputs_manifest_is_complete_and_forbidden_free():
    """The committed inventory certifies the ENTIRE data/csr8_phase_c tree:
    no forbidden C4-D domain can be listed (or exist), the local tree must
    match every pinned hash/mode exactly, and the pinned production chain
    links to the frozen anchor head hash."""
    import importlib.util
    cert = ROOT / "config/audit/certified_live_inputs.json"
    assert cert.is_file(), "config/audit/certified_live_inputs.json missing"
    manifest = json.loads(cert.read_text())
    assert manifest["version"] == 2
    assert {r["root"] for r in manifest["roots"]} == {
        "data/csr8_phase_c", "data/adjustment_baostock"}
    assert manifest["fileCount"] == sum(len(r["files"]) for r in manifest["roots"])
    paths = []
    for r in manifest["roots"]:
        paths += [f"{r['root']}/{f['path']}" for f in r["files"]]
        paths += [f"{r['root']}/{d['path']}" for d in r["dirs"]]
    for forbidden in ("data/csr8_phase_c/c4d_receipts/",
                      "data/csr8_phase_c/c4d_proposals/"):
        assert not any(p.startswith(forbidden) for p in paths), \
            f"forbidden C4-D domain certified: {forbidden}"
    # required gate inputs are pinned
    listed = {f"{r['root']}/{f['path']}" for r in manifest["roots"]
              for f in r["files"]}
    for required in (
        "data/csr8_phase_c/secret/secret_salt",
        "data/csr8_phase_c/secret/packet_plan.json",
        "data/csr8_phase_c/production/c4-prod-0002/sealing/sealing_log.jsonl",
        "data/csr8_phase_c/c4c_proposals/c4-prod-0002/first_reveal.proposal.json",
        "data/csr8_phase_c/annotator/c4-prod-0002/annotation_session_registry.json",
        "data/adjustment_baostock/fetch_manifest.json",
    ):
        assert required in listed, f"gate input not certified: {required}"
    annotator_files = [p for p in listed
                       if p.startswith("data/csr8_phase_c/annotator/")]
    assert len(annotator_files) == 3, \
        "B2 annotator domain must pin packet, registry, and draft"
    # the local trees must equal the manifest exactly (bridge-certified
    # materialization or native live tree — either way, zero tolerance)
    spec = importlib.util.spec_from_file_location(
        "c4d_machine_audit", ROOT / "scripts/csr8_phase_a_machine_audit.py")
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    checked = audit.verify_certified_tree()
    assert checked["fileCount"] == manifest["fileCount"]
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


def test_b1_real_annotator_domain_gates_pass_on_live_tree():
    """All seven B1 gates measure PASS against the real (or certified
    materialized) tree: exact-copy vs C2 archive, closed-world domain,
    opaque annotation_session_id, leak scans, boundary domains absent."""
    b1 = _load_b1()
    res = b1.verify_b1()
    assert set(res["gates"].values()) == {"PASS"}
    assert res["reveal_event_hash"] == b1.LIVE_R1
    assert res["annotation_sessions"] == 1


def test_b1_gates_fail_closed_on_tampered_copies(tmp_path):
    """Every B1 gate is a real re-measurement: tampering a tmp copy of
    the real domains must fail with the exact gate name."""
    b1 = _load_b1()
    real = b1.REAL_CSR
    root = tmp_path / "csr8_phase_c"
    root.mkdir()
    import shutil
    shutil.copytree(real / "production", root / "production")
    shutil.copytree(real / "annotator", root / "annotator")
    # baseline passes on the copy
    assert set(b1.verify_b1(root)["gates"].values()) == {"PASS"}

    sid = b1.SID
    dom = b1.c4d.annot_dom(root, sid)
    r1 = b1.read_chain(root, sid)[0]
    pkt_file = dom / "packet" / f"{r1['payload']['packet_id']}.json"

    # exact-copy violation: flip one byte of the handed-off packet
    raw = bytearray(pkt_file.read_bytes())
    raw[0] ^= 0x01
    pkt_file.write_bytes(bytes(raw))
    with pytest.raises(RuntimeError, match="G-B1-EXACTCOPY"):
        b1.verify_b1(root)
    pkt_file.write_bytes((real / "annotator" / sid / "packet" /
                          f"{r1['payload']['packet_id']}.json").read_bytes())

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
    # boundary violation: c4d_receipts domain appears early
    (root / "c4d_receipts").mkdir()
    with pytest.raises(RuntimeError, match="G-B1-BOUNDARY"):
        b1.verify_b1(root)


def test_b1_do_handoff_refuses_duplicate_and_audits_itself(capsys):
    """do_handoff is one-shot on the REAL domain (already executed at
    B1): a second execution must refuse, and --verify measures green."""
    import subprocess, sys as _sys
    b1 = _load_b1()
    with pytest.raises(RuntimeError, match="already executed"):
        b1.do_handoff()
    result = subprocess.run(
        [_sys.executable, str(B1_SCRIPT), "--verify"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    out = json.loads(result.stdout.strip().splitlines()[-1])
    assert out["b1"] == "VERIFIED"
    assert set(out["gates"].values()) == {"PASS"}


# B2 real blinded annotation draft
B2_SCRIPT = ROOT / "scripts/csr8_phase_b2_real_annotation.py"


def _load_b2():
    import sys
    sys.path.insert(0, str(B2_SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("csr8_b2_impl", B2_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_b2_real_draft_generation_and_all_gates_pass():
    b2 = _load_b2()
    generated = b2.build_draft()
    assert generated["annotation_attempt"] == 1
    assert [j["hypothesis_id"] for j in generated["annotation"]["rt_judgments"]] == list(b2.c4d.HYPOTHESES)
    result = b2.verify_b2()
    assert set(result["gates"].values()) == {"PASS"}
    assert result["annotation_session_id"] == generated["annotation_session_id"]


def test_b2_draft_gate_rejects_invalid_pointer(tmp_path):
    b2 = _load_b2()
    import shutil
    root = tmp_path / "csr8_phase_c"
    root.mkdir()
    shutil.copytree(b2.CSR / "production", root / "production")
    shutil.copytree(b2.CSR / "annotator", root / "annotator")
    assert set(b2.verify_b2(root)["gates"].values()) == {"PASS"}
    p = b2.c4d.annot_dom(root, b2.SID) / "draft" / "annotation_draft.json"
    draft = json.loads(p.read_text())
    draft["annotation"]["rt_judgments"][0]["evidence_refs"] = ["/not/in/packet"]
    p.write_text(json.dumps(draft, indent=2))
    with pytest.raises(RuntimeError, match="G-B2-DRAFT"):
        b2.verify_b2(root)
