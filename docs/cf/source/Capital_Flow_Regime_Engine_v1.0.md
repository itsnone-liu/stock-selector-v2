# A股 Capital Flow Regime Engine 技术方案 v1.0

> 目标：建立一个位于现有选股系统上游的“资金状态引擎”，先判断不同性质资金当前所处状态、未来潜在买卖压力与市场主导力量，再决定是否参与市场、参与哪些板块、选择哪些个股以及如何控制仓位。

---

## 1. 研究出发点

A股价格并不是数字自身演化的结果，而是不同类型资金在不同目标、约束和时间尺度下博弈的结果。

传统技术分析通常从价格、成交量、均线、突破、回撤等结果变量出发，试图预测后续价格。但对于A股，尤其是在机构化、ETF化、杠杆化程度不断提高以后，更有效的研究路径应当是：

> **先判断谁在买、谁在卖、为什么必须买或必须卖、还能持续多久，再观察这些行为留下的价格与成交痕迹。**

因此，本项目不以“预测明天涨跌”为核心，而以识别和预判：

- 哪些资金正在流入；
- 哪些资金正在流出；
- 哪些资金存在潜在被迫卖出压力；
- 哪些资金可能因政策、估值、负债约束或风险预算而被迫买入；
- 当前市场的新增买盘能否吸收正在释放的卖盘；
- 这种资金状态对大盘、板块和个股分别意味着什么。

价格、成交量、ETF份额、两融、基金持仓、龙虎榜等数据在本体系中属于**资金行为传感器**，而不是模型本身。

---

# 2. 总体架构

整体资金体系采用：

```text
L1 政策稳定资本
        ↓
L2 结构性机构资本
        ↓
L3 个股主动资本
        ↓
L4 情绪与跟随资本

M 杠杆场：贯穿 L2-L4，放大上涨与下跌
```

上层决定市场大环境，下层决定局部行情。

对应到决策系统：

```text
Capital Flow Regime Engine
        ↓
市场风险状态
        ↓
Sector Flow Engine
        ↓
Stock Capital Structure Engine
        ↓
Stock Selection
        ↓
Entry / Position / Exit
```

即：

```text
宏观资金系统决定：现在是否值得下注
板块资金系统决定：资金正在往哪里走
个股资金系统决定：哪些股票存在主动资金推进
交易系统决定：什么时候进入、仓位多大、什么时候退出
```

---

# 3. 资金分层定义

## 3.1 L1：政策稳定资本

### 核心主体

- 中央汇金及类似政策稳定资金；
- 明确承担市场稳定功能的国有长期资金；
- 特定阶段通过宽基ETF等工具介入的政策性资本。

### 核心目标

第一目标不是短期收益最大化，而是：

```text
防止系统性风险
↓
稳定指数
↓
恢复流动性
↓
改善市场预期
```

### 时间尺度

日 → 月。

### 典型行为

```text
市场正常
    ↓
STANDBY

系统性下跌扩大
    ↓
WATCH

流动性/情绪恶化
    ↓
STABILIZATION_READY

宽基ETF异常放量 / 权重承接
    ↓
STABILIZATION_ACTIVE

市场恢复
    ↓
HOLD / NORMALIZE
```

### 重要原则

实时系统通常无法直接证明“某一天是中央汇金买入”。

因此必须区分：

```text
身份确认
```

与：

```text
行为识别
```

实时输出：

```text
L1-like stabilization activity = LOW / MEDIUM / HIGH
```

季度或半年持有人数据再用于身份验证。

---

# 4. L2：结构性机构资本

L2必须拆分，因为不同机构的目标函数和约束完全不同。

---

## 4.1 L2-A：险资 / 养老金 / 超长期配置资金

### 目标函数

```text
长期收益
+ 资产负债匹配
+ 低波动
+ 长期安全性
```

### 主要约束

- 偿付能力；
- 权益仓位上限；
- 负债久期；
- 年度考核；
- 风险预算；
- 流动性需求。

### 状态

```text
UNDERWEIGHT
NEUTRAL
ACCUMULATING
OVERWEIGHT
RISK_PRESSURE
DE-RISKING
```

### 重点研究

不是问：

> 险资持有多少股票？

而是问：

> 险资现在是否正在增加权益暴露，还是已经接近风险预算上限？

---

## 4.2 L2-B：银行理财 / 固收+ / 低回撤资金

