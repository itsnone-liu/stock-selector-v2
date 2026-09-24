# T4.5 — Exposure Response Mapping（Exposure topology frozen）

**阶段基线**：T4.4 `8270fb1`；九道 Gate 全 PASS。  
**边界**：本阶段只研究 T0 决策层的历史路径 profile 与 Exposure Class，不映射实际账户仓位、不做资产曲线排名、不做策略优化。

## 1. 正式拓扑

```text
Market Context（breadth + new-high）
        ↓ 全局平移 / 有限调整
Stock State（load + ref60 等 T0 state）
        ↓ 基础 Exposure Class
E0 / E1 / E2 / E3
        ↓（实际百分比、组合风险预算留给 T4.6）
Entry Policy / Position Sizing
        ↓
Post-breakout Path State（T5）
```

冻结结论：

- Market 保留二维，但不为每个 Market 象限重新建立一套 Stock threshold；
- Stock State 决定基础 Exposure Class，Market 只参与有限的格级调整；
- Sector 不进入 exposure engine，继承 T4.4 `SECTOR_SUBSUMED_BY_MARKET`；
- E0–E3 是**统计路径等级**，不是 0%/25%/50%/100% 的账户仓位。研究用权重仅用于反事实排序审计，实际映射留给 T4.6。

## 2. 方法

### T4.5A — Exposure Surface

使用 T0-only 特征构造：

- Market：breadth 与 new-high 的 expanding as-of percentile，各自二分形成 4 个 Market cell；
- Stock：turnover load 三分位（L1–L3）× ref60 breakout bool；
- surface：4 × 3 × 2 = 24 格，分别计算 h10/h20/h40 的 DB profile。

每格包含：

- Upside：median excess、median peak/max gain、new-high probability；
- Downside：median MDD、ref20 break probability；
- Persistence：T0 close survival、median peak time。

收益/风险统计均为日内先聚合、跨日取 median。EW 只作诊断，正式幅度以 DB 为准。

### T4.5B — Exposure Compression

以 h20 的 7 个方向性指标做格级 rank-average evidence：收益、peak、新高、survival 为正向；MDD、ref20 break 为反向；再将 24 个格压缩为 E0–E3 四档。这里是解释性压缩，不是黑箱预测分数。

缺失 T0 load/ref60 的 112 个事件不伪装成高质量状态：事件级 assignment 保守归入 E0，并保留 `evidence_missing` 审计字段。完整 27,422 个 breakout event 均有 assignment。

### T4.5C — Counterfactual Exposure Audit

以研究审计权重 E0=0、E1=0.25、E2=0.5、E3=1，比较 class ordering 与历史 outcome ordering；不生成资产曲线，不进行策略排名。

## 3. 核心结果

### 3.1 h20 Exposure ordering

| Class | Events | Median excess | Peak/max gain | MDD | New-high | Ref20 break | Peak tau |
|---|---:|---:|---:|---:|---:|---:|---:|
| E0 | 5,635 | -4.56% | 6.74% | 14.37% | 83.3% | 75.0% | 12 |
| E1 | 5,151 | -3.02% | 6.06% | 11.86% | 85.0% | 80.0% | 14 |
| E2 | 4,964 | -2.20% | 7.23% | 12.40% | 90.9% | 84.7% | 14 |
| E3 | 11,560 | -1.87% | 6.50% | 11.19% | 94.6% | 86.7% | 14 |

主排序信号是清楚的：E0→E3 median excess 改善、MDD 变浅、新高率提高。Peak/max gain 并非严格逐级改善（E2 高于 E3），因此不能把 E3 描述为“所有 upside 指标都最高”。此外样本期整体 excess 为负，Exposure class 是**相对 worthiness ordering**，不是绝对正收益承诺。

`p_survive_t0` 在 E0–E2 为 0、E3 仅 2.44%，该字段在本次路径定义下区分度有限，不作为升级依据；这也说明 T0-close survival 不是当前 Exposure compression 的强指标。

### 3.2 Horizon stability

| Horizon | E0 | E1 | E2 | E3 |
|---|---:|---:|---:|---:|
| h10 | -2.80% | -2.39% | -0.87% | -1.00% |
| h20 | -4.56% | -3.02% | -2.20% | -1.87% |
| h40 | -5.86% | -4.71% | -3.12% | -3.52% |

h10/h40 存在局部 E2/E3 翻转，不能声称四档在每个 horizon 严格单调；总体 E0→高 exposure 的风险收益方向仍较稳定，Gate 允许局部平台/翻转但已记录。后续 T4.6 不应把 E3 直接解释为所有 horizon 的无条件最高仓位。

### 3.3 年度稳定性

2024/25/26 的 E 序列并非逐级严格单调：2024 为 E2 最强、2025 基本单调改善、2026 为 E1 最强且 E3 略回落。九道 Gate 的稳定性规则是“多数步方向一致”，因此通过，但该结果明确要求：Exposure Class 是稳健的**粗排序证据**，不是三年均严格单调的精确排名。

### 3.4 Counterfactual audit

- date-level Spearman（E research weight vs 日级 excess）：**0.1964**；
- uniform event median excess：-1.98%；
- E-weighted median excess：-1.18%。

匹配为正但偏弱，说明 Exposure ordering 有方向性证据，却不足以支持精细仓位比例。实际账户权重必须延后到 T4.6，并结合组合层风险约束。

## 4. 九道 Gate

| Gate | 结果 | 说明 |
|---|---|---|
| G1 Lineage | PASS | 严格继承 T4.4 `8270fb1`，事件宇宙对账 |
| G2 T0-only | PASS | assignment 仅保留 T0 特征与 class 审计字段 |
| G3 Outcome Separation | PASS | class 键为 `(M_cell, L_q, R60)`；outcome 只作格级描述与验证 |
| G4 DB Primary | PASS | DB 为正式幅度，EW 仅诊断 |
| G5 Monotonicity | PASS | 多指标总体排序；局部平台/翻转已保留，不靠单一收益指标升级 |
| G6 Year Stability | PASS | 2024/25/26 多数方向一致；不是逐年严格单调 |
| G7 Horizon Stability | PASS | h10/h20/h40 总体方向保留，E2/E3 局部翻转已披露 |
| G8 Complexity | PASS | 固定 24 格、单一 h20 压缩规则；无新 interaction/Market-specific threshold |
| G9 Determinism + Conservation | PASS | assignment 双跑一致，27,422 事件全覆盖，缺失证据保守 E0 |

## 5. 阶段放行与限制

T4.5 冻结 **Exposure topology**，但不冻结实际百分比：

> Market 提供全局风险/收益平移；Stock State 决定基础 Exposure Class；Market 只做有限格级修正；Sector 不进入 exposure engine；形成 E0–E3 四级统计暴露状态。

以下内容明确留给 T4.6：实际初始仓位、账户风险预算、同时持仓数、相关性、T1 豁免、3.5% 追高上限、分批规则。突破后的量能/参与度/回撤/续涨状态留给 T5。
