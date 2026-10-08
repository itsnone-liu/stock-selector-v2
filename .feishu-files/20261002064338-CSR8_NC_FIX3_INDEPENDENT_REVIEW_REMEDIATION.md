# CSR-8 NC-FIX3 — Independent NC_FINAL Remediation and H Resume

## Audit target

```text
repo: itsnone-liu/stock-selector-v2
branch: main
audited commit:
72cd37831765b483adf8bba753c882a46656d79a
```

Independent review verdict:

```text
NC_FINAL = REVISE
```

Phase H must remain paused at:

```text
R1,S1,R2,S2,R3,S3
candidate_prefix = 3
NO R4
NO S4
```

No existing R1–R3 artifact may be changed.

---

# 1. P0 — Real C2 replay is still missing

File:

```text
scripts/verify_nc0_invariance.py
```

Current implementation sets:

```text
c2_full_replay = (event_types == anchor.production_chain)
```

This is not C2 replay.

Required:

```python
lg = c4d.c2.SealingLog(
    c4d.log_path(CSR, c4d.REAL_SESSION),
    c4d.head_path(CSR, c4d.REAL_SESSION),
)
c4d.c2translate(lg.load().verify, True)
```

`c2_full_replay=true` may be emitted only if that verification succeeds.

Keep separate:

```text
chain_exact
c2_full_replay
semantic_replay
ordinal_1_to_3_history
```

Negative:
- corrupt log byte -> C2 replay FAIL
- corrupt head -> C2 replay FAIL
- same event-type sequence with wrong bytes -> must FAIL

---

# 2. P0 — NATIONAL_CTX_V1 is not candidate-specific

File:

```text
scripts/build_national_capital_context.py
```

Current implementation loads all rows in `national_holdings_pit.csv` whose
`available_date <= T`.

That mixes holdings from all 84 frozen stocks into ordinal-4 context.

Required selector-side derivation:

```text
ordinal
→ c4d.candidate_for_ordinal(ordinal)
→ opaque_case_id + T
→ resolve opaque_case_id against frozen C1 cases using frozen salt
→ exactly one internal stock_code
→ filter holdings to that stock only
```

The resolved stock identity is selector-only and must never enter sidecar bytes.

Do not trust caller-provided packet identity.

Recommended CLI:

```text
build_national_capital_context.py --ordinal 4 --out ...
```

Internally derive:

```text
candidate
T
packet_id
stock_code(selector-only)
```

If optional `--packet-id` or `--as-of` are retained for tests, require exact equality
with the internally derived values or fail.

Negative:
- wrong packet_id -> FAIL
- wrong T -> FAIL
- wrong ordinal/candidate mapping -> FAIL
- holdings for any other stock entering sidecar -> FAIL

---

# 3. P0 — Stock capital state is currently hard-coded

Current sidecar writes:

```text
state = FIRST_DISCLOSED
```

for every holding row.

Required current-state projection for the current candidate stock at T.

For each matched actor:

```text
latest PIT-safe disclosure <= T
previous PIT-safe disclosure before latest
```

Derive deterministically:

```text
FIRST_DISCLOSED
INCREASE
STABLE
DECREASE
NOT_DISCLOSED_IN_TOP10
UNKNOWN
```

Rules:

```text
latest present, no usable previous
→ FIRST_DISCLOSED

latest ratio > previous ratio
→ INCREASE

latest ratio == previous ratio
→ STABLE

latest ratio < previous ratio
→ DECREASE

previous actor present,
latest complete TOP10 exists,
actor absent from latest TOP10
→ NOT_DISCLOSED_IN_TOP10

source/table incomplete
→ UNKNOWN
```

Never infer:

```text
EXIT
```

from TOP10 disappearance.

Sidecar should carry the current state, not every historical holding row.

Suggested record:

