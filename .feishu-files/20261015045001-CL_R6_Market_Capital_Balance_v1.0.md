# CL-R6 — Market Capital Balance / A股市场资金供需状态研究方案

> 版本：v1.0  
> 状态：Proposal / Ready for Preregistration  
> 目标：建立一个面向 A 股的 **MarketCapitalRegime（市场资金状态）**，用于回答“市场有没有增量风险资本、资金是否真正进入股票、市场需要消化多少筹码、资金能否吸收这些筹码”，并最终作为现有 Capital Decision 体系的市场背景与风险预算输入。

---

## 1. 研究背景

当前 CL Radar 已完成：

- R1：历史成交密度 / 筹码供应假说 → **NEGATIVE**
- R2：事件锚定成本 / AVWAP → **NEGATIVE**
- R3：Daily Effort → Future Impact Penalty → **POSITIVE**
- R4：Opening Effort / Timing Increment → **POSITIVE**
- R5 OOS-A：
  - F1 Daily Effort Penalty → **PASS**
  - F2 Episode Amplification → **FAIL，永久淘汰**
  - F3 Opening Effort Replication → **PASS**
  - F4 Timing Increment → **PASS**

当前最稳固的个股/盘中链条是：

\[
DailyEffort
\leftrightarrow
OpeningEffortStructure
\leftrightarrow
FutureImpactEfficiency
\]

但个股层仍然受到消息面、游资、题材、随机性、旧筹码长期滞留、个股主力行为不可观测等强噪声干扰。

因此下一阶段研究层级上移，从个股资金行为转向：

\[
\boxed{
市场有没有钱
\rightarrow
钱有没有进入股票
\rightarrow
股票市场要消化多少供给
\rightarrow
这些钱能不能接住这些筹码
}
\]

核心思想不是预测指数，而是建立 **A 股市场资金供需状态机**。

---

# 2. 核心研究问题

CL-R6 不回答：

> 明天上证指数涨还是跌？

而回答：

1. 金融体系当前是否处于资金扩张 / 收缩？
2. 宏观流动性是否真正传导到股票市场？
3. 股票市场获得的是增量资金，还是存量资金反复轮动？
4. 当前市场潜在 / 实际股票供给有多大？
5. 新进入的风险资本是否足以吸收这些股票供给？
6. 同一个 CD 候选状态，在不同市场资金状态下，是否具有不同的参与价值和风险预算？

最终目标：

\[
\boxed{
MarketCapitalRegime
\rightarrow
Participation / Exposure Context
}
\]

而不是：

\[
MarketCapitalRegime
\rightarrow
StockRanking
\]

---

# 3. 已有外部研究基础

CL-R6 不是从零发明指标，而是把已有研究拆成可验证模块。

## 3.1 宏观流动性与股票市场

已有中国市场研究表明：

- 货币政策 / 流动性对股票市场流动性的作用具有明显时变性；
- 牛熊阶段、风险偏好、流动性预期会改变传导结果；
- 因此不能简单使用：

\[
M2\uparrow \Rightarrow 股市资金\uparrow
\]

更合理的研究对象是：

\[
MacroFunding
\rightarrow
EquityTransmission
\]

### 研究启示

宏观资金只能解释“资金条件”，不能自动解释“资金已经进入股票”。

---

## 3.2 ETF 资金传导

已有 A 股研究支持：

- ETF 持有、ETF 套利、ETF 资金变化会影响成分股流动性和价格效率；
- 但不同研究对 ETF 对价格效率的净作用存在分歧。

因此：

\[
\boxed{
ETFFlow \neq BullishSignal
}
\]

ETF 更适合被定义为：

> 股票市场资金进入、退出与再配置的真实通道。

推荐原子量：

\[
Flow^{ETF}_{t}
=
\sum_i
(\Delta Shares_{i,t})\times NAV_{i,t}
\]

拆分为：

- BroadMarketETFFlow
- SectorETFFlow
- StyleETFFlow

---

## 3.3 融资资金

中国市场研究表明：

- 融资交易对市场流动性的作用随市场状态变化；
- 融资余额不仅代表新增买盘，也代表未来潜在需要平仓的存量杠杆筹码。

因此同时保留：

\[
MarginFlow_t
=
MarginBalance_t-MarginBalance_{t-1}
\]

和：

