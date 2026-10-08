# Round 2 — Capital & Chip Intelligence System
## 国家队 / 机构主力筹码、吸筹拉升规律与当前选股体系技术方案

**版本**：v1.0  
**日期**：2026-10-05  
**状态**：Round 2 技术方案冻结稿  
**目标**：从“严格证明型研究”切换到“不完全信息下的资金与筹码概率推断”，最终服务于当前大盘、板块和重点个股判断。

---

# 0. 项目重新定义

Round 2 不再把“无法绝对证明”当作停止条件。

本轮系统的目标不是：

> 精确知道所有国家队、机构和主力账户的真实持仓与真实成本。

而是：

> 利用全部可获得的公开数据、历史成交行为和筹码痕迹，构建对国家队、机构主力、板块与个股资金状态的概率性判断；再通过历史大样本验证这些判断是否具有现实价值，并最终用于当前选股与风险判断。

本轮必须交付三个最终结果：

1. **当前资本与筹码地图**：对大盘、板块、重点个股给出国家队/机构/主力的持仓方向、估计成本区、筹码集中程度、行情阶段和置信度。
2. **历史吸筹—拉升规律库**：从 2021–2026 历史数据中系统研究大行情启动前 20/60/120/250 日的资金、成交、筹码、机构持仓、板块背景和发展路径。
3. **当前选股系统**：将当前资金地图 + 历史规律结合，输出当前市场判断、重点板块、重点股票、主力阶段判断、成本区、风险和建议。

---

# 1. Round 2 方法论

## 1.1 第一原则：禁止绝对严谨主义

严格性只保留在事实基础层：

```text
数据不能伪造
时间不能穿越
股票身份不能错
复权不能错
程序不能静默丢数据
来源必须可追溯
```

市场判断层允许：

```text
估计
概率
置信度
矛盾证据
缺失数据
近似成本
隐藏状态推断
```

禁止：

```text
无法百分百证明
→ 不分析
→ 不判断
→ UNKNOWN
```

改为：

```text
证据不足 → confidence 下降
证据冲突 → contradiction 上升
无法精确 → 输出区间
无法直接观察 → 输出 latent-state inference
```

## 1.2 四层语义

系统所有字段和结论分为四层：

```text
FACT       原始事实或直接可观测数据
DERIVED    由确定公式计算的数据
INFERENCE  对资金/筹码/主力行为的概率推断
DECISION   当前筛选、观察、参与和风险建议
```

示例：

```text
FACT:
2026Q2 某基金持股增加 500 万股

DERIVED:
该季度新增持股占流通盘约 1.8%

INFERENCE:
机构资金可能在 11.2–12.6 元区间建立主要新增仓位

DECISION:
当前股价 12.9 元，距推定机构成本区不远，进入重点观察池
```

---

# 2. 系统总体架构

```text
                        ┌─────────────────────┐
                        │      数据采集层      │
                        │ OHLCV / amount      │
                        │ turnover / float    │
                        │ holder / fund       │
                        │ ETF / LHB / margin  │
                        │ block trade / etc.  │
                        └──────────┬──────────┘
                                   │
                                   ▼
                        ┌─────────────────────┐
                        │   数据标准化与历史库   │
                        │ PIT / provenance    │
                        │ identity / calendar │
                        └──────────┬──────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             │                     │                     │
             ▼                     ▼                     ▼
     Market Capital Map     Sector Capital Map    Stock Chip Engine
             │                     │                     │
             └──────────────┬──────┴──────────────┬──────┘
                            │                     │
                            ▼                     ▼
                    Latent Capital State     Cost/Chip State
                            │                     │
                            └──────────┬──────────┘
                                       ▼
                          Historical Pattern Engine
                          markup / accumulation library
                                       │
                                       ▼
                           Probability / Evidence Engine
                                       │
                                       ▼
                              Current Market Scan
                                       │
                     ┌─────────────────┼──────────────────┐
                     ▼                 ▼                  ▼
                  Market            Sector              Stock
                  view              ranking             shortlist
```

---

# 3. 数据策略

Round 2 采用“能拿多少先用多少”的数据策略，不等待所有字段完整。

每个数据源记录：

```text
source
retrieved_at
effective_date
asof_date
coverage
confidence
raw_sha256
parser_version
```

缺失值只影响推断置信度，不阻塞整个系统。

---

# 4. 数据源优先级

## 4.1 P0：行情与成交

