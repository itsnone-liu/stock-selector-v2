"""Phase H H0 entry-gate script: end-to-end machine checks.

The H0 gate (taskbook v1.1 §8/§31) is executor-run and reviewer-approved;
these tests pin the PERSISTED campaign state so the pure-read `verify`
path keeps passing against the live frozen tree:

- the review ledger + PHASE_ENTRY verdict stay well-formed, hash-chained,
  bound to the exact packet bytes, and reviewer-independent. Expectations
  are derived structurally from the append-only ledger (§6/§15): prior
  REVISE rounds persist forever, so counts are never pinned to a
  fresh-campaign happy path (fast checks, no full-tree hashing);
- the full pure-read `verify` command exits 0 with the machine-measured
  round-0 §10 caliber and an APPROVE verdict (end-to-end).
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

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
    # append-only lifecycle: genesis + every persisted reviewer round. The
    # counts are DERIVED, never pinned to a fresh-campaign happy path —
    # prior REVISE rounds stay in the ledger forever (§6/§15).
    assert ledger["records"] >= 3
    verdicts = ledger["verdicts"]
    assert len(verdicts) >= 2
    assert [v["sequence"] for v in verdicts] == list(
        range(1, len(verdicts) + 1))
    for verdict_line in verdicts:
        assert verdict_line["operation"] == "PHASE_ENTRY"
        assert verdict_line["ordinal"] == 3
        assert verdict_line["campaign_id"] == cid
    reviewer_ids = [v["reviewer_run_id"] for v in verdicts]
    assert h0.EXECUTOR_RUN_ID not in reviewer_ids
    assert len(set(reviewer_ids)) == len(reviewer_ids)  # independent each round

    # the persisted verdict file is the LATEST ledger round and binds the
    # exact CURRENT packet bytes (§5) — no superseded binding may survive
    verdict = h0.verify_verdict_file(cid, verdicts)
    assert verdict["state"] == "APPROVE"
    assert verdict["issues"] == [] and verdict["required_changes"] == []
    assert verdict["reviewer_run_id"] == verdicts[-1]["reviewer_run_id"]
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


def test_h0_round_bookkeeping_is_as_of_round():
    """iteration-3 round-3 修复：轮次簿记 as-of-round 派生 + fail-closed
    一致性（reviewer 合法追加 verdict 不得使持久化 manifest/packet 漂移；
    最新 verdict 必须绑定当前 packet 字节）。"""
    h0 = _load_h0()
    gates = h0.entry_gates()
    chain = gates["chain"]
    r0 = h0.round0_facts(chain)
    cid = h0.derive_campaign_id(chain, r0)

    rstate = h0.campaign_round_state(cid)
    assert rstate["packet_exists"] is True
    assert rstate["round"] >= 3
    assert len(rstate["prior_verdicts"]) == rstate["round"] - 1
    assert rstate["prior_count"] == rstate["round"] - 1
    live = rstate["live_verdicts"]
    assert len(live) in (rstate["round"] - 1, rstate["round"])
    if len(live) == rstate["round"]:
        packet = (h0.campaign_dir(cid) / "review_packets" /
                  "phase_entry.json").read_bytes()
        assert live[-1]["input_commitment_sha256"] == h0.sha(packet)

    # the persisted manifest and packet VERIFY byte-exact under as-of-round
    # derivation even though the reviewer appended a verdict after they
    # were persisted (the pre-fix code structurally could not pass here)
    staged, staged_bytes, _ = h0.build_staged_proposal_via_frozen_builder()
    manifest_bytes, mstate = h0.build_or_verify_manifest(
        gates, chain, r0, cid, staged, chain["production_head"])
    assert mstate == "VERIFIED"
    genesis_line = (h0.campaign_dir(cid) / "reviews.jsonl"
                    ).read_bytes().splitlines()[0]
    packet_bytes, pstate = h0.build_or_verify_packet(
        gates, chain, r0, cid, staged, staged_bytes, manifest_bytes,
        genesis_line)
    assert pstate == "VERIFIED"
    assert json.loads(packet_bytes)["campaign_review_round"] == \
        rstate["round"]


def test_h0_write_surface_proof_reconstructed_baseline():
    """写面证明重建基线语义：reviewer 两写必须被机器观察到；执行者
    packet 重生成仅在「当前 packet == 最新 verdict 绑定」时豁免并披露；
    任何其余差分 fail-closed。post 快照由 postreview 落盘（未运行时跳过）。
    """
    h0 = _load_h0()
    gates = h0.entry_gates()
    chain = gates["chain"]
    r0 = h0.round0_facts(chain)
    cid = h0.derive_campaign_id(chain, r0)
    post = h0.campaign_dir(cid) / "executor_state" / \
        "post_review_write_surface.json"
    if not post.is_file():
        pytest.skip("postreview has not run for the live campaign yet")

    proof = h0.prove_write_surface(cid)
    reviewer_writes = proof["reviewer_wrote_exactly"]
    assert f"h_campaign/{cid}/reviews.jsonl" in reviewer_writes
    assert f"h_campaign/{cid}/verdicts/phase_entry.verdict.json" in \
        reviewer_writes
    regen = proof["executor_packet_regeneration"]
    if regen != "none":
        packet = (h0.campaign_dir(cid) / "review_packets" /
                  "phase_entry.json").read_bytes()
        assert regen["post_commitment"] == h0.sha(packet)
        assert h0.verify_ledger(cid)["verdicts"][-1][
            "input_commitment_sha256"] == h0.sha(packet)
    assert proof["frozen_annotator_domain_unchanged"] is True


def test_h0_verify_command_is_pure_read_and_passes_end_to_end():
    result = subprocess.run(
        [sys.executable,
         str(ROOT / "scripts/csr8_phase_h_entry_gate.py"), "verify"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stage"] == "H0" and payload["iteration"] == 3
    assert payload["state"] == "VERIFIED"
    assert payload["phase_entry_review"] == "APPROVE"
    assert payload["round0"]["total"] == 64
    assert payload["round0"]["completed"] == 2
    assert payload["round0"]["remaining"] == 62
    assert payload["verifier_battery"]["all_pass"] is True
    assert payload["verifier_battery"]["certified_files"] > 10563