这一类是市场下跌阶段最重要的潜在“被迫卖方”之一。

### 目标函数

```text
低波动
+ 稳定净值
+ 绝对收益
```

### 核心约束

- 产品回撤；
- 赎回压力；
- VaR / 波动率；
- 权益风险预算；
- 客户风险偏好。

### 典型状态机

```text
RISK_ON
   ↓
OVERWEIGHT
   ↓
NAV_PRESSURE
   ↓
RISK_BUDGET_PRESSURE
   ↓
FORCED_SELLING
   ↓
DELEVERAGED
```

### 最重要的前瞻问题

> 它是否已经进入“还没有大量卖，但已经必须准备卖”的状态？

这类资金最适合做前瞻压力预测。

---

## 4.3 L2-C：主动公募

### 目标函数

```text
相对收益
+ 排名
+ 基准
+ 规模增长
```

### 核心约束

- 基金申赎；
- 持仓集中度；
- 基准偏离；
- 年度排名；
- 流动性；
- 重仓股容量。

### 典型特征

容易产生：

```text
赛道抱团
→ 资金正反馈
→ 高拥挤
→ 回撤
→ 净赎回
→ 被动减仓
```

### 状态

```text
INFLOW
ACCUMULATING
CROWDED
NEUTRAL
REDEMPTION_PRESSURE
DE-RISKING
```

---

## 4.4 L2-D：私募 / 绝对收益机构

需要至少区分：

- 长周期主观私募；
- 趋势型CTA/量化；
- 市场中性；
- 高频/高换手策略；
- 事件驱动。

不应把“私募”看成单一资金。

状态模型需要根据策略类型分别建立。

---

## 4.5 L2-E：外资

需要区分：

```text
长期配置资本
```

与：

```text
交易型资本
```

主要驱动包括：

- 中国资产风险溢价；
- 汇率；
- 全球利率；
- MSCI/指数权重；
- 全球风险偏好；
- 海内外收益率差；
- 行业相对估值。

---

# 5. L3：个股主动资本

本层不直接使用“庄家”作为工程标签。

原因：

公开数据无法稳定证明一只股票存在统一庄家。

因此工程定义为：

> **能够在有限股票上形成集中买卖力量，并显著改变边际定价的主动资金。**

包括：

- 游资；
- 活跃私募；
- 产业资本；
- 大股东；
- 大户；
- 部分量化；
- 事件驱动资金；
- 其他集中交易资本。

---

## 5.1 个股资金生命周期

建立可验证的生命周期模型：

```text
ACCUMULATION
    ↓
CONTROL_BUILDING
    ↓
TESTING
    ↓
MARKUP
    ↓
ACCELERATION
    ↓
DISTRIBUTION_WARNING
    ↓
DISTRIBUTION
    ↓
EXIT
```

注意：

这不是预设所有牛股都存在统一庄家。

而是将上述状态作为：

```text
待验证的资本行为模式
```

---

# 6. L4：情绪与跟随资本

包括：

- 散户；
- 短线跟随资金；
- 热点追涨资金；
- 题材扩散资金。

### 特征

单个主体没有持续定价能力，但群体同步后可形成巨大短期合力。

### 核心机制

```text
价格上涨
↓
注意力增加
↓
传播扩散
↓
资金进入
↓
成交放大
↓
继续上涨
↓
更多资金进入
```

下跌时同样会形成反向反馈。

### 状态

```text
APATHY
RECOVERY
FOMO
EUPHORIA
PANIC
CAPITULATION
```

---

# 7. M：杠杆场

两融不属于某个固定投资者类别。

它是一个贯穿市场的：

> **风险放大器 + 强制交易机制**

因此单独建模。

---

## 7.1 两融基本状态

组合：

```text
价格方向 × 融资余额方向
```

得到：

| 股价 | 融资余额 | 解释 |
|---|---|---|
| ↑ | ↑ | 杠杆追涨，趋势强化 |
| ↑ | ↓ | 去杠杆上涨，筹码可能更健康 |
| ↓ | ↑ | 融资抄底，风险可能累积 |
| ↓ | ↓ | 主动/被动去杠杆 |
| 急跌 | 急降 | 强制去化风险 |

---

## 7.2 融资压力模型

核心链：

```text
融资买入
↓
形成融资筹码成本区
↓
价格跌破成本区
↓
浮亏扩大
↓
主动止损 / 保证金压力
↓
融资卖出
↓
价格继续下降
↓
更多融资盘承压
```