```text
OHLC
volume
amount
turnover_rate
free_float_market_cap
total_market_cap
adjust_factor
suspension
limit_up/down
ST
```

现有 OHLCV 继续使用。

新增优先级最高：

```text
amount
turnover_rate
free_float_market_cap
```

因为同样的成交量，对不同流通盘的意义完全不同。

## 4.2 P0：Ownership / Holder

目标字段：

```text
holder_count
avg_holding_per_holder
top10_shareholders
top10_float_shareholders
shareholder_type
holding_amount
holding_ratio
change_amount
change_ratio
report_period
announcement_date
```

重点识别：

```text
中央汇金
证金
社保
保险
基金
券商
QFII
香港中央结算
企业法人
自然人大户
其他机构
```

## 4.3 P0：基金与机构

```text
fund_stock_holdings
fund_industry_allocation
ETF_components
ETF_shares
ETF_creation_redemption
institutional_holding_summary
```

至少按：

```text
report_period
stock
institution_type
holding
change
```

保存历史。

## 4.4 P1：交易型公开资金证据

```text
龙虎榜
机构专用席位
大宗交易
融资融券
回购
增持
减持
定增
解禁
质押
机构调研
```

存在即作为 evidence boost，不要求全覆盖。

---

# 5. 数据源适配器架构

建议新增：

```text
src/capital_data/
├── base.py
├── market/
├── holders/
├── funds/
├── etf/
├── lhb/
├── margin/
├── block_trade/
├── corporate_actions/
└── registry/
```

统一接口：

```python
fetch(symbol, start, end)
normalize(raw)
validate(rows)
write_snapshot(...)
```

每个源必须输出：

```text
coverage
freshness
field_quality
source_reliability
```

---

# 6. 国家队实体注册表

新增：

```text
config/national_team_registry.json
```

区分：

```text
NATIONAL_TEAM_CONFIRMED
POLICY_CAPITAL_PROXY
```

其中：

```text
NATIONAL_TEAM_CONFIRMED
= 可明确识别为国家队账户/机构

POLICY_CAPITAL_PROXY
= 无法确认最终账户主体，但资金工具/交易行为高度政策相关
```

不得混用，但都允许进入资金判断。

---

# 7. 主力与机构成本估计引擎

新增：

```text
src/capital_inference/cost_engine.py
```

目标输出：

```text
cost_center
cost_low
cost_high
cost_dispersion
confidence
evidence
```

## 7.1 市场成交成本分布

使用：

```text
typical_price
amount
turnover
volume
```

构造滚动 volume-price / amount-price distribution，输出：

```text
P10
P25
P50
P75
P90
major_volume_nodes
cost_center
band_width
```

## 7.2 机构增仓成本估计

若：

```text
T0 institutional holding = H0
T1 institutional holding = H1
ΔH = H1 - H0 > 0
```

则在 `(T0, T1]` 内结合：

```text
成交额分布
换手率
异常放量
价格区间
量价稳定性
```

估计新增持仓成本区间。

输出：

```text
estimated_institution_cost_low
estimated_institution_cost_center
estimated_institution_cost_high
confidence
```

## 7.3 国家队成本估计

组合：

```text
公开持仓变化
ETF资金变化
宽基指数持仓
成份股权重
区间成交成本
政策资金代理
```

输出：

```text
national_team_cost_band
national_team_position_state
confidence
```

---

# 8. 筹码结构引擎

新增：

```text
src/capital_inference/chip_engine.py
```

输出至少包括：

```text
chip_concentration
chip_locking
floating_supply_pressure
profit_chip_proxy
trapped_supply_proxy
cost_band_width
cost_center_slope
turnover_accumulation
```

## 8.1 CHIP_LOCKING

支持证据：

```text
股东户数下降
机构持仓增加或稳定
低位大量换手后成交缩小
回调缩量
成本带变窄
价格重心上移
突破后不回旧成本区
```

输出：

```text
LOW
MEDIUM
HIGH
```

## 8.2 FLOATING_SUPPLY_PRESSURE

证据：

```text
上方历史高成交密集区
股东户数增加
机构减仓
高位换手放大
反弹放量但推进弱
成本带快速发散
```

---

# 9. 隐藏资金状态模型

新增：

```text
src/capital_inference/state_engine.py
```

第一版状态：

```text
ACCUMULATION
ACCUMULATION_MATURE
MARKUP_READY
MARKUP_ACTIVE
DISTRIBUTION_RISK
DECLINE
CONFLICTED
```

