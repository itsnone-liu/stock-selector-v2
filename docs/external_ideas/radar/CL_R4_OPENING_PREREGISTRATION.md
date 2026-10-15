# CL-R4 — Opening Effort / Impact Integration 预注册

状态：ACTIVE（2026-10-14 用户裁决启动；定义为 R3 正结构的盘中复现 + Opening EI 独立增量检验，**非分钟因子挖矿**）

## 0. 两个研究问题（冻结）

- **R4-Q1 盘中复现**：R3 的 `Effort↑ → FutureImpactEfficiency↓` 能否在开盘阶段观察到（OpeningEffort → PostOpeningImpactEfficiency）？
- **R4-Q2 增量价值**：已知 DailyEffort / EpisodeState / 基础流动性 / 波动 / 价格状态后，开盘结构是否仍增信息？不过 ⇒ Opening EI 只是 R3 提前 30 分钟重测，无单独成状态理由。

## 1. 设计原则（冻结）

1. **首轮不压成单一 EI 比率**：保留原始二维 OpeningEffort + OpeningResult 与路径信息（开盘量相对基线 / 开盘位移 / 路径效率 / 回撤深度 / 二次推升 / 10:00 位置）；不预设努力×结果同时成立（R3 教训：Result 未必有贡献）。
2. **开盘窗口**（依 G1 合同）：`09:30–10:00` 连续窗口 = 5m bar 09:35..10:00 共 6 根求和；**集合竞价不可分离**（含于首根 bar）——G1 普查判定的合同限制，待用户接受后冻结为"opening continuous incl. auction"口径；若用户要求严格分离则改道数据源，本研究暂停。
3. **R4-A（复现）**：`E_open = log(Amount_open / ExpectedOpeningAmount)`，基线仅用 T 日前信息（前 20 个交易日同窗口 amount 均值）；outcome 禁用开盘窗口本身（Gate S）。
4. **R4-B（episode 复验）**：`OpeningEffort × EpisodeState`，沿用 R3-B 硬判据 A/B/C。
5. **R4-C（增量门）**：`Y = β1·DailyEffort + β2·OpeningEffort + β3·Episode + controls (+ β4·OpeningEffort×Episode)`；β2/β4 无稳定独立信息 ⇒ Opening EI 无存在理由。

## 2. Outcome family（冻结，禁晚挑；禁 FutureReturn 主 outcome）

- **A（主）**：`λ_{10:00→close}` = 10:00 后至收盘的单位成交额价格推进效率（5m bar 级 B1 式；无量纲化 λ̃ 同 R3-B）；
- **B**：OpeningGain → CloseRetention —— **必须先建 Gate M 机械基线**（开盘涨幅大→绝对回撤空间机械大）；
- **C**：`λ_{T+1:T+5}` / `λ_{T+1:T+20}`（日线级，接回 R3 的桥）。

## 3. Gate（冻结）

- **G1 Opening Data Contract**：分钟 amount 单位 / auction-continuous 边界 / 停牌 / 一字板 / 涨跌停 / 缺分钟 / 午前中断 / qfq-unadj / timestamp。→ 见 `CL_R4_G1_DATA_CONTRACT_CENSUS.md`；**baostock 5m 合同 PARTIAL SUPPORT**（auction 不可分离为唯一限制）。
- **G2 Opening Mechanism**：OpeningEffort → PostOpeningImpact 稳定（股票 cluster bootstrap、全控制 ADV/换手/波动/市值/近期收益、不共享窗口、不共享构造项）。
- **G3 R3 Replication / Episode Interaction**：A/B/C 硬判据（CI 不跨零 / 量级 ≥20% / 方向可解释）。
- **G4 Incremental Information**（生产价值门）：加 DailyEffort 后 β2/β4 是否保留独立信息；**G4 FAIL ⇒ 不进 OpeningState，即使 G2/G3 漂亮**。

## 4. 选择偏差边界（冻结）

数据若非全市场而仅候选池/样本内 84 股，结论一律写 **conditional on candidate cohort**，禁写"A 股普遍规律"；cohort 内开盘 timing 实用价值本身更高，但边界必须如此标注。

## 5. 停止树（冻结）

1. G2 FAIL → R4 CLOSE，不救援；
2. G2 PASS + G3 FAIL → 保留无条件 opening effort 结构，继续 G4；
3. G2/G3 PASS + G4 FAIL → 结论"Opening pattern 是日线 Effort 的早期表现，无独立增量" → R4 CLOSE, no integration；
4. G2 + G4 PASS → 才可创建 OpeningImpactState（shadow feature）；G3 同过则记录 EpisodeAmplifiedOpeningEffort；**仍禁主力抢筹/派发/absorption 命名**。

## 6. 解释边界

开盘结构是可观测成交行为，不识别参与者与意图；全部 PIT、非因果、不修改生产、不建 CapitalState；若 Q1+Q2 均立，方可谓首次串成"中期资金事件 → 日线资金努力 → 开盘执行效率"跨时间尺度链（仍为统计结构，非行为学断言）。