需要构建：

```text
Financing Cost Band
Financing Loss Pressure
Deleveraging Velocity
Forced-Selling Risk
```

---

# 8. 核心思想：预测资金约束，而不是预测股价

系统禁止直接将目标定义为：

```text
预测明天指数涨跌
```

主要预测对象改为：

```text
未来1-5日谁可能必须卖？
未来1-20日谁可能持续买？
哪些资金正接近风险约束？
哪些卖方压力正在衰减？
哪些买方正在增强？
```

因为：

> **人的制度约束和资金约束通常比价格方向更稳定。**

例如：

```text
固收+ 回撤扩大
→ 风险预算下降
→ 卖出概率提高
```

比：

```text
指数跌破某条均线
→ 明天继续跌
```

具有更强的经济解释。

---

# 9. 数据体系

数据分为六级。

---

## 9.1 D1：政策稳定资金传感器

数据：

- 宽基ETF成交额；
- 宽基ETF份额；
- ETF申赎；
- 大盘权重股异常承接；
- 尾盘成交结构；
- 指数跌幅修复；
- ETF持有人变更；
- 汇金等公开披露。

重点ETF：

```text
沪深300
上证50
中证500
中证1000
科创50
创业板
A500
```

---

## 9.2 D2：机构资金数据

### 险资

- 上市公司前十大股东；
- 险资持股披露；
- 保险资金运用余额；
- 权益配置比例；
- 保险产品资金流；
- 机构调研；
- 大宗交易。

### 公募

- 基金份额；
- ETF份额；
- 主动基金申赎；
- 季度持仓；
- 基金重仓股；
- 行业暴露；
- 规模变化。

### 固收+

直接数据较少，需要使用代理变量：

- 理财产品净值；
- 含权债基/二级债基表现；
- 产品规模；
- 债券基金申赎；
- 权益市场同步卖压；
- 机构重仓方向；
- 市场新闻与公开机构观点。

---

## 9.3 D3：外资

- 北向/互联互通可见数据；
- QFII持仓；
- 外资机构季度持股；
- 人民币汇率；
- 美债收益率；
- 全球风险资产；
- MSCI/FTSE指数调整。

---

## 9.4 D4：个股主动资本

- 龙虎榜；
- 大宗交易；
- 股东人数；
- 前十大流通股东；
- 大股东增减持；
- 解禁；
- 机构调研；
- 成交量；
- 换手率；
- VWAP；
- 筹码分布；
- 开盘/尾盘成交；
- 异常大单；
- 连续资金方向。

---

## 9.5 D5：散户情绪

- 全市场成交额；
- 上涨/下跌家数；
- 涨停/跌停；
- 连板高度；
- 炸板率；
- 新开户；
- 融资买入；
- 搜索/社媒热度；
- 小微盘指数；
- 题材扩散速度。

---

## 9.6 D6：杠杆

- 融资余额；
- 融资买入；
- 融资偿还；
- 融券余额；
- 行业融资变化；
- 个股融资变化；
- 融资成本区；
- 价格相对融资成本位置。

---

# 10. 每层统一数据结构

每种资金都使用统一结构：

```yaml
capital_layer:
  id:
  name:

  objective_function:
  constraints:
  time_horizon:

  observables:
  proxies:

  current_state:
  confidence:

  buying_pressure:
  selling_pressure:

  forced_buy_probability:
  forced_sell_probability:

  state_duration:
  state_velocity:

  upstream_drivers:
  downstream_impact:

  evidence:
  counter_evidence:

  last_updated:
```

---

# 11. 状态识别

不直接输出单一买卖结论。

每层输出：

```text
Current State
Pressure
Velocity
Confidence
```

例如：

```text
L2-B 固收+

State:
RISK_BUDGET_PRESSURE

Selling Pressure:
HIGH

Velocity:
INCREASING

Confidence:
0.74
```

---

# 12. “状态”和“身份”分离

这是系统的重要原则。

例如宽基ETF突然异常放量。

不能直接输出：

```text
中央汇金买入
```

而应该输出：

```text
STABILIZATION_BEHAVIOR = HIGH
```

证据：

```text
宽基ETF异常放量
+ ETF份额增加
+ 权重承接
+ 午后集中成交
+ 指数跌幅收窄
```

然后：

```text
Possible Actor:
Policy stabilization capital
Confidence:
Medium
```

