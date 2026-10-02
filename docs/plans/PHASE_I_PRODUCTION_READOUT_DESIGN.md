# Phase I — Production Readout Design

**Status:** PRE-OUTCOME-READ / design freeze candidate  
**Corpus:** CSR-8 Batch H production ordinals 1–38 (pilot corpus; production cases 7–38 plus the sealed historical prefix)  
**Baseline:** Batch H production mechanism approved at `7b4660a`  
**Scope:** readout design only. This document does **not** read, derive, or attach hidden outcome data.

## 0. Purpose and stopping rule

The first 38 sealed production cases are a **pilot corpus**, not a final probability-estimation sample and not a basis for freezing a trading rule. Phase I asks whether the frozen annotation/context taxonomy has observable research value before more reviewer-gated cases are produced.

No Batch H ordinal 39+ is authorized by this document. The next action is I0 inventory, followed by I1 contract approval, followed only then by I2 outcome unlock.

The readout must preserve the blind-design boundary:

```text
sealed production corpus
  → read-only inventory (I0; no outcome)
  → frozen outcome/readout contract (I1)
  → first sealed-case outcome unlock (I2)
```

After I1 is frozen, no metric, horizon, inclusion rule, taxonomy label, or primary/secondary status may be changed in response to the 38-case results. Any later change is a versioned taxonomy/contract revision and uses new cases or is explicitly exploratory.

## 1. Corpus and provenance

The pilot is the union of the frozen Batch H production records:

| batch | ordinals | completion record | reviewer samples |
|---|---:|---|---|
| Batch 1 | 7–14 | `docs/audit/evidence/batch_h_batch1_completion.json` | recovery-era evidence; inventory must preserve its provenance label |
| Batch 2 | 15–22 | `docs/audit/evidence/batch_h_batch2_completion.json` | `batch_h_batch2_samples.json` |
| Batch 3 | 23–30 | `docs/audit/evidence/batch_h_batch3_completion.json` | `batch_h_batch3_samples.json` |
| Batch 4 | 31–38 | `docs/audit/evidence/batch_h_batch4_completion.json` | `batch_h_batch4_samples.json` |

The intended I0 analysis unit is **one sealed production case / ordinal**, not one reviewer gate. The five reviewer rows per ordinal are provenance and gate evidence, not five independent observations. `reviewer_run_id`, `reviewer_session_id`, ledger sequence, packet/reveal identity, annotation envelope, context/support commitments, receipt, and seal must be joined without rewriting the sealed artifacts.

I0 must produce a deterministic inventory with at least:

- ordinal and batch/provenance regime;
- packet/proposal/reveal identifiers and hashes;
- annotation envelope hash and its component commitments;
- context version and context commitment;
- support-map hash and support-reference count;
- draft/annotation hash;
- receipt and seal commitments, chain position, and final verification state;
- field availability, missingness, and vocabulary counts;
- an explicit `outcome_locked=true` marker.

I0 may inspect public/sealed annotation and context metadata. It must not read hidden outcome bytes, outcome tables, forward-price paths, or any field whose value is computed using post-seal information.

## 2. I1 preregistered outcome contract

### 2.1 Unit and clock

- **Unit:** one ordinal/case, with no weighting by the five reviewer gates.
- **Origin:** the production case's sealed reveal/event anchor date, as recovered from the frozen production artifact; if the origin cannot be established without opening outcome material, the case is `origin_unresolved` and is not silently dropped.
- **Clock:** exchange trading sessions for the relevant instrument, not calendar days. Suspended/non-trading sessions are not zero-return observations.
- **Observation windows:** H+1, H+3, H+5, and H+10 eligible trading observations after origin. H+5 is the primary horizon; H+1/H+3/H+10 are secondary path horizons.
- **Adjustment:** use one frozen adjusted-price convention for every case and record its version/hash. Raw and adjusted values must never be mixed in one endpoint.

