# CL-R1-B2 控制与行为结果（closure pass）

- valid joined observations: 2327
- market-cap control: PIT `log(close * outstanding_share)` from `market_ext`; no imputation
- behavior outcome: PIT-safe fixed breakout difficulty, not a trading return test

| model/metric | n | raw rho | controlled partial rank |
|---|---:|---:|---:|
| M0|supply_above_2pct | 2327 | -0.191882 | -0.056050163452646934 |
| M0|supply_above_5pct | 2327 | -0.175337 | -0.07778152697235234 |
| M0|supply_above_10pct | 2327 | -0.161753 | -0.0933813310828033 |
| M0|overhead_total | 2327 | 0.010549 | -0.051335524556691575 |
| M1|supply_above_2pct | 2327 | -0.137153 | -0.044862716846321794 |
| M1|supply_above_5pct | 2327 | -0.118561 | -0.06890671505337732 |
| M1|supply_above_10pct | 2327 | -0.102599 | -0.08443532791479366 |
| M1|overhead_total | 2327 | -0.000304 | -0.07379498749533339 |
| M2|supply_above_2pct | 2327 | -0.238660 | -0.03231453304447048 |
| M2|supply_above_5pct | 2327 | -0.256341 | -0.09038025147552087 |
| M2|supply_above_10pct | 2327 | -0.250953 | -0.10223531150939821 |
| M2|overhead_total | 2327 | -0.064268 | -0.07447701364144098 |
| M3|supply_above_2pct | 2327 | -0.255654 | 0.03764964928334086 |
| M3|supply_above_5pct | 2327 | -0.266151 | -0.03242429788623454 |
| M3|supply_above_10pct | 2327 | -0.281960 | -0.07193703246113346 |
| M3|overhead_total | 2327 | -0.083296 | -0.05783452924486113 |

## Breakout outcome

| model/outcome | n | rho(local +5%, hit) |
|---|---:|---:|
| M0|break_5_20_hit | 2327 | -0.106569 |
| M0|break_5_40_hit | 2327 | -0.088051 |
| M0|break_10_20_hit | 2327 | -0.113000 |
| M0|break_10_40_hit | 2327 | -0.107565 |
| M0|break_5_20_amt | 1046 | -0.003358 |
| M0|break_5_20_turn | 1046 | -0.119673 |
| M0|break_5_20_time | 1046 | 0.120123 |
| M0|break_5_40_amt | 1303 | 0.018184 |
| M0|break_5_40_turn | 1303 | -0.109058 |
| M0|break_5_40_time | 1303 | 0.135749 |
| M1|break_5_20_amt | 1046 | 0.034965 |
| M1|break_5_20_turn | 1046 | -0.017819 |
| M1|break_5_20_time | 1046 | 0.118792 |
| M1|break_5_40_amt | 1303 | 0.051402 |
| M1|break_5_40_turn | 1303 | -0.007452 |
| M1|break_5_40_time | 1303 | 0.128185 |
| M2|break_5_20_amt | 1046 | 0.083517 |
| M2|break_5_20_turn | 1046 | 0.074469 |
| M2|break_5_20_time | 1046 | 0.159973 |
| M2|break_5_40_amt | 1303 | 0.077305 |
| M2|break_5_40_turn | 1303 | 0.052178 |
| M2|break_5_40_time | 1303 | 0.135444 |
| M3|break_5_20_amt | 1046 | 0.098615 |
| M3|break_5_20_turn | 1046 | 0.096790 |
| M3|break_5_20_time | 1046 | 0.130062 |
| M3|break_5_40_amt | 1303 | 0.095436 |
| M3|break_5_40_turn | 1303 | 0.076950 |
| M3|break_5_40_time | 1303 | 0.097879 |
| M1|break_5_20_hit | 2327 | -0.089398 |
| M1|break_5_40_hit | 2327 | -0.071208 |
| M1|break_10_20_hit | 2327 | -0.100055 |
| M1|break_10_40_hit | 2327 | -0.083692 |
| M2|break_5_20_hit | 2327 | -0.129685 |
| M2|break_5_40_hit | 2327 | -0.137214 |
| M2|break_10_20_hit | 2327 | -0.127371 |
| M2|break_10_40_hit | 2327 | -0.136921 |
| M3|break_5_20_hit | 2327 | -0.114691 |
| M3|break_5_40_hit | 2327 | -0.133823 |
| M3|break_10_20_hit | 2327 | -0.111148 |
| M3|break_10_40_hit | 2327 | -0.132724 |

Market-regime control and full distance curve remain incomplete. Stock-cluster bootstrap is recorded in `r1b_controls_behavior.json`; results are mechanism associations, not causal or investment conclusions. Closure report: `CL_R1B2_INDEPENDENT_MECHANISM_CLOSURE.md`.