统一输出：

```json
{
  "state": "MARKUP_READY",
  "confidence": 0.73,
  "support": [],
  "contradictions": [],
  "missing_evidence": [],
  "evidence_family_scores": {}
}
```

---

# 10. Evidence Family

每个状态由六大证据族共同判断。

## E1 Price Structure

```text
长期价格位置
距长期高低点
趋势斜率
长期 drawdown
回撤深度
波动收敛
价格压缩
突破结构
```

## E2 Participation / Turnover

```text
volume ratio
amount ratio
turnover ratio
up-day vs down-day participation
abnormal turnover
```

## E3 Chip / Cost

```text
cost center
cost band
band contraction
cost migration
distance to cost
volume nodes
```

## E4 Ownership

```text
holder count
holder concentration
top10 changes
institution changes
national team changes
```

## E5 Public Capital Signals

```text
LHB
block trade
margin
repurchase
increase/decrease holding
research activity
```

## E6 Market / Sector Context

复用 Round 1：

```text
L1 market regime
L2 sector state
sector breadth
sector concentration
SW2 explanation
```

---

# 11. Evidence Scoring

第一版不追求复杂数学最优。

每个 evidence family 输出：

```text
STRONG_SUPPORT
SUPPORT
NEUTRAL
CONTRADICT
STRONG_CONTRADICT
MISSING
```

可先采用粗粒度映射：

```text
STRONG_SUPPORT     +2
SUPPORT            +1
NEUTRAL             0
CONTRADICT         -1
STRONG_CONTRADICT  -2
MISSING             0，但降低 coverage/confidence
```

最终同时输出：

```text
support_score
contradiction_score
coverage_score
confidence
```

注意：`confidence` 不等于看多分数。

---

# 12. Historical Markup Episode Library

新增：

```text
data/r2/markup_episodes.parquet
```

扫描 2021–2026 全市场，至少构造：

```text
M60_50
M120_100
M250_200
M250_300
M250_500
```

示例定义：

```text
future_60d_max_return >= 50%
future_120d_max_return >= 100%
future_250d_max_return >= 200%
```

这些标签只用于历史研究结果定义，不得作为历史特征输入。

---

# 13. Episode 字段

```text
stock
start_date
peak_date
end_date
max_return
days_to_50
days_to_100
days_to_peak
max_drawdown_before_markup
market_regime_at_start
sector_state_at_start
```

另保存启动前：

```text
pre20
pre60
pre120
pre250
```

完整 feature snapshot。

---

# 14. Matched Control

每个成功 episode 匹配控制组：

```text
同一时期
同 L2
相似市值
相似流动性
相似长期 drawdown
相似 market regime
```

但未来没有进入对应 markup threshold。

目标不是做完美因果推断，而是找出：

> 成功大行情启动前，相比“看起来差不多但后来没涨”的股票，多了哪些资金/筹码特征。

---

# 15. Pattern Discovery

新增：

```text
src/r2/pattern_discovery/
```

重点研究：

```text
长期低位时间
价格止跌
低位累计换手
成本带收敛
股东集中
机构增仓
下跌缩量
上涨放量
回撤越来越浅
相对强度由负转平
试盘
突破
```

同时研究失败路径：

```text
假吸筹
突破失败
高位接盘
机构增仓但价格不响应
成本发散
```

---

# 16. 发展路径模型

不强迫统一四阶段。

允许多路径：

```text
Path A
长期低位吸筹
→ 成本收敛
→ 试盘
→ 拉升

Path B
快速大换手
→ 整理
→ 成本稳定
→ 突破

Path C
机构连续增仓
→ 缓慢趋势
→ 加速

Path D
板块政策资金进入
→ 龙头启动
→ 板块扩散

Path E
假突破
→ 失败
```

第一版使用：

```text
sequence census
transition probability
median duration
failure probability
```

不急着 HMM。

---

# 17. 历史验证框架

建议：

```text
Discovery:
2021–2023

Validation:
2024–2026
```

同时增加逐年滚动：

```text
train <= year-1
test = year
```

验证指标：

```text
probability lift
hit rate
false positive
MAE
time-to-markup
drawdown
cross-year stability
sector stability
```

---

# 18. Probability Model

第一版双轨。

## 18.1 Explainable Rule Engine

直接输出：

```text
为什么判断吸筹
为什么判断拉升准备
为什么认为成本区有效
为什么判断派发风险
```

## 18.2 Statistical Model

候选：

