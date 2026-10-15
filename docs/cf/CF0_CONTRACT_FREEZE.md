# Capital Flow Regime Engine — CF-0 Contract Freeze

*Contract:* `cf0_contract_freeze.json` · **v2 sha256 `d3322754ab1b797508ae5521962613ef0e9103305bf6bfb3125e37412f3c7207`**（v1 `b143302e…e89aa`）· 源方案 `source/Capital_Flow_Regime_Engine_v1.0.md`（用户 2026-10-15 飞书下发）
*Status:* **CAPITAL FLOW REGIME ENGINE ACTIVE · CF-0 FROZEN · CF-1 GO（2026-10-15 裁决：P1 preemptible，OOS-B 保持 P0 唯一机制主线）**

> **v2 修订（2026-10-15 用户 CF-1 GO 裁决）**：OPEN-1/OPEN-3 CLOSED；CF-1 拆为 CF-1A（Source/PIT Closure，前置硬门）→ CF-1B（L1/M+L4 原子引擎）→ CF-1C（Capital Weather v0.1，禁聚合）；八道 Gate G1-G8 冻结；L1 v1 状态集修订为五态（NORMAL/WATCH/STABILIZATION_READY/STABILIZATION_ACTIVE/NORMALIZING）、M v1 五态+三派生量（暂缓爆仓概率）；backfill 用途白名单/黑名单冻结。全文见 `CF1_GO_RULING_20261015.md`。

**立项裁决**：用户 2026-10-15 ——「这是上游架构。立项。」CF Engine 位于现有选股系统上游：

```text
CF Engine（资金状态）→ 市场风险状态 → Sector Flow → Stock Capital Structure
                      → 现有选股系统 → Entry / Position / Exit
```

**CF-0 范围铁律**：本阶段只做合同冻结（分类/状态语义/schema/接口/决策集）与数据普查继承，**不证明任何市场结论、不给任何状态赋观测值、不构造历史 panel**。看过 CF-1+ 结果后回来修 CF-0 冻结项禁止。

**核心目标冻结**：不预测价格，预测资金约束——未来 1-5 日谁可能必须卖、1-20 日谁可能持续买、哪些资金正接近风险约束、卖压在扩大还是衰减。**禁止把系统目标定义为预测指数涨跌。**

**v1 验收 = 七问稳定回答**（源方案 §23，冻结）：Q1 当前最大卖方是谁 / Q2 卖压扩大还是减弱 / Q3 当前最大买方是谁 / Q4 买盘主动进攻还是被动托底 / Q5 两融加杠杆还是去杠杆 / Q6 Regime 归类（FORCED_SELLING / STABILIZATION / RECOVERY / RISK_ON）/ Q7 当前允许建仓/试仓/加仓/仅观察/清仓中的哪种。

---

## 合同 1 · Capital Classification Contract（资金分类）

九类资金冻结如下。**P2 原则合同化：禁止把所有机构混成"主力"，每类必须按目标函数+约束+期限区分**（源方案 §3-7）：

| 层 | 名称 | 目标函数/机制 | 关键约束 | 时间尺度 | 传感器 |
|---|---|---|---|---|---|
| L1 | 政策稳定资本 | 防系统性风险→稳指数→恢复流动性→改善预期 | 非短期收益最大化 | 日→月 | D1 |
| L2-A | 险资/养老金/超长期配置 | 长期收益+资产负债匹配+低波动 | 偿付能力/权益上限/负债久期/风险预算 | 月→年 | D2 |
| L2-B | 银行理财/固收+/低回撤 | 低波动+稳定净值+绝对收益 | 产品回撤/赎回压力/VaR/权益风险预算 | 周→季 | D2 代理 |
| L2-C | 主动公募 | 相对收益+排名+基准+规模 | 申赎/集中度/基准偏离/年度排名 | 季→年 | D2 |
| L2-D | 私募/绝对收益 | **禁单一状态机**：长周期主观/趋势CTA/市场中性/高频/事件驱动分别建模 | 按策略类型 | 各异 | D2/D4 |
| L2-E | 外资 | **必须区分**长期配置型 vs 交易型 | 风险溢价/汇率/全球利率/指数权重 | 各异 | D3 |
| L3 | 个股主动资本 | 工程定义：能在有限股票上形成集中买卖力量并显著改变边际定价的主动资金（游资/活跃私募/产业资本/大股东/大户/部分量化/事件驱动）——**不用"庄家"作工程标签** | — | 日→月 | D4 |
| L4 | 情绪与跟随资本 | 注意力正反馈（上涨→关注→扩散→资金→成交→再上涨；下跌反向）；单体无定价力，群体同步有短期合力 | — | 日→周 | D5 |
| M | 杠杆场（两融） | **不属于任何固定投资者类别**：贯穿 L2-L4 的风险放大器+强制交易机制，单独建模 | 保证金/强制平仓线 | 日→周 | D6 |

