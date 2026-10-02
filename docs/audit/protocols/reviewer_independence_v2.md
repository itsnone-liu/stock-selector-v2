# Reviewer Independence Protocol v2

- **protocol_id**: `csr8-reviewer-independence-v2`
- **status**: FROZEN (H2-CANARY-FIX1 item 5, 2026-10-02)
- **supersedes**: the H0-era transcript-anchored independence mechanism
  (as practiced in H0/H1 reviews)
- **scope**: every CSR-8 review operation whose verdict appends to
  `h_campaign/<cid>/reviews.jsonl` (NEXT_REVEAL / ANNOTATION / RECEIPT /
  SEAL / POST_SEAL)

## 1. Why v2 exists

The H0-era contract assumed the reviewer runs as a full harness session
whose transcript is persisted under `/root/.dsh/sessions/<workspace>/`
and can be disk-scanned by the reviewer itself to prove "the writer of
this verdict is a session distinct from the executor". In the current
harness this assumption fails structurally:

- subagent sessions persist only a 464-byte stub (session header +
  permission events); tool calls and messages are NOT written to the
  stub, and
- subagent `bash` environments do not expose `DSH_SESSION_ID` /
  `DSH_SESSION_JSONL`.

The H2 ordinal-4 canary therefore ran under a weaker attestation
without a formal erratum — a contract violation flagged by the canary
closed-loop review (finding 4). This protocol freezes the replacement
and its proof boundaries.

## 2. Attestation levels

### 2.1 `TRANSCRIPT_ANCHORED` (H0/H1 practice — historical)

Machine-provable properties:
- the verdict's `reviewer_run_id` marker appears in exactly one
  persisted harness session transcript, and that transcript is not the
  executor's;
- the same transcript contains the tool calls that wrote the verdict
  file and appended the ledger line;
- transcript bytes can be hashed and pinned.

NOT provable: that the session was driven by a different underlying
model instance/operator (a transcript proves a distinct session
record, not a distinct mind).

### 2.2 `PLATFORM_OPAQUE_SUBAGENT` (v2, current)

Machine-provable properties:
- **context isolation**: the reviewer is spawned as a subagent that
  does not see the executor conversation (platform guarantee of the
  delegation mechanism);
- **identity novelty**: `reviewer_run_id` and `reviewer_session_id`
  are generated inside the reviewer session from a CSPRNG and are
  unknown to the executor before the reviewer reports them; any
  premature occurrence of the value in the executor transcript
  disproves novelty post hoc;
- **write locality**: the verdict/ledger write tool call runs inside
  the reviewer session with the run id in its arguments; the executor
  never writes `reviews.jsonl` or verdict files;
- **distinctness (declared)**: the executor verifies the ledger's
  reviewer-declared session ids are pairwise distinct across
  operations of one ordinal.

NOT provable (must be stated honestly wherever this level is claimed):
- that a declared `reviewer_session_id` corresponds to an actual
  distinct session object (ids are reviewer-declared, opaque, not
  platform-issued);
- therefore "N distinct declared ids" is not machine proof of "N
  distinct sessions" — the distinct-session guarantee rests on the
  delegation mechanism plus fresh spawns per operation.

## 3. Usage rules

1. Every reviewer delegation MUST spawn a fresh subagent per operation
   (no reuse of one reviewer conversation across operations).
2. The reviewer generates `reviewer_run_id` (and, under 2.2,
   `reviewer_session_id`) itself and passes them through its own tool
   calls; executor-provided ids are forbidden.
3. The executor's verify gate MUST check: verdict closed-world schema,
   input commitment binding, ledger hash chain integrity, pairwise
   distinctness of declared session ids within the ordinal.
4. Whenever `PLATFORM_OPAQUE_SUBAGENT` is used, the run report and any
   evidence file MUST disclose the level explicitly; claiming
   transcript anchoring without persisted transcripts is a contract
   violation.
5. If a future harness restores persisted subagent transcripts (or
   exposes `DSH_SESSION_ID` inside subagent shells), reviewers SHOULD
   upgrade to `TRANSCRIPT_ANCHORED` and pin the transcript sha in the
   ledger record; until then 2.2 is the accepted floor for single-case
   reviews.
6. Batch H (8 ordinals per batch) additionally REQUIRES per-batch
   executor-side novelty spot-checks: sample declared ids and grep the
   executor transcript for premature occurrence (must find none).

## 4. Historical record

- H0 (ordinals 1-2) and H1 (ordinal 3) reviews: `TRANSCRIPT_ANCHORED`
  per the then-frozen contract.
- H2 ordinal-4 canary (ledger seq 7-11): `PLATFORM_OPAQUE_SUBAGENT`
  with random novelty — recorded under
  `H2_CANARY_EVIDENCE_PROFILE = PROTOCOL_ERRATUM` (see
  `docs/audit/evidence/h2_ordinal4_canary_status.json`); the five
  reviewers were five separate subagent spawns.
- From ordinal-5 onward this protocol v2 governs all review
  operations.
