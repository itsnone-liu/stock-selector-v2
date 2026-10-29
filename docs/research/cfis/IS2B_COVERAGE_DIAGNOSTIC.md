# IS2B 反弹覆盖诊断（自动生成）

固定规则不变；rally_4w 仅为后验标签，不写回前置特征或节点。
每个 current_known=true 周作为 synthetic 节点调用 is2b_node_outcomes.build，严格 assessment 后进入、4完整交易周；原 status/return 原样继承，非 COMPLETE 标签留空（未知，非 false）。

- 当时已知周：194；4周完整结果：179；未知结果：15。
- 完整结果中期末 return >= 5% 标签周：33；描述性占比：18.44%。
- 相邻标签周 run 数：13（按原 features 观测序号相邻合并）。
- 重叠标签周共享未来行情，不是独立样本；run 也不是经验证独立事件。上述占比不是规则召回率、交易胜率或独立事件成功率。

## 结果状态

- COMPLETE: 179
- ENTRY_GAP: 2
- MISSING_ENDPOINT: 3
- RIGHT_CENSORED_NO_ENTRY: 1
- RIGHT_CENSORED_PARTIAL_WEEK: 4
- WEEKLY_GAP: 5

## 前置分类

| 类别 | 全部已知周 | rally标签周 | rally周举例（ISO week） |
|---|---:|---:|---|
| actual_A | 6 | 0 |  |
| merged_A_condition | 1 | 0 |  |
| feature_incomplete | 55 | 3 | 2025-W04, 2026-W12, 2026-W13 |
| failed_A_conditions | 132 | 30 | 2022-W18, 2022-W19, 2022-W20, 2022-W21, 2022-W22, 2022-W23, 2022-W43, 2022-W51, 2022-W52, 2024-W06, 2024-W16, 2024-W35 |

actual_A 为实际节点；merged_A_condition 仅指当周 a_candidate=true 但未产生新A，并非“无覆盖”。loss/到期周也可能属于此栏，须看 active 状态。
feature_incomplete 不视为规则拒绝；完整但不触发A的所有周均保留。

## 当时已有 episode（各阶段都可覆盖，不借未来）

按实际A节点独立重放：已知 close < anchor_low × 0.97 退出，原观测序号 A+12 到期，B/C 节点仅更新当时可见stage；含本周新A。无法确认则 unknown；缺失观察之后即使后来close恢复，期间是否已失效仍不确定，直到可确认退出/到期或新实际A。此为保守覆盖确认，不声称未知期间原状态机必已退出。
- active: 全部 34 周；rally 3 周；例：2022-W51:A, 2022-W52:A, 2024-W16:C
- none: 全部 160 周；rally 30 周；例：2022-W18, 2022-W19, 2022-W20, 2022-W21, 2022-W22, 2022-W23, 2022-W43, 2024-W06, 2024-W35, 2024-W36, 2024-W37, 2024-W38
- unknown: 全部 0 周；rally 0 周；例：

## 多重A门槛失败（非互斥）

仅 feature coverage_status=COMPLETE 周计失败；缺失条件标 unknown，不归 false。阈值照原规则：dd12<=-5%、low_change>=-1%、pressure_easing、margin_easing、l1_mean2>=0。

| 条件 | 完整特征失败周 | 其中rally周 | rally例 |
|---|---:|---:|---|
| dd12_deep | 84 | 18 | 2022-W22, 2022-W23, 2022-W52, 2024-W16, 2024-W39, 2024-W41, 2025-W24, 2025-W25, 2025-W26, 2025-W29 |
| low_stable | 47 | 9 | 2022-W19, 2022-W43, 2022-W51, 2024-W06, 2024-W16, 2024-W37, 2025-W02, 2025-W25, 2025-W51 |
| pressure_easing | 72 | 16 | 2022-W21, 2022-W22, 2022-W43, 2022-W51, 2022-W52, 2024-W06, 2024-W16, 2024-W36, 2024-W37, 2024-W41 |
| margin_easing | 97 | 22 | 2022-W18, 2022-W21, 2022-W22, 2022-W23, 2022-W51, 2022-W52, 2024-W06, 2024-W16, 2024-W35, 2024-W38 |
| support_nonnegative | 56 | 13 | 2022-W19, 2022-W20, 2022-W21, 2022-W22, 2022-W23, 2025-W24, 2025-W25, 2025-W26, 2025-W29, 2025-W30 |

完整逐周记录（含未涨、未知、失败列表及episode状态）：`data/cfis/is2b_coverage_diagnostic.csv`（ignored）。
