"""Phase H H0 entry-gate script: end-to-end machine checks.

The H0 gate (taskbook v1.1 §8/§31) is executor-run and reviewer-approved;
these tests pin the PERSISTED campaign state so the pure-read `verify`
path keeps passing against the live frozen tree:

- the review ledger + PHASE_ENTRY verdict stay well-formed, hash-chained,
  bound to the exact packet bytes, and reviewer-independent (fast checks,
  no full-tree hashing);
- the full pure-read `verify` command exits 0 with the machine-measured
  round-0 §10 caliber and an APPROVE verdict (end-to-end).
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_h0():
    spec = importlib.util.spec_from_file_location(
        "csr8_phase_h_entry_gate",
        ROOT / "scripts/csr8_phase_h_entry_gate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_h0_ledger_and_verdict_are_persisted_and_independent():
    h0 = _load_h0()
    gates = h0.entry_gates()
    chain = gates["chain"]
    r0 = h0.round0_facts(chain)
    cid = h0.derive_campaign_id(chain, r0)
    assert h0.campaign_dir(cid).is_dir()

    ledger = h0.verify_ledger(cid)
    assert ledger["records"] == 2
    assert len(ledger["verdicts"]) == 1
    verdict_line = ledger["verdicts"][0]
    assert verdict_line["operation"] == "PHASE_ENTRY"
    assert verdict_line["ordinal"] == 3
    assert verdict_line["sequence"] == 1
    assert verdict_line["campaign_id"] == cid
    assert verdict_line["reviewer_run_id"] != h0.EXECUTOR_RUN_ID

    verdict = h0.verify_verdict_file(cid, ledger["verdicts"])
    assert verdict["state"] == "APPROVE"
    assert verdict["issues"] == [] and verdict["required_changes"] == []
    packet = (h0.campaign_dir(cid) / "review_packets" /
              "phase_entry.json").read_bytes()
    assert verdict["input_commitment_sha256"] == h0.sha(packet)

    # §10 round-0 caliber: unique eligible cases, not (case,T) pairs
    assert r0["total"] == 64 and r0["completed"] == 2 and r0["remaining"] == 62
    assert r0["pair_order_size"] == 1717
    assert "unique eligible cases" in r0["caliber"]

    # the ordinal-3 proposal is PREPARED campaign-side only: the live
    # annotator proposal domain stays closed-world at ordinal-0002
    staged = h0.campaign_dir(cid) / "ordinal_0003" / \
        "next_reveal.proposal.staged.json"
    assert staged.is_file()
    staged_doc = json.loads(staged.read_bytes())
    assert staged_doc["scope"] == "NEXT_REVEAL_ONLY"
    assert staged_doc["reveal_ordinal"] == 3
    assert staged_doc["sealed_prefix_head"] == chain["production_head"]
    live_proposals = sorted(
        p.relative_to(h0.c4d.REAL_PROPOSALS_C4D).as_posix()
        for p in h0.c4d.REAL_PROPOSALS_C4D.rglob("*") if p.is_file())
    assert live_proposals == [
        "c4-prod-0002/ordinal-0002/next_reveal.proposal.json"]


def test_h0_verify_command_is_pure_read_and_passes_end_to_end():
    result = subprocess.run(
        [sys.executable,
         str(ROOT / "scripts/csr8_phase_h_entry_gate.py"), "verify"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stage"] == "H0" and payload["iteration"] == 2
    assert payload["state"] == "VERIFIED"
    assert payload["phase_entry_review"] == "APPROVE"
    assert payload["round0"]["total"] == 64
    assert payload["round0"]["completed"] == 2
    assert payload["round0"]["remaining"] == 62
    assert payload["verifier_battery"]["all_pass"] is True
    assert payload["verifier_battery"]["certified_files"] > 10563
