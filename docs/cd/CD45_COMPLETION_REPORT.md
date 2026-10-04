# CD-4.5 — L1 Market Observable Regime · Completion Report

*预注册: `cd45_preregistration.json`（含一处**结果产出前**的执行修正：trend MA 500→250，因 500 日前置会使 dev 窗只剩 2023 单年）· 结果: `cd45_regime_results.json` · 轴表: `data/cd/sector_axes/l1_market_axes.json.gz`（1,143 日 2022-01-13..2026-09-30）· V2 设计原则已冻结于预注册*

## 五个研究问题的答案

### Q1 市场状态有多少稳定结构？——5 个，全部 support 合格

| Regime | 份额 | 含义 |
|---|---|---|
| R_RISK_ON_BROAD | 37.3% | 趋势上方+广度/收益不弱 |
| R_RISK_ON_NARROW | 29.4% | 趋势上方但广度或收益 LOW |
| R_REBOUND_MIXED | 17.8% | 趋势下方+当前恢复 |
| R_RISK_OFF | 8.3% | 趋势下方+跌+广弱 |
| R_DEPRESSED | 7.2% | 趋势下方+弱漂移无主动卖出 |

无 LOW_SUPPORT（<2%）regime。

### Q2 状态持续多久？——**日频 regime 几乎不持续（中位 1-2 天，max 4-23 天）**

这是本阶段最重要的结构性发现：**日频 regime 粒度对"context 层"太细**。RISK_ON_BROAD/NARROW 之间日频互切（146/138 次双向转移），像高频噪声而非状态区间。含义：L1 要成为稳定分层变量，需要滚动平滑聚合（如 N 日众数）——**平滑窗口属于 CD-4V2 预注册内容，本阶段不调**。

### Q3 2021/22 与 2023+ 差异是什么？——regime 构成完全不同

| 年份 | RISK_ON(BROAD+NARROW) | RISK_OFF+DEPRESSED | REBOUND |
|---|---|---|---|
| 2022 | 58% | 17.5% | 24.7% |
| 2023 | 81% | 11.6% | 7.4% |
| 2024 | 25.7% | **35.5%** | 38.8% |
| 2025 | **100%** | 0% | 0% |
| 2026 | 69% | 12.1% | 18.8% |

2022-2023 与 2024 的差异是结构性的：2024 是 RISK_OFF/DEPRESSED/REBOUND 占 74% 的修复年（这解释了 V1 漏斗 dev 窗空池——2022 熊市 + trend=BELOW 主导）；2025 是纯 RISK_ON 年。**V1 漏斗行为差异由此获得机制解释**。

### Q4 funnel×regime 关系多强？——吞吐差 5 倍、召回差 4 倍

| Regime | V1 中位 pool | 中位 recall_full |
|---|---|---|
| R_RISK_ON_BROAD | 366 | 9.3% |
| R_RISK_ON_NARROW | 316 | 5.8% |
| R_DEPRESSED | 193 | 6.0% |
| R_REBOUND_MIXED | **71** | 2.3% |
| R_RISK_OFF | **68** | 2.5% |

RISK_OFF/REBOUND 下 V1 漏斗近乎关闭且召回最差——**stratification 完成，未动任何阈值**（边界遵守）。

### Q5 连续还是状态区间？——底层轴全部单峰（5/5 NO multimodality）

ret20d/breadth/part/conc50/disp 的 dev 分布均无多峰——市场背景是**连续变化的，离散 regime 是人为切分**（服务于可解释性）。诚实记录：regime 标签是连续背景的离散化投影，其合法性来自 support 与可解释性，不来自"市场真有离散状态"。

## 边界遵守

无 regime 化漏斗阈值调整 · 无方向预测声明 · 无 BUY/SELL 映射 · V2 未执行（仅设计原则冻结）· regime 命名待 V2 报告定稿（artifacts 用 R1..R5 稳定码）

## 给 CD-4V2 的输入（已就绪）

1. 冻结的 V2 设计原则（高召回低成本资源调度；MID/SHORT=来源/元数据非 AND gate）
2. 两级结构 + 多入口 union + candidate_source[] + 增量召回协议
3. L1 分层变量（含"日频 regime 需平滑"的结构发现——平滑窗口在 V2 预注册冻结）
4. Pareto frontier 评价（count×recall×stability×downstream cost）

**全局状态**：`CD-0..CD-4 + CD-4.5 COMPLETE · CD-4V2 NEXT（待 GO）· CD-5/CD-6 NOT STARTED · L2_RISK_CONTEXT_V1 冻结 · CSR-8 不变`