\[
MarginStock_t
=
\frac{MarginBalance_t}{FreeFloatMV_t}
\]

含义：

- `MarginFlow`：新增杠杆需求
- `MarginStock`：潜在未来杠杆供给

---

## 3.4 股票供给 / 解禁

已有中国市场研究表明：

- 解禁附近市场流动性和波动率可能发生显著变化；
- 但解禁不等于实际卖出。

因此：

\[
\boxed{
UnlockSupply \neq RealizedSelling
}
\]

解禁应被定义为：

> 潜在股票供给压力

而非确定性卖盘。

---

## 3.5 资本市场专项政策流动性

2024 年以后，A 股宏观资金体系中增加了过去不存在或不显著的专项工具，例如：

- 证券、基金、保险公司互换便利
- 股票回购增持再贷款
- 其他面向资本市场的逆周期流动性工具

因此必须独立建立：

\[
PolicyEquityLiquidityState
\]

禁止把这类工具简单混入普通 M2 / 社融。

---

# 4. CL-R6 总体架构

第一版不建立综合分数。

禁止：

\[
LiquidityScore
=
0.3M1+0.2ETF+...
\]

第一版只维护四个独立状态轴：

\[
\boxed{
C_t=
[
Funding_t,\;
EquityFlow_t,\;
EquitySupply_t,\;
Absorption_t
]
}
\]

---

## 4.1 F — Funding State

回答：

> 金融体系的钱松不松？

### 变量候选

#### 货币 / 信用

- M1
- M2
- M1-M2
- 社融存量增速
- 社融新增
- 人民币贷款
- 信用脉冲 Credit Impulse

示意：

\[
CreditImpulse_t
\approx
\Delta
\left(
\frac{NewCredit_t}{GDP_t}
\right)
\]

核心问题不是信用总量，而是：

> 信用创造是在加速还是减速？

#### 资金价格

- DR007
- Shibor
- 国债收益率
- 实际利率
- 信用利差

#### 专项资本市场政策

- SFISF
- 股票回购增持再贷款
- 其他资本市场稳定工具

---

## 4.2 E — Equity Flow State

回答：

> 钱有没有真正进入股票？

### 第一优先：ETF

\[
ETFNetFlow_t
=
\sum_i
\Delta Shares_{i,t}\times NAV_{i,t}
\]

拆分：

- 全市场宽基 ETF
- 行业 ETF
- 风格 ETF

### 第二优先：融资

\[
MarginFlow_t
\]

\[
MarginStock_t
\]

### 第三优先：权益基金

- 主动权益基金发行
- 基金申赎
- 权益仓位变化

该模块只作为低频补充，不假设因果单向。

---

## 4.3 S — Equity Supply State

回答：

> 市场现在要消化多少股票供给？

第一阶段原子量：

- IPO
- 再融资 / 增发
- 定增
- 解禁
- 大股东减持
- 产业资本减持
- 回购
- 重要股东增持

原则：

\[
\boxed{
PlannedSupply
\neq
PotentialSupply
\neq
RealizedSupply
}
\]

严格区分：

- 已计划
- 已解禁 / 可卖
- 已实际卖出

禁止将三者直接混为一个值。

---

## 4.4 A — Absorption State

回答：

> 进入股票市场的钱，能不能接住当前筹码供给？

候选变量：

- 全市场成交额
- Turnover / FreeFloatMV
- 市场级 Impact Efficiency
- 上涨家数 / 下跌家数
- 市场 breadth
- 行业 breadth
- 创新高 / 创新低比例
- 行业同步性
- 成交集中度

重要状态示例：

\[
成交额\uparrow
+
指数停滞
+
Breadth\downarrow
\]

可能描述为：

\[
\boxed{
高成交 / 低吸收效率
}
\]

这不是自动等价于“出货”。

只描述：

> 大量资金活动并未转化为广泛、有效的价格推进。

---

# 5. 初始 MarketCapitalRegime 假设空间

第一阶段不预先给行为解释，只允许描述性命名。

## Regime A — Funding Contraction

特征候选：

\[
Funding\downarrow
\]

\[
EquityFlow\downarrow
\]

描述：

> 金融体系和股票市场同时缺乏增量风险资金。

## Regime B — Stock Rotation / 存量轮动

特征候选：

\[
Funding\approx Neutral
\]

\[
EquityFlow\approx Neutral
\]

