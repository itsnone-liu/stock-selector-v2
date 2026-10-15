# CL-R3-B Conditional Interaction Closure 结果

- rows: 110,510（Y=λ̃_next=λ·ADV20/close 无量纲化，合并 P1/P99 缩尾 [0.0042, 0.0735]；股票 cluster bootstrap 1000 次 × 84 股，逐股 Gram 矩阵重采样）
- 行数与 R3 mechanism1 差 2 行（110,510 vs 110,508，重算边界差异，占 0.002%，不影响任何结论方向）
- 模型：Y ~ 1 + Effort + C + Effort×C + 冻结控制（log ADV20/换手/σ20/log close/ret20/log 市值）；Result 不入模型（预注册）

## 交互检验（判据 A∧B∧C）

| model | n | β_E | β_EC | β_EC P05/P95 | A: CI 不跨零 | B: \|β_EC/β_E\|≥0.20 | C: 结构 | G3 |
|---|---:|---:|---:|---:|---|---|---|---|
| PricePosition（高 vs 低位，中间三分组剔除） | 77,989 | −6.15e-3 | +2.04e-4 | [−4.66e-4, +7.15e-4] | **FAIL**（跨零） | **FAIL**（+3.3%） | — | **FAIL** |
| EpisodeState（CD-5 L4 内 vs 外） | 110,510 | −4.52e-3 | **−2.37e-3** | **[−2.85e-3, −1.87e-3]** | **PASS** | **PASS**（−52.4%） | PASS（见下） | **PASS** |
| MarketRegime（强 vs 弱） | 103,017 | −6.24e-3 | −1.47e-4 | [−5.46e-4, +2.59e-4] | **FAIL**（跨零） | **FAIL**（−2.4%） | — | **FAIL** |

三个模型的秩稳健性副检验（Y 全局秩 z 同模型）β_EC 符号全部与主检验一致。

## 结构判读（判据 C，EpisodeState）

- episode 外：β_E = −0.00452；
- episode 内：β_E = −0.00452 + (−0.00237) = **−0.00689**（effort 惩罚放大 ~52%）。

语义（描述层）：**同样的异常高成交努力，发生在 CD-5 L4 资金事件窗口内时，其后 20 日单位成交额价格推进效率的下降显著更陡**；价格位置与市场强弱对此结构无实质调节（量级 3% 上下且不稳定）。

按用户纪律：这只是 "episode-amplified effort penalty" 的结构描述，最多上升到 hypothesis（供应消耗/事件内冲击前置等候选解释均未排除），**不命名为 absorption/distribution/主力行为**。

## 机械性检查（非判据，披露）

episode 内一字板日更多会压低 lam_den、改变 λ̃ 分布，但 Y 已缩尾、控制含 σ20/换手，交互项在 T 日 Effort 上，方向经秩检验一致；无共享构造项（Gate S 合规）。

## 终止树执行

**1/3 交互通过 → `R3_CLOSE_effort_plus_single_interaction`**

- 保留：无条件 Effort→λ̃ 惩罚 + EpisodeState 单交互；
- 明确判负：PricePosition、MarketRegime（A、B 双败，非边缘）；
- 禁二层交互挖掘；R3 关闭，见 `CL_R3_CLOSURE.md`。

产物：`data/cl_radar/r3_effort_result/interaction.json`；脚本 `scripts/cl_r3b_interaction.py`。
