# CSR-8 Phase H — Final Freeze

*Freeze ID:* `csr8-phase-h-final-freeze-v1` · *Frozen at:* 2026-10-04T01:17:31Z · *Git head at freeze:* `3f46515` · *Status:* **FROZEN**

Ruling (user, 2026-10-04): **PHASE H — 128 PRODUCTION MILESTONE: ACCEPT / READY TO FREEZE.**
This is a read-only terminal freeze: no production-semantics change, no ordinal 129+.

```
CSR-8 PHASE H
FINAL PRODUCTION CORPUS: 128
STATUS: FROZEN

ORDINALS 1-128: CLOSED
ORDINALS 129+: UNAUTHORIZED / HOLD

PRODUCTION: COMPLETE
EVIDENCE: COMPLETE
READOUT: COMPLETE
PREREGISTERED PERSISTENCE: 3/3 PRESERVED
HISTORICAL EQUIVALENCE: PASS
IDENTITY / LINEAGE VIOLATIONS: 0
```

## 1. Production terminal manifest

- Sealing log: **256 events**, strict alternating **128 REVEAL_PACKET/SEAL_ANNOTATION pairs**, per-pair opaque-case-id match: True, event-hash chain intact: True, sequence numbers 0–255 contiguous: True
- Campaign structure: **64 distinct opaque case entities × 2 production epochs** — ordinals 1-64 (epoch 1) and 65-128 (epoch 2) sample the same 64 opaque case entities at different as_of dates; paired ordinals i and i+64 share opaque_case_id but differ in packet bytes (packet_sha256) and observation date T; paired packet/T distinct: **True** (the third readout corpus treats (case, T) observations; (code, T) injectivity across 122 ordinals was verified separately and holds)
- Terminal seal / production head: `4fd1d50de05f0baa10fcb26da55b95cffca2d7b2aa644ebadebf856297e7ab39` — equal in `sealing_log.head.json` and `c4d_seal_anchor.production_head_hash` (terminal_state_consistent = True)
- Epoch-2 reviews ledger (live production ledger for the ordinal-50+ era): **396 rows, terminal seq 395** (POST_SEAL o128 APPROVE), `prev_review_hash` chain intact over all rows: True, sequences contiguous: True, coverage: 51-128 (78) full five-op ordinals + partial {"50": ["POST_SEAL", "SEAL"]} (epoch transition; epoch-2 ledger is the live production ledger for the ordinal 50+ era; ordinal 50 entered mid-flow at the epoch transition (SEAL+POST_SEAL only); ordinals 1-49 are recorded in the earlier epoch-1 campaign artifacts and the sealing log covers all 128 seals)
- Ledger provenance rows (not incidents): [{"sequence": 0, "ordinal": null, "operation": "RECOVERY_GENESIS"}, {"sequence": 1, "ordinal": null, "operation": "RECOVERY_CHECKPOINT"}, {"sequence": 76, "ordinal": 65, "operation": "ANNOTATION_CORRECTION"}, {"sequence": 82, "ordinal": 66, "operation": "ANNOTATION_CORRECTION"}]; total ANNOTATION_CORRECTION rows: 2 (o65 seq76, o66 seq82 — see ERR-1)

## 2. Evidence completeness manifest

**15/15** batch evidence archives (batch2–batch16, covering ordinals 15–128), each with committed manifest + descriptor and a hash-pinned GitHub Release asset, live-checked at freeze time. Ordinals 1–14 (batch1, pre-archive era): APPEND_ONLY_RECOVERED_PREFIX, realtime capture NOT_AVAILABLE, erratum BATCH-H-RECOVERY-ERRATUM-1 — the earliest production era predates the capture-path relocation; no per-op DSH capture archive exists for ordinals 1-14 by design of that era — their production state is carried by the sealing log (all 128 seals), epoch-1 campaign artifacts, and the batch1 completion record with its recovery erratum.

