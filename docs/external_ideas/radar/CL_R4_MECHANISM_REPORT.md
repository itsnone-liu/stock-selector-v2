# CL-R4 Opening Mechanism 结果（G2/G3/G4 终版）

- rows: 109,449（outcome 有效 108,882；episode 日占 69.1%）
- Y = λ̃_{10:00→close} = λ·ADV20_prior/close_qfq(T)，合并 P1/P99 缩尾 [0.030, 0.523]
- 控制 PIT 至 10:00：log ADV20_prior / 换手(T-1) / σ20_prior / log close(T-1) / ret20 / log 市值(T-1)
- 股票 cluster Gram bootstrap 1000 次；corr(E_open, DailyEffort)=0.822（高共线，β2 稳定因而更值得注意）

## 审计披露：一次无效运行与修复链

首轮运行 β 量纲病态（~−3e5）→ 诊断为 bar 数组索引错误（close 误取 b[5]=volume，应为 b[4]）→ 修复一次 → 重跑，结果按原样接受。两次日志均留存（/tmp/cl_r4_mech.log 病态版、mech2/3.log 修正版）。修复动机是量纲异常，非结果方向；此为代码正确性修复，不属结果救援。另修正报告中 β₄ 显示索引（beta[8]→beta[9]），计算本身无误。

## G2 开盘复现（R4-Q1）：**PASS**

\[
\beta_E = -0.0354,\quad CI[-0.0375,-0.0332]\ 不跨零
\]

**R3 的 Effort→ImpactPenalty 结构在开盘阶段复现**：当日开盘窗（09:30–10:00，含竞价）成交努力相对自身 20 日开盘基线异常高时，10:00 后至收盘的单位成交额价格推进效率显著更低。

## G3 episode 交互复验：**FAIL（判据 B）**

\[
\beta_{EC}=-0.00416,\ CI[-0.0064,-0.0020]\ （A 过，方向与 R3 一致），\quad rel=-11.7\% < 20\%（B 败）
\]

episode 内 β_E=−0.0396 vs 外 −0.0354：方向与 R3 的"事件内放大"一致，但开盘时间尺度上量级仅 ~12%，低于冻结的 20% 实际意义线。**R3 的 episode 放大不延伸到开盘尺度（按硬判据）**。

## G4 增量门（R4-Q2）：**PASS**

| 系数 | 值 | CI | 判定 |
|---|---:|---|---|
| β₁ DailyEffort | −0.1101 | — | 日内版 R3：全日努力越高→当日剩余效率越低 |
| **β₂ OpeningEffort\|DailyEffort** | **+0.0310** | **[0.0285, 0.0340] 不跨零** | **独立增量成立** |
| β₄ Opening×Episode（G4 条件下） | +0.0041 | [0.0006, 0.0080] 不跨零 | 小幅稳定（量级 <2%，不主张） |

**核心读法**（Q2 = YES）：
- 单独看（G2）：开盘努力高 → 之后效率低（R3 复现）；
- 控制全日总努力后（G4）：**开盘占比高的日子，其余时段的推进效率相对更高**（β₂>0）——即"钱在一天内何时、以什么路径进入"携带全日总量之外的信息：前载型努力日的剩余时段比总量 alone 预测的更高效。

## 终裁（停止树）

**G2 PASS + G4 PASS + G3 FAIL → `R4_PASS_G2_G4_create_OpeningImpactState(no episode amplification)`**

- 允许创建 **OpeningImpactState**（shadow feature 层，不进生产）；
- 不授予 EpisodeAmplifiedOpeningEffort（开盘尺度量级不足）；
- 命名纪律不变：无主力/派发/absorption 语义。

## 边界（冻结）

- 结论 **conditional on candidate cohort**（84 股冻结样本），非 A 股普遍规律；
- 开盘窗含集合竞价（baostock 5m 合同限制，已冻结）；
- 单日 5m λ 分布修正后健康（P50≈0.047、P99≈0.24、无爆炸尾）；
- 全部 PIT、非因果、不修改生产。

产物：`data/cl_radar/r4_opening/{ingestion_census.json, mechanism.json}`；脚本 `cl_r4_ingest_5m.py`（含 worker 变体）、`cl_r4_mechanism.py`。
