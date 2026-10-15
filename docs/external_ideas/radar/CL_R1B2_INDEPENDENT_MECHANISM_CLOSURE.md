# CL-R1-B2 — Independent Mechanism Closure

## Final status

**R1-B2: CLOSE — independent LocalSupply mechanism not established.**

The round was explicitly limited to one closure pass. It did not tune kernels, bins, decay, windows, or search for a better threshold.

## What was verified

- 2,327 valid PIT snapshots joined to B1 `lambda_norm`; 84 frozen stocks.
- `market_ext` contains PIT `outstanding_share` for all audited files/rows. Market-cap proxy was therefore added as `log(close × outstanding_share)`; it was not imputed.
- Declared controls: log ADV20, current turnover, 20-day volatility, close, log close, 20-day return, log market cap.
- Stock-cluster bootstrap: 1,000 resamples over 84 stocks.
- Breakout capital outcomes: fixed +5% target over 20/40 sessions, with hit censoring and successful-path cumulative amount, cumulative turnover, and days-to-target.

## G1 — component attribution

The cleanest available evidence remains:

- turnover decay alone weakens the +5% raw relation:
  - M0 −0.175 → M1 −0.119;
- interval allocation strengthens it:
  - M1 −0.119 → M2 −0.256;
- M2→M3 improvement is smaller:
  - M2 −0.256 → M3 −0.266.

However the current stored M0–M3 run does not constitute the fully clean A0–A5 factorial with identical bins and only one toggled component at every edge. Therefore G1 is **directional evidence only**, not a passed attribution gate.

## G2 — independent information after controls

Controlled partial rank associations for +5% local historical-volume density:

| model | raw | after declared controls |
|---|---:|---:|
| M0 | −0.175 | −0.078 |
| M1 | −0.119 | −0.069 |
| M2 | −0.256 | −0.090 |
| M3 | −0.266 | −0.032 |

The market-cap control changed little relative to the prior control pass. It does not rescue a strong independent M3 signal.

Stock-cluster bootstrap median rho for +5%:

| model | median | p05 | p95 |
|---|---:|---:|---:|
| M0 | −0.576 | −0.683 | −0.440 |
| M1 | −0.374 | −0.521 | −0.194 |
| M2 | −0.576 | −0.717 | −0.430 |
| M3 | −0.626 | −0.735 | −0.479 |

The raw stock-level association is stable across stock resampling, but that does not overturn the substantial attenuation after covariate controls. G2 is **not passed as an independent mechanism gate**.

## G3 — distance structure

The available fixed +2/+5/+10 checks remain negative, but the pre-registered full 1/2/3/5/7.5/10/15/20% per-bin distance curve was not produced in this closure pass. Therefore G3 is **not passed**. No isolated +5% threshold is promoted.

## G4 — breakout capital requirement

For successful paths only:

- M0 +5%@20d: supply vs cumulative amount rho −0.003; cumulative turnover −0.120; days +0.120.
- M2 +5%@20d: amount +0.084; turnover +0.074; days +0.160.
- M3 +5%@20d: amount +0.099; turnover +0.097; days +0.130.
- At +5%@40d, M2/M3 amount correlations are +0.077/+0.095 and time correlations +0.135/+0.098.

This is not a clean “higher local supply requires more capital” result: cumulative amount is near zero to weakly positive, turnover is mixed, and the sample is conditioned on successful breakouts. Hit probability is negative (e.g. M2 −0.130 at +5%@20d), but hit difficulty and successful-path capital cost are different quantities.

G4 is therefore **not passed**.

## Closure decision

The correct endpoint is not “no relationship.” The evidence supports a narrower statement:

> Local historical volume density near the current price has reproducible raw associations with lower lambda and lower breakout hit rates. Those associations attenuate materially after liquidity, price-state, volatility, return, and PIT market-cap controls. The closure pass does not establish an independent local-supply mechanism, a distance-decay law, or a capital-requirement consequence.

Consequences:

- Do not create `LocalSupplyState` or `ChipSupplyState`.
- Do not integrate M3 or alter CD-5.
- Keep the artifacts as a negative/conditional mechanism reference.
- Do not continue by tuning kernels, bins, decay, windows, or thresholds.
- If revisited later, it requires a new preregistration and a genuinely new data source or measurement design, not another parameter search.

All results remain research-only, PIT-scoped, and non-causal. No true holder cost, actor identity, or trading signal is inferred.
