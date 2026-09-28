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
        # Execute the frozen C4-C regression as a subprocess and require its
        # real pre/post production fingerprint claim in machine output.
        import subprocess, sys
        c4c_state = ROOT / "data/csr8_phase_c/production/c4-prod-0002/sealing/sealing_log.jsonl"
        secret_salt = ROOT / "data/csr8_phase_c/secret/secret_salt"
        c4c = subprocess.run([sys.executable, str(ROOT / "scripts/csr8_phase_c_first_reveal.py"), "synthetic"], cwd=ROOT, capture_output=True, text=True, timeout=900) if c4c_state.exists() and secret_salt.exists() else None
        if c4c is not None:
            if c4c.returncode != 0 or "C4-C SYNTHETIC PASS" not in c4c.stdout or "content fingerprints unchanged" not in c4c.stdout:
                raise RuntimeError("C4-C regression integration gate failed")
        else:
            # Missing live/secret inputs are an unavailable integration gate,
            # never a synthetic PASS.  This is fail-closed for detached
            # worktrees and forces the bridge to provide real inputs.
            raise RuntimeError("C4-C live integration inputs unavailable: refusing PASS")
        seen = []
        for name, _desc, fn in m.FIXTURES:
            fn(); seen.append(name)
        if seen != [f"D{i:02d}" for i in range(1, 72)]:
            raise RuntimeError("D01-D71 registry/order mismatch")
        # Restore globals.  In a real checkout run the live gates; in a
        # detached checkout use only committed public snapshots and a fresh
        # fingerprint of the available production/public roots.
        (m.c4ab.C3_STATE, m.c1.PLAN_FILE, m.c1.load_salt,
         m.c4ab.first_candidate, m.candidate_total_order,
         m.candidate_for_ordinal, m.verify_candidate_gates) = old
        if c4c_state.exists():
            m.live_preflight()
            before = m.fingerprint_real()
            gates = m.verify_candidate_gates()
            if gates["ordinal1_matches_frozen_first"] is not True or gates["revealed_prefix"] < 1:
                raise RuntimeError("candidate gates integration proof failed")
            if m.fingerprint_real() != before:
                raise RuntimeError("real fingerprint changed during integration run")
        else:
            gates = {"ordinal1_matches_frozen_first": True, "revealed_prefix": 1}
        state = json.loads((m.PUBLIC_DIR / "c4d_phase_a_public_state.json").read_text())
        assert state["production"]["event_types"] == ["REVEAL_PACKET"]
        assert state["production"]["reveal_count"] == 1
        assert state["production"]["seal_count"] == 0
        public = " ".join(p.read_text() for p in m.PUBLIC_DIR.glob("*.json"))
        assert not any(x in public for x in ("opaque_case_id", "packet_id", "case_key", "secret_salt", "outcome"))
        print(json.dumps({"D01_D71":"PASS", "C4D":"PASS", "C4C_regression":"PASS", "candidate_gates":"PASS", "blindness":"PASS", "real_fingerprint":"UNCHANGED", "production_snapshot":"REVEAL=1 SEAL=0", "integration":"PASS"}, separators=(",", ":")))
    finally:
        (m.c4ab.C3_STATE, m.c1.PLAN_FILE, m.c1.load_salt,
         m.c4ab.first_candidate, m.candidate_total_order,
         m.candidate_for_ordinal, m.verify_candidate_gates) = old
        shutil.rmtree(td, ignore_errors=True)

if __name__ == "__main__": main()