**L3 状态机限制**：CF-0 只冻结 L3 的定义，**不另立生命周期状态机**——源方案 §5.1 的八态（ACCUMULATION→…→EXIT）与 CD-0 合同 6 已冻结的 lifecycle 八态（BASE_FORMING→…→STRUCTURE_BROKEN）不同名不同义，一个概念只能有一个合同。映射关系在 CF-6 前裁决（OPEN-2），此前 L3 无状态集。

## 合同 2 · State Semantics Contract（状态语义）

各层状态集**语义冻结**（完整定义见 JSON `state_sets`）：

- **L1**：STANDBY / WATCH / STABILIZATION_READY / STABILIZATION_ACTIVE / HOLD / NORMALIZE。实时输出为 `L1-like stabilization activity = LOW/MEDIUM/HIGH`——**身份确认与行为识别分离**（P1 合同化）：宽基 ETF 异常放量只能输出"稳定行为=HIGH + 可能行为方=政策稳定资本(置信度 Medium)"，禁止输出"中央汇金买入"；季度/半年持有人数据仅用于事后身份验证。
- **L2-A**：UNDERWEIGHT / NEUTRAL / ACCUMULATING / OVERWEIGHT / RISK_PRESSURE / DE-RISKING
- **L2-B**：RISK_ON → OVERWEIGHT → NAV_PRESSURE → RISK_BUDGET_PRESSURE → FORCED_SELLING → DELEVERAGED。**前瞻核心问题冻结：它是否已进入"还没有大量卖、但已经必须准备卖"的状态**——这是 v1 最重要机构卖压模块（CF-2）。
- **L2-C**：INFLOW / ACCUMULATING / CROWDED / NEUTRAL / REDEMPTION_PRESSURE / DE-RISKING
- **L4**：APATHY / RECOVERY / FOMO / EUPHORIA / PANIC / CAPITULATION
- **M**：基础状态=价格方向×融资余额方向四象限（↑↑杠杆追涨/↑↓去杠杆上涨/↓↑融资抄底/↓↓去杠杆/急跌急降=强制去化风险）；派生量四件套=Financing Cost Band / Financing Loss Pressure / Deleveraging Velocity / Forced-Selling Risk
- **Market Regime（8 态）**：LIQUIDITY_EXPANSION / STRUCTURAL_BULL / SPECULATIVE_EXPANSION / DISTRIBUTION / DELEVERAGING / FORCED_SELLING / STABILIZATION / CAPITAL_RECOVERY，**允许复合态**（如 FORCED_SELLING × STABILIZATION = 卖方未出清但出现强力承接）。**Regime 在 CF-4 GO 前为 NON-OPERATIVE**：只冻结语义，禁构造历史 panel、禁观察 regime-outcome 关系、禁调聚合权重（继承 2026-10-15 晨间 R6 裁决精神；外部文献只支持组成机制、不支持市场级聚合状态模型，Market Regime 证据上限默认 E1）。
- **Sector（7 态）**：OUTFLOW / BASE_BUILDING / ACCUMULATION / INFLOW / ACCELERATION / CROWDED / DISTRIBUTION

**阈值规则**：CF-0 只冻结语义，数值阈值在各 Phase spec 中**预注册后冻结**；看过结果后修语义禁止；状态=资本行为模式解释，**不断言 actor intention**（继承 CD-0 lifecycle 纪律）。

## 合同 3 · Unified Schema Contract（统一数据结构）

每层资金统一使用源方案 §10 的 20 字段 schema（冻结，逐字段见 JSON `unified_schema_fields`）：identity（id/name）→ 目标与约束（objective_function/constraints/time_horizon）→ 观测（observables/proxies）→ 状态（current_state/confidence）→ 压力（buying_pressure/selling_pressure/forced_buy_probability/forced_sell_probability）→ 动力学（state_duration/state_velocity）→ 传导（upstream_drivers/downstream_impact）→ 证据（evidence/counter_evidence）→ last_updated。**evidence/counter_evidence 为必填**：任何状态输出必须携带证据向量与反证向量。

## 合同 4 · Output Interface Contract（输出接口）

- **每层四元组**：`Current State / Pressure / Velocity / Confidence`——不输出单一买卖结论。
- **市场层**：`Net Capital Pressure = Expected Buying Pressure − Expected Selling Pressure`，同时输出 `Pressure Velocity`（扩大还是减弱）。
- **日报**：Capital Weather（每层状态+方向+Market Regime+Net Capital Pressure，格式见源方案 §15）。
- **下跌末端判据冻结**（源方案 §14.1）：卖方流量下降 + 稳定资金继续进入 + 融资去杠杆速度下降 + 公募/固收+赎回压力下降，且 Expected Buying > Expected Selling 连续维持 → Market Recovery Probability ↑。禁止用指数位置/均线作为主判据（P3：价格是结果不是原因）。

## 合同 5 · Decision Set Contract（决策集合）

**七档市场决策封闭集**：RISK_OFF / DEFENSIVE / WATCH / NEUTRAL / PROBE / RISK_ON / AGGRESSIVE。每档输出必须附 Reason（哪些层的状态驱动）与 Action 边界（如 WATCH=禁止重仓/允许小仓位观察/仅参与资金强势板块）。

