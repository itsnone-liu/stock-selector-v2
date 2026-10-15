# CL-R3 — 正式关闭声明（CLOSED：unconditional effort effect + episode interaction）

关闭日期：2026-10-14（R3-B 交互闭包完成，终止树 1/3 分支执行）

## 裁决

\[
\boxed{\text{CL-R3 CLOSED — Effort effect retained + EpisodeState interaction; no lifecycle naming}}
\]

## 冻结结论

R3 在 84 股、110,510 日样本上确立了两个通过独立性检验的结构，其余预注册假设明确判负：

**成立（保留）：**

1. **无条件主结构（G2 PASS，R3 首轮）**：异常高相对成交努力后，其后 20 日单位成交额的价格推进效率下降（连续 Effort×λ_next raw −0.078 → 控制后 −0.193；股票内对比 bootstrap 不跨零；OLS 框架下三模型 β_E 均显著为负）。
2. **EpisodeState 单交互（R3-B G3 PASS）**：该 effort 惩罚在 CD-5 L4 资金事件窗口内放大约 52%（β_EC=−2.37e-3，P05/P95=[−2.85e-3, −1.87e-3] 不跨零；量级判据 −52.4% 远超 20%；秩稳健同号）。

**判负（明确，非边缘）：**

- Result（|ret|/σ20）维无独立贡献（raw ≈ 0）——R3 不是"Effort vs Result"二维故事，而是更窄更扎实的 **Relative Trading Effort → Future Price Impact Efficiency**；
- PricePosition 调节：CI 跨零，量级 +3.3%（双败）；
- MarketRegime 调节：CI 跨零，量级 −2.4%（双败）。

## 命名纪律（持续有效）

- 保留结构为描述层规律；episode 放大最多上升为 **hypothesis**（候选解释：事件内冲击前置/供应消耗/筹码重组——均未区分），**不命名 absorption/distribution/吸筹/派发/主力耗竭**；
- 候选描述名（用户提案，暂存）：Impact Exhaustion / Effort Persistence Penalty——待未来研究独立验证后再定名。

## 证据链存档

| 阶段 | 文档 |
|---|---|
| 预注册 | `CL_R3_EFFORT_RESULT_PREREGISTRATION.md` |
| 构造普查（G1 PASS） | `CL_R3_EFFORT_RESULT_CENSUS.md` |
| 首轮机制（G2 PASS / G3 首轮加性） | `CL_R3_EFFORT_RESULT_MECHANISM1.md` |
| 交互预注册 | `CL_R3B_INTERACTION_PREREGISTRATION.md` |
| 交互闭包（1/3 通过） | `CL_R3B_INTERACTION_REPORT.md` |
| 数据 | `data/cl_radar/r3_effort_result/`（census.json、mechanism1.json、interaction.json） |

## 程序意义与下一步

R1 负、R2 负、R3 首个正结构——CL Radar 过滤器三轮产出第一个通过全部独立性门禁的行为结构，且交互闭包按硬判据 A/B/C 完成，未做任何二层挖掘。

下一步（待用户裁决）：roadmap 顺序为 R4 Price Impact / Opening EI integration。episode-amplified effort penalty 作为 R4 的直接输入之一（事件窗口内 effort→impact 效率下降更陡），与 Opening EI 集成问题天然衔接。
