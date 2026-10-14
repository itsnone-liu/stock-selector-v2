# CL-R1-B — Local Supply Pressure 机制验证预注册

## Status and boundary

- Parent: CL-R1 frozen as `HIGH PRIORITY MECHANISM REFERENCE`.
- Question: what form of near-current historical-traded supply best explains difficulty of price progress?
- No strategy backtest, no Factor→Return, no production feature/threshold change.
- All cost/chip quantities are `model_derived` historical traded-price distributions, never true holder cost, profit ownership, or actor identity.

## Primary construct

For decision date T and distance δ:

```text
LocalSupply_δ(T) = estimated distribution mass with
                   P_T < cost_bin_center <= P_T*(1+δ)
                   / total estimated mass
```

Primary δ grid is fixed before analysis: 1%, 2%, 3%, 5%, 7.5%, 10%, 15%, 20%. No best δ selection is permitted. `overhead_total` is reported as a comparator, not the primary construct.

## Factorial components

The component axes are:

- D — uniform turnover decay: off/on (`dist *= 1 - turnover`)
- K — interval allocation: point HLC/3 vs Gaussian allocation within [L,H]
- V — center: HLC/3 vs valid clamped VWAP
- B — bin resolution: 50 vs 80 vs 120

The primary clean attribution at fixed 50 bins is:

```text
A0 = D0 K_point V_HLC3
A1 = D1 K_point V_HLC3
A2 = D0 K_gaussian V_HLC3
A3 = D1 K_gaussian V_HLC3
A4 = D0 K_gaussian V_VWAP
A5 = D1 K_gaussian V_VWAP
```

B is tested separately at 50/80/120 with the same D/K/V recipe. Each comparison reports paired T-level change, not only pooled correlation. The external M3 remains a reference reconstruction, not an endorsed model.

## Mechanism response

Primary response: existing B1 `lambda_norm` (20-day no-intercept return response to signed amount/ADV), used only as an observable price-impact proxy.

Secondary response: Amihud comparator. No future return is used as a primary mechanism response.

## Confound controls

Predeclared control fields at T: log ADV20, log amount T, turnover T, ATR20/close, recent return 20d, price level log(close), year/era, and market-regime strata where available. Results are reported as:

1. raw snapshot description;
2. stock-equal weighted result;
3. stock/episode cluster bootstrap or cluster-robust estimate;
4. controlled partial association/linear rank residual check.

Raw snapshot count is never treated as independent-evidence count.

## Distance structure Gate G3

Report rho(δ) for the complete fixed δ grid. Expected mechanism pattern is strongest association near current price with attenuation as δ expands. A single isolated δ result does not pass G3.

## Behavioral outcome Gate G4

At least one must be tested without using future data in the state variable:

### Breakout difficulty

From T, first passage to `close >= P_T*(1+x)` for fixed x∈{5%,10%}, within H∈{20,40} sessions. Report time-to-target, cumulative amount/turnover to target, success/failure, and failure after first attempt. Censored paths remain censored, not failures.

### Drawdown sell pressure

For a fixed post-T drawdown episode, report downside return per unit amount/ADV, downside-volume share, and whether selling pressure weakens or intensifies. Do not infer ownership or intent.

The first implementation may choose one outcome only if its input coverage is adequate; the choice and coverage are recorded before reading outcome values.

## Four gates

- G1 Component attribution: D/K/V/B increment is stable and isolatable.
- G2 Confound control: LocalSupply remains associated with lambda after declared controls and stock/episode clustering.
- G3 Distance structure: rho(δ) has distance-decay shape across the fixed grid, not a single tuned threshold.
- G4 Behavioral consequence: at least one fixed breakout-difficulty or drawdown-sell-pressure outcome is explained.

Decision:

- G1/G2/G3/G4 pass: permit a separate CapitalState design review for `LocalSupplyState`; still no automatic production integration.
- G2 or G4 fails: stop complexity expansion; retain only descriptive research evidence.
- G1 fails: do not choose M3; retain CD-5 baseline and archive component claims.