The horizon and price convention are contract fields. If the data source cannot provide an auditable adjusted-price clock, the affected endpoint is `unavailable`, not imputed.

### 2.2 Primary endpoint

The preregistered primary endpoint is **H+5 adjusted log return**:

```text
R5 = log(adjusted_close at the fifth eligible observation / adjusted_close at origin)
```

The readout reports the raw case-level values and descriptive summaries. It does not convert R5 into a buy/sell/position rule.

Primary endpoint completeness is separate from the value:

```text
R5_complete ∈ {true, false}
R5_missing_reason ∈ {no_quote, suspended, insufficient_history, data_error, origin_unresolved}
```

Incomplete R5 is not treated as zero and is not removed without a reason count.

### 2.3 Secondary endpoints

The following are fixed secondary/descriptive endpoints:

1. `R1`, `R3`, and `R10` adjusted log returns;
2. **MFE5/MFE10:** maximum favorable adjusted close return from origin inside the window;
3. **MAE5/MAE10:** minimum adverse adjusted close return from origin inside the window;
4. `path_high_before_low`: whether the window first reaches a positive threshold before the adverse threshold, with thresholds fixed before unlock;
5. `breakout_persistence_5`: whether the event remains above the pre-event reference level at H+5, if that reference is present in the frozen case contract;
6. path/censoring status: complete, right-censored, suspended, no-quote, or data-error.

Thresholds for categorical path endpoints must be fixed in I1. The initial contract uses **+5% favorable** and **−5% adverse** adjusted close return, with a boundary convention of `>= +5%` and `<= −5%`; this is descriptive only and must not be tuned after seeing pilot outcomes.

If a secondary endpoint cannot be defined from a predeclared, auditable field, it is marked `not_applicable` rather than retrofitted.

### 2.4 Primary explanatory variables

The following frozen annotation/context variables are eligible as **primary explanatory variables**, subject to availability in I0:

- annotation taxonomy labels at the case level;
- disclosed stock-layer summary / visibility state;
- market-context summary and context version;
- support-map coverage/count and support-reference classes;
- annotation evidence-quality fields explicitly present before seal;
- case/order position only as a prespecified descriptive blocking variable, never as a post-outcome feature.

The first readout must preserve the original categorical values and missingness. It must not collapse labels after seeing R5.

### 2.5 Descriptive-only variables

These may be tabulated or used for audit stratification but do not enter a conclusion about predictive value in the pilot:

- reviewer identity/session and ledger sequence;
- archive or raw transcript hashes;
- packet IDs and cryptographic commitments;
- batch number as a production/provenance regime;
- sample availability/technical failure flags;
- any field discovered during I0 that was not demonstrably available before seal.

No cryptographic or reviewer-provenance field is a substantive explanatory variable.

### 2.6 Missingness, censoring, and extremes

- Missing values remain explicit; no mean/median/zero imputation for endpoints.
- Right-censored cases remain in the denominator for corpus accounting and are excluded only from the corresponding complete-endpoint numerator/summary, with both counts reported.
- Suspensions are not zero returns. A suspended path is reported with its observation count and censoring reason.
- Data errors are quarantined with a reproducible reason and never silently repaired from a later source.
- No winsorization, clipping, or outlier deletion in the primary readout. Raw values, finite-value counts, and an optional clearly labeled robust descriptive summary may coexist; robust summaries cannot replace raw primary summaries.
- Duplicate instrument/date observations are a data error requiring resolution before I2, not deduplication by an outcome-dependent rule.

## 3. I2 first sealed-case readout

I2 starts only after the I1 contract, its canonical hash, the data-source/version commitment, and the I0 inventory are frozen in Git. The unlock operation must be a separate, auditable step from inventory construction.

I2 deliverables:

1. a case-level analysis table, one row per ordinal;
2. endpoint completeness/censoring ledger;
3. annotation/context × outcome descriptive tables using only the I1 variables;
4. effect-size/coverage summaries with exact denominators;
5. a taxonomy coverage report showing labels with zero, sparse, or ambiguous support;
6. a machine-readable manifest and deterministic replay report;
7. an explicit statement that the 38-case readout is pilot/descriptive and not confirmatory.

