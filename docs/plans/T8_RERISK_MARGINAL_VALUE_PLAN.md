# T8 Plan：第 N 次 Re-risk 的边际价值（独立预注册，已拍板冻结版 v2）

> **立项 provenance（拍板④）**：T7 synthesis 暴露的 open question（§3.1）——
> **不是** "T7.4 D1→新规则"。研究对象已变：从"何时恢复风险"转向"风险重新
> 扩张的次数/顺序是否改变边际价值"。段编号 T8 独立（T7 已 FINAL FROZEN）。
>
> **研究纪律句（冻结）**：T8 研究 repeated re-risk 的**条件边际结构**，
> 不预设"次数越多越差"，也不从 T7.4 的 D1=75.9% 反推出停止规则。

## 1. 研究问题与 estimand（拍板新增：两个 estimand 严格区分）

**Conditioning 契约（冻结）**：ADD₂/ADD₃ 的存在本身是前序路径的结果——能到
ADD₃ 的 episode 已经历至少两轮状态转移，是高度选择后的 risk set。因此：

- **Estimand A — Observed order profile**：在实际到达 ADD_k 的 risk set 中，
  ADD_k 后五维 outcome 如何随 k 变化？（描述性 risk-set profile）
- **Estimand B — Conditional order contrast**：在预注册 outcome₁ 条件
  （{FR, CYCLE_OK, OTHER}）下，k 的差异是否仍然存在？（条件分解）

**命名纪律**：即使 B 有差异，也只能叫 **conditional association / marginal
profile**，禁止表述为"第三次 ADD 导致更差"（因果词禁用）。

**RQ1（主）**：Estimand A——k1/k2/k3+ 五维：False ADD 风险（frozen 定义，
锚各 ADD_k 自己的 a0_day）/恢复捕获/资本占用/后续 dd/收益贡献。
**RQ2（次）**：Estimand B——outcome₁ 已能解释多少 order gradient？（先回答
order effect 是否存在；MAE 深度分层**明确不做**——防"第几次 re-risk"变成
新的状态发现工程，MAE 留后续独立机制研究。）

## 2. k 分组（拍板①：无数据依赖规则）

- **主分析固定三组：k=1 / k=2 / k≥3**。不设"k=4 若 n≥300 则单列"——报告
  结构不得由样本量决定。
- 原始 cycle_index 全量保存；预注册**纯描述 appendix**：逐 k 报 n 与五维
  指标，达到最低展示量可显示 k=4/5/…，但**不进主 inference、不改主
  grouping**。

## 3. 分段结构（拍板③：T8.2 不产生 policy）

| 段 | 内容 | 权限 |
|---|---|---|
| **T8.0** | Sequence Fact Layer：完整 REDUCE-cycle risk set + ADD order 重构 + G40 守恒 | 全段，机械重构 |
| **T8.1** | Order Anatomy：k1/k2/k3+ 五维 outcome | **descriptive only**（dev 报告，VAL/CONF primary） |
| **T8.2** | Preregistered Order Inference：三个固定 contrast（k1 vs k2 / k2 vs k3+ / k1 vs k3+）+ outcome₁ conditional decomposition | **descriptive + preregistered inference 止步**，不产生"第 3 次禁止 ADD"类规则 |
| **T8.3** | Synthesis：decreasing / flat / conditional 三形态均合法 | — |
| [条件门] | **仅当证据值得继续**：独立 Policy Amendment Design → Freeze → VAL → CONF（仅 VAL 通过才进） | 完整 C1 纪律管线 |

红线：发现"漂亮的 order gradient"≠它具有可执行政策价值（C1 教训原文承继）。

## 4. T8.0 数据结构（拍板新增：competing path 完整 risk set）

**cycle_attempt table（全分类，无样本消失）**：

```
cycle_attempt
├── RECOVERED_ADD → 有 ADD_k（k 序列编在此）
├── NO_RECOVERY   → 无 ADD（competing path：未再次进入）
├── FAILED_EXIT   → 无 ADD（competing path：失败退出）
└── CENSORED      → censor
```