| Batch | Ordinals | Files/Sets | closed_world | archive sha256 | release live |
|---|---|---|---|---|---|
| b2 | 15-22 | 123/41 | PASS@closeout | `f44a9e0f4049f2c9…` | uploaded |
| b3 | 23-30 | 120/40 | PASS@closeout | `60576f17d81bacd6…` | uploaded |
| b4 | 31-38 | 120/40 | PASS@closeout | `777969d455696965…` | uploaded |
| b5 | 39-46 | 120/40 | PASS@closeout | `5e30a4ce358e9b2d…` | uploaded |
| b6 | 47-54 | 120/40 | PASS | `78e5cb49b6031e35…` | uploaded |
| b7 | 55-62 | 120/40 | PASS | `4c2400369a099fb7…` | uploaded |
| b8 | 63-64 | 30/10 | PASS | `0cb94c27258812c3…` | uploaded |
| b9 | 65-72 | 129/43 | PASS | `01d6851b984b9254…` | uploaded |
| b10 | 73-80 | 120/40 | PASS | `a7c8d8cefda8d994…` | uploaded |
| b11 | 81-88 | 120/40 | PASS | `8686fde6d6f10c8f…` | uploaded |
| b12 | 89-96 | 120/40 | PASS | `88bf7e5c771cc8cd…` | uploaded |
| b13 | 97-104 | 120/40 | PASS | `862a89e0894c397f…` | uploaded |
| b14 | 105-112 | 120/40 | PASS | `2451b8fb705e0273…` | uploaded |
| b15 | 113-120 | 120/40 | PASS | `432b92380e420e36…` | uploaded |
| b16 | 121-128 | 120/40 | PASS | `dc2e5cfd572397e7…` | uploaded |

Three-layer evidence model: **authoritative** = GitHub Release archive + committed manifest/descriptor (hash-pinned); **recoverable local cache** = `captures/` (batch12/13 pruned during the disclosed H16 disk incident, restorable from releases); **ephemeral** = `/tmp`.

## 3. Final readout authority

Authority commit **3f46515**; driver `scripts/phase_i_third_readout_128.py` (additive; frozen I1/I2 semantics unchanged).

| Report | sha256 |
|---|---|
| frozen I2 pilot 7–38 | `c3d86305c0aad86f937afe870bc45d19dc7dd899fa7925f2ab4b4281cb97e3e1` |
| second readout 7–64 | `deb2046c93809660bd53f5b6f14172a8f78351f52145c88577108269b929dd4b` |
| third readout 7–128 | `cc87cd8dc2abbd21f0fee40768553471f269e60821893f377abffc78ade07917` |

Double historical equivalence gate: pilot 7–38 ≡ frozen I2 report (**PASS**); chained 7–64 ≡ committed second report (**PASS**). Corpus 7–128: 122/122 complete (complete_R5 = 1.0), frozen decision **A** (P3 >=1 CONSISTENT qualifying pair), identity/cross-lineage violations **0**.

## 4. Scientific conclusions (frozen)

- **Preregistered persistence: 3/3 PRESERVED** —
  - `stock_layer_summary` NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10 vs NO_PIT_VISIBLE_REPORT: dR5 -0.0256, Cliff's δ -0.249 (n=86/18, CONSISTENT, qualifying) — **PRESERVED**
  - `etf_expansion_count` 4 vs 8: dR5 -0.0635, Cliff's δ -0.318 (n=15/17, CONSISTENT, qualifying) — **PRESERVED**
  - `etf_expansion_count` 8 vs 9: dR5 +0.0436, Cliff's δ +0.479 (n=17/14, CONSISTENT, qualifying) — **PRESERVED**
- Exploratory structure drift 64→128: **12 PRESERVED / 18 WEAKENED / 3 REVERSED** — exploratory structures contract under corpus expansion while the preregistered core persists.
- taxonomy_v2 diagnostic: **False** — dominant structure described, but 20 non-dominant support ordinals (8, 15, 41, 44, 48, 51, 53, 55, 63, 67, 68, 72, 79, 105, 108, 112, 115, 117, 119, 127) expose real heterogeneity; taxonomy is not closed-world complete.
- **Interpretation boundary (frozen):** persistence of descriptive structure associations only. No causality, control, or investment-alpha inference is made or implied. NATIONAL_ACTORS_PRESENT means PIT-visible disclosure presence only.