```text
Logistic Regression
CatBoost
LightGBM
Survival model
```

预测：

```text
P(markup >= 50% in 60d)
P(markup >= 100% in 120d)
P(markup >= 200% in 250d)
```

模型用于校准证据组合的概率提升，不替代解释引擎。

---

# 19. 当前 Market Capital Map

输出：

```text
market_date
national_team_state
institution_state
ETF_state
market_cost_center
market_cost_band
profit_chip_proxy
trapped_supply_proxy
market_regime
risk_state
confidence
```

---

# 20. Sector Capital Map

对 83 L2 + 可用 SW2 输出：

```text
sector
institution_holding_trend
ETF_flow_state
national_team_exposure
chip_concentration
cost_center
cost_band
price_distance_to_cost
accumulation_probability
markup_ready_probability
markup_active_probability
distribution_risk
confidence
```

---

# 21. Current Stock State

每只重点股输出：

```text
symbol
name
sector_L2
sector_SW2

capital_actor_guess
institution_state
national_team_state
holder_concentration

estimated_main_cost_low
estimated_main_cost_center
estimated_main_cost_high

chip_locking
floating_supply_pressure
price_distance_to_cost

latent_state
state_probability
confidence

supporting_evidence[]
contradictions[]
missing_data[]

future_markup_prob_60d
future_markup_prob_120d
future_markup_prob_250d
```

---

# 22. 当前选股系统

## A — PRIORITY

```text
ACCUMULATION_MATURE
或 MARKUP_READY
+
较强机构/筹码支持
+
板块背景至少不差
+
当前价格没有严重脱离成本区
```

## B — WATCH

```text
ACCUMULATION
但尚未成熟
```

## C — ACTIVE

```text
MARKUP_ACTIVE
```

需要继续判断：

```text
距成本
拉升阶段
筹码锁定
是否已经过度扩张
```

禁止简单追高。

## D — RISK

```text
DISTRIBUTION_RISK
DECLINE
CONFLICTED HIGH-RISK
```

---

# 23. 每日输出

```text
outputs/r2/YYYY-MM-DD/
├── market_capital_map.json
├── sector_capital_map.parquet
├── stock_state.parquet
├── priority_candidates.json
├── watch_candidates.json
├── active_candidates.json
├── risk_candidates.json
└── daily_report.md
```

---

# 24. Daily Report 必答问题

```text
1. 当前大盘资金状态是什么？
2. 国家队目前大概率在哪些方向？
3. 机构主要在增加还是减少哪些板块？
4. 哪些板块筹码结构最好？
5. 哪些股票最像吸筹成熟/拉升准备？
6. 哪些股票已经拉升但离主力成本太远？
7. 当前最值得观察、参与和回避的股票有哪些？
```

---

# 25. 工程目录建议

```text
project/
├── src/
│   ├── capital_data/
│   ├── capital_inference/
│   │   ├── cost_engine.py
│   │   ├── chip_engine.py
│   │   ├── ownership_engine.py
│   │   ├── actor_engine.py
│   │   └── state_engine.py
│   ├── r2/
│   │   ├── markup_library.py
│   │   ├── matched_controls.py
│   │   ├── pattern_discovery/
│   │   ├── validation.py
│   │   ├── probability_model.py
│   │   └── current_scan.py
│   └── reports/
│
├── config/
│   ├── national_team_registry.json
│   ├── institution_registry.json
│   └── r2_config.json
│
├── data/
│   └── r2/
│
├── docs/
│   └── r2/
│
└── outputs/
    └── r2/
```

---

# 26. 与 Round 1 的关系

Round 1 保留并复用：

```text
PIT 数据处理
Market regime
Sector infrastructure
Candidate infrastructure
Episode infrastructure
Cost proxy
Shadow runtime
```

但 Round 2 不再继承：

```text
“无法严格证明就不判断”
```

Round 1 定位：

```text
基础设施
风险控制
工程纪律
```

Round 2 定位：

```text
资金行为推断
主力筹码研究
历史规律发现
当前选股
```

Shadow 与 Round 2 并行，不阻塞 Round 2。

---

# 27. 实施阶段

## R2-0 — Capital Data Expansion

目标：

```text
补 amount / turnover / float
补 holder history
补 institutional holdings
补 ETF
补 LHB / block / margin
```

原则：

```text
不等待全部完成
```

## R2-1 — Current Capital / Chip Snapshot

第一阶段必须快速产生当前结果：

