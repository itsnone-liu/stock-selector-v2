#!/usr/bin/env python3
"""Self-contained Phase-A machine audit used by the bridge pytest.

It deliberately uses only a temporary C3 packet universe and temporary C4-D
sandboxes.  No ignored secret, live production state, or executor-written
claim is an input.  The output is a compact machine-readable result.
"""
import hashlib, importlib.util, json, shutil, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/csr8_phase_c_annotation_seal.py"

def load():
    import sys
    sys.path.insert(0, str(TARGET.parent))
    spec = importlib.util.spec_from_file_location("c4d_audit_target", TARGET)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def main():
    m = load(); td = Path(tempfile.mkdtemp(prefix="csr8-audit-"))
    old = (m.c4ab.C3_STATE, m.c1.PLAN_FILE, m.c1.load_salt,
           m.c4ab.first_candidate, m.candidate_total_order,
           m.candidate_for_ordinal, m.verify_candidate_gates)
    try:
        packets = td / "c3" / "packets"; packets.mkdir(parents=True)
        m.c4ab.C3_STATE = packets.parent
        m.c1.PLAN_FILE = td / "packet_plan.json"
        m.c1.load_salt = lambda: "phase-a-machine-audit-salt"
        ocid = m.c2.synth_ocid(m.SYNTH_CASE)
        order = [{"opaque_case_id": ocid, "T": m.SYNTH_T,
                  "t_rank": 0, "case_rank": 0},
                 {"opaque_case_id": ocid, "T": "2099-01-03",
                  "t_rank": 1, "case_rank": 0}]
        key = "G1_complete_bull|" + m.SYNTH_CASE
        m.c1.PLAN_FILE.write_text(json.dumps({"entries": [
            {"case_key": key, "T": x["T"]} for x in order]}))
        for x in order:
            pid = hashlib.sha256(f'{x["opaque_case_id"]}|{x["T"]}'.encode()).hexdigest()
            (packets / f"{pid}.json").write_bytes(m.synth_packet_bytes(m.SYNTH_CASE, x["T"]))
        m.c4ab.first_candidate = lambda _: dict(order[0], digest="machine")
        m.candidate_total_order = lambda: list(order)
        m.candidate_for_ordinal = lambda n: dict(order[n - 1])
        m.verify_candidate_gates = lambda: {"size": 2, "ordinal1_matches_frozen_first": True, "revealed_prefix": 1}
        seen = []
        for name, _desc, fn in m.FIXTURES:
            fn(); seen.append(name)
        if seen != [f"D{i:02d}" for i in range(1, 72)]:
            raise RuntimeError("D01-D71 registry/order mismatch")
        state = json.loads((m.PUBLIC_DIR / "c4d_phase_a_public_state.json").read_text())
        assert state["production"]["event_types"] == ["REVEAL_PACKET"]
        assert state["production"]["reveal_count"] == 1
        assert state["production"]["seal_count"] == 0
        public = " ".join(p.read_text() for p in m.PUBLIC_DIR.glob("*.json"))
        assert not any(x in public for x in ("opaque_case_id", "packet_id", "case_key", "secret_salt", "outcome"))
        print(json.dumps({"D01_D71":"PASS", "C4D":"PASS", "candidate_snapshot":"PASS", "blindness":"PASS", "production_snapshot":"REVEAL=1 SEAL=0"}, separators=(",", ":")))
    finally:
        (m.c4ab.C3_STATE, m.c1.PLAN_FILE, m.c1.load_salt,
         m.c4ab.first_candidate, m.candidate_total_order,
         m.candidate_for_ordinal, m.verify_candidate_gates) = old
        shutil.rmtree(td, ignore_errors=True)

if __name__ == "__main__": main()
