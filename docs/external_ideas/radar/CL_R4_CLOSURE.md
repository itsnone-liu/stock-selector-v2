# CL-R4 — 关闭声明（CLOSED：首个双正结构 + 跨时间尺度链合龙）

关闭日期：2026-10-14（G1–G4 全部执行完毕，停止树 G2+G4 PASS 分支）

## 裁决

\[
\boxed{\text{CL-R4 CLOSED — OpeningImpactState 合格（shadow 层）；episode 放大不延伸至开盘}}
\]

## 冻结结论（全部 conditional on candidate cohort，84 股冻结样本）

1. **R3 结构开盘复现（G2 PASS）**：开盘窗（09:30–10:00，含竞价）成交努力相对自身 20 日开盘基线异常高 → 10:00 后至收盘单位成交额推进效率显著更低（β_E=−0.0354，CI 不跨零）。R3 的 Effort→ImpactPenalty 不是日线统计假象，**在日内开盘阶段即已出现**。
2. **开盘路径的独立增量（G4 PASS）**：控制全日总努力与全部 PIT 控制后，开盘努力占比仍携带稳定信息（β₂=+0.0310，CI 不跨零）：前载型（开盘占比高）努力日的其余时段效率，比全日总量 alone 预测的更高。**"钱何时、以何路径进入"有全日总量之外的信息**——Opening EI 不是日线 Effort 的提前 30 分钟采样。
3. **episode 放大不延伸（G3 FAIL by B）**：方向与 R3 一致（episode 内 −0.0396 vs 外 −0.0354）但量级 11.7% < 20% 硬线。R3 的 EpisodeState 交互是日线尺度现象。

## 跨时间尺度链（本程序首个）

\[
\text{中期资金事件（episode，日线放大）}\ \longrightarrow\ \text{日线资金努力（Effort penalty）}\ \longrightarrow\ \text{开盘执行效率（G2 复现 + 路径增量）}
\]

三层中两层（日线↔开盘）已双向衔接；episode 层与开盘层直接交互不足 20% 量级线。

## 允许的后续（不自动执行）

- **OpeningImpactState** 可创建为 shadow feature（E_open、opening share、λ̃_open 三件套），随日更数据离线运行；**不进生产、不建 CapitalState、不命名主力/派发/absorption**；
- auction 分离（需新数据源）入 backlog。

## 证据链存档

| 阶段 | 文档 |
|---|---|
| 预注册 | `CL_R4_OPENING_PREREGISTRATION.md` |
| G1 数据合同普查（路径 A 分叉） | `CL_R4_G1_DATA_CONTRACT_CENSUS.md` |
| G2/G3/G4 结果（含索引 bug 审计披露） | `CL_R4_MECHANISM_REPORT.md` |
| 数据 | `data/cl_radar/r4_opening/`（per_stock/ 84 文件 5m bar、ingestion_census.json、mechanism.json） |
| 采集 | `scripts/cl_r4_ingest_5m.py`（+ worker 分片变体），baostock 5m，97.58% 支持率 |

## 程序意义

R1 负（筹码密度）、R2 负（成本锚）、R3 正（日线 effort 惩罚 + episode 放大）、R4 正（开盘复现 + 路径增量）：CL Radar 四轮完成从"否证两个直觉机制"到"确立并跨尺度衔接一个可复现结构"的完整弧线。方法门禁（U/M/S）与硬判据（A/B/C）全程执行，无一次结果救援。