\[
Turnover\uparrow
\]

\[
Breadth\downarrow
\]

描述：

> 交易活跃但总风险资本没有明显扩张，资金主要在股票和板块之间重新分配。

这可能是典型的 A 股“存量内卷”状态。

## Regime C — Incremental Capital Expansion

特征候选：

\[
ETFFlow>0
\]

\[
MarginFlow>0
\]

\[
SupplyPressure\ low
\]

\[
Breadth\uparrow
\]

描述：

> 新风险资本进入，并形成较广泛市场参与。

## Regime D — Capital Inflow Absorbed by Supply

可能出现：

\[
EquityFlow>0
\]

同时：

\[
SupplyPressure\uparrow
\]

\[
AbsorptionEfficiency\downarrow
\]

描述：

> 资金确实进入，但主要被新老筹码供给吸收，市场广度和推进效率没有同步改善。

这一状态对 A 股尤其值得研究。

---

# 6. 研究范围 v1

第一版只做四个核心轴：

\[
\boxed{
Credit/Funding
+
ETFFlow
+
Margin
+
Unlock/Supply
}
\]

暂缓：

- 主动基金全量申赎
- 保险资金
- 国家队身份推断
- 北向资金细分
- 大股东完整减持链
- 回购 / 增持全量建模
- Level2
- 新闻 / 事件文本
- 个股高频 OFI

目的：

> 先证明“市场资金供需状态”是否存在稳定结构，再扩展数据源。

---

# 7. 数据时间范围

建议历史重建：

\[
\boxed{2018\rightarrow2026}
\]

理由：

- ETF 市场已具规模
- 包含资管新规后环境
- 包含疫情时期
- 包含 2021–2023 房地产 / 信用转型
- 包含 2024 以后资本市场专项政策工具
- 市场状态差异足够大
- 数据规模仍极小

---

# 8. PIT 数据合同

这是 R6 的第一硬门。

每一条数据必须至少包含：

```text
observation_date
available_at
source
raw_value
normalized_value
revision_flag
```

模型在决策日 T 只能使用：

\[
available\_at\le T
\]

## 8.1 月度宏观数据

例如：

- 9 月社融
- 9 月 M1/M2
- 9 月贷款

不能假定 9 月 30 日可知。

必须使用官方实际发布日期。

## 8.2 ETF

ETF 份额通常在清算后可知。

必须区分：

```text
trade_date
available_at
```

禁止日内提前使用 EOD 清算结果。

## 8.3 融资

融资余额、融资买入额等通常为收盘后数据。

用于次日状态时：

\[
available\_at=T\ close\ after
\]

## 8.4 解禁

解禁公告通常提前可知。

因此未来潜在供给表可以包含：

\[
KnownFutureSupply(T+h)
\]

但必须基于当时已经公开的信息。

---

# 9. 研究阶段

## R6-0 — Evidence Atlas

### 目标

不写预测模型。

先建立现成研究地图。

### 研究域

1. Macro Liquidity
2. Credit Impulse
3. ETF Transmission
4. Margin Financing
5. Equity Supply / Unlock
6. Policy Liquidity
7. Market Breadth / Absorption

### 每篇论文 / 仓库建立机制卡

```text
idea
capital_layer
physical_mechanism
observable
formula
data_required
sample
market
period
oos
main_result
failure_mode
a_share_fit
pit_risk
existing_overlap
local_test
verdict
```

### 关键纪律

严格分开：

- 作者真正证明的结果
- 我们的资金逻辑解释

## R6-1 — PIT Data Contract

冻结：

- 数据源
- 单位
- 日期语义
- available_at
- 缺失规则
- revision policy
- 数据版本
- 时间范围

### Gate U

沿用 CL Radar：

\[
\boxed{\text{Unit Contract}}
\]

单位不清楚直接停止。

## R6-2 — Historical Capital Panel

建立：

```text
date
FundingState atoms
ETFFlow atoms
Margin atoms
Supply atoms
Absorption atoms
market controls
data_quality flags
```

只保留原子量。

第一阶段：

\[
\boxed{\text{禁止综合评分}}
\]

---

# 10. 核心验证 Gate

## G1 — Funding Transmission

问题：

> 宏观资金改善以后，股票市场资金流是否真的改善？

验证：

\[
Funding_t
\rightarrow
EquityFlow_{t+h}
\]

