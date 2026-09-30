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

## Iteration-2 commit chain (stage-terminal consolidation)

The authorization artifacts (approval / permit / unattended record) are
byte-identical since cd0571e (iteration 1); every later commit is
reviewer-facing hardening with no further state change:

| commit | content |
|---|---|
| cd0571e | the C2 transaction: approval + permit + unattended record, tests, manifest, evidence (iteration 1) |
| 4a7e39d | iteration-2 interpretation ruling (bound object = proposal, not receipt) + machine pinning test |
| 460f151 | machine-audit c2 section surfaces the three-way binding hashes; C2 CLI mode mutual exclusion |
| e295d14 | CLI mutual-exclusion test + audit-surface evidence note |
| 80d2fe2 | fail-closed tests: premature R2 append, non-canonical record |
| 1641e5b | evidence doc test-inventory sync (16 C2 tests) |
| 97c0812 | module docstring records the bound-object ruling |

Terminal state at each of these commits is identical where it matters:
8/8 G-C2 gates PASS, three-way hash chain intact
(`d0457783…cecc578`), authorization UNUSED, chain [R1,S1], full suite
green (539 passed / 0 failed at 80d2fe2 and later).

Byte-identity machine-check (recorded at 30579ad):
`git diff cd0571e..30579ad -- <approval> <permit> <unattended record>`
is EMPTY — the three authorization artifacts are byte-identical across
the whole iteration-2 chain; only gates, tests, and documentation
moved.

## Authoritative freeze clarification (iteration 3)

**正式更正：C2 v2 中的 `session / reveal / attempt`、`exact receipt
bytes` 与 `receipt_sha256` 是 B4 文案沿用笔误。C2 应正式解释为：绑定
`ordinal-2 proposal exact bytes`，措辞与字段中的 hash 绑定
`approved_proposal_sha256`。** 这不是把一个尚未实现的 receipt 绑定降级，
而是确定 C2 的正确被批准对象；冻结 §6 C2 原文已经明确“批准 exact
proposal hash”及三方一致合同。

为避免歧义，C2 不绑定任何 receipt 或 attempt：在 C2 边界
`c4d_receipts/c4-prod-0002/ordinal-0002/` 不存在。cycle-2 的 receipt
及其 attempt 属于后续 C4 注释/annotation 阶段产物；它们既不能在 C2
被读取，也不能替代 C2 proposal 作为授权对象。B4 的 receipt 绑定适用于
B4，未来 C5 对已由 C4 产生的 cycle-2 receipt 的绑定适用于 C5，二者均
不改变 C2 的 proposal 语义。

因此三方合同的字段对应关系是唯一且同时成立的：

```text
proposal exact bytes
  == SHA256(proposal exact bytes) == approved_proposal_sha256
  == approved_authorization_sha256   (chain-side approval field)
  == SHA256(permit exact bytes)
permit exact bytes == proposal exact bytes
```

这里 `receipt_sha256` 不参与 C2 合同；要求 receipt/attempt 在 C2 同时
存在会与阶段边界及冻结 approval schema 冲突。该裁定由
`test_c2_bound_object_is_proposal_not_receipt`、冻结 schema 的闭世界校验、
C2 的 G-C2-THREEWAY 及 machine audit 共同钉住。

## Iteration-5 re-verification

For `audit_20260930021152297` / C2 / iteration 5, the live transaction was
re-verified from persisted bytes with `csr8_phase_c2_next_reveal_approval.py
--verify`: all eight G-C2 gates passed, `approved_by=UNATTENDED_POLICY`,
`scope=NEXT_REVEAL_ONLY`, and authorization consumption remained `UNUSED`.
The observed three-way value remained
`d045778390478d5cdc31bedcf44078fd9307c10fa08d0bc84a18df596cecc578`.
No C3 append or other stage action was performed.