**门控规则**：仅 NEUTRAL/PROBE/RISK_ON/AGGRESSIVE 允许进入正常板块筛选；板块层回答四问（哪个板块得到 L2 增配/被 L2 减仓/只是 L4 炒作/存在 L3 集中）；个股模型只在 Market Allowed AND Sector Allowed 时执行。**技术指标地位变更冻结**：技术结构仅用于入场确认，不再独立产生交易判断（源方案 §19）。

## 合同 6 · Data & PIT Contract（数据与 PIT）

六级传感器 D1-D6（政策/机构/外资/个股主动/情绪/杠杆）完整清单冻结于 JSON `data_contracts`。三条强制规则：

1. **PIT 继承**（CD-0 合同 2）：一切传感器 `available_at ≤ decision_time`；宏观资金背景值若为最新修订版必须显式标 `REVISION_CONTAMINATED`（继承 R6 FundingContext 三边界：不参与强机制结论、不因回归显著升级、证据上限 E1）；解禁类只能用 decision_time 前已公告事件——历史"当时已知未来供给"重建已判 UNSUPPORTED-for-PIT **不重试**。
2. **Support-First 继承**（CD-0 合同 3，总合同级）：每层状态进入决策/验证前必须先做传感器 support census（频率/覆盖/历史深度/空窗/时代集中/发布时滞）；支持不足 → 该层输出 `INSUFFICIENT_SUPPORT`，**禁调阈值/合并状态/换代理抢救**。
3. **Fail-closed**：缺数据输出 INSUFFICIENT_SUPPORT，禁止伪造状态。

**R6-0.5 Census 结论直接继承（2026-10-15）**：ETF 份额 **SUPPORTED**（SSE `fund_etf_scale_sse` 2012+ / SZSE `fund_scale_daily_szse` 2018+，官方双所，按日查询自然 PIT；遗留：发布时点 T晚vs次晨待一次实测、SSE 类型标签为当前口径）；两融 **SUPPORTED**（SSE 官方日线 2018-01-02+，SZSE 单日制可自动化；断点表待合同化）；宏观资金 REVISION_CONTAMINATED/可逐期重建（~108 期费工）；解禁供给判死。**CF-1 的三大目标层（L1/M/L4）中，L1 与 M 的核心数据源已过 G0 生死门**——这是 CF-1 可行性的直接依据。

## 合同 7 · Research Principles Contract（研究原则）

P1 禁止绝对身份确认 / P2 禁止混为"主力" / P3 禁止把价格当原因 / P4 接受不确定性（允许 70% 置信判断，而非"不知 100% 真相就不判断"——继承 R2 章程第一原则）/ P5 优先研究被迫行为（必须卖>可能卖；约束型行为最稳定）/ P6 状态优先于点预测。全部冻结（JSON `research_principles`）。

## 与现有程序的关系（+ OPEN 决策点）

| 程序 | 关系 |
|---|---|
| R2 Capital&Chip | CF 为市场级上游；R2 的个股 Latent Capital State 与 CF-L3 衔接（受 OPEN-2 约束） |
| CD Program | CF 七档市场决策/板块七态将作为 CD 合同 1"市场风险预算/板块优先级"的上游输入（OPEN-4 冻结映射表） |
| R6 Pre-Research | Census 结论与 PIT 合同已继承进合同 6；Evidence Atlas 的证据上限结论同样约束 CF-4 |
| OOS-B | 主线地位待裁决（OPEN-1） |
| Shadow | 不受影响，独立运行 |

- **OPEN-1**（CF-1 GO 前）：OOS-B 与 CF-1 的资源分配——今晨"OOS-B=唯一活跃机制验证主线"裁决如何修订。
- **OPEN-2**（CF-6 前，不阻塞 CF-1~5）：L3 生命周期 ↔ CD lifecycle 八态映射。
- **OPEN-3**（CF-1 GO 前）：R6 剩余动作（ETF 发布时点实测定案等）是否并入 CF-1 census。
- **OPEN-4**（CF-5 交付前）：CF↔CD 接口映射表冻结。

## 路线（冻结）

**CF-0** 合同冻结（本文档，DONE）→ **CF-1** L1+M+L4 三类最可观测资金，产出 Capital Weather v0.1（gate：census 通过+GO）→ **CF-2** L2-B 固收+压力模型 → **CF-3** L2-A 险资+L2-C 公募 → **CF-4** Market Regime 聚合（gate：单层可用+聚合规则预注册）→ **CF-5** Sector Flow Engine → **CF-6** L3 Stock Capital Engine（gate：OPEN-2 裁决）。工程约束继承项目硬约束（内存≤2.5G/单进程/单文件≤2G/每阶段全量最多跑一次）。

## 变更控制

本合同任何字段修改须用户裁决，bump 版本并记录；看过 CF-1+ 结果后回改冻结项禁止。
