# CF-1 GO 裁决存档（用户 2026-10-15 正式裁决）

*Authority:* 用户飞书裁决原文 · *Effect:* OPEN-1 CLOSED / OPEN-3 CLOSED / CF-1 GO（三小阶段）/ 合同 bump `cf0-contract-freeze-v2`
*Priority contract:* **OOS-B = P0 唯一活跃机制验证主线（今晨裁决不修改）；CF-1 = P1 观测基础设施/日报原型线，preemptible**

## 一、OPEN 状态表（裁决后）

| OPEN | 裁决 |
|---|---|
| OPEN-1 | **CLOSED** — OOS-B=P0 唯一机制主线；CF-1=P1 观测基础设施线，并行不冲突 |
| OPEN-2 | 保持 OPEN，CF-6 前解决 |
| OPEN-3 | **CLOSED** — ETF/两融等 PIT Census 并入 CF-1A 作为前置硬门；R6 机制部分不并入 |
| OPEN-4 | 保持 OPEN，CF-5 前解决 |

## 二、优先级与资源（冻结）

- OOS-B = P0：拥有共享算力、数据工程、人工注意力的**抢占权**，不得因 CF-1 延迟其 60 日闭包。
- CF-1 = P1 / preemptible：优先独立 agent、独立机器、空闲资源；资源冲突立即让位。
- 共享预算量化（如需）：OOS-B ≥ 75%，CF-1 ≤ 25%。
- **CF-1 任何结果不得反向修改 OOS-B 已冻结合同。**
- 分工语义：OOS-B 回答"机制是否成立"；CF-1 回答"市场今天有哪些可观测资金状态"——并行无逻辑冲突。

## 三、CF-1 三小阶段（冻结）

```text
CF-1A  Source/PIT Closure（L1/M/L4 全部核心输入：官方源身份/历史覆盖/字段语义/单位/
       available_at/缺失语义/修订语义/PIT 重放证明；不研究市场，只证明传感器可用）
        ↓
CF-1B  Atom State Engines（三个独立原子引擎，Atom-Only）
        ↓
CF-1C  Capital Weather v0.1（并排展示 L1/M/L4，禁止聚合）
```

### CF-1B 状态集（v1 冻结，含对 CF-0 合同 2 的两处修订）

- **L1**（输出=stabilization behavior，非"汇金正在买"）：`NORMAL / WATCH / STABILIZATION_READY / STABILIZATION_ACTIVE / NORMALIZING`
  （修订注：CF-0 原冻结六态 STANDBY/WATCH/STABILIZATION_READY/STABILIZATION_ACTIVE/HOLD/NORMALIZE → 用户裁决精简重命名为上述五态）
- **M**：`LEVERAGE_BUILDING / NEUTRAL / DELEVERAGING / DELEVERAGING_ACCELERATING / DELEVERAGED`，单独输出 `financing_balance_pressure / financing_flow / deleveraging_velocity`；**v1 不构造复杂"爆仓概率"**（Forced-Selling Risk 暂缓）
- **L4**：`APATHY / RECOVERY / FOMO / EUPHORIA / PANIC / CAPITULATION`（基于市场宽度、涨跌停、成交、题材扩散等事实）

### CF-1C 输出形式（冻结）

允许：每层 state/pressure/velocity/confidence 并排展示 + 自然语言描述（如"L1 承接增强，两融仍在去杠杆，情绪仍处于恐慌阶段"）。
**禁止**：`Market Regime = STABILIZATION`、`Net Capital Pressure = -37`、`明日反弹概率 73%`——均属 CF-4，CF-0 的 NON-OPERATIVE 保持干净。

## 四、八道 Gate（冻结）

| # | Gate | 内容 |
|---|---|---|
| G1 | Source Authority | 核心数据源身份、字段和单位冻结 |
| G2 | PIT | available_at ≤ decision_time |
| G3 | Replay | 相同 as-of 时间重放结果完全一致 |
| G4 | Atom-Only | L1/M/L4 独立运行，不跨层构造特征 |
| G5 | No Future Outcome | 禁用未来收益/未来最大回撤等标签决定状态 |
| G6 | Fail-Closed | 核心字段缺失不得猜状态 |
| G7 | No Aggregation | 禁 Market Regime / Net Capital Score / 跨层权重 |
| G8 | OOS-B Non-Interference | CF-1 不修改、不占用、不依赖 OOS-B 冻结实验结果和机制合同 |

## 五、CF-1A 前置硬门（ETF/两融 PIT 细则）

**核心问题：交易日 T 的数据，在 T 日几点以前真实可知？** 若只能 T+1 获得，CF 日报绝不能伪装成 T 日盘中信息。硬门：available_at ≤ decision_time，不满足即 `NOT_YET_OBSERVABLE`，禁止回填后当作当时已知。

**ETF 必做九项**：effective_date / query_date / available_at / release_time_distribution / same-day usable? / T+1 usable? / revision behavior / holiday behavior / new-listed-delisted fund behavior。

**两融确认四项**：融资余额对应交易日 / 官方实际发布时间 / 盘中-收盘后-T+1 哪个时点可用 / 历史数据是否修订。R6 已有实测凭证的部分直接继承，不重复劳动。

**不并入 CF-1 的 R6 内容（保持原冻结）**：FundingContext(E1)→EquityFlow→MarketAbsorption→Historical Panel→G1-G3 链条。**MarketAbsorption / Historical Panel / G1-G3 不得借 CF 名义提前启动。** R6 Census 证据可复用；R6 机制验证授权不可复用。

## 六、CF-1 历史数据用途（白名单/黑名单，冻结）

**允许**（backfill 用途）：数据覆盖检查 / 状态计算重放 / 异常值发现 / 阈值量纲检查 / 状态持续性检查 / PIT 验证。
**禁止**：状态→未来收益 / 状态→次日涨跌 / 状态→最大收益 / 跨层组合→最优市场结果（一旦做了，CF-1 就事实上变成第二条机制验证主线）。

## 七、GO 指令原文要点

```text
Authorized:   CF-1A Source/PIT Closure; CF-1B L1+M+L4 atom engines; CF-1C Capital Weather v0.1
Not Authorized: Market Regime; Net Capital Pressure composite; cross-layer weighting;
              historical outcome panel; future-return validation; CF-4 aggregation; R6 G1-G3 activation
Priority:     OOS-B remains P0 and sole active mechanism-validation mainline.
              CF-1 is P1, preemptible, and must not delay OOS-B closure.
```

OOS-B 闭包后再决定是否授权 CF-4；在此之前不让 CF 掉进"先把各种变量拼成一个漂亮综合指标"的老路。
