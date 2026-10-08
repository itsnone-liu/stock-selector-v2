# CSR-8 NC-FIX2 — Finalize National-Capital Extension and Resume Phase H

## Baseline

Repository:

```text
itsnone-liu/stock-selector-v2
main @ 16665f899cb097d68a3a7f088ee29fc633119c9f
```

Current immutable production boundary:

```text
R1,S1,R2,S2,R3,S3
REVEAL=3
SEAL=3
open_reveals=0
candidate_prefix=3

production_head:
37f625beec6ca022a791bfc26e99d6fbc38943b8a5a43e6fce14fc2b0ca198a8
```

Do not create R4/S4 until this task reaches `READY_FOR_ORDINAL_4`.

---

## Goal

Close the last proof gaps in NC-FIX1, build the blinded `NATIONAL_CTX_V1` sidecar, independently audit/freeze the extension, then reopen Phase H from ordinal 4.

This is the last H-PRE task. Do not expand scope.

---

# A. Strengthen the 84×22 coverage proof

Modify:

```text
scripts/build_holdings_coverage_ledger.py
```

Current defect:

```text
sha_verified = bool(meta contains sha256)
```

This is not byte verification.

Required:

1. Derive the corresponding raw `.json` from each `.meta.json`.
2. Require raw file exists.
3. Recompute `SHA256(raw bytes)`.
4. Require recomputed hash equals `meta.sha256`.
5. Detect duplicate `(stock_code, report_period)` request cells.
6. PASS iff:

```text
expected_cells = 1848
ledger_cells = 1848
duplicate_request_cells = 0
missing = 0
failed = 0
raw_sha_verified_cells = 1848
all cells = SUCCESS_NONEMPTY | SUCCESS_EMPTY
```

Keep:

```text
SUCCESS_EMPTY
→ absence_semantics=UNKNOWN
```

Never convert it to absence evidence.

---

# B. Strengthen NC0 production invariance

Modify:

```text
scripts/verify_nc0_invariance.py
```

Current defect:

```text
candidate_commitment_unchanged
```

compares the anchor against a hard-coded commitment.

Required live derivation:

```python
live_order = c4d.candidate_total_order()
live_commitment = sha256(c4d.canon(live_order).encode())
live_commitment == anchor.candidate_order_commitment
```

Also run real machine replay:

```text
C2 full replay PASS
semantic_replay PASS
ordinal 1 history seal-bound PASS
ordinal 2 history seal-bound PASS
ordinal 3 history seal-bound PASS
```

Final checks must contain:

```text
chain_exact
counts
head_unchanged
candidate_prefix_unchanged
candidate_order_size_unchanged
candidate_commitment_unchanged
c2_full_replay
semantic_replay
ordinal_1_to_3_history
no_r4_s4
```

No hard-coded PASS booleans.

---

# C. Make actor matching actually registry-driven

Modify:

```text
scripts/normalize_national_capital_history.py
```

Remove runtime hard-coded matching such as:

```python
if "中央汇金" in name
if "社保基金" in name
...
```

Required policy:

```text
1. exact alias match
2. declared wrapper_rules from
   config/csr/national_actor_registry_v1.json
3. otherwise UNMATCHED
```

Compile and execute only the frozen registry rules.

Machine gates:

```text
all actor_id targets exist
no duplicate exact alias maps to different actors
wrapper rule IDs unique
wrapper target IDs valid
unknown names remain UNMATCHED
LLM never classifies at runtime
```

The registry filename may remain `national_actor_registry_v1.json`;
its internal schema version is already v2.

---

# D. Fix ETF availability boundary semantics

Modify:

```text
scripts/join_etf_lineage.py
```

Current problem:

```text
available_date = "UNAVAILABLE_AFTER_CALENDAR"
```

is a status embedded in a date field, and the readiness check sees it as truthy.

Required fields:

```text
available_date
availability_status
raw_sha256
```

Rules:

```text
if next frozen trading day exists:
    available_date = YYYY-MM-DD
    availability_status = AVAILABLE_PIT

if no next frozen trading day exists:
    available_date = ""
    availability_status = OUTSIDE_FROZEN_CALENDAR
```

The out-of-calendar case is allowed only at the frozen calendar tail.

Also verify raw lineage by bytes:

```text
SHA256(raw exchange response)
==
meta.sha256
==
row.raw_sha256
```

Do not merely copy the SHA string from metadata.

Readiness must require:

```text
all context-eligible rows:
  availability_status=AVAILABLE_PIT
  valid ISO available_date
  raw SHA verified

tail rows:
  availability_status=OUTSIDE_FROZEN_CALENDAR
  available_date empty
  never enter H context
```

---

# E. Replace remaining “manual review” with auditable statuses

Update:

```text
scripts/production_readiness_check.py
docs/research/NATIONAL_CAPITAL_SIDECAR_PRODUCTION.md
```

The final report must not have `manual_review_required`.

Use:

```text
nonblocking_limitations
```

and record:

