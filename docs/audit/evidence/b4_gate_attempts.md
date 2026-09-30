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
