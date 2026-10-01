"""Phase H H0 entry-gate script: end-to-end machine checks.

The H0 gate (taskbook v1.1 §8/§31) is executor-run and reviewer-approved;
these tests pin the PERSISTED campaign state so the pure-read `verify`
path keeps passing against the live frozen tree:

- the review ledger + PHASE_ENTRY verdict stay well-formed, hash-chained,
  bound to the exact packet bytes, and reviewer-independent. Expectations
  are derived structurally from the append-only ledger (§6/§15): prior
  REVISE rounds persist forever, so counts are never pinned to a
  fresh-campaign happy path (fast checks, no full-tree hashing);
- iteration 4: reviewer independence is transcript-anchored (harness
  session storage is outside the executor's writable sandbox); the battery
  runs in-process with ZERO certifying/auditing subprocesses and ZERO
  forbidden-zone byte access;
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


def _live_campaign(h0):
    gates = h0.entry_gates()
    chain = gates["chain"]
    r0 = h0.round0_facts(chain)
    cid = h0.derive_campaign_id(chain, r0)
    assert h0.campaign_dir(cid).is_dir()
    return gates, chain, r0, cid


def test_h0_ledger_and_verdict_are_persisted_and_independent():
    h0 = _load_h0()
    gates, chain, r0, cid = _live_campaign(h0)

    ledger = h0.verify_ledger(cid)
    # append-only lifecycle: genesis + every persisted reviewer round. The
    # counts are DERIVED, never pinned to a fresh-campaign happy path —
    # prior REVISE rounds stay in the ledger forever (§6/§15). The
    # iteration-4 campaign is a fresh round-1 review (the iteration-3
    # campaign with rounds 1-3 lives under h_campaign_archive).
    assert ledger["records"] >= 2
    verdicts = ledger["verdicts"]
    assert len(verdicts) >= 1
    assert [v["sequence"] for v in verdicts] == list(
        range(1, len(verdicts) + 1))
    for verdict_line in verdicts:
        assert verdict_line["operation"] == "PHASE_ENTRY"
        assert verdict_line["ordinal"] == 3
        assert verdict_line["campaign_id"] == cid
        # v2 schema: every reviewer round carries its own harness session
        assert verdict_line["reviewer_session_id"] not in (
            "", h0.EXECUTOR_SESSION_ID, h0.GENESIS_REVIEWER)
    reviewer_ids = [v["reviewer_run_id"] for v in verdicts]
    assert h0.EXECUTOR_RUN_ID not in reviewer_ids
    assert len(set(reviewer_ids)) == len(reviewer_ids)  # independent each round

    # the persisted verdict file is the LATEST ledger round and binds the
    # exact CURRENT packet bytes (§5) — no superseded binding may survive
    verdict = h0.verify_verdict_file(cid, verdicts)
    assert verdict["state"] == "APPROVE"
    assert verdict["issues"] == [] and verdict["required_changes"] == []
    assert verdict["reviewer_run_id"] == verdicts[-1]["reviewer_run_id"]
    assert verdict["reviewer_session_id"] == \
        verdicts[-1]["reviewer_session_id"]
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

    # iteration-3 campaign archived whole, never deleted (§6/§15 policy)
    arch = h0.CSR / "h_campaign_archive"
    superseded = [d for d in arch.iterdir()
                  if d.name.startswith("hc-c88d2a507bcf569da372deadf4c4ec39"
                                       "--superseded-")] if arch.is_dir() \
        else []
    assert superseded, "iteration-3 campaign must be archived, not deleted"
    archived_ledger = superseded[0] / "reviews.jsonl"
    assert len(archived_ledger.read_text().splitlines()) == 4
    assert (superseded[0] / "SUPERSESSION.json").is_file()


def test_h0_round_bookkeeping_is_as_of_round():
    """as-of-round 簿记：reviewer 合法追加 verdict 不得使持久化
    manifest/packet 漂移；最新 verdict 必须绑定当前 packet 字节。"""
    h0 = _load_h0()
    gates, chain, r0, cid = _live_campaign(h0)

    rstate = h0.campaign_round_state(cid)
    assert rstate["packet_exists"] is True
    assert rstate["round"] >= 1
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
    gates, chain, r0, cid = _live_campaign(h0)
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


def test_h0_reviewer_independence_is_transcript_anchored():
    """iteration-4 核心修复：reviewer 独立性锚定 harness 会话 transcript。

    写入者会话由 transcript 机器发现（tool-call 参数含 verdict/ledger 写
    标记）；全部写入者 origin=subagent 且非执行者会话；执行者 transcript
    负检；会话存储机器探测不可写；transcript sha 钉定。"""
    h0 = _load_h0()
    gates, chain, r0, cid = _live_campaign(h0)
    ledger = h0.verify_ledger(cid)
    verdict = h0.verify_verdict_file(cid, ledger["verdicts"])

    proof = h0.prove_reviewer_independence(cid, verdict, ledger)
    writers = proof["writer_sessions"]
    assert writers, "writer sessions must be machine-discovered"
    for w in writers:
        assert w["origin"] == "subagent"
        assert w["session_id"] != h0.EXECUTOR_SESSION_ID
        assert (w["wrote_verdict"] or w["appended_ledger"]) is True
        assert len(w["transcript_sha256"]) == 64
        from pathlib import Path as _P
        assert _P(w["transcript_file"]).is_file()
    assert proof["executor_session_is_writer"] is False
    assert proof["executor_session_scanned"] is True
    assert proof["all_writers_subagent_origin"] is True
    assert proof["storage_probe"][
        "executor_cannot_write_or_edit_transcripts"] is True
    # the verdict's self-declared session id is among the discovered writers
    assert verdict["reviewer_session_id"] in {w["session_id"] for w in writers}
    assert proof["sessions_scanned"] >= 1


def test_h0_battery_runs_in_process_with_zero_subprocess_escape():
    """iteration-4 核心修复：电池零子进程、零禁区字节访问。

    * certify / machine-audit / C6 整树拷贝脚本永不运行、永不导入；
    * restricted anchor 只哈希 review-surface 条目，禁区条目仅计数；
    * C6 受限重放排除的只有 crash-recovery 机制重模拟，且如实披露。"""
    h0 = _load_h0()
    gates, chain, r0, cid = _live_campaign(h0)
    import re
    src = (ROOT / "scripts/csr8_phase_h_entry_gate.py").read_text()
    # the audit-layer tools are neither RUN nor IMPORTED anywhere; their
    # names may appear only inside the frozen-boundary drift file list
    # (gate_frozen_infra_clean's git diff path set)
    for forbidden_call in (
            r"subprocess\.run\([^)]*csr8_phase_a_certify_inputs",
            r"subprocess\.run\([^)]*csr8_phase_a_machine_audit",
            r"subprocess\.run\([^)]*csr8_phase_c6_seal_s2",
            r"load_module\([^)]*csr8_phase_a_certify_inputs",
            r"load_module\([^)]*csr8_phase_a_machine_audit",
            r"load_module\([^)]*csr8_phase_c6_seal_s2"):
        assert re.search(forbidden_call, src) is None, forbidden_call
    # every spawned subprocess is a git invocation
    for m in re.finditer(r"subprocess\.run\(\[(.*?)\]", src):
        assert m.group(1).strip().strip("'\"").startswith("git"), m.group(1)

    batt = h0.battery()
    assert batt["subprocesses_spawned"] == 0
    anchor = batt["certified_anchor"]
    assert anchor["verified_entries"] > 5000
    assert anchor["deferred_forbidden_zone_entries"] >= 1
    assert "never opened" in anchor["anchor_scope"]
    assert anchor["review_zone_closed_world"] == "PASS"
    c6 = gates["c6_dual_cycle"]
    assert c6["crash_recovery"] == "RESULT-INVARIANTS-PASS"
    assert "AUDIT-LAYER-DEFERRED" == c6["outcome_untouched"]
    assert "never run" in c6["execution_isolation"]
    guard = h0.ForbiddenReadGuard()
    h0.GUARD = guard
    with guard:
        h0.battery()
        h0.entry_gates()
    assert guard.violations == []
    zones = guard.summary()["opened_paths_by_zone"]
    assert "outcomes" not in zones and "analysis_labeled" not in zones
    assert guard.summary()["exempted_processes"].startswith("none")


def test_h0_verify_command_is_pure_read_and_passes_end_to_end():
    result = subprocess.run(
        [sys.executable,
         str(ROOT / "scripts/csr8_phase_h_entry_gate.py"), "verify"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["stage"] == "H0" and payload["iteration"] == 4
    assert payload["state"] == "VERIFIED"
    assert payload["phase_entry_review"] == "APPROVE"
    assert payload["independence_transcript_proof"] == "PASS"
    assert payload["round0"]["total"] == 64
    assert payload["round0"]["completed"] == 2
    assert payload["round0"]["remaining"] == 62
    assert payload["verifier_battery"]["all_pass"] is True
    assert payload["verifier_battery"]["subprocesses_spawned"] == 0
    # restricted-zone anchor: review-surface entries verified in-process
    # (the full-tree count belongs to the audit layer, not Phase H)
    assert payload["verifier_battery"]["certified_files"] > 5000
    # frozen taskbook checklist surfaced item-by-item in the pure-read
    # verify output (audit hash ddeb1ec260fa expectations, fail-closed)
    c = payload["taskbook_checklist"]
    assert c["taskbook_sha256_binding"] == "PASS"
    assert c["production_infra_final_frozen_status"] == \
        "FINAL VERDICT: APPROVE"
    assert c["production_infra_freeze_commit"] == \
        "cd7f2a5db0fddee824bd1e5ce6da0f8bcd7431ca"
    assert c["marker_bound_to_freeze_commit"] == "PASS"
    assert c["chain_sequence"] == ["REVEAL_PACKET", "SEAL_ANNOTATION",
                                   "REVEAL_PACKET", "SEAL_ANNOTATION"]
    assert (c["reveal_count"], c["seal_count"], c["open_reveals"],
            c["candidate_prefix"]) == (2, 2, 0, 2)
    assert c["c2_full_replay"] == "PASS"
    assert c["r1_s1_exact_replay"] == "PASS"
    assert c["r2_s2_exact_replay"] == "PASS"
    assert c["ordinal1_history"] == "PASS"
    assert c["ordinal2_history"] == "PASS"
    assert c["authorization1"] == "CONSUMED"
    assert c["authorization2"] == "CONSUMED"
    assert c["forensic_state"] == "NONE"
    assert c["forensic_findings"] == 0
    assert c["G5"] == "BLOCKED" and c["XP"] == "BLOCKED_FOR_PIT"
    assert (c["round0_total"], c["round0_completed"],
            c["round0_remaining"]) == (64, 2, 62)
    assert c["campaign_id"] == payload["campaign_id"]
    assert c["campaign_manifest"] == "PERSISTED"
    assert c["review_ledger_genesis"] is True
    assert c["ordinal3_proposal_staged"] is True
    assert c["frozen_infra_zero_drift"] == "PASS"
    assert payload["reviewer_session_id"]
    # the same checklist is PERSISTED in the committed evidence file
    ev = json.loads((ROOT / "docs/audit/evidence/h_phase_entry_gate.json"
                     ).read_bytes())
    ec = ev["taskbook_checklist"]
    assert ec["chain_sequence"] == c["chain_sequence"]
    assert ec["production_infra_freeze_commit"] == \
        c["production_infra_freeze_commit"]
    assert (ec["round0_total"], ec["round0_completed"],
            ec["round0_remaining"]) == (64, 2, 62)
    assert ec["authorization1"] == "CONSUMED"
    assert ec["ordinal3_proposal_staged"] is True