```text
50 empty holdings cells:
  UNAVAILABLE
  absence_semantics=UNKNOWN
  nonblocking=true

publication date source:
  SECONDARY_CAPTURED
  exact raw provenance required
  official cross-check = OPTIONAL_ENRICHMENT

residual actor names:
  UNMATCHED
  excluded from actor evidence
  LLM proposal-only

SZSE ETF history:
  OPTIONAL_ENRICHMENT
  UNAVAILABLE in v1
  nonblocking=true
```

These are explicit evidence limitations, not hidden overrides.

---

# F. Publication-date provenance audit

Add:

```text
scripts/audit_publication_provenance.py
```

Do not perform random/manual spot checks.

For every row used in `national_holdings_pit.csv`:

1. `(stock_code, report_period)` must resolve to one captured publication record.
2. Captured publication raw file must exist.
3. Recompute raw SHA and bind it to `publication_raw_sha256`.
4. The exact report period and publication date must be present in the captured source response.
5. Require:

```text
available_date > publication_date
```

and `available_date` is in the frozen exchange calendar.

Output:

```text
output/research/csr/national_capital/
publication_provenance_audit.json
```

Status:

```text
PASS
```

The source grade may remain:

```text
SECONDARY_CAPTURED
```

Do not falsely label Sina metadata as official exchange evidence.

---

# G. Actor-registry audit

Add:

```text
scripts/audit_national_actor_registry.py
```

Output:

```text
registry_sha256
actor_count
alias_count
wrapper_rule_count
duplicate_aliases
invalid_wrapper_targets
matched_actor_rows
unmatched_holder_name_count
status
```

`UNMATCHED` is allowed and nonblocking.

It must not be silently classified.

---

# H. Build blinded NATIONAL_CTX_V1 sidecar

Add:

```text
scripts/build_national_capital_context.py
```

Usage:

```text
python3 scripts/build_national_capital_context.py \
  --ordinal 4 \
  --out <path>
```

The builder runs selector-side.

It may internally resolve:

```text
opaque_case_id → frozen case stock code
```

but the output must never contain that identity.

Input authorities:

```text
candidate_for_ordinal(n)
national_holdings_pit.csv
holdings_coverage_ledger.csv
etf_share_daily_sse.csv
national_actor_registry_v1.json
frozen exchange calendar
```

Output closed-world top level:

```json
{
  "context_version": "csr8-national-capital-v1",
  "evidence_profile": "BASE_V1+NATIONAL_CTX_V1",
  "ordinal": 4,
  "packet_id": "<existing frozen packet id>",
  "as_of": {
    "T": "YYYY-MM-DD",
    "availability_rule": "available_date<=T"
  },
  "stock_capital_records": [],
  "market_etf_records": [],
  "limitations": [],
  "source_commitments": {},
  "context_commitment_sha256": "<hash>"
}
```

`context_commitment_sha256` is defined as SHA256 of canonical JSON with
that field omitted.

Forbidden output fields/values:

```text
stock_code
stock_name
ticker
symbol
case_key
group
identity
future candidate
outcome
analysis_labeled
```

### Stock-capital records

Only use records whose:

```text
available_date <= T
actor_id != empty
pit_status = AVAILABLE_PIT
```

Recommended fields:

```text
context_record_id
capital_layer=STOCK
evidence_type=NATIONAL_ACTOR_HOLDING
actor_id
csr_actor_class
report_period
publication_date
available_date
holding_ratio
shares
previous_report_period
previous_holding_ratio
state
evidence_grade
```

State is deterministic:

```text
FIRST_DISCLOSED
INCREASE
STABLE
DECREASE
```

Do not infer `EXIT` from top-10 disappearance.

If a complete source table exists and the actor is absent, use only:

```text
NOT_DISCLOSED_IN_TOP10
```

Never `EXIT`.

### Market ETF records

Only rows with:

```text
availability_status=AVAILABLE_PIT
available_date<=T
```

ETF total-share evidence is:

```text
MARKET proxy only
actor_attribution=FORBIDDEN
```

No row may say or imply that Huijin/Zhengjin caused daily ETF share changes.

---

# I. Context determinism / blindness gates

Add:

```text
scripts/audit_national_capital_context.py
```

For ordinal 4:

1. Build context twice in separate temp paths.
2. Require byte-identical output.
3. Recompute `context_commitment_sha256`.
4. Verify every source row has `available_date<=T`.
5. Verify no forbidden identity/outcome keys.
6. Verify no ETF actor attribution.
7. Verify source commitments match current production inputs.
8. Verify ordinal 4 is exactly `candidate_for_ordinal(4)`.
9. Do not create R4.

Output:

```text
docs/audit/evidence/
national_capital_context_preflight.json
```

---

# J. Context support map contract

Add a schema/validator, not a production annotation yet:

```text
scripts/validate_context_support_map.py
```

Closed-world structure:

```json
{
  "version": "csr8-national-context-support-v1",
  "ordinal": 4,
  "packet_sha256": "<sha>",
  "context_sha256": "<sha>",
  "judgments": {
    "rt_H01": [],
    "rt_H02": [],
    "rt_H03": [],
    "rt_H04": [],
    "rt_H05": [],
    "rt_H06": []
  }
}
```

Each referenced `context_record_id` must exist in the sidecar.

