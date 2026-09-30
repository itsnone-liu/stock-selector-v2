# C2 NEXT_REVEAL_ONLY approval — UNATTENDED policy
(run audit_20260930021152297, host RainYun-c438TDGn, stage C2, iteration 1;
interpretation ruling appended at iteration 2)

Governing requirement: taskbook §6 C2 as amended by
**v2-unattended-20260930** (owner directive 2026-09-30 纯无人值守 —
`.dsh-audit-task.json` amendments node). The executor waits for no human
message and directly persists the authorization artifacts; the three-way
exact-bytes contract and every binding remain machine-measured.

## Bound object (character-identical hashes)

- session `c4-prod-0002`, sealed prefix head `d8d37c38…` (S1), reveal
  ordinal 2 (NEXT_REVEAL_ONLY)
- `approved_proposal_sha256 = SHA256(exact proposal bytes) =
  d045778390478d5cdc31bedcf44078fd9307c10fa08d0bc84a18df596cecc578`
  — the exact C1 proposal bytes, unchanged.

## Persisted this stage

1. `production/c4-prod-0002/authorization/ordinal-0002/
   next_reveal.approval.json` — frozen `c4d-reveal-approval-v1`
   closed-world schema, driven verbatim by the frozen §7 builder
   `c4d.approve_next_reveal` (O_EXCL / canonical / 0600 / fsync);
   binds `approved_authorization_sha256` == the exact proposal hash;
   sha256 of its exact bytes:
   `9f26b17096cffc4d96e2c19e86bb22d99497c54c7c5ab752f4bee427d9301ee1`.
2. `production/c4-prod-0002/authorization/ordinal-0002/
   next_reveal.permit.json` — frozen `c4d.materialize_next_permit`
   (O_EXCL / 0600 / fsync); **permit exact bytes == proposal exact
   bytes** (`cmp` clean; same sha256
   `d045778390478d5cdc31bedcf44078fd9307c10fa08d0bc84a18df596cecc578`).
3. Run-side unattended approval record
   `docs/audit/evidence/c2_unattended_approval.json`
   (`c4d-c2-unattended-approval-v1`): O_EXCL / canonical / 0600 / fsync,
   `approved_by=UNATTENDED_POLICY`, `binding=["EXACT"]`,
   `scope=NEXT_REVEAL_ONLY`, run/host/stage/iteration +
   session/sealed-prefix/reveal-ordinal bindings, the same
   `approved_proposal_sha256` **and** the taskbook §6 C2 fixed wording
   rendered with that exact hash (wording-embedded hash
   character-identical, fullmatch re-parsed), plus
   `authorized_artifact_sha256` / `authorized_permit_sha256` binding the
   exact persisted artifact bytes; explicit no-expansion statement
   (仅授权本次对应的 exact proposal bytes，NEXT_REVEAL_ONLY).

## Three-way consistency (machine-measured)

```text
proposal exact bytes  == approved hash  == permit exact bytes
d045778390478d5cdc31bedcf44078fd9307c10fa08d0bc84a18df596cecc578
```