若不存在稳定传导：

> 宏观宽松不能直接进入股票状态。

## G2 — Equity Flow Consequence

问题：

> 真正进入股票市场的资金，是否改善市场吸收能力？

观察：

- Breadth
- Liquidity
- Turnover
- ImpactEfficiency
- Market Participation

而非只看未来指数收益。

## G3 — Supply Absorption

核心问题：

在相同 `EquityFlow` 条件下：

\[
SupplyPressure\uparrow
\]

是否对应：

- Breadth 降低
- 推进效率降低
- 波动提高
- 轮动加快
- 持续性降低

如果成立，这是 R6 最有生产意义的结果之一。

## G4 — Regime Persistence

宏观状态必须具有持续性。

目标时间尺度：

\[
weeks\rightarrow months
\]

如果状态每天切换：

\[
A\rightarrow C\rightarrow B\rightarrow A
\]

则视为噪声，不允许生产化。

## G5 — CD Incremental Value

最后才测试与现有选股体系的关系。

冻结一个 CD 候选状态，例如：

```text
Support + T2 + T3
```

比较同一候选结构在不同 MarketCapitalRegime 下：

- breakout success
- +5d survival
- +10d survival
- +20d survival
- MFE
- MAE
- participation outcome
- exposure outcome
- holding duration

目标：

\[
\boxed{
MarketCapitalRegime
\rightarrow
Candidate Outcome Distribution
}
\]

而不是：

\[
MarketCapitalRegime
\rightarrow
Stock Selection
\]

---

# 11. 与现有 Capital Decision 的接入

当前：

\[
StockState
\rightarrow
Participation
\rightarrow
Exposure
\]

未来候选：

\[
\boxed{
MarketCapitalRegime
\rightarrow
StockState
\rightarrow
Participation / Exposure
}
\]

## 示例

同样：

```text
Support + T2 + T3
```

### 存量轮动状态

候选策略可能：

- Participation 较低
- 初始仓位较低
- 追突破限制更严格
- 加仓门槛提高
- 持有周期缩短

### 增量扩张状态

候选策略可能：

- Participation 提高
- 初始仓位提高
- staged add 更宽松
- 容忍更长持有周期
- breakout 参与度提高

注意：这些只能在 G5 通过后进入 Decision-Shadow。

---

# 12. 生产升级路径

禁止：

\[
Research
\rightarrow
直接生产
\]

建议：

\[
EvidenceAtlas
\rightarrow
PIT\ Data\ Contract
\rightarrow
Historical\ Capital\ Panel
\rightarrow
Mechanism\ Validation
\rightarrow
MarketCapitalRegime
\rightarrow
CD\ Candidate\times Regime
\rightarrow
Shadow
\rightarrow
Decision\text{-}Shadow
\rightarrow
Production
\]

---

# 13. 三个永久禁区

## 禁区 1

禁止：

\[
M2\uparrow
\Rightarrow
牛市
\]

正确语义：

> M2 只描述宏观资金条件之一。

## 禁区 2

禁止：

\[
ETF申购
\Rightarrow
国家队买入
\]

正确语义：

> ETF 份额变化表示该 ETF 通道的净申购 / 赎回行为，不自动识别资金身份。

## 禁区 3

禁止：

\[
解禁
\Rightarrow
实际卖出
\]

正确语义：

> 解禁表示潜在可交易供给增加，不等于实际减持。

---

# 14. 其他方法纪律

继续继承 CL Radar 的三道方法门：

## Gate U — Unit Contract

所有单位在研究前冻结。

## Gate M — Mechanical Baseline

任何与价格距离 / 阈值有关的结果，必须先去除机械距离效应。

## Gate S — Shared Construction Contamination

解释变量和结果变量如果共享同一构造项，不允许把机械相关解释为行为机制。

---

# 15. 正负结果处理

若某模块失败：

\[
\boxed{
FAIL\rightarrow CLOSE\ HONESTLY
}
\]

禁止：

- 改窗口救结果
- 换变量救结果
- 找最佳 regime
- 扫阈值
- 事后命名
- 重新定义结果变量
- 使用复杂 ML 作为救援

外部研究只提供先验，不改变本地验证标准。

---

# 16. 推荐第一阶段交付物

## 16.1 文档