No support map is allowed to reference a record from another ordinal.

This artifact will be produced together with the H annotation after R4;
the pre-H task only freezes the contract and validator.

---

# K. NC final machine audit

Add:

```text
scripts/nc_final_machine_audit.py
```

It must run/recompute all of:

```text
G-NC-01 actor registry deterministic
G-NC-02 raw provenance exact
G-NC-03 publication provenance PASS
G-NC-04 strict available_date > publication_date
G-NC-05 future disclosure excluded
G-NC-06 empty cells remain UNKNOWN/UNAVAILABLE
G-NC-07 actor matching registry-driven
G-NC-08 ETF actor attribution forbidden
G-NC-09 sidecar contains no identity/outcome
G-NC-10 context deterministic rebuild
G-NC-11 context commitment exact
G-NC-12 support-map contract validator PASS
G-NC-13 R1-R3 full replay unchanged
G-NC-14 production head unchanged
G-NC-15 candidate order live commitment unchanged
```

Also bind exact hashes of:

```text
actor registry
holdings coverage ledger
national_holdings_pit.csv
publication provenance audit
empty-resolution ledger/report
etf_share_daily_sse.csv
ETF lineage report
ordinal-4 preflight context
context-support-map schema/validator
NC0 pause anchor
NC0 invariance report
```

Output:

```text
docs/audit/evidence/
national_capital_context_extension_final_audit.json
```

The machine audit may say:

```text
PREREQUISITES_COMPLETE
```

but must not self-declare independent approval.

---

# L. Independent LLM final review

Create a canonical review packet containing only the final-audit facts and exact
artifact commitments.

Operation:

```text
NC_FINAL
```

Reviewer output:

```text
APPROVE | REVISE | HALT
```

The reviewer must be independent from the executor and bind the exact review
packet hash.

No human approval.

Persist the verdict in the existing append-only reviewer mechanism or a dedicated
NC review ledger with the same hash-chain semantics.

---

# M. Freeze marker

Only after:

```text
machine final audit = PREREQUISITES_COMPLETE
independent reviewer = APPROVE
live NC0 invariance = PASS
```

create:

```text
docs/audit/evidence/
national_capital_context_extension_frozen.json
```

Required fields:

```text
status = NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN
declared_by = INDEPENDENT_LLM_AUDIT
final_verdict = APPROVE

base_infra_freeze = cd7f2a5db0fddee824bd1e5ce6da0f8bcd7431ca
nc_fix1_base = 16665f899cb097d68a3a7f088ee29fc633119c9f

pause_chain = R1,S1,R2,S2,R3,S3
pause_production_head =
37f625beec6ca022a791bfc26e99d6fbc38943b8a5a43e6fce14fc2b0ca198a8

effective_from_ordinal = 4
past_ordinals_mutated = false
production_head_unchanged = true
candidate_order_unchanged = true

final_audit_sha256
review_packet_sha256
review_verdict_sha256
actor_registry_sha256
holdings_pit_sha256
etf_share_sha256
context_preflight_sha256
context_schema_version = csr8-national-capital-v1
```

---

# N. Resume gate

Add:

```text
scripts/nc_resume_h_gate.py
```

This is read-only.

It must verify:

```text
freeze marker valid
independent NC_FINAL APPROVE exact-bound
live NC0 invariance PASS
chain still R1,S1,R2,S2,R3,S3
open_reveals=0
candidate_prefix=3
candidate_for_ordinal(4) available
ordinal-4 context deterministic preflight PASS
```

Only output:

```json
{
  "state": "READY_FOR_ORDINAL_4",
  "ordinal": 4,
  "evidence_profile": "BASE_V1+NATIONAL_CTX_V1"
}
```

No mutation.

---

# O. Resume Phase H

Only after `nc_resume_h_gate.py` exits 0 with `READY_FOR_ORDINAL_4`:

1. Generalize the existing H1 ordinal executor or create ordinal-4 executor.
2. Keep original frozen packet unchanged.
3. At annotation handoff, provide:
   - frozen packet
   - exact `NATIONAL_CTX_V1` sidecar
4. Executor LLM creates:
   - annotation draft under frozen H01-H06 contract
   - `context_support_map.json`
5. ANNOTATION reviewer input commitment binds:

```text
packet_sha256
context_commitment_sha256
context_support_map_sha256
draft_sha256
```

6. Existing receipt/SEAL schema remains unchanged.
7. Reviewer ledger provides the sidecar/draft binding.
8. Complete:

```text
R4 → annotation + context → receipt → S4
```

9. Verify final chain:

```text
R1,S1,R2,S2,R3,S3,R4,S4
```

10. From ordinal 4 onward:

```text
evidence_profile = BASE_V1+NATIONAL_CTX_V1
```

---

# Hard stop

Do not append R4 if any NC final gate is incomplete.

Do not rewrite R1-R3.

Do not modify frozen C1/C3 packet bytes.

Do not change the frozen C4-D annotation/receipt/SEAL schema.

Do not treat `UNAVAILABLE` as negative evidence.

Do not attribute ETF total-share changes to a named national-capital actor.
