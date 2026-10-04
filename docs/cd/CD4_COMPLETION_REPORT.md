# CD-4 — L3 Candidate Funnel Infrastructure · Completion Report (V1)

*预注册: `cd4_preregistration.json` · 结果: `cd4_funnel_results.json` · 候选池: `data/cd/l3_candidate_pool.json.gz`（64 个月度 checkpoint）*

## 交付物

排除 census + 三时间尺度触发器 + 4 级漏斗（64 checkpoints 2021-06..2026-09）+ 召回/换手评估（dev/holdout 分报）+ 候选池附带 sector metadata。

## RQ1 排除层（fail-closed，月度中位）

| 排除理由 | dev 中位 | holdout 中位 |
|---|---|---|
| EXCLUDED_NEW（<120 日历史） | 196 | 59 |
| EXCLUDED_LOW_PRICE（<2 元，ST 代理） | 102 | 195 |
| EXCLUDED_SUSPENDED（60 日活跃<10 天） | 0 | 0 |
| EXCLUDED_ILLIQUID（量 2% 分位以下） | 90 | 100 |

排除后可计算池：dev 中位 4,480 / holdout 中位 4,956。

## RQ2/RQ3 主发现：V1 触发器链召回不足 + 强 regime 依赖

### 发现 1：漏斗通过率是市场 regime 的函数

| 年份 | lvl_full 月度中位 |
|---|---|
| 2021 | 0 |
| 2022 | 0 |
| 2023 | 273 |
| 2024 | 164 |
| 2025 | 433 |
| 2026 | 366 |

dev 窗（2021-2023 熊市）31 个 checkpoint 中 **19 个候选池为空**——长期触发器（24 月收益>0 且价在 500 日均线上）在熊市自动关闭漏斗。这是设计语义的直接结果，同时暴露 **L1 Market Regime 层（六层架构中仍空）与 L3 漏斗的交互**：漏斗通过率本身就是 regime 的读数。

### 发现 2：每一层触发器的召回代价（holdout，30 个有前瞻窗的 checkpoint）

| 层级 | 池中位 | top-decile 召回中位 |
|---|---|---|
| LEVEL_EXCL | 4,956 | 100%（定义域） |
| LEVEL_LONG | 2,078 | **38.0%** |
| LEVEL_MID | 744 | 14.5% |
| LEVEL_FULL | 366 | **7.9%** |

**每加一层丢失一半以上召回**：mid（13 周动量+自身参与度 1.5×）把 38% 砍到 14.5%；short（60 日新高+2 倍量）再砍到 7.9%。V1 三层 AND 链作为唯一候选来源**不合格**——会漏掉 92% 的未来 top-decile 股票。

### 发现 3：月度换手 89%（Jaccard 0.107）

候选池月度换血近九成，主要由 T_SHORT 的 20 日事件窗驱动——池稳定性差，直接接昂贵分析会产生高沉没成本。

## 结论（结构层，如实）

> **V1 漏斗验证了"压缩层级-召回"的测量协议本身，但三层 AND 链不能作为唯一候选来源。** 长期层单独（~2,000 只、38% 召回）作为"值得观察池"是合格的；mid/short 触发器把召回代价推到了不可用区。V2 方向（需重新预注册，不在本阶段调参）：放宽为 OR/加权结构、缩短 short 事件窗定义、或把 mid/short 从"过滤层"降级为"优先级元数据"（与 sector metadata 同等待遇，L4/L5 消费）。

**没有为召回调任何阈值**（预注册禁令）；V1 数字原样冻结作为基线。

## RQ4：sector metadata 已附带

每个 LEVEL_FULL 候选携带 l2/base/path/narrowing_risk（trailing 10 日 NARROWING）——无 gating，纯元数据，供 L4/L5 消费。divergent 标记=base 字段本身；sw2_context_if_needed 按合同 defer。

## 边界

无复合评分、无最终排名、无 L4 生命周期/成本工作、无 L5 规则；未来收益仅用于召回评估（evaluation only）；全触发器 trailing-only。

**全局状态**：`CD-0..CD-3 COMPLETE · CD-4 COMPLETE (V1 baseline; V2 待裁定) · CD-5 NOT STARTED · L2_RISK_CONTEXT_V1 冻结待 CD-6 · CSR-8 不变`
