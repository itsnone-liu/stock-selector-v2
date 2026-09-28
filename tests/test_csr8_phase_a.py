"""Machine-executable CSR-8 Phase A evidence.

These tests bind the Phase-A claim to the implementation and its executable
D01-D71/D71 paths; the audit document is not treated as evidence by itself.
The synthetic runner uses temporary sandboxes and its live preflight is
read-only, so no production annotation/receipt/SEAL domain is created.
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
SCRIPT = ROOT / "scripts" / "csr8_phase_c_annotation_seal.py"
ANCHOR = ROOT / "output/research/csr/08_pilot_cases/phase_c/c4_public/c4c_anchor.json"


def _run(*args):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "src")
    return subprocess.run(
        [PYTHON, str(SCRIPT), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_phase_a_synthetic_gate_and_d71_are_executable():
    before = ANCHOR.read_bytes()
    result = _run("synthetic")
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-4000:]
    out = result.stdout
    assert "CANDIDATE GATES PASS" in out
    assert "[D71] PASS" in out
    assert "D01–D71 (71 PASS)" in out
    assert '"c4c_regression":"PASS"' in out
    assert '"mode":"synthetic only; real chain/domains untouched"' in out
    assert '"live_invariants":"REVEAL=1 SEAL=0 annotation=0 c4d_domains=absent anchor=absent"' in out
    assert ANCHOR.read_bytes() == before, "synthetic run mutated c4c_anchor.json"


def test_phase_a_candidate_gate_and_frozen_anchor_are_bound():
    result = _run("candidates")
    assert result.returncode == 0, result.stdout + result.stderr
    assert '"ordinal1_matches_frozen_first":true' in result.stdout
    assert '"revealed_prefix":1' in result.stdout
    assert '"size":1717' in result.stdout
    assert hashlib.sha256(ANCHOR.read_bytes()).hexdigest() == (
        "afe7baa5888b973382b534d722492b69fbb8840d24d208984f03b377fd8aeff5"
    )