待后续披露验证。

---

# 13. 市场总状态模型

最终将各层状态聚合成：

```text
Market Capital Regime
```

建议第一版定义八种：

```text
1. LIQUIDITY_EXPANSION
2. STRUCTURAL_BULL
3. SPECULATIVE_EXPANSION
4. DISTRIBUTION
5. DELEVERAGING
6. FORCED_SELLING
7. STABILIZATION
8. CAPITAL_RECOVERY
```

允许复合状态。

例如：

```text
FORCED_SELLING × STABILIZATION
```

意味着：

> 卖方仍未完全出清，但出现了强力承接资金。

---

# 14. 买卖力量平衡

真正决定大盘拐点的不是指数位置，而是：

```text
新增买方流量
vs
潜在卖方流量
```

定义：

```text
Net Capital Pressure
=
Expected Buying Pressure
-
Expected Selling Pressure
```

同时计算：

```text
Pressure Velocity
```

即压力是在扩大还是减弱。

---

## 14.1 下跌末端判断

比传统技术支撑更重要的是：

```text
卖方流量下降
+
稳定资金继续进入
+
融资去杠杆速度下降
+
公募/固收+赎回压力下降
```

当：

```text
Expected Buying Pressure
>
Expected Selling Pressure
```

且连续维持：

```text
Market Recovery Probability ↑
```

---

# 15. “资金天气图”

系统每天输出统一结果。

示例：

```text
A股 Capital Weather

L1 政策稳定资本
STABILIZATION_ACTIVE
↑↑

L2-A 险资
DE-RISKING
↓

L2-B 固收+
FORCED_SELLING
↓↓

L2-C 主动公募
REDEMPTION_PRESSURE
↓

L2-D 私募
LOW_EXPOSURE
→

L2-E 外资
NEUTRAL
→

M 两融
DELEVERAGING
↓↓

L3 个股主动资本
SELECTIVE

L4 散户情绪
PANIC

Market Regime
FORCED_SELLING × STABILIZATION

Net Capital Pressure
NEGATIVE BUT IMPROVING
```

---

# 16. 决策输出

最终市场层只输出有限决策集。

```text
RISK_OFF
DEFENSIVE
WATCH
NEUTRAL
PROBE
RISK_ON
AGGRESSIVE
```

例如：

```text
Market Decision:
WATCH

Reason:
L1托底增强
但L2-B和M仍在释放卖压

Action:
禁止重仓
允许小仓位观察
仅参与资金强势板块
```

---

# 17. 接入板块系统

只有 Market Regime 达到：

```text
NEUTRAL / PROBE / RISK_ON / AGGRESSIVE
```

才进入正常板块筛选。

板块层重点判断：

```text
哪个板块正在得到L2资金增配？
哪个板块正在被L2减仓？
哪些板块只是L4题材炒作？
哪些板块存在L3主动资本集中？
```

---

# 18. 板块资金状态

建议状态：

```text
OUTFLOW
BASE_BUILDING
ACCUMULATION
INFLOW
ACCELERATION
CROWDED
DISTRIBUTION
```

---

# 19. 接入个股系统

个股模型只在：

```text
Market Allowed
AND
Sector Allowed
```

时执行。

最终结构：

```text
L1/L2/M
↓
Market Regime
↓
Sector Flow
↓
L3 Stock Capital
↓
Price / Volume / Chip Structure
↓
Entry Timing
```

这样价格技术指标的地位就发生变化：

以前：

```text
技术指标 → 交易判断
```

以后：

```text
资金逻辑
→ 资金状态
→ 市场许可
→ 板块许可
→ 个股资本状态
→ 技术结构用于确认入场
```

---

# 20. 研究原则

## P1 禁止“绝对身份确认”

允许：

```text
高概率行为识别
```

禁止：

```text
无证据宣布某资金身份
```

---

## P2 禁止把所有机构混成“主力”

必须按：

```text
目标函数
+
约束
+
期限
```

分类。

---

## P3 禁止把价格当原因

价格是：

```text
资金行为结果
```

不是原因。

---

## P4 接受不确定性

系统允许：

```text
70% confidence
```

而不是：

```text
不知道100%真相 → 不做判断
```

---

## P5 重点研究被迫行为

优先级：

```text
必须卖
>
可能卖

必须买
>
可能买
```

因为约束型行为最容易产生稳定模式。

---

## P6 状态优先于点预测

