# T4.6 — Entry Policy & Position Sizing（initial exposure topology）

**基线**：T4.5 `1565e25`；十道 Gate 全 PASS。  
**边界**：只冻结 initial exposure policy；T0 后加仓、减仓、持有、退出留给 T5。

## 1. 冻结结构

```text
T0 Context / Stock State
        ↓
Exposure Class E0–E3
        ↓
Participation Policy P0–P3
        ↓
Base Risk Budget Class
        ↓
Execution Adjustment（T0/T1、chase distance、分批）
        ↓
Actual Initial Exposure
```

E-class 不是实际百分比。T4.5 的局部 E2/E3 翻转与 date-level Spearman 0.1964 不支持机械的 0%→100% 映射。

## 2. T4.6A Participation Mapping

| E-class | Policy | 语义 |
|---|---|---|
| E0 | P0_no_participation | 不消耗正常风险预算；仅允许账户层明确的例外/观察 |
| E1 | P1_probe | 仅 probe risk budget |
| E2 | P2_normal | normal risk budget eligibility |
| E3 | P3_aggressive_eligible | 可申请 normal/elevated budget，但受执行与组合上限约束 |

这是一份最简单、可解释的候选映射，不是收益最大化搜索。E0 缺失/证据不足事件保守归入 P0，并在 assignment 中保留审计语义。

直接回放中，DB h20 net return（保留成交/未成交语义）为：E0 -2.56%、E1 -2.08%、E2 -1.97%、E3 -1.68%；MAE 也从 -6.76% 改善至 -5.21%。这支持参与资格的粗排序，但不是精确仓位证据。

## 3. T4.6B Chase & Timing

### Chase response curve

固定分箱：`0–1% / 1–2% / 2–3.5% / 3.5–5% / 5–7% / >7%`。使用 frozen entry-replay 的 T0 signal gain、close/next 两视角及 net h20/MFE/MAE；DB 为正式幅度。

总体形态非常清楚：3.5% 以上的 direct-chase 组风险明显恶化。例如：

- E3：`≤3.5%` h20 close **-0.75%**、MAE **-5.28%**；`>3.5%` **-2.36%**、MAE **-8.22%**；
- E2：`≤3.5%` **-1.07%**；`>3.5%` **-3.39%**；
- E0：`≤3.5%` **-1.40%**；`>3.5%` **-3.92%**。

> 结论：3.5% 得到执行层面的实证支持，至少是显著风险分界候选；本阶段不扫描并选择另一个最优阈值，避免参数优化。

### T0 / T1 语义

- T0 close 与 next-open 是 frozen replay 的独立视角，不能互相替代；
- staged_entry 的 T1 是真实的第一批后续执行语义：27,422 个生命周期均有 T1 字段，后续批次受交易日、停牌、涨停与事件链约束；
- 因此不能把普通 direct-chase 的 next view 改名成“观察一天后的 T1 策略”；报告只把它作为 next-open 诊断，T1 豁免应由 staged entry 的真实语义消费。

按 E3 的 direct chase，`0–1%` h20 close -0.06%，`2–3.5%` -0.39%，`3.5–5%` -1.11%，`5–7%` -3.55%，`>7%` -3.71%；越过 3.5% 后回撤和收益质量明显变差，但仍有局部非单调，故不升级为精确收益模型。

## 4. T4.6C Initial Position Sizing

只冻结风险预算档，不冻结账户百分比：

| Policy | Risk budget |
|---|---|
| P0 | zero / exception only |
| P1 | probe budget |
| P2 | normal budget |
| P3 | normal or elevated，必须通过执行与组合约束 |

研究权重 0/0.25/0.5/1 仅用于审计，不是账户仓位。没有“E3=63%”之类结果。

## 5. T4.6D Portfolio Guardrails

保留四项账户层约束，但不把它们包装成 alpha：

- single-name cap；
- total initial exposure cap；
- same-day entry cap；
- sector concentration cap。

T4.4 证明 sector 不进入信号/Exposure engine，不等于同一行业的相关性风险可以忽略。

## 6. 十道 Gate

| Gate | 结果 |
|---|---|
| G1 Lineage | PASS，继承 1565e25 |
| G2 T0 Decision Integrity | PASS，assignment 不含 post-T0 outcome |
| G3 Class Conservation | PASS，55,646 lifecycle × 4 strategy = 222,584 |
| G4 Execution Semantics | PASS，T0 close/next 及 chase bins 唯一定义 |
| G5 No Counterfactual Leakage | PASS，fill 采用 frozen replay 语义 |
| G6 DB Primary | PASS |
| G7 Policy Stability | PASS，三年均有覆盖；不做单年优化 |
| G8 Complexity | PASS，无新增 Market-specific threshold/interaction policy |
| G9 Risk Conservation | PASS，event→daily exposure 聚合守恒 |
| G10 Determinism | PASS，assignment hash 与 lifecycle×strategy 数量可重算 |

## 7. 正式冻结结论

1. E-class 决定基础参与资格与风险预算档；
2. E-class 不直接决定实际百分比；
3. 3.5% 以上 chase 在多 E-class 下呈现更差收益/回撤分布，保留为 execution threshold；
4. T0 与 T1 必须使用各自 execution semantics；普通 next-open 诊断不得伪装成 T1 策略；
5. 超过允许 chase 时宁可不参与，不使用未来回调反事实补仓；
6. T4.6 只决定 initial exposure；
7. 后续加仓、减仓、持有和退出全部进入 T5 Path State；
8. 组合 guardrail 保留 sector concentration，但 sector 不进入 alpha/exposure engine。

本阶段冻结的是**政策前沿的结构**，不是唯一最优策略：保守方向是 E2/E3 + probe/normal + 严格 chase；平衡方向是 E1–E3 + normal + 3.5% 上限；更高暴露始终需要执行与组合约束共同批准。
