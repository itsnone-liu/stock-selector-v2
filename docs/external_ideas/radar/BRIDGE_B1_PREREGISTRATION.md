# Bridge Experiment B1 — 筹码状态 × 日线推进效率 λ

- `protocol_id`: `capital-bridge-b1-v1`
- `status`: PREREGISTERED / offline-only / no production change
- `date`: 2026-10-14
- `authority`: user GO in conversation:「就把他作为第一个实验」

## 1. Scientific question

在同一股票、同一历史时期和相近流动性条件下，筹码成本状态是否条件性影响单位资金的价格推进效率？

资金假说：

```
历史成交成本/筹码结构 → 可供卖压 → 单位资金价格响应（λ）
```

不是检验“成本代理能否选股”，也不是检验 λ 方向因子；第一阶段只检验机制中介关系。

## 2. Frozen sample and data

- Sample: Phase A frozen `sample_selection.json` universe84, canonical chosen order, 84 unique codes.
- Source SHA: SHA256(`code` joined by newline, trailing newline)=`083ca9ef0292310aad2415843e8756511b2d74682abb9b1d4b2f897fc0e026d6`.
- Price: `data/cd/daily_fullmarket/{code}.json.gz`, qfq OHLC for returns/price, unadjusted volume for traded volume, amount if present.
- CD-5 cost semantics are copied exactly: qfq `(H+L+C)/3`, unadjusted volume, running episode 50-bucket weighted histogram, weighted P25/P50/P75 and `volume_below_current_price_ratio`; all are `model_derived`, never called participant cost or ownership.
- Episode boundaries: `data/cd/l4_episodes.json.gz`; only dates within `start..end` are eligible. CENSORED is retained through data end; no future endpoint information is used for a day’s features.
- No production module, schema, threshold, cost-band parameter, or decision output is changed.

## 3. Primary response variables

For each stock and eligible episode day `t`, using a trailing 20-trading-day window ending at `t`:

1. Daily signed flow: `OF_d = amount_d * sign(qfq_close_d - qfq_close_(d-1))`. `sign(0)=0`. One-price/one-sided limit days and invalid amount are flagged and excluded from the primary fit, not silently treated as normal flow.
2. Paper-replication lambda: no-intercept OLS slope `Δqfq_close ~ OF` over the window, requiring ≥15 valid days.
3. Scale-normalized lambda (primary cross-stock comparison): `return_d ~ OF_d / ADV20_d` no-intercept OLS slope, where `return_d=Δclose/previous_close` and `ADV20` is trailing mean amount. This measures return response per one ADV of signed input.
4. Amihud comparator: mean `abs(return_d)/amount_d` over valid window.
5. Marginal-efficiency exploratory measure: split a sustained same-sign flow run/window into early/late halves and compare local slopes. It is secondary because the first pass must not let an exploratory segmentation replace the frozen primary response.

The paper-replication price lambda and normalized return lambda must be reported separately; no post-hoc choice of the better one.

## 4. Primary conditioning variables

At day `t`, from the CD-5 running histogram:

- `cost_position`: below / inside / above P25-P75 band;
- `distance_to_cost_center = close / cost_center - 1`;
- `cost_dispersion` and normalized band width;
- `volume_below_current_price_ratio` (descriptive historical traded-price relation only);
- concentration proxy: inverse normalized cost-band width, reported descriptively and not renamed “chip concentration”.

Predeclared state contrasts:

- low-distance / inside-or-near-lower-band + narrow-band vs above-band / wide-band / high historical-volume-below-current-price;
- continuous specification first; binary state contrast only as a predeclared readout, not a threshold search.

## 5. Mechanism hypotheses

- H1: after stock-size, ADV, volatility and market-period controls, normalized λ differs by cost state.
- H2 directional expectation: lower-cost / narrower-band / lower-supply-pressure states have higher normalized λ than high-distance / wider-band states.
- H3 optional: impact concavity differs by state; estimate `log(abs(return)) ~ beta*log(amount/ADV20)` by state, with beta<1 interpreted only as concavity evidence.

These are falsifiable expectations, not acceptance criteria. Null or reverse results are valid outcomes.

## 6. Confounder controls and exclusions

- Report stock, episode origin, year/regime strata; do not use regime to rewrite stock-level signals.
- Control/stratify by log ADV, volatility, price level and amount/ADV; do not claim λ is actor identity.
- qfq return is mandatory; raw-price results are diagnostic only.
- Flag/exclude invalid amount, missing bars, one-sided limit/zero-range days and insufficient windows; report counts.
- No future episode end, future state, future outcome, or post-day revised data enters a feature.
- Cluster uncertainty by stock and episode (not raw day count alone); report stock/episode N and date span.

## 7. Decision rule

Report effect direction, magnitude, uncertainty, stock/episode coverage, and predeclared regime windows. A mechanism is “supported” only if direction is consistent in at least 2/3 predeclared time windows and the median effect is on the expected side, while coverage and data-quality gates pass. Otherwise report NULL / REVERSE / INCONCLUSIVE; never rescue by changing window, threshold, or response definition.

A supported mechanism does not authorize production integration. It only authorizes a second experiment: whether the state-conditioned efficiency improves a frozen decision/path outcome.

## 8. Planned outputs

- `data/cl_radar/bridge_b1/observations.parquet` (or CSV fallback): one row per eligible stock-episode-day with provenance flags;
- `data/cl_radar/bridge_b1/lambda_windows.parquet`;
- `docs/external_ideas/radar/BRIDGE_B1_REPORT.md`;
- `data/cl_radar/bridge_b1/run_manifest.json` with sample SHA, code version, input hashes, counts and exclusions.