输出：

```text
FORCED_SELLING
```

比：

```text
明天跌1.3%
```

更有实际意义。

---

# 21. 工程模块

建议代码结构：

```text
capital_flow/
│
├── data/
│   ├── policy/
│   ├── insurance/
│   ├── mutual_fund/
│   ├── fixed_income_plus/
│   ├── foreign/
│   ├── margin/
│   ├── sentiment/
│   └── stock_active/
│
├── features/
│   ├── l1_policy.py
│   ├── l2a_insurance.py
│   ├── l2b_fixed_income_plus.py
│   ├── l2c_mutual_fund.py
│   ├── l2d_private.py
│   ├── l2e_foreign.py
│   ├── margin.py
│   ├── sentiment.py
│   └── active_capital.py
│
├── states/
│   ├── state_machine.py
│   ├── pressure.py
│   ├── velocity.py
│   └── confidence.py
│
├── market/
│   ├── capital_balance.py
│   ├── regime.py
│   └── decision.py
│
├── sector/
│   └── sector_flow.py
│
├── stock/
│   └── stock_capital_state.py
│
└── reports/
    ├── capital_weather.py
    └── daily_report.py
```

---

# 22. 第一阶段实施建议

不要一次把所有资金做完。

## Phase CF-0：合同冻结

冻结：

- 资金分类；
- 状态定义；
- 数据结构；
- 输出接口；
- 决策集合。

不做预测。

---

## Phase CF-1：先做三类最可观测资金

优先：

```text
L1 政策稳定资金
M 两融
L4 情绪
```

原因：

数据频率高、公开性高、历史长度较好。

目标：

每天生成：

```text
Capital Weather v0.1
```

---

## Phase CF-2：L2-B 固收+压力模型

核心任务：

识别：

```text
NORMAL
NAV_PRESSURE
RISK_BUDGET_PRESSURE
FORCED_SELLING
DELEVERAGED
```

这是最重要的机构卖压模块之一。

---

## Phase CF-3：L2-A 险资 + L2-C 公募

建立：

```text
长期配置状态
+
申赎压力
+
行业暴露变化
```

---

## Phase CF-4：Market Capital Regime

将：

```text
L1
L2
M
L4
```

汇总为：

```text
Market Regime
+
Net Capital Pressure
+
Pressure Velocity
```

---

## Phase CF-5：Sector Flow Engine

将机构资金变化投影到行业。

输出：

```text
Sector Accumulation
Sector Outflow
Sector Crowding
Sector Rotation
```

---

## Phase CF-6：L3 Stock Capital Engine

研究：

```text
吸筹
控筹
推进
加速
派发
```

并接入现有个股系统。

---

# 23. 第一版验收目标

v1不要求预测指数涨跌。

只要求回答：

### Q1

当前最大卖方是谁？

### Q2

卖压正在扩大还是减弱？

### Q3

当前最大买方是谁？

### Q4

买盘是在主动进攻还是被动托底？

### Q5

两融是在加杠杆还是去杠杆？

### Q6

当前市场属于：

```text
FORCED_SELLING
STABILIZATION
RECOVERY
RISK_ON
```

中的哪一种？

### Q7

当前是否允许：

```text
建仓
试仓
加仓
仅观察
清仓
```

如果这七个问题能够稳定回答，则CF系统具备接入现有选股系统的价值。

---

# 24. 长期目标

最终每天系统只需要生成三层核心结论。

## 第一层：市场

```text
现在是否值得下注？
```

## 第二层：板块

```text
钱正在往哪里走？
```

## 第三层：个股

```text
哪个标的正在被主动资本推动？
```

最终完整决策链：

```text
资金来源
↓
目标函数
↓
约束
↓
当前状态
↓
未来压力
↓
市场状态
↓
板块方向
↓
个股资本结构
↓
价格确认
↓
交易执行
```

---

# 25. 最终原则

本系统不试图证明：

> 某一个庄家控制了A股。

真正的研究目标是：

> **把A股拆解为若干具有不同目标函数、约束条件和时间尺度的资本群体，然后利用公开和可获取数据识别它们当前的状态以及下一步高概率行为。**

因此整个体系的核心可以浓缩为一句话：

> **不预测价格，先预测资金压力；不猜市场图形，先判断谁必须买、谁必须卖。**

这应当作为后续大盘判断、行业轮动、个股筛选和仓位决策的共同上游。