```text
当前国家队状态
当前机构状态
板块筹码地图
重点个股成本区
当前吸筹/拉升状态
```

这是第一批业务可见成果。

## R2-2 — Historical Markup Library

构造五年大行情 episode。

## R2-3 — Accumulation / Markup Discovery

研究：

```text
吸筹
吸筹成熟
拉升准备
拉升
派发
失败
```

历史特征和路径。

## R2-4 — Validation & Probability Calibration

验证：

```text
哪些特征真的提高未来大行情概率
```

输出 probability lift。

## R2-5 — Current Full-Market Scan

将历史规律应用于当前市场。

## R2-6 — Capital Decision Dashboard

最终产出：

```text
Market
Sector
Stock
Capital Actor
Cost
Chip Structure
Stage
Probability
Confidence
Risk
Recommendation
```

---

# 28. 每阶段验收标准

本轮禁止设置大量形式门禁，只看是否产生业务结果。

## R2-0

```text
新增数据覆盖是否显著提升
```

## R2-1

```text
是否能输出当前资金/筹码地图
```

## R2-2

```text
是否构建足够大的历史大行情库
```

## R2-3

```text
是否找到具有重复性的吸筹/拉升特征与路径
```

## R2-4

```text
是否相对 matched control 有明显 probability lift
```

## R2-5

```text
是否能筛出当前重点股票
```

## R2-6

```text
是否能形成每天可直接使用的判断报告
```

---

# 29. 停止条件

Round 2 不因“不够严谨”停止。

只因以下情况停止某一研究分支：

```text
历史上完全无 probability lift
跨年份完全反转
加入证据后反而恶化
数据质量低到无法区分方向
```

否则允许继续改进。

---

# 30. 当前立即执行顺序

不要再继续设计，直接执行：

```text
STEP 1
R2-0 数据源普查与补抓
+
R2-1 第一版当前资本/筹码地图
并行

STEP 2
建立 Historical Markup Library

STEP 3
成功案例 vs matched control
做吸筹/拉升结构 discovery

STEP 4
冻结第一版 latent-state evidence model

STEP 5
2024–2026 验证 probability lift

STEP 6
全市场 current scan

STEP 7
输出当前大盘 / 板块 / 个股建议
```

---

# 31. 第一轮代码任务拆解

## Task A — 数据源普查

输出：

```text
docs/r2/R2_DATA_SOURCE_CENSUS.md
config/r2_data_sources.json
```

要求记录：

```text
字段
来源
时间范围
更新频率
历史可得性
免费/限制
覆盖率
实现难度
可靠性
```

优先完成 `amount / turnover / free_float / holder / institutional holdings / ETF`。

## Task B — 当前筹码快照 V0

使用现有数据先实现：

```text
cost_engine.py
chip_engine.py
state_engine.py
```

即使 ownership 数据尚不齐，也必须输出第一版：

```text
market map
sector map
stock state
```

缺失字段降低 confidence。

## Task C — Markup Library

一次性扫描全市场历史，生成：

```text
markup_episodes.parquet
markup_episode_summary.json
```

## Task D — Historical Feature Matrix

为 markup 与 control 样本生成：

```text
pre20
pre60
pre120
pre250
```

特征矩阵。

## Task E — Discovery Report

输出：

```text
哪些筹码/资金特征最常出现在大行情之前
哪些 matched controls 中明显更少
哪些是假象
```

## Task F — Current Scan V1

扫描当前全市场并输出：

```text
PRIORITY
WATCH
ACTIVE
RISK
```

---

# 32. 最终输出示例

系统最终不再只说：

> 无法确认主力是否吸筹。

而要输出类似：

```text
股票：XXXX

估计主力主要成本区：
11.4–12.3

当前价格：
12.8

机构状态：
过去两个报告期净增仓

股东结构：
持续集中

筹码状态：
低位换手充分，成本带收敛

板块：
资金状态中强

状态判断：
ACCUMULATION_MATURE / MARKUP_READY

置信度：
HIGH

历史条件概率：
未来120日进入显著行情的概率明显高于 matched baseline

主要风险：
14.5–15.2 存在历史高成交套牢区
```

---

# 33. 核心原则

> **事实层严格，推断层大胆，验证层务实，决策层接受不确定性。**

> **不追求掌握全部真相，只追求比不知道更接近真相。**

> **Round 2 的产出必须最终落到“现在怎么看大盘、怎么看板块、看哪些股票、为什么”上。**
