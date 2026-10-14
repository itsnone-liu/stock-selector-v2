# CL-R1-B LocalSupplyPressure 首轮机制结果

- joined snapshot n: 2327
- no future return; response is existing B1 lambda_norm
- this is a first-pass mechanism audit, not a production or factor result

## Fixed distance checks

| model | δ | rho(LocalSupply, λ) | n |
|---|---:|---:|---:|
| M0 | 0.02 | -0.191882 | 2327 |
| M0 | 0.05 | -0.175337 | 2327 |
| M0 | 0.1 | -0.161753 | 2327 |
| M1 | 0.02 | -0.137153 | 2327 |
| M1 | 0.05 | -0.118561 | 2327 |
| M1 | 0.1 | -0.102599 | 2327 |
| M2 | 0.02 | -0.238660 | 2327 |
| M2 | 0.05 | -0.256341 | 2327 |
| M2 | 0.1 | -0.250953 | 2327 |
| M3 | 0.02 | -0.255654 | 2327 |
| M3 | 0.05 | -0.266151 | 2327 |
| M3 | 0.1 | -0.281960 | 2327 |

## Stock-equal +5% check

| model | stocks | rho |
|---|---:|---:|
| M0 | 84 | -0.576025 |
| M1 | 84 | -0.372785 |
| M2 | 84 | -0.588701 |
| M3 | 84 | -0.626061 |

## Interpretation

The local-supply direction is observable and remains negative in the fixed +2/+5/+10 checks. G1 component attribution and G3 full distance-decay require a clean per-bin factorial rerun before passing. G2 controls and G4 behavioral outcome remain open.
