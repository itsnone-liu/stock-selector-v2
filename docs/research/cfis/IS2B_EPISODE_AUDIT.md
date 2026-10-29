# IS2B Episode Audit

由 frozen `is2b_features.csv` 与 `is2b_nodes.csv` 自动生成；独立逐周重放已与原 `build_nodes` 及 frozen nodes 的 episode、阶段、周、周末与 assessment 日期逐条精确核对，mismatch 立即 raise。未修改或调优 candidate 规则。

共 246 个观测周，6 轮 episode；A/B/C = 6/3/2；LOSS = 4；EXPIRED = 2；右删失 = 0。

## 逐轮表

| Episode | A | B | C | 终止周 | 状态 | B等待/观测周 | C等待/观测周 | anchor close/low | terminate close |
|---|---|---|---|---|---|---|---|---|---|
| IS2B-2022-W14 | 2022-W14 | — | — | 2022-W16 | LOSS | —/2 | —/2 | 5078.0/5010.57 | 4718.91 |
| IS2B-2022-W42 | 2022-W42 | — | — | 2022-W43 | LOSS | —/1 | —/1 | 4706.91/4668.57 | 4503.14 |
| IS2B-2022-W45 | 2022-W45 | 2023-W01 | 2023-W05 | 2023-W06 | EXPIRED | 8/8 | 11/11 | 4817.24/4719.89 | 5139.43 |
| IS2B-2024-W01 | 2024-W01 | — | — | 2024-W03 | LOSS | —/2 | —/2 | 4292.79/4273.72 | 4117.72 |
| IS2B-2024-W08 | 2024-W08 | 2024-W09 | 2024-W12 | 2024-W20 | EXPIRED | 1/1 | 4/4 | 4187.61/3991.63 | 4424.81 |
| IS2B-2024-W29 | 2024-W29 | 2024-W31 | — | 2024-W34 | LOSS | 2/2 | —/5 | 4042.73/3966.88 | 3806.93 |

## 口径与边界

- 失效是候选状态机失效，不是策略执行、交易、止损或收益评价。状态到期后的上涨不归为该 episode 的恢复；C 亦不等于交易成功。
- LOSS：当前已知 close < anchor low × 0.97；优先于 A+12 观测周 EXPIRED。到期/失效周不能重 A；同周只能升级一阶段。C 后仍合并至失效/到期。
- age 从 A=0 起按输入观测周位置计数，坏周照常计龄但不能升级；坏周清空 previous breadth，不能跨坏周满足 C 的连续广度条件。未插补缺失周。
- trace 仅含当时及过去信息，终止行保留该 episode/age，state 为 NONE；不在最后一行预知右删失，不回填未来 B/C。current_known 沿用原规则（含有效 assessment）；未知价格不作为已知信息输出。
- summary 允许最终路径描述；wait_B/C_weeks 均为从 A 起观测周差，另给 B→C 周差；缺失阶段的 observed_weeks 为截止终止/样本末的观测 age，不当作成功等待时间。
- 样本末仍活跃者标 RIGHT_CENSORED（右删失），不伪造终止周/价格；未到 B/C 的晚期 episode 同样明确右删失。已失效未到达者为 TERMINATED_UNREACHED，不标右删失。
- at_A 快照包括 dd12、breadth、part、margin easing、l1、pressure 等原始特征；全量见 summary CSV。使用 frozen 可见性代理，不宣称历史 vintage PIT 保证。
