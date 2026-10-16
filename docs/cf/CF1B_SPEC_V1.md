# CF-1B Atom State Engines — Frozen Spec v1.0

*Prerequisite:* CF-1A v1.0 field-level activation CLOSED

*Mode:* descriptive atoms; Historical Replay + Prospective Shadow

*Forbidden:* future outcome calibration, cross-atom features, composite score, Market Regime, return probability

## Common gates

- G1 source authority is explicit; TDX is third-party statistics.
- G2 each record carries conservative `available_at`.
- G3 replay uses only date-T and prior records.
- G4 L1/M/L4 implementation and outputs are independent.
- G5 no future return or price outcome is read.
- G6 missing core input → `INSUFFICIENT_SUPPORT`/`NOT_YET_OBSERVABLE`.
- G7 Capital Weather displays atoms side by side only.
- G8 CF does not change OOS-B contracts or resource priority.
- G9 L1 large share-ratio jump requires independent adjustment verification; otherwise L1 date fails closed.

Thresholds below are engineering priors frozen before examining any future outcome. They may be changed only by contract bump, never to improve returns.

## L1 Policy Stabilization Behavior

Input: daily PIT family aggregation from SSE/SZSE official ETF share snapshots. Frozen family universe and exclusion words are in `l1_broad_etf_universe_v1.json`.

Per-family change: `shares_t / shares_t-1 - 1`. Main statistic: median among at least three observable families.

G9 v1 conservative guard: family ratio `<=0.5` or `>=2.0` without independently verified adjustment factor makes that date `INSUFFICIENT_SUPPORT`. This intentionally sacrifices coverage rather than mistake a split for flow.

Scale: median absolute family-median change over the preceding 60 records, requiring 20 records.

- `STABILIZATION_ACTIVE`: median change ≥ 3× scale.
- `STABILIZATION_READY`: median change ≥ 1.5× scale.
- `WATCH`: positive but below READY.
- `NORMALIZING`: non-positive and ACTIVE occurred in previous five records.
- `NORMAL`: otherwise.

Semantics are stabilization behavior, not actor identity. Price/amount confirmation remains a planned refinement; v1 does not fabricate it from unavailable historical sources.

## M Margin Atom

Input: SSE and SZSE official summary on the same trade date. SSE yuan; SZSE 亿元 × 1e8. Both exchanges are mandatory.

- `financing_balance_pressure = balance / mean(previous 20 balances) - 1`
- `financing_flow = balance_t - balance_t-1`
- `deleveraging_velocity = flow_t - flow_t-1`

States:

- `LEVERAGE_BUILDING`: last five flows all positive and pressure ≥ +1%.
- `DELEVERAGING_ACCELERATING`: current flow <0, velocity <0, and at least four of last five flows negative.
- `DELEVERAGING`: current flow <0 and at least three of last five flows negative.
- `DELEVERAGED`: pressure ≤ -3% and current flow non-negative.
- `NEUTRAL`: otherwise.

No liquidation probability is produced.

## L4 Sentiment Atom

Input only TDX 880005 advancers/whole-market amount and 880006 limit-up count. Minimum 60-record warm-up. Advancer percentile uses prior up to 250 observations; amount ratio uses previous 20-day median.

- `CAPITULATION`: advancer percentile ≤10% and amount ratio ≥1.25.
- `PANIC`: advancer percentile ≤20%.
- `EUPHORIA`: percentile ≥90%, limit-up ≥80, amount ratio ≥1.20.
- `FOMO`: percentile ≥75% and limit-up ≥50.
- `RECOVERY`: percentile ≥50% and advancers above prior-five median.
- `APATHY`: otherwise.

v1 does not use down-count, theme diffusion, Legu or Eastmoney pools in replay.

## Capital Weather v0.1

Output contains the latest independent L1/M/L4 records and explicitly fixes:

```text
aggregation = FORBIDDEN
market_regime = NON_OPERATIVE
```

It may narrate factual coexistence of states, but may not reduce them to one direction, score, pressure index, probability or trading instruction.

## Implementation

- `src/stock_selector/cf/atoms.py`
- `scripts/cf/run_atoms.py`
- `data/cf/derived/atoms/*.jsonl`
- `data/cf/derived/capital_weather/latest.json`

Daily execution follows official collection and local TDX evening update. Atomic temp-file replacement prevents partial outputs.
