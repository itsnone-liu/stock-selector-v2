# B4 human gate attempts — run audit_20260930010058058 (stage B4, iteration 1)

Bound session artifacts: session c4-prod-0002, reveal
b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5,
ordinal-0001 / attempt-0001.
receipt_sha256 = SHA256(exact receipt.json bytes) =
85a224a3e748b569060a14aea8fe5fe353b62e8a804e0f43cfb4c51a18063aa6.

| # | Human reply | Machine verdict |
|---|---|---|
| 1 | fixed wording, hash slot = `b5ec0ba1…37d5` (the REVEAL_PACKET head hash — wrong artifact) | REFUSED `G-B4-APPROVAL: message hash mismatch vs exact receipt bytes; refusing persistence`; no artifact written |
| 2 | byte-identical to #1 (message sha256 `77f417cc…0a3`) | REFUSED (same fail-closed check); no artifact written |
| 3 | fixed wording, hash slot = `85a224a3…63aa6` (character-identical to receipt_sha256) | ACCEPTED → persisted `seal_approval.json` (O_EXCL / canonical / 0600 / fsync) + provenance |

Accepted message (verbatim transcription, exact bytes in
`b4_human_approval_message.txt`, sha256 `3fcdd036…3caf`):

```
我明确批准 SEAL_ANNOTATION_ONLY receipt exact hash:
85a224a3e748b569060a14aea8fe5fe353b62e8a804e0f43cfb4c51a18063aa6

该批准仅授权当前 session / reveal / attempt 所绑定的
这一份 exact receipt bytes，不授权任何其他 receipt、REVEAL、
outcome 或 next ordinal。
```

Run-2 context: its B4 commit (8a98386) persisted from a HARDCODED
in-script "approval message" (executor self-approval, forbidden); the
artifact was removed from the live tree and this run re-executed the
gate with the real bound-session human exchange above. The in-script
message constant no longer exists in
`scripts/csr8_phase_b4_human_approval.py`.

## Machine record (iteration 2 fix)

Iteration 1 was rejected because the committed evidence was an
executor transcription/claim. Iteration 2 binds the approval to the
harness's own machine session record (same host as the audit bridge):

- session store: `/root/.dsh/sessions/--root-project-workspace-stock-selector-v2--/session-5d158168-d2f9-444e-b5bc-9a4587f77b97/session.jsonl.zstd`
  (record id `session-5d158168-d2f9-444e-b5bc-9a4587f77b97`)
- attempt 1 — `user/message` line 2308, seq 27914, time
  1790730735705 (2026-09-30T01:12:15.705Z), message sha256
  `77f417cc85bf3bd72ee8663d5504fc6a96111d0610aefcd2cf6b53f1d93dd0a3`
  → machine-refused (wrong hash)
- attempt 2 — line 2474, seq 30259, time 1790730773604
  (2026-09-30T01:12:53.604Z), byte-identical to attempt 1 →
  machine-refused
- attempt 3 (ACCEPTED) — line 2580, seq 31712, time 1790730797763
  (2026-09-30T01:13:17.763Z), message sha256
  `3fcdd036301611c9419489d88e785fb682a6cc266213b65162ade59c72b03caf`
  == SHA256(`b4_human_approval_message.txt` exact bytes)
- temporal order: human message 01:13:17.763Z → seal_approval.json +
  provenance persisted `recorded_at` 2026-09-30T01:13:49Z

Artifacts: `b4_session_record_excerpt.jsonl` carries the three
transcript lines VERBATIM (per-line sha256 pinned in
`b4_preauth_v1.json`); `b4_preauth_v1.json` is the PREAUTH v1 record
(verbatim wording + message provenance + expiry 24h) per the frozen
task-packet preauthorization clause.
`csr8_phase_b4_human_approval.py --verify` re-proves everything from
persisted bytes and additionally locates seq 31712 in the LIVE session
store (gate `session_record_live`), failing closed on any drift.
