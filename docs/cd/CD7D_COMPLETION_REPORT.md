# CD-7D — Absolute Risk Budget · Completion Report

*预注册: `cd7d_preregistration.json` · 结果: `cd7d_results.json` · 引擎: `scripts/cd7d_risk_budget.py`*

## 1. 口径与实现修正

CD-7D 验证的是“已经允许参与以后，在不同风险背景下暴露多少资本”，不是用 sizing 挽救负 alpha。E-class 是最大允许暴露上限，不是精确目标仓位。

执行中发现并修正一个 P0 统计缺陷：CD-7 R1/R2 原引擎在单单位仓位执行 DECAYING-reduce 时先把 `pos` 减为 0，随后 close guard 拒绝生成 trade，因此静默丢失被减仓的交易。这个缺陷造成 R1/R2 的 2,813/25,164 生存者样本。修复方式是先调用 `close_trade('REDUCED_OUT')`，再把仓位置零；完整重建结果落档于 `cd7_rebuild_results.json`，原 R1/R2 的绝对统计不再作为证据。

CD-7D 的 25,164 个 plans 是入场计划全集，没有上述 trade-记录丢失问题。另修正了 monotonicity 的 dev/holdout adverse 拆分及 D0-D5 的 `n_entered` 统计。

## 2. E-class 风险单调性

| class | n | dev median MAE | holdout median MAE | dev p10 ret | holdout p10 ret | dev adverse | holdout adverse |
|---|---:|---:|---:|---:|---:|---:|---:|
| E1 | 19,390 | −16.37% | −12.61% | −27.27% | −22.13% | 0.913 | 0.904 |
| E2 | 349 | −19.15% | −17.35% | −27.82% | −25.42% | 0.963 | 0.992 |
| E3 | 5,425 | −19.85% | −15.49% | −29.07% | −26.02% | 0.923 | 0.955 |

Dev 中 MAE 的风险排序大体符合 E1 < E2 < E3，但 holdout 不稳定：E3 的 MAE/adverse 均反而优于 E2（E2 的 holdout adverse 0.992 高于 E3 的 0.955）。因此离散 E-class **未通过“稳定风险排序”**，尤其 E2/E3 不能在 holdout 中形成可靠的序关系。这里不进行任何百分比、阈值或连续仓位搜索。

**单调性判定：FAIL。** 未发现足以预先解释该 holdout 反转的结构性证据，触发预注册 stop rule。

## 3. D0-D5 层消融

| layer | total pnl* | max drawdown* | avg utilization | n entered | missed by budget |
|---|---:|---:|---:|---:|---:|
| D0 fixed equal exposure | 83.73% | −475.78% | 210.19x | 25,164 | 0 |
| D1 + market gross | 83.73% | −475.78% | 210.19x | 25,164 | 0 |
| D2 + lifecycle ceiling | 38.34% | −410.14% | 128.45x | 25,164 | 0 |
| D3 + cost ceiling | 38.34% | −410.14% | 128.45x | 25,164 | 0 |
| D4 + sector ceiling | 38.34% | −410.14% | 128.45x | 25,164 | 0 |
| D5 + portfolio caps | −0.0551% | −30.19% | 0.4377x | 117 | 25,047 |

`*` D0-D4 是预注册的无组合集中度约束对照，并非可部署组合绩效；其 utilization 大于 1 正是无限制叠加暴露的诊断结果。D5 才施加 gross、per-name、sector、concurrent caps，因此只有 D5 具有生产风险预算语义。

D3 在当前冻结 cost band 下没有改变聚合结果；这不是重新放宽或调参的理由，而是该层在本数据/规则交集中的边际贡献为零，应在 shadow 中监测分布漂移。

## 4. Stop-rule 处置与下一步

- 不继续 sizing 研究；不搜索连续仓位，不用 sizing 拯救负 alpha。
- 不改变 ENTRY eligibility；E-class 不能绕过 L1/PRIMARY_ZONE。
- EXIT/REDUCE 规则继续执行，即使仓位很小。
- **CD-7D sizing research：STOP（holdout monotonicity FAIL）。**
- 按用户冻结 fallback，进入 Round-1 System Freeze，然后进入路径 β Shadow Monitoring。

Shadow 是 NO ORDER / NO CAPITAL。每日记录完整链条的 `knew-at-T`、emitted-at-T 与 afterward，并监测结构漂移而非 P&L：market/sector axis、regime distribution、candidate throughput、source mix、episode duration、lifecycle share、PRIMARY_ZONE frequency、decision frequency、E-class distribution。短期损益不触发阈值修改；只有结构漂移触发 regime-change review。

## 5. CD-7 R1/R2 更正结论

完整 REDUCED_OUT 修复后的三臂 holdout：CHASE n=10,821、ret_rel −6.60%、MAE −7.88%；PRIMARY_ZONE n=10,532、ret_rel −5.02%、MAE −5.04%；ZONE 的相对方向仍优于 CHASE，但绝对收益显著低于原生存者统计 −1.2%。PRIMARY_ZONE 的 top-decile capture 10.67%，未入场全集 2.43%；因此原“ZONE 以机会成本换风险改善、错过直线强股”的数量结论作废。SECONDARY-only n=1,402、top-decile 8.06%、MAE −9.63%，仍未提供足以重开 timing 研究的证据。

**全局状态：CD-7D COMPLETE · sizing stop-rule triggered · Round-1 System Freeze / Shadow Monitoring ready · CSR-8 unchanged.**
