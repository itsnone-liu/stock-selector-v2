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
    old_state, old_plan = mod.c4ab.C3_STATE, mod.c1.PLAN_FILE
    old_salt = mod.c1.load_salt
    try:
        c3 = tmp_path / "c3" / "packets"
        c3.mkdir(parents=True)
        mod.c4ab.C3_STATE = c3.parent
        mod.c1.load_salt = lambda: "phase-a-test-salt"
        mod.c1.PLAN_FILE = tmp_path / "packet_plan.json"
        ocid = mod.c2.synth_ocid(mod.SYNTH_CASE)
        case_key = f"G1_complete_bull|{mod.SYNTH_CASE}"
        second_t = "2099-01-03"
        mod.c1.PLAN_FILE.write_text(json.dumps({"entries": [
            {"case_key": case_key, "T": mod.SYNTH_T},
            {"case_key": case_key, "T": second_t},
        ]}))
        for packet_t in (mod.SYNTH_T, second_t):
            packet_id = hashlib.sha256(f"{ocid}|{packet_t}".encode()).hexdigest()
            (c3 / f"{packet_id}.json").write_bytes(mod.synth_packet_bytes(mod.SYNTH_CASE, packet_t))
        old_first = mod.c4ab.first_candidate
        old_candidate = mod.candidate_for_ordinal
        mod.c4ab.first_candidate = lambda _c1: {"opaque_case_id": ocid, "T": mod.SYNTH_T, "digest": "test"}
        mod.candidate_for_ordinal = lambda ordinal: {"opaque_case_id": ocid, "T": second_t, "t_rank": 1, "case_rank": 0}
        output = io.StringIO()
        with redirect_stdout(output):
            mod.d71()
        text = output.getvalue()
        assert "PASS D71" in text
        assert "G-C4D-AUTHZ" in text
    finally:
        mod.c4ab.C3_STATE = old_state
        mod.c1.PLAN_FILE = old_plan
        mod.c1.load_salt = old_salt
        if 'old_first' in locals():
            mod.c4ab.first_candidate = old_first
        if 'old_candidate' in locals():
            mod.candidate_for_ordinal = old_candidate


def test_guard_semantics_and_five_entrypoints_are_machine_checked():
    tree = ast.parse(SCRIPT.read_text())
    funcs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    guard = funcs["prove_next_reveal_eligible"]
    calls = [n for n in ast.walk(guard) if isinstance(n, ast.Call)]
    call_text = {ast.unparse(n) for n in calls}
    assert "c2translate(lg.load().verify, True)" in call_text
    assert any("event_type" in ast.unparse(n) and "c2.SEAL" in ast.unparse(n) for n in ast.walk(guard))
    assert any("ordinal != reveals + 1" in ast.unparse(n) for n in ast.walk(guard))
    for name in ("build_next_reveal_proposal", "approve_next_reveal",
                 "materialize_next_permit", "verify_next_authorization_chain",
                 "reveal_transaction"):
        assert name in funcs
        body = ast.unparse(funcs[name])
        assert "prove_next_reveal_eligible(sb, sid, ordinal)" in body, name


def test_live_fingerprint_and_blindness_scan_are_explicitly_executed():
    mod = _load()
    before = mod.fingerprint_real()
    mod.live_preflight()
    candidate = mod.verify_candidate_gates()
    assert candidate["ordinal1_matches_frozen_first"] is True
    assert candidate["revealed_prefix"] >= 1
    assert mod.fingerprint_real() == before
    assert mod.REAL_ANNOTATOR.exists() is False
    assert mod.REAL_RECEIPTS.exists() is False
    assert mod.REAL_PROPOSALS_C4D.exists() is False
    public = mod.PUBLIC_DIR
    forbidden = ("opaque_case_id", "packet_id", "case_key", "secret_salt", "outcome")
    for p in public.glob("*.json"):
        text = p.read_text()
        assert not any(word in text for word in forbidden), p


def test_executable_runner_reports_all_frozen_gate_classes():
    mod = _load()
    result = __import__("subprocess").run(
        [__import__("sys").executable, str(SCRIPT), "synthetic"],
        cwd=ROOT, capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    out = result.stdout
    for token in ("CANDIDATE GATES PASS", "[D71] PASS", "C4-D SYNTHETIC AUDIT GREEN"):
        assert token in out
    assert '"fixtures":"D01–D71 (71 PASS)"' in out
    assert '"c4c_regression":"PASS"' in out
    assert '"live_invariants":"REVEAL=1 SEAL=0 annotation=0 c4d_domains=absent anchor=absent"' in out
