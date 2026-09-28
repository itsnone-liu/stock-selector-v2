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
    # The real-domain check is explicit and must never manufacture state.
    assert not any(p.exists() for p in (mod.REAL_ANNOTATOR, mod.REAL_RECEIPTS, mod.REAL_PROPOSALS_C4D))


def test_phase_a_machine_evidence_manifest_is_complete():
    text = SCRIPT.read_text()
    for token in ("D71", "C4-C regression", "CANDIDATE GATES PASS",
                  "fingerprint_real() != before", "live_preflight()",
                  "C4-D SYNTHETIC AUDIT GREEN"):
        assert token in text
