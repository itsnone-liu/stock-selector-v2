# CL-R5 OOS-A 报告（180 股 untouched，零定义改动）

- daily rows 226100；opening rows 207529；股票 180

| fact | 估计 | CI | 冻结值 | 判定 |
|---|---:|---|---:|---|
| F1 | -0.22329052778853434 | None | -0.193 | **PASS** |
| F2 | 3.351810948131935e-10 | [1.6780286001381932e-10, 4.866916994517393e-10] | -0.524 | **FAIL** |
| F3 | -0.03704934337800309 | [-0.038832714207984634, -0.035296792121905646] | -0.03544 | **PASS** |
| F4 | 0.03073170504580627 | [0.02827679647114246, 0.033106604466797356] | 0.03102 | **PASS** |

## 总裁决：**FAILED_RECORD_HONESTLY**

OOS-A 无论结果：OpeningImpactState 保持 SHADOW；晋升讨论至少等 OOS-B 首个 60 日闭包（用户裁决）。

## G1 数据合同审计（合并）

180/180 股采集完成（合同同 R4：48 bar 全 + Σ5m/日线 ∈[0.95,1.05]）。日线股票日 233,480，有效 218,058（**93.39% ≥ 85%** → SUFFICIENT_SUPPORT），一字日 280，支持率中位 99.3%（个别零支持股 fail-closed 零权重，未换股）。冻结名单 sha256 27356a34ab5edf03（种子 20261015，采集前锁定）。

## 审计披露：控制变量时点修复（两轮运行）

首轮运行发现控制变量 turnover 与 close/mcap 误用 T 日（冻结定义为 T-1）→ 按冻结定义修正 → 重跑一次，修正版为权威。两轮均留存（`/tmp/oosa_run1_leaky_controls.json` 为首版）。修复为代码-合同一致性修复（同 R4 索引 bug 类别），非结果救援：**两轮的 F1/F3/F4 判定一致（PASS）、F2 判定一致（FAIL）**，修复不改变任何结论方向。

## 分层如实解读（不做救援）

- **F1（日线 Effort 惩罚）PASS**：−0.2233 vs 冻结 −0.193，带内 [−0.386,−0.0965] ✓；
- **F3（开盘复现）PASS**：β_E=−0.0370 vs 冻结 −0.0354，几乎重合 ✓；
- **F4（timing 增量）PASS**：β₂=+0.0307 vs 冻结 +0.0310，重合度极高 ✓——**R4 核心两发现跨股票复现**；
- **F2（episode 放大）FAIL**：rel=+0.199（CI 不跨零但符号翻转，冻结 −0.524）。episode 放大未跨股票泛化——按冻结裁决树如实记录，OOS-B 不可抹除此负结果。含义：EpisodeState 交互很可能是原 84 股 cohort/彼时 episode 结构的样本特征，非普适规律。

## 裁决

- OOS-A 总裁决：**FAILED_RECORD_HONESTLY**（任一 FAIL 即此档；禁救援）；
- OpeningImpactState **维持 SHADOW**（未满足全 PASS 升级条件，不升 OOS-A VERIFIED）；
- 跨尺度链更正：EpisodeContext↔DailyEffort 的"放大"环节降级为 **84 股条件结构**；DailyEffort↔OpeningEffortStructure↔FutureImpactEfficiency 主链（F1/F3/F4）经 180 只 untouched 股票跨股票验证成立；
- OOS-B（T>2026-10-14）继续自然累积，F1/F3/F4 的 60 日闭包检验仍将执行（F2 不再作为 OOS-B 判据——其在 OOS-A 已判负，禁用新样本救旧负结果）。

证据：`data/cl_radar/r5_oos/{oosa_sample_frozen.json, ingestion_census.json, oosa_results.json, per_stock/}`；脚本 `cl_r5_oosa_ingest.py`、`cl_r5_oosa_run.py`。

## 用户终裁（2026-10-15，冻结）

1. **F2 永久判负**：Episode amplification = in-sample cohort-specific structure；−52.4%→+19.9%（CI 不跨零）= 结构方向翻转；禁 OOS-B 救援；今后表述只能是"曾在原 84 股稳定存在，未跨股票泛化"。
2. **主链改写**：DailyEffort ↔ OpeningEffortStructure ↔ FutureImpactEfficiency；Episode 退回 context variable。
3. **OpeningImpactState**：维持 SHADOW，状态标记 = **CROSS-STOCK OOS VERIFIED / FORWARD PENDING**。
4. **CD-5 EpisodeState 不直接降权**：先证据依赖审计（A/B/C）+ 敏感性审计（Current vs without-EpisodeState vs preR3-weight）；只撤销 R3-B amplification 的 evidence credit。
5. **F4/CapitalTiming** 为潜在长期研究轴（总量+时间分布两维度），禁行为命名。
6. **Roadmap**：不开新 CL 主题；优先级 = OOS-B forward validation + shadow 日更；60 日闭包 F1/F3/F4 全过 → 提请 SHADOW→DECISION-SHADOW 讨论（仍不真交易）。
