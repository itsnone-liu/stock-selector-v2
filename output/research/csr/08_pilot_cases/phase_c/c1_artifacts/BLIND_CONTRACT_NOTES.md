# Blind contract notes (C1 audit record, non-normative for v1.0 design)

## Git-history disclosure note (user ruling, C1-AUDIT-FIX2 review)

Commit 4ff88d2 (superseded by 9847a20) briefly carried derived hidden-plan
aggregates (total packet count and per-group packet counts) in the public
`plan_commitment.json`. The values remain retrievable from Git history.

Decision: do NOT rewrite Git history. Instead the blind contract states:

- Annotation sessions are **packet-only**: they consume the packet delivered
  at each REVEAL and hold no access to the repository or its history.
- The evaluator side may access repository history but never joins it into
  annotation-session inputs.
- Because C1 had zero REVEAL and zero annotation before the values were
  removed, no experiment contamination occurred (audit trail: 4ff88d2 ->
  9847a20 -> FIX2).

## Secret-domain lifecycle (FIX2, authoritative behavior)

- `salt_commitment` frozen + salt present  -> `salt` command = verify no-op.
- `salt_commitment` frozen + salt missing  -> FAIL-CLOSED (a hash cannot be
  reversed; regeneration would redefine the frozen identity space).
- commitment absent + salt present          -> FAIL-CLOSED (never establish
  a frozen fact from an unknown-origin secret).
- `plan_commitment` frozen + plan present   -> `plan` = double check no-op
  (stored bytes AND recomputation must equal the commitment).
- `plan_commitment` frozen + plan missing   -> deterministic recovery ONLY
  if recompute == commitment; otherwise FAIL. The commitment is NEVER
  rewritten by any command.
