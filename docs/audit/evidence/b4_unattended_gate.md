# B4 exact-hash approval — UNATTENDED policy
(run audit_20260930021152297, host RainYun-c438TDGn, stage B4, iteration 1)

Governing requirement: taskbook §5 B4 as amended by
**v2-unattended-20260930** (owner directive 2026-09-30 纯无人值守 —
`.dsh-audit-task.json` amendments node). The executor waits for no human
message and directly persists the approval artifacts; the preauthorization
节 (PREAUTH v1) mechanism was removed from the bridge code with it.

## Bound object (character-identical hashes)

- session `c4-prod-0002`, reveal
  `b5ec0ba1d485219fd7a2198b23e7ac0f979c23d4dd0cced16faa80d8f19437d5`,
  ordinal-0001 / attempt-0001
- `receipt_sha256 = SHA256(exact receipt.json bytes) =
  85a224a3e748b569060a14aea8fe5fe353b62e8a804e0f43cfb4c51a18063aa6`

## Persisted this stage

1. Chain-side `seal_approval.json` (frozen `c4d-seal-approval-v1`
   closed-world schema) — already the immutable O_EXCL artifact on the
   live chain, re-proven to bind the exact receipt bytes above
   (`approved_receipt_sha256` character-identical);
   sha256 of its exact bytes:
   `110e01d6709c08cac28dddf55bdaf8ab9f75f735ac11fb51cbbe8a69b0a9c0c9`.
2. Run-side unattended approval record
   `docs/audit/evidence/b4_unattended_approval.json`
   (`c4d-b4-unattended-approval-v1`): O_EXCL / canonical / 0600 / fsync,
   `approved_by=UNATTENDED_POLICY`, `binding=["EXACT"]`,
   `scope=SEAL_ANNOTATION_ONLY`, run/host/stage/iteration +
   session/reveal/attempt bindings, the same
   `approved_receipt_sha256` **and** the taskbook §5 B4 fixed wording
   rendered with that exact hash, plus `authorized_artifact_sha256`
   binding the exact `seal_approval.json` bytes; explicit no-expansion
   statement (仅授权本次对应的 exact receipt bytes).

## Machine-measured gates (`csr8_phase_b4_human_approval.py --verify`)

| Gate | Result |
|---|---|
| G-B4-RECEIPT_HASH_EXACT | PASS |
| G-B4-APPROVAL_ARTIFACT_BINDING | PASS |
| G-B4-APPROVED_BY_UNATTENDED_POLICY | PASS |
| G-B4-WORDING_HASH_CHAR_IDENTICAL | PASS |
| G-B4-NO_AUTHORIZATION_EXPANSION | PASS |
| G-B4-CLOSED_WORLD_CANONICAL | PASS |
| G-B4-FROZEN_REPROOF | PASS |
| G-B4-O_EXCL_0600_FSYNC | PASS |

`csr8_phase_a_machine_audit.verify_b4_approval_domain()` re-proves the
same gates through the audit entry point (b4_approval PRESENT, all 8
PASS); `verify_b3_receipt_domain()` PASS (B1–B3 chain intact);
`verify_certified_tree()` zero drift (10532 files) vs the committed
`config/audit/certified_live_inputs.json` (regenerated this stage,
byte-identical).

## Commit-included tests (tests/test_csr8_phase_a.py, B4 section)

- live unattended approval binds the exact receipt hash in both the
  approval artifact and the record, wording hash character-identical,
  0600 permission bits, canonical bytes for both artifacts;
- unattended persist is one-shot (O_EXCL) on the real domain;
- PREAUTH v1 mechanism removed from executable bridge code (artifact
  dependency / schema / entry points absent);
- end-to-end transaction on a tmp copy (frozen `make_seal_approval`
  path) then fail-closed tamper matrix: wording drift, embedded-hash
  drift, receipt-hash drift, approved_by drift, binding widening,
  authorized-artifact hash drift, wrong run, non-canonical bytes,
  0600→0644 mode drift — each refuses; restored baseline re-verifies
  green;
- gate fails closed without the unattended record.

## Environment incident (recorded, not silently skipped)

`tests/test_csr8_phase_a.py::test_bridge_machine_audit_script_executes_
complete_matrix` cannot run to completion in this session: the frozen
C4-C regression fixture f11 (staging-cross-fs) creates its staging dir
under `/dev/shm`, which the session sandbox (landlock) denies
(`mkdir /dev/shm/...` → Permission denied; `/dev/shm` is a normal rw
tmpfs, 3.9G free). Verified pre-existing at unmodified HEAD
(`git stash` → same failure), i.e. unrelated to this stage's changes.
Sandbox escalation was requested once and failed closed (no approval
channel available). All B4/B3-domain gates and the certified-tree check
are unaffected and measured green through the real audit functions
above.

## Historical note

The prior run's human-gate evidence (`b4_human_approval_message.txt`,
`b4_human_approval_provenance.json`, `b4_preauth_v1.json`,
`b4_session_record_excerpt.jsonl`, `b4_gate_attempts.md`,
`b4_gate_reconfirmation.txt`) stays committed as inert history; it is no
longer part of the B4 gate under amendment v2.