**为什么**：只重构 ADD 序列会条件化在"系统最终又 ADD 了"，恰好漏掉
"什么时候停止下注"问题的一半——无 ADD 的 REDUCE cycle 是
"停止重新承担风险"的 competing path，**不能从样本中消失**。

**G40 守恒（升级版，先于任何分析）**：
- 每个冻结 REDUCE→ADD cycle 恰好映射到一个 T8 cycle row；
- `(event_id, cycle_index)` unique；
- Σ cycle rows = 冻结 T6.2 eligible cycles 总数；
- 每个 ADD_k 的 `a0_day` / preceding `r0_day` / next reduce-or-exit /
  horizon end 全部可追溯 frozen fact（逐字段对账）。

k 定义（预注册）：k 锚 **REDUCE→ADD 尝试**（含 FR cycle）；
NO_RECOVERY/NO_ADD cycle 不入 k 序列（无 re-risk 行为）；episode 首次建仓
不是 re-risk（k 从首次 REDUCE 后的首次 ADD 起算）。

## 5. 统计框架（全冻结复用）

双 cluster bootstrap（stock_code/T0_date，cluster_boot_diff 4 元组）；
est=wmedian；Holm dict 接口；三个固定 contrast 的 p 值族内 Holm 校正；
frontier 二维呈现（x=False ADD 风险，y=恢复捕获/收益贡献），禁单轴 score。

## 6. Gate 计划（承 T7 编号）

- **G40 lineage+守恒（升级版如上）**；
- **G41 分段防污染**（VAL/CONF 在任何规则 Freeze 前不可见；产物 segment 列
  +计算路径扫描，承 G22）；
- **G42 双 clock**（False ADD 锚各 ADD_k 自己的 a0_day；恢复捕获锚公共
  cycle clock，承 G26/G29）；
- **G43 描述纪律**（T8.1 零规则词/零阈值，承 G20）；
- **G44 estimand 命名纪律**（B 类结果禁因果词——报告扫描
  "导致/造成/因果"于 contrast 表述）；
- G45（仅条件门触发）：Amendment Freeze 时序+counterfactual 守恒+sizing
  继承（承 G25/G27/G-F6 Lock）。

## 7. 预期结果三形态（预注册，防事后择优）

1. **decreasing**：ADD₃+ 边际 profile 显著低于 ADD₁ → 边界存在，值得后续
   policy 研究（仍需独立 Freeze→VAL）；
2. **flat**：各 k 无系统差异 → 循环再入无衰减，"停止规则"无数据基础；
3. **conditional**：outcome₁ 条件化后 order gradient 消失/大幅缩小 →
   边界在"路径历史"而非"次数"（RQ2 成立）。

三形态均合法终点；不因不显著视为失败（承 T7.4 F6' 大≠失败纪律）。

## 8. 开放边界如实清单

- horizon 限制承 T7.4（≥60 日形态不可检验，max span=41）不在 T8 范围；
- sector/市场情境变量：EXPLORATORY sidecar 至多，禁入 primary；
- MAE 深度分层：明确不做（§1 RQ2）。

## 9. 拍板记录（2026-09，用户四项+两项结构增强）

1. k 分组固定三组无数据依赖规则；描述 appendix 承载逐 k；
2. RQ2 仅 outcome₁ 三值条件，MAE 不做；
3. T8.2 止于 descriptive+preregistered inference，不产生 policy；policy
   路线仅条件门后另开完整管线；
4. 段编号 T8 独立；provenance=T7 synthesis open question≠D1 派生。
5. （新增）两个 estimand（A observed order profile / B conditional order
   contrast）严格区分；B 结果命名禁因果词；
6. （新增）cycle_attempt table 全分类 + G40 升级守恒（无 ADD 的 REDUCE
   cycle=competing path 不消失）。

**本 Plan 冻结后开工 T8.0 编码。**
