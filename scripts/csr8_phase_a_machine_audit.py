#!/usr/bin/env python3
"""Bridge-executable Phase-A machine audit (iteration 17 contract).

Synthetic gates (D01-D71 matrix, guard semantics) run self-contained in
tmp sandboxes.  The REAL production gates (C4-C regression subprocess,
live preflight, candidate gates, blindness scan, production
REVEAL=1/SEAL=0, forbidden-domain absence, real fingerprint
before==after) read live state under data/csr8_phase_c.

The audit bridge executes this script in a detached worktree of the
exact TARGET_COMMIT where gitignored data/ does not exist.  Per the
iteration-16 audit verdict, the bridge therefore provides CERTIFIED
inputs: it reads the committed inventory
config/audit/certified_live_inputs.json FROM THE TARGET COMMIT,
verifies the executor's live tree matches every pinned sha256/mode with
no extra entries, and materializes the tree into the worktree (recorded
in the bridge test record).  This script independently re-verifies that
rule before any gate runs; a missing or drifted tree fails loudly —
never a synthetic PASS.
"""
import hashlib, importlib.util, json, shutil, stat, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "scripts/csr8_phase_c_annotation_seal.py"
CERT_MANIFEST = ROOT / "config/audit/certified_live_inputs.json"
FORBIDDEN_PREFIXES = ("annotator/", "c4d_receipts/", "c4d_proposals/")

def load():
    import sys
    sys.path.insert(0, str(TARGET.parent))
    spec = importlib.util.spec_from_file_location("c4d_audit_target", TARGET)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m

def verify_certified_tree():
    """Local data trees must equal the committed v2 manifest exactly."""
    if not CERT_MANIFEST.is_file():
        raise RuntimeError("certified inputs manifest missing from commit: config/audit/certified_live_inputs.json")
    manifest = json.loads(CERT_MANIFEST.read_text())
    if manifest.get("version") != 2 or not isinstance(manifest.get("roots"), list) \
            or not manifest["roots"]:
        raise RuntimeError("certified inputs manifest must be version 2 multi-root")
    bad = []
    for r in manifest["roots"]:
        live = ROOT / r["root"]
        if not live.is_dir():
            raise RuntimeError(
                "certified live inputs not materialized in this checkout "
                f"({r['root']} absent); the audit bridge must provide them "
                "per config/audit/certified_live_inputs.json — refusing PASS")
        m_dirs = {d["path"]: d["mode"] for d in r["dirs"]}
        m_files = {f["path"]: f for f in r["files"]}
        for rel in list(m_dirs) + list(m_files):
            if any(rel.startswith(fp) for fp in FORBIDDEN_PREFIXES):
                raise RuntimeError(f"certified manifest lists forbidden C4-D path: {r['root']}/{rel}")
        seen_dirs, seen_files = set(), set()
        for p in sorted(live.rglob("*")):
            rel = p.relative_to(live).as_posix()
            st = p.lstat()
            if p.is_dir():
                seen_dirs.add(rel)
                if m_dirs.get(rel) != stat.S_IMODE(st.st_mode):
                    bad.append(f"dir mode drift: {r['root']}/{rel}")
            elif p.is_file():
                seen_files.add(rel)
                entry = m_files.get(rel)
                if entry is None:
                    bad.append(f"extra live file not in manifest: {r['root']}/{rel}")
                    continue
                if entry["bytes"] != st.st_size or entry["mode"] != stat.S_IMODE(st.st_mode):
                    bad.append(f"size/mode drift: {r['root']}/{rel}")
                h = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 20), b""):
                        h.update(chunk)
                if h.hexdigest() != entry["sha256"]:
                    bad.append(f"sha256 drift: {r['root']}/{rel}")
            else:
                bad.append(f"non-regular entry: {r['root']}/{rel}")
            if len(bad) >= 10:
                break
        for rel in set(m_dirs) - seen_dirs:
            bad.append(f"manifest dir missing from live tree: {r['root']}/{rel}")
        for rel in set(m_files) - seen_files:
            bad.append(f"manifest file missing from live tree: {r['root']}/{rel}")
        if len(bad) >= 10:
            break
    if bad:
        raise RuntimeError("certified live inputs mismatch: " + "; ".join(bad[:10]))
    return manifest

def main():
    manifest = verify_certified_tree()
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
        # verify_certified_tree() above already proved the live inputs are
        # present (native or bridge-certified), so this runs unconditionally.
        import subprocess, sys
        c4c = subprocess.run([sys.executable, str(ROOT / "scripts/csr8_phase_c_first_reveal.py"), "synthetic"], cwd=ROOT, capture_output=True, text=True, timeout=900)
        if c4c.returncode != 0 or "C4-C SYNTHETIC PASS" not in c4c.stdout or "content fingerprints unchanged" not in c4c.stdout:
            raise RuntimeError("C4-C regression integration gate failed")
        seen = []
        for name, _desc, fn in m.FIXTURES:
            fn(); seen.append(name)
        if seen != [f"D{i:02d}" for i in range(1, 72)]:
            raise RuntimeError("D01-D71 registry/order mismatch")
        # Restore the module's real C1/C3 bindings before the production
        # integration gate.  The isolated fixture must never contaminate the
        # real module globals used by live_preflight/candidate gates.
        (m.c4ab.C3_STATE, m.c1.PLAN_FILE, m.c1.load_salt,
         m.c4ab.first_candidate, m.candidate_total_order,
         m.candidate_for_ordinal, m.verify_candidate_gates) = old
        m.live_preflight()
        before = m.fingerprint_real()
        gates = m.verify_candidate_gates()
        if gates["ordinal1_matches_frozen_first"] is not True or gates["revealed_prefix"] < 1:
            raise RuntimeError("candidate gates integration proof failed")
        if m.fingerprint_real() != before:
            raise RuntimeError("real fingerprint changed during integration run")
        state = json.loads((m.PUBLIC_DIR / "c4d_phase_a_public_state.json").read_text())
        assert state["production"]["event_types"] == ["REVEAL_PACKET"]
        assert state["production"]["reveal_count"] == 1
        assert state["production"]["seal_count"] == 0
        public = " ".join(p.read_text() for p in m.PUBLIC_DIR.glob("*.json"))
        assert not any(x in public for x in ("opaque_case_id", "packet_id", "case_key", "secret_salt", "outcome"))
        print(json.dumps({"certified_inputs": "VERIFIED", "certified_files": manifest["fileCount"], "certified_roots": len(manifest["roots"]), "D01_D71": "PASS", "C4D": "PASS", "C4C_regression": "PASS", "candidate_gates": "PASS", "blindness": "PASS", "real_fingerprint": "UNCHANGED", "production_snapshot": "REVEAL=1 SEAL=0", "integration": "PASS"}, separators=(",", ":")))
    finally:
        (m.c4ab.C3_STATE, m.c1.PLAN_FILE, m.c1.load_salt,
         m.c4ab.first_candidate, m.candidate_total_order,
         m.candidate_for_ordinal, m.verify_candidate_gates) = old
        shutil.rmtree(td, ignore_errors=True)

if __name__ == "__main__": main()
