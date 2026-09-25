# T8 Plan：第 N 次 Re-risk 的边际价值（独立预注册，不从 D1 派生）

> **立项依据**（T7 Synthesis §3.1，用户终审确认）：及时 re-expansion 很重要，
> 但 repeated re-risk 是否仍具有相同的风险收益结构——T5-T7 动态仓位体系最后
> 一个核心未答问题："允许资金循环重新进入"与"什么时候应该停止给这条路径
> 继续下注"之间的边界在哪里。
>
> **纪律边界**：不从 T7.4 D1（振荡形态）反推规则；不寻找新价格/量能特征；
> 核心是先把 episode 重构为 re-risk 序列，再研究条件边际价值。

## 1. 研究问题（预注册）

**RQ1（主）**：ADD₁ / ADD₂ / ADD₃+ 的**条件边际价值**是否发生系统性变化？
维度（每 k 分组报，全部 outcome-based）：
- False ADD 风险（frozen 定义：policy-independent W10+adverse excursion，
  承 T7.3 口径但锚各 cycle 自己的 a0_day）；
- 恢复捕获（该次 re-risk 是否参与 TrueRecovery 建立，承 T7.0 冻结定义）；
- 资本占用（exposure-days / occupancy）；
- 后续 drawdown（ADD_k 后的 MAE/running dd）；
- 每 cycle 收益贡献（exposure-weighted，承 T7.3 sizing 语义=实际 A 路径）。

**RQ2（次）**：若边际价值递减存在，其**结构**是信息性的（前期 outcome₁ 可
预测后续 ADD_k 的价值——如 outcome₁=FR 后的 ADD₂ 更差）还是纯序数性的
（第 k 次本身就差）？——RQ2 只做预注册对比，不产生 policy。

## 2. 数据基础：T8.0 Sequence Fact Layer（唯一新 fact 层）

从**已冻结**产物重构（零新变量定义）：
- T6.2 cycle master（31,260 cycles：event_id/r0_day/a0_day/type/false_recovery/
  true_recovery）→ 按 episode 内时间序编 **k = cycle_index**（第 k 次
  REDUCE→ADD 尝试）；
- T7.0 outcomes（per-cycle mfe/mae/bh、true_recovery、recovery_established_day）；
- T6.0 daily master（exposure path、close_adj）→ per-cycle 窗口计量。

**守恒 Gate（先于任何分析）**：重构后 Σcycles（各 k）=31,260；每 episode 的
k 序列连续（无跳号）；与 T6.2/T7.0 冻结行逐位对账（G40 lineage）。

## 3. 分段协议（沿用 T7 纪律）

| 段 | 内容 | 段权限 |
|---|---|---|
| T8.0 | sequence fact layer 重构+守恒 gate | 全段，机械重构 |
| T8.1 | k-分组的描述性 frontier（RQ1 全维度×全段报告） | development 报告，VAL/CONF primary |
| T8.2 | RQ2 预注册对比（outcome₁ 条件下的 ADD₂/₃+ 边际） | 若含任何可执行规则形态 → 先 Freeze 后 VAL（承 T7 Amendment Freeze 纪律）；纯描述则止于报告 |
| T8.3 | synthesis（成立/否定/开放三分法，承 T7 格式） | — |

**红线**：T8.1 的任何"递减"视觉/统计印象不得直接进入 T8.2 的规则设计——
若 T8.2 需要阈值，须 DEV-only 选择 + Amendment Freeze + VAL 验证完整管线
（T7 C1 案例的全部纪律）。

## 4. 统计框架（全部冻结复用）

- 双 cluster bootstrap（stock_code / T0_date，cluster_boot_level/diff 4 元组）；
- est=wmedian（STATS 冻结）；Holm dict 接口；
- k 组间对比：ADD₁ vs ADD₂ vs ADD₃+（若 k≥4 样本不足则合并为 3+，预注册
  合并规则：k≥3 合并，k=4 单列仅当 n≥300）；
- frontier 呈现：x=False ADD 风险，y=恢复捕获/收益贡献（承 T7 二维纪律，
  禁单轴 score）。

## 5. Gate 计划（编号承 T7 继续）

- **G40 lineage/守恒**：重构逐位对账+k 连续性；
- **G41 分段纪律**：VAL/CONF 在任何规则 Freeze 前不可见（承 G22 防污染：
  产物 segment 列+计算路径扫描）；
- **G42 双 clock**：False ADD 锚各 ADD_k 自己的 a0_day；恢复捕获锚公共
  cycle clock（承 G26/G29）；
- **G43 描述纪律**：T8.1 零规则词、零阈值（承 G20）；
- **G44（若 T8.2 走 freeze 路线）**：Amendment Freeze 时序+counterfactual
  守恒+sizing 继承（承 G25/G27/G-F6 Lock）。

## 6. 预期结果形态（预注册三种可能，防止事后择优解读）

1. **递减**（ADD₃+ 边际价值显著低于 ADD₁）→ 边界存在，值得后续 policy 研究；
2. **平坦**（各 k 无系统差异）→ 循环再入无衰减，"停止规则"无数据基础；
3. **条件性**（outcome₁=FR 后的 ADD₂ 差，CYCLE_OK 后不差）→ RQ2 结构成立，
   边界在"路径历史"而非"次数"。

三种形态均为合法终点；报告按实际落入形态收束，不因结果"不显著"视为失败
（承 T7.4 F6' 大≠失败的同型纪律）。

## 7. 开放边界如实清单（预注册时点）

- k 的定义锚 REDUCE→ADD 尝试（含 FR cycle）；NO_RECOVERY/NO_ADD cycle 不入
  k 序列（它们没有 re-risk 行为）——该排除规则预注册；
- episode 首次建仓不是 re-risk（k 从首次 REDUCE 后的首次 ADD 起算）；
- horizon 限制承 T7.4：≥60 日形态不可检验（max span=41）不在 T8 范围；
- sector/市场情境变量：EXPLORATORY sidecar 至多，禁入 primary（承 T7 纪律）。

## 8. 待您拍板

1. k 合并规则（k≥3 合并；k=4 单列仅当 n≥300）；
2. RQ2 的条件变量集（当前仅 outcome₁ ∈ {FR, CYCLE_OK, 其他}；是否加
   outcome₁ 的 MAE 深度分层）；
3. T8.2 走"纯描述"还是"预注册 freeze 路线"（影响 gate 集合）；
4. 段编号沿用 T8 还是并入 T7.5（建议 T8：独立预注册阶段，与用户"不从
   D1 派生"的边界一致）。