```json
{
  "context_record_id": "...",
  "capital_layer": "STOCK",
  "evidence_type": "NATIONAL_ACTOR_HOLDING_STATE",
  "actor_id": "...",
  "csr_actor_class": "...",
  "state": "INCREASE",
  "current_report_period": "...",
  "current_publication_date": "...",
  "current_available_date": "...",
  "current_holding_ratio": "...",
  "previous_report_period": "...",
  "previous_holding_ratio": "...",
  "evidence_grade": "SECONDARY_CAPTURED"
}
```

---

# 4. P1 — ETF context must be a current snapshot, not the entire history

Current builder emits every SSE ETF row whose `available_date <= T`.

That can produce thousands of records and does not express the current market state.

For each tracked ETF, emit only a bounded PIT-safe summary.

Minimum:

```text
latest row with available_date <= T
previous row before latest
```

Fields:

```text
etf_code_hash
latest_trade_date
latest_available_date
latest_total_shares
previous_trade_date
previous_total_shares
share_change
share_change_ratio
state = EXPANSION | CONTRACTION | STABLE
actor_attribution = FORBIDDEN
```

No named national actor may be attached to daily ETF share changes.

Do not use `OUTSIDE_FROZEN_CALENDAR` rows.

---

# 5. P0 — Context audit is currently too shallow

File:

```text
scripts/audit_national_capital_context.py
```

Current defects:

1. forbidden-key test only checks top-level keys;
2. `no_r4_created = true` is hard-coded;
3. does not prove `available_date <= T` for every record;
4. does not verify ETF actor-attribution firewall;
5. does not verify ordinal-4 packet/T against `candidate_for_ordinal(4)`;
6. does not prove stock records belong only to the internally resolved current case.

Required machine checks:

```text
candidate_binding_exact
packet_id_exact
as_of_exact
deterministic_bytes
context_commitment_exact
recursive_forbidden_key_scan
stock_case_isolation
all_available_date_le_T
no_outside_calendar_rows
etf_actor_attribution_forbidden
source_commitments_exact
live_chain_still_6_events
no_r4_s4
```

`no_r4_s4` must be read from the live production sealing log.

---

# 6. P0 — Support-map contract is under-bound

File:

```text
scripts/validate_context_support_map.py
```

Freeze exact closed-world schema:

```json
{
  "version": "csr8-national-context-support-v1",
  "ordinal": 4,
  "packet_sha256": "<64hex>",
  "context_sha256": "<64hex>",
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

Judgment values are lists of `context_record_id` strings.

Validator receives the sidecar separately:

```text
validate_context_support_map.py MAP --sidecar SIDECAR
```

Require:

```text
closed-world top-level keys
exact six hypotheses
ordinal matches sidecar
packet_sha256 matches actual current packet bytes
context_sha256 matches sidecar commitment
every referenced context_record_id exists
no duplicate refs
no reference to another ordinal
```

Do not put a mutable/unbound `sidecar_path` inside the frozen map contract.

Add negative fixtures:
- wrong context hash
- wrong packet hash
- unknown record id
- extra key
- missing hypothesis
- duplicate ref
- wrong ordinal

---

# 7. P0 — Final machine audit is not yet G-NC-01..15

File:

```text
scripts/nc_final_machine_audit.py
```

Current problems include hard-coded:

```text
etf_attribution_forbidden = True
no_r4_s4 = True
```

and the audit does not consume the ordinal-4 preflight or support-map contract proof.

The final audit must recompute all gates:

```text
G-NC-01 actor registry deterministic
G-NC-02 holdings raw provenance exact
G-NC-03 publication provenance PASS
G-NC-04 strict PIT availability
G-NC-05 future disclosure excluded
G-NC-06 empty cells remain UNAVAILABLE/UNKNOWN
G-NC-07 registry-driven actor matching
G-NC-08 ETF actor attribution forbidden
G-NC-09 context identity/outcome blindness
G-NC-10 context deterministic rebuild
G-NC-11 context commitment exact
G-NC-12 support-map contract/validator negative suite PASS
G-NC-13 C2 + semantic + ordinal 1–3 replay unchanged
G-NC-14 production head / no-R4 invariant
G-NC-15 candidate order live commitment unchanged
```

Also bind hashes of:

```text
actor registry
coverage ledger + report
national_holdings_pit
publication provenance audit
empty-resolution ledger/report
ETF normalized file + lineage report
NC0 pause anchor
NC0 invariance report
ordinal-4 context preflight
support-map contract test report
```

State may be:

```text
PREREQUISITES_COMPLETE
```

but machine code must never declare independent approval.

---

# 8. P0 — Build a real NC_FINAL review packet

Add:

```text
scripts/build_nc_final_review_packet.py
```

Canonical packet fields:

```text
review_version = csr8-nc-final-review-v1
operation = NC_FINAL
audit_target_commit = <HEAD being reviewed>
base_infra_freeze
nc0_pause_head
final_audit_sha256
context_preflight_sha256
support_contract_report_sha256
artifact_commitments
production_invariance
no_r4_s4
```

Write:

```text
docs/audit/evidence/nc_final_review_packet.json
```

Commitment:

```text
review_packet_sha256 = SHA256(canonical exact packet bytes)
```

Independent reviewer verdict closed-world:

```json
{
  "review_version": "csr8-nc-final-review-v1",
  "operation": "NC_FINAL",
  "input_commitment_sha256": "<packet sha>",
  "state": "APPROVE|REVISE|HALT",
  "issues": [],
  "required_changes": [],
  "reviewer_run_id": "<independent>",
  "created_at": "<UTC>"
}
```

Persist append-only / hash-chained.

---

# 9. P0 — Resume gate currently can never open

File:

```text
scripts/nc_resume_h_gate.py
```

Current code contains:

```text
'independent_approve': False
```

hard-coded.

Replace with real verification of:

```text
national_capital_context_extension_frozen.json
NC_FINAL exact-bound APPROVE verdict
review packet hash
final audit hash
live NC0 invariance
live R1,S1,R2,S2,R3,S3
open_reveals=0
candidate_prefix=3
candidate_for_ordinal(4)
ordinal-4 context preflight PASS
```

Do not trust booleans copied into the freeze marker without re-verification.

Output only:

```json
{
  "state": "READY_FOR_ORDINAL_4",
  "ordinal": 4,
  "evidence_profile": "BASE_V1+NATIONAL_CTX_V1",
  "mutation": "NONE"
}
```

---

# 10. Freeze marker

Only after independent `NC_FINAL=APPROVE`:

```text
docs/audit/evidence/
national_capital_context_extension_frozen.json
```

Required binding:

```text
status = NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN
declared_by = INDEPENDENT_LLM_AUDIT
final_verdict = APPROVE

audited_commit
base_infra_freeze
nc_fix1_base
nc0_pause_production_head

effective_from_ordinal = 4
past_ordinals_mutated = false
production_head_unchanged = true
candidate_order_unchanged = true

final_audit_sha256
context_preflight_sha256
support_contract_report_sha256
review_packet_sha256
review_verdict_sha256

actor_registry_sha256
holdings_pit_sha256
etf_share_sha256
```

---

# 11. Resume H only after gate PASS

When:

```text
nc_resume_h_gate.py
→ READY_FOR_ORDINAL_4
```

then implement/run ordinal 4:

```text
R4
→ exact frozen packet
→ exact NATIONAL_CTX_V1 sidecar
→ executor annotation
→ context_support_map
→ independent ANNOTATION review binding:
     packet_sha256
     context_sha256
     context_support_map_sha256
     draft_sha256
→ receipt
→ SEAL
→ S4
```

Existing `c4d-receipt-v1`, SEAL payload, C2 event schema and H01–H06 annotation schema remain unchanged.

Final expected production chain:

```text
R1,S1,R2,S2,R3,S3,R4,S4
```

---

# Exit criteria

NC-FIX3 completes only when:

```text
all G-NC-01..15 = PASS
NC_FINAL independent reviewer = APPROVE
NATIONAL_CAPITAL_CONTEXT_EXTENSION_FROZEN exists and exact-binds approval
nc_resume_h_gate.py = READY_FOR_ORDINAL_4
```

Before that:

```text
NO R4
NO S4
```