## 5. Known incidents / errata register

- **ERR-1 (H9, o65/66)** — wrong ANNOTATION commitments admitted (ledger seq75/seq81) and retained append-only. Resolution: ANNOTATION_CORRECTION rows seq76/seq82 APPROVED; receipt gates stopped irreversible action; pre-admission annotation binding guard deployed (commit 2651d59); readout binding uses the LATEST of (ANNOTATION, ANNOTATION_CORRECTION) Evidence chain intact: **True**
- **ERR-2 (H10, o79)** — organic pre-admission guard rejection. Resolution: fail-closed pre-correction, re-admitted exactly once; no sealed-state change Evidence chain intact: **True**
- **ERR-3 (H11, o81)** — transport timeout during reviewer admission. Resolution: live ledger/verdict state checked first, fresh reviewer spawned, no double admission Evidence chain intact: **True**
- **ERR-4 (H12, o96)** — reviewer-interpretation divergence on uniform 2099-01-02T00:00:00Z packet template marker. Resolution: fail-closed pre-admission (zero ledger mutation); marker verified uniform across all packets; fresh reviewer admitted seq231 exactly once; o97+ reviewer prompts carry uniformity context proactively (zero divergence since) Evidence chain intact: **True**
- **ERR-5 (H14, o105/108/112)** — NATIONAL_ACTORS_PRESENT stock-records states. Resolution: reviewer-verified disclosed-presence consistent; no control/causality inference drawn Evidence chain intact: **True**
- **ERR-6 (H15, o119)** — stock_records=1 combined with NOT_DISCLOSED_IN_LATEST_VISIBLE_TOP10 (record existence vs contemporaneous disclosure edge case). Resolution: deep reviewer verification: A2-SSF NOT_DISCLOSED_IN_TOP10 for current period 2025-09-30; prior-period holding does not establish current top-10 presence; retained as the canonical "record existence != contemporaneous disclosure" exemplar Evidence chain intact: **True**
- **ERR-7 (H16, o127)** — NATIONAL_ACTORS_PRESENT stock_records=1 (A2-SSF FIRST_DISCLOSED 2023-03-31). Resolution: reviewer-verified disclosure-presence consistent; no control/causality inference drawn Evidence chain intact: **True**
- **ERR-8 (H16 closeout)** — local disk filled during evidence-archive verify (100% /). Resolution: stale /tmp tooling caches cleared; local captures/batch12+batch13 pruned only after live confirmation of their GitHub release assets; event disclosed in batch_h_batch16_status.json; authoritative evidence chain unaffected (see three-layer evidence model in the freeze markdown) Evidence chain intact: **True**
- **ERR-9 (H5 (repaired at final freeze), o39-46)** — release asset batch-h-b5-evidence-archive-v1 found MISSING at final-freeze live check (descriptor claimed hash-pinned durable GitHub asset; the only missing one of 15 batches). Root cause visible in batch_h_batch5_status.json: close_out was left "EVIDENCE ARCHIVED LOCALLY; RELEASE PENDING" — the upload step was never completed at batch time. Resolution: local captures/batch5 re-verified and re-packed byte-identically to the committed root commitment (archive sha256 5e30a4ce358e9b2dee4b8ffe85336d7cf1ea1061819819bccd6d7e870b82ccca and 784220681 bytes reproduced exactly; manifest sha 6f9232747b07a60cb803bf289c34e953f547cbaa5b1fb1a22bd5268b771bf061; 120 files / 40 capture sets closed_world PASS; 40 samples full DSH-v4 trust-root re-verified); asset re-uploaded under the original pinned tag (release 402765500, asset 608870012) and download-back hash verified Evidence chain intact: **True**

Ledger provenance note: epoch-2 ledger opens with RECOVERY_GENESIS (seq0) and RECOVERY_CHECKPOINT (seq1) rows predating Phase H session scope (epoch transition at ordinal ~50); they are provenance rows, not incidents, and are covered by the hash chain.

Known open non-blocking items: P1 debt: reviewer tool optional cross-check of context commitments (carried from earlier review; does not affect frozen evidence or readout results).

**All register entries: authoritative evidence chain intact.**