I2 must not silently merge the Batch 1 recovery provenance with realtime-capture batches. It may report pooled pilot descriptions only with the provenance regime shown as a stratification or limitation.

## 4. Interpretation rules for the 38-case pilot

The pilot is not used to estimate stable probabilities, select thresholds, rank trading actions, or claim causal effects. In particular:

- no p-value/significance threshold is a continuation criterion;
- no post-outcome feature selection or taxonomy relabeling is allowed;
- apparent separation is reported with uncertainty and cell counts;
- sparse cells are labeled sparse, not interpreted as null or strong evidence;
- outcome association is not evidence that the annotation caused the path;
- a null result is not proof that the taxonomy is useless, but it is a stop signal against scaling blindly.

The first readout must answer exactly three questions:

1. Do annotation/context categories show reproducible-looking descriptive differences in predeclared endpoints and path types?
2. Which fields have inadequate coverage, near-zero variation, or ambiguous semantics and should be removed or clarified?
3. Does a repeated path structure appear that cannot be represented by the current taxonomy?

## 5. Expansion decision gate

After I2, choose exactly one documented disposition; do not silently mix them:

### A. Structure has useful information

Keep the frozen taxonomy and continue Batch H. The next milestone is **64 total cases**, then a second readout at **128 total cases**. Each expansion batch retains the same I1 contract unless a separately versioned taxonomy is approved before new cases are opened.

### B. Partial usefulness / taxonomy defect

Freeze the 38-case pilot and all of its results. Do not rewrite old annotations. Create taxonomy v2 with an explicit version boundary and rationale; new production cases use v2, and v1/v2 readouts are reported separately. No outcome-driven relabeling of the pilot is permitted.

### C. No useful structure

Pause Batch H expansion. Do not spend reviewer capacity on the remaining candidates. Revisit the research hypothesis, endpoint choice, or annotation semantics in a new versioned design; the 38-case pilot remains an immutable negative/indeterminate result.

The gate itself is qualitative and contract-based, not a hidden numerical optimizer. The decision record must state evidence, coverage, limitations, and why A/B/C was selected.

## 6. Required I0/I1/I2 artifacts

Planned paths (to be created only at the corresponding phase):

```text
docs/plans/PHASE_I_PRODUCTION_READOUT_DESIGN.md       # this preregistration/design

docs/audit/evidence/phase_i_i0_corpus_inventory.json   # I0, no outcomes
docs/audit/evidence/phase_i_i1_contract.json           # canonical contract + hash
docs/audit/evidence/phase_i_i2_readout_manifest.json   # I2 replay/lineage

docs/reports/PHASE_I_PRODUCTION_READOUT_PILOT.md      # descriptive pilot report
```

Before I1 approval, these prohibitions are active:

- no Batch H ordinal 39+;
- no hidden outcome reads;
- no result-driven changes to this document;
- no claim that 38 cases establish stable probabilities or a production trading rule.

## 7. Contract acceptance checklist

- [ ] I0 inventory proves one-row-per-ordinal mapping and preserves batch/provenance regimes.
- [ ] I0 records `outcome_locked=true` and passes a no-outcome dependency scan.
- [ ] Outcome source, adjusted-price convention, clock, and endpoint formulas are frozen.
- [ ] H+5 is primary; H+1/H+3/H+10 are fixed secondary horizons.
- [ ] Censoring, suspension, missingness, duplicate rows, and extremes have fixed handling.
- [ ] Primary explanatory variables and descriptive-only fields are listed before unlock.
- [ ] 38-case pilot status and non-confirmatory interpretation are explicit.
- [ ] A/B/C expansion gate is frozen before any outcome is read.
- [ ] I1 canonical hash is committed before I2 unlock.
