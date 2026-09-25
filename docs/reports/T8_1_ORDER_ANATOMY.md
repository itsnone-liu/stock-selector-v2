# T8.1 报告：Order Anatomy（Estimand A — observed order profile）

> **身份**：descriptive only——无 p 值、无阈值、无规则（G43）；Estimand A =
> **在实际到达 ADD_k 的 risk set 中** ADD_k 后五维如何随 k 变化。到达
> ADD₂/ADD₃+ 本身已通过前序路径选择（高度选择 risk set），本报告**不是**
> "第 k 次 ADD 的因果边际价值"（G44 命名纪律）。全段 15,646 个 ADD（k1
> 10,125 / k2 3,723 / k3+ 1,798）。

## 1. 主表（全段，W10 预注册窗口，中位数）

| 维度 | k1 | k2 | k3+ | 结构 |
|---|---|---|---|---|
| n | 10,125 | 3,723 | 1,798 | — |
| **False ADD 风险**（frozen false_recovery） | 44.89% | 43.81% | 43.21% | **平坦** |
| **恢复捕获**（frozen true_recovery） | 61.40% | 57.75% | 51.56% | **递减（−9.8pp）** |
| ret_w10 中位 | +2.16% | +1.50% | +1.26% | 递减 |
| dd_w10 中位 | −0.60% | −1.05% | −1.68% | 恶化 |
| mfe_w10 中位 | +6.32% | +6.13% | +6.10% | **平坦** |
| occ_w10 中位 | 0.688 | 0.700 | 0.637 | 平坦 |
| contrib_w10 中位（occ×ret） | 0.0134 | 0.0095 | 0.0069 | 递减（≈减半） |
| cycle_life 中位（动作日口径） | 3 | 4 | 2 | 非单调 |

**by_segment 方向一致**（VAL：recovery 64.36→59.99→53.94；CONF：56.15→51.80→
47.09；false_add 各段均无递增梯度，CONF 46.76→47.12→45.55）。

## 2. 核心观察（描述性，对照预注册三形态）

对照 Plan §7 三形态（decreasing / flat / conditional），全段呈现**混合结构**：

1. **False ADD 风险无递增梯度**："False ADD 风险随次数单调上升"的描述性
   假设未得到支持（44.89%→43.81%→43.21%，在 observed ADD_k risk set 中
   无上升梯度）。
2. **"对的收益"在下降**：恢复捕获 −9.8pp；中位贡献 ≈ 减半（0.0134→
   0.0069）。上行 excursion 的**中位水平没有同步下降**（MFE median
   6.32%→6.13%→6.10%，基本平坦），但实际终点收益中位数下降（2.16%→
   1.26%）、下行 excursion 加深（DD −0.60%→−1.68%）——问题形态上不在
   "完全没有上涨空间"，而在**兑现/维持上涨的路径质量下降**（该机制句是
   T8.2 待解释问题，非当前结论）。
3. 可冻结的 Estimand A 概括：在实际到达 ADD_k 的选择后 risk set 中，随
   re-risk order 增加，False ADD rate 基本平坦，但 recovery capture、终点
   收益和 contribution 下降，同时 downside excursion 加深；MFE 中位水平
   基本保持。该结构**是否被 outcome₁ 条件化解释**（RQ2 / Estimand B）是
   T8.2 的预注册问题——本报告不做任何条件分解。

## 3. 时钟语义发现（T8.0 审计警告的实证）

对账发现两个"下一次 REDUCE"时钟：`re_reduce_day`（**动作日**，仓位实际
被降）与 `next_r0_day`（**确认日**，下一 cycle 的 R0 锚）。nan-pattern
逐位一致（11,856/11,856），动作日 ≤ 确认日恒成立，间隔中位 **1 天**、
最大 27 天。cycle_life 采用 frozen 动作日口径；next_r0_day 保持纯 topology
用途（T8.0 审计警告：不得解释为 ADD_k 的 outcome endpoint）。

## 4. 描述 appendix（逐 k，n<130 的行如实报不解读）

k=1: n=10,125 / fa 44.9% / rec 61.4% / contrib 0.0134
k=2: n=3,723 / fa 43.8% / rec 57.8% / contrib 0.0095
k=3: n=1,227 / fa 45.2% / rec 52.4% / contrib 0.0073
k=4: n=392 / fa 42.6% / rec 50.8% / contrib 0.0057
k=5: n=129 / fa 31.8% / rec 48.1% / contrib 0.0055
k=6: n=34 / k=7: n=12 / k=8: n=3 / k=9: n=1（样本过小，仅记录）

## 5. Gate

`t8_1_gates.json` 全 PASS：G1（3 输入）/ G41 固定三组+segment 齐全 /
G42 双 clock（150 抽样 W10 终点+窗口指标+frozen 标签逐项重放 0 mismatch）/
G43 描述纪律（无 p/threshold/rule 词）/ G44 estimand 命名（无因果词，
identity 明示 NOT causal marginal value）。

## 6. 边界（如实）

- 本表是 risk-set 条件化 profile：能到 k3+ 的 episode 是至少两轮状态转移
  后的幸存路径——梯度存在 ≠ "第 3 次 ADD 导致更差"；
- "为什么递减"（序数性 vs outcome₁ 信息性）= T8.2 预注册 conditional
  decomposition 的专属问题；
- 不构成任何 policy 建议（Plan §3 红线：order gradient ≠ 可执行政策价值）。