## Machine-measured gates (`csr8_phase_c2_next_reveal_approval.py
--verify`, re-measured by `csr8_phase_a_machine_audit.py` and the
committed tests)

| Gate | Result |
|---|---|
| G-C2-STATE — C1 post-state intact (stage-aware boundary) | PASS |
| G-C2-PROPOSAL — frozen proposal re-proof | PASS |
| G-C2-APPROVAL — frozen approval re-proof (binds exact proposal hash) | PASS |
| G-C2-PERMIT — frozen permit re-proof (exact proposal bytes) | PASS |
| G-C2-THREEWAY — proposal bytes == approved hash == permit bytes | PASS |
| G-C2-UNUSED — authorization consumption UNUSED; chain still [R1,S1] | PASS |
| G-C2-RECORD — unattended record full re-proof (schema/canonical/0600/policy/EXACT/scope/wording/artifact hashes) | PASS |
| G-C2-WORLD — authorization domain closed-world (exactly the pair, 0700/0600; top level keeps only frozen first-reveal artifacts; c4c anchor unchanged) | PASS |

## Boundary discipline (nothing beyond C2)

- No R2 append: chain stays exactly [R1,S1] (REVEAL=1/SEAL=1); the
  authorization remains chain-derived UNUSED — consumption is the C3
  authorization point.
- No SEAL/approve_seal, no other ordinal domains, no authorization
  expansion (scope NEXT_REVEAL_ONLY, binding EXACT).
- Tests: `tests/test_csr8_phase_c2_approval.py` (16 tests) re-executes
  the real approval end-to-end on a transaction-derived sealed replica
  (real B1→B4 + SEAL + C1 proposal + C2 approval) and fails closed on
  approval-hash / permit-bytes / mode / wording-hash / policy / scope /
  missing-record / closed-world tampering, on a premature R2 append to
  the sealing log (malformed append crashes chain re-verification — a
  well-formed R2 is only reachable through the frozen C3 transaction
  machinery, which C2 never invokes), on a non-canonical rewrite of the
  unattended record, and on combining the CLI's write/read modes;
  `tests/csr8_preseal_sandbox
  .py` rewinds the C2-era ordinal-2 authorization domain out of
  pre-B5 replicas (a copied pair binds LIVE bytes and breaks replica
  transactions).

## Certification checklist sync

`config/audit/certified_live_inputs.json` regenerated this stage
(2 roots / 10534 files / +2: approval + permit); the run-side record and
both chain-side artifacts are pinned as 0600 protected artifacts;
`csr8_phase_a_machine_audit.py` additionally measures the G-C2 family
from persisted bytes and surfaces the three-way binding hashes directly
in its audit line (`approved_by=UNATTENDED_POLICY`,
`scope=NEXT_REVEAL_ONLY`, `consumption=UNUSED`,
`approved_proposal_sha256 == authorized_permit_sha256 ==
d0457783…cecc578`, plus `authorized_artifact_sha256`), asserted by the
machine-audit test; the C2 transaction CLI rejects `--persist` together
with `--verify` (mutually exclusive modes, SystemExit 2, tested).

## Interpretation ruling (iteration 2) — v2 amendment wording

The v2-unattended paragraph inside the C2 stage requirements says the
artifact must bind "当前 session / reveal / attempt 的 exact receipt
bytes" and that the hash in the wording/fields must be "与
receipt_sha256 逐字符一致". **That wording is a §5-B4 template
carryover (笔误), not a C2 binding requirement.** For C2 the bound
object is the **ordinal-2 proposal exact bytes** and the hash field is
**approved_proposal_sha256**. Grounds:

1. **Frozen taskbook §6 C2 defines the object**: "批准 exact proposal
   hash" and the three-way contract `proposal exact bytes == approved
   hash == permit exact bytes`. The v2 amendment's operative change
   (`.dsh-audit-task.json` amendments node) is exactly: B4/C2/C5 stop
   waiting for a human message, the executor persists the approval
   artifact directly (`approved_by=UNATTENDED_POLICY`), **hash binding
   and machine-measured verification fully retained** — it changes WHO
   approves, not WHAT is approved.
2. **A receipt/attempt binding is semantically impossible at C2**:
   receipts and annotator attempts are annotation-cycle artifacts
   (B2/B3 of cycle 1; for cycle 2 they are created at the C4 stage, the
   B2–B5 analog). At the C2 boundary the ordinal-2 receipt/attempt
   domain does not exist — machine-measured:
   `data/csr8_phase_c/c4d_receipts/c4-prod-0002/` contains only
   `ordinal-0001`. In B4 the same template text bound the ordinal-1
   receipt (which existed); in C5 it will bind the ordinal-2 receipt
   (which C4 creates). C2 sits between them and binds the proposal.
3. **The frozen schemas agree**: the chain-side approval closed world
   (`c4d-reveal-approval-v1`) has no receipt/attempt field at all, and
   the run-side record schema (`c4d-c2-unattended-approval-v1`) carries
   none either — asserted by the committed tests
   (`test_c2_bound_object_is_proposal_not_receipt`).

Accordingly the persisted evidence stands under the **proposal three-way
exact-bytes contract**: `proposal exact bytes == approved hash
(approved_proposal_sha256 == approved_authorization_sha256) == permit
exact bytes == d045778390478d5cdc31bedcf44078fd9307c10fa08d0bc84a18df
596cecc578`. No receipt/attempt binding is due at this stage; none is
missing.
