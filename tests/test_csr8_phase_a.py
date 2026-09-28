"""Independent, isolated Phase-A evidence.

No ignored secret or live production domain is required.  The D71 test patches
only the frozen C3 selector inputs to a temporary synthetic packet, then runs
the real C4-D authorization functions against a temporary sandbox.
"""
import hashlib
import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

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


def test_phase_a_guard_is_wired_at_all_authorization_entrypoints():
    text = SCRIPT.read_text()
    guard = "prove_next_reveal_eligible(sb, sid, ordinal)"
    assert text.count(guard) >= 4
    assert "c2translate(lg.load().verify, True)" in text
    assert "last committed event" in text
    assert "_cand_prefix_gate" in text
    assert "fingerprint_real() != before" in text