```text
CL_R6_EVIDENCE_ATLAS.md
CL_R6_DATA_SOURCE_CENSUS.md
CL_R6_PIT_CONTRACT.md
CL_R6_PREREGISTRATION.md
```

## 16.2 数据

```text
data/cl_radar/r6/
  macro/
  etf/
  margin/
  supply/
  market/
  manifests/
```

## 16.3 核心 Panel

```text
market_capital_panel_daily.parquet
market_capital_panel_monthly.parquet
```

---

# 17. 推荐数据源方向

优先官方 / 原始来源：

- 中国人民银行
  - M1 / M2
  - 社融
  - 人民币贷款
  - 政策工具
- 上海证券交易所
  - ETF 份额
  - 融资融券
- 深圳证券交易所
  - ETF / 融资相关数据
- 中国证监会 / 交易所
  - IPO / 再融资
  - 解禁 / 减持 / 回购
- 市场行情源
  - 全市场成交额
  - 市值
  - breadth
  - 指数与行业行情

第三方源仅用于：

- 交叉验证
- 缺口补充
- 开发阶段快速探索

不作为最终唯一事实源。

---

# 18. 现成研究 / 工程参考

以下仅作为 Evidence Atlas 起点，不代表直接采用其结论。

### Macro Liquidity Regime

- `dbose/liquidity-valuation-research`
- 用途：参考宏观代理矩阵 → liquidity factor → regime 的工程方式
- 注意：主要针对美国市场，不能直接移植结论

### A 股 ETF / Flow 工程参考

- `cyijun/a-share-flow-dashboard`
- 用途：ETF 份额变化、板块资金流实现参考
- 注意：其行业历史 membership 存在 PIT 风险，不能直接用作历史事实库

### ETF / 流动性研究

重点关注：

- ETF ownership 与标的流动性
- ETF arbitrage 与 price efficiency
- ETF flow 与市场微观结构

### Margin Research

重点关注：

- margin flow
- margin stock
- built-in future supply
- regime dependence

### Equity Supply Research

重点关注：

- unlock
- IPO / SEO
- realized reduction
- volatility / liquidity impact

---

# 19. 当前最重要的研究假设

CL-R6 的核心不是：

\[
Liquidity\Rightarrow Return
\]

而是：

\[
\boxed{
Funding
\rightarrow
EquityFlow
\rightarrow
SupplyAbsorption
\rightarrow
MarketParticipationEnvironment
}
\]

如果这条链能成立，才进一步进入：

\[
\boxed{
MarketCapitalRegime
\rightarrow
CD Participation / Exposure
}
\]

---

# 20. 最终目标

建立一个低频、稳健、可解释的 A 股市场资金状态层：

\[
\boxed{
MarketCapitalState_t
}
\]

它不负责：

- 预测指数点位
- 选择具体股票
- 识别“主力”
- 预测题材
- 捕捉游资

它只负责回答：

> **当前整个股票市场处于什么资金供需环境？**

并给现有选股系统提供：

\[
\boxed{
风险预算背景
+
参与度背景
+
持仓周期背景
}
\]

---

# 21. 项目边界

## 本阶段做

- 宏观流动性
- ETF
- 融资
- 股票供给
- 市场吸收能力
- MarketCapitalRegime
- 与现有 CD 候选的增量验证

## 本阶段不做

- Level2
- Tick / OFI
- 新闻 NLP
- 个股主力身份
- 龙头预测
- Profit Mass / Trapped Mass
- 高频分钟全市场扫描
- 复杂 ML

---

# 22. 建议执行顺序

\[
\boxed{
R6-0\ Evidence\ Atlas
}
\]

↓

\[
\boxed{
R6-1\ PIT\ Data\ Contract
}
\]

↓

\[
\boxed{
R6-2\ Historical\ Capital\ Panel
}
\]

↓

\[
\boxed{
Funding
\rightarrow
EquityFlow
\rightarrow
Supply/Absorption
}
\]

↓

\[
\boxed{
MarketCapitalRegime
}
\]

↓

\[
\boxed{
CD\ Candidate\times Regime
}
\]

↓

\[
\boxed{
Participation/Exposure\ Shadow
}
\]

---

# 23. 一句话定义

> **CL-R6 研究的不是“股票为什么明天涨”，而是“整个市场现在有没有足够的新风险资本去接住不断释放出来的股票筹码，以及这种资金供需状态应不应该改变我们的参与度和风险预算”。**
