# CL-R1 — a-stock-data-quant 筹码分布外部对照审计

## Status

- classification: `HIGH PRIORITY MECHANISM REFERENCE`
- not a strategy candidate
- not a code dependency
- no production integration
- repository snapshot: `jangviktor-web/a-stock-data-quant`
- audited commit: `0944c726f19aa041ecf2d93ac7357223d061823d`
- primary source: `lib/chip_distribution.py`

## 1. Source algorithm recovered

The module is an OHLCV/turnover approximation, not true participant holding data:

1. establish one price grid from the min/max high/low in the supplied K-line window;
2. for each day, decay existing distribution by `1 - turnover_percent/100`, clipped to `[0, 0.98]` turnover;
3. allocate the day's volume over bins intersecting `[low, high]` using a Gaussian kernel centered on VWAP (`amount/volume`) when valid;
4. fall back to `(H+L+C)/3`, then `(H+L+O+C)/4`;
5. report weighted average cost, price-at-or-below-current-close ratio, and top-five-bin concentration.

Default bins = 80; accepted range 10..300. Gaussian sigma = max((high-low)/4, bin_width/2).

## 2. Runtime data-contract finding

The algorithm's declared inputs and the default CLI input path do not match.

- `bin/quant.py::cmd_chip` maps missing `amount` and `turnover` to numeric zero.
- `lib/ashare.py::get_price_sina` returns only `open/high/low/close/volume`.
- `lib/ashare.py::get_price_day_tx` requests qfq and returns only `open/close/high/low/volume`.
- Therefore the normal Sina/QQ qfq path supplies no amount and no turnover to `cmd_chip`.
- With those missing fields, the algorithm silently executes `remain=1.0` every day and cannot use VWAP.
- `lib/sources_mootdx.py::get_kline` comments that mootdx returns amount, but the normalized result emits only OHLCV; it does not pass amount or turnover onward.

This is not necessarily a failure of the standalone algorithm, but it is a material runtime-contract limitation. Any claim that the default CLI performs turnover-decay/VWAP chip estimation is unsupported until the input path is changed or audited with actual frames.

## 3. PIT risk

The global `min(high/low)` and `max(high/low)` grid is safe only when the supplied window is itself truncated at decision date T. Passing a full 2020–2026 window and reading an earlier T snapshot can make bin boundaries depend on post-T prices. R1 must construct each T's grid from data available at or before T, or use a frozen predeclared grid whose construction date is PIT-valid.

## 4. Frozen ablation models

All models use the same qfq prices, unadjusted volume, amount and turnover rows, same episode/date sample, and same current-close convention:

- **M0**: existing CD-5 running 50-bin histogram; daily `(H+L+C)/3`; no turnover decay.
- **M1**: M0 price assignment, plus turnover decay `dist *= (1-turnover)`.
- **M2**: M1 turnover decay plus Gaussian allocation across `[L,H]`; center = `(H+L+C)/3`.
- **M3**: complete a-stock-data-quant method; turnover decay plus Gaussian allocation; center = valid clamped `amount/volume`, otherwise typical price; default 80 bins.

These models are distribution-estimation comparisons only. They do not use future returns to choose bins, parameters, thresholds, or labels.

## 5. Mechanism questions after A

Only if the distribution comparison is technically valid:

- Does the model change supply-pressure proxies near current price?
- Does it explain pullback selling pressure, breakout difficulty, or unit-amount price impact better than M0?
- Is any increment attributable to turnover decay, Gaussian intraday allocation, or VWAP center?

No `profit_ratio > 80%` → “回调压力” and no top concentration → “主力控盘” interpretation is admitted. These are hypotheses requiring separate mechanism validation.

## 6. Planned decision

- A fails: archive the external algorithm as a non-reproducible/runtime-contract reference; do not compare mechanism results.
- A passes, B null: the more complex estimator does not add observable capital-mechanism information; retain M0 and stop.
- A and B pass: allow a separate decision-value design, still no production integration.
