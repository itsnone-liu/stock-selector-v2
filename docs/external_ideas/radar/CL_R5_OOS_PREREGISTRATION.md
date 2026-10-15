# CL-R5 — Effort/Impact Out-of-Sample Validation 预注册

状态：ACTIVE（2026-10-14 用户裁决；R1/R2 已关闭，R3/R4 正结构进入验证期；Profit Mass / Trapped Mass 继续冻结）

## 0. 唯一目标

确认 R3/R4 正结构是稳定规律而非"84 股 + 当前时期"的样本特征。**不发现新结构、不重新估参数。**

\[
EpisodeContext \leftrightarrow DailyEffort \leftrightarrow OpeningEffortStructure \leftrightarrow FutureImpactEfficiency
\]

已验证（冻结基准，R5 只复现不重估）：

| 冻结事实 | 冻结估计 |
|---|---|
| F1：DailyEffort↑ → λ_next↓（R3，控制后） | rank partial −0.193；OLS β_E<0 |
| F2：episode 内 F1 放大（R3-B） | rel −52.4% [−2.85e-3,−1.87e-3] |
| F3：OpeningEffort 单独 → post-open λ̃↓（R4-G2） | β_E=−0.0354 [−0.0375,−0.0332] |
| F4：OpeningTiming 在 DailyEffort 之外有增量（R4-G4） | β₂=+0.0310 [0.0285,0.0340] |

未验证（不做）：Episode×OpeningEffort 大交互（R4-G3 判负 11.7%<20%）。

## 1. 零参数改动清单（硬约束）

禁改：10:00 开盘窗 / 20 日基线（开盘窗与 ADV20）/ winsor P1-P99 / λ 与 λ̃ 定义 / episode 定义（CD-5 L4）/ 控制集 / Gate 判据（A/B/C、20% 量级线）/ 一字板处理。R5 只问：**符号、相对量级、经济意义能否复现**。

## 2. 三种 OOS

### OOS-A 股票外推（横截面）

- 总体：`daily_fullmarket` 全量股票中**从未参与 R3/R4 建模**者（排除 84 股冻结样本）；
- 抽样规则（现在冻结）：上市 ≥1 年（抽样日回溯）、market_ext 可得、按 ADV20（截至抽样日）三分层各随机 60 只，**N=180，种子 20261015**；
- 分钟数据：baostock 5m 同合同采集（预计 ~180 股 ≈ 1 亿级 bar 量 1/3，采集 ~2–3 小时）；
- 检验：F1–F4 在新股票上重跑同一脚本（零改动），判据见 §3。

### OOS-B 时间外推（前向累积——shadow 主使命）

- 窗口：**T > R4FreezeDate = 2026-10-14** 的全部新交易日；
- 机制：`shadow_daily.jsonl.gz` append-only 每日追加，成熟列（lambda_next_5/20）到期补写，禁回改；
- 检验节奏（冻结）：每满 60 个新交易日做一次 F1–F4 复现检验；不足 60 日只追加不判定；
- 数据源：baostock 5m 增量采集（同一合同）+ 日线日更。

### OOS-C 市场环境外推（稳健性）

- 分层（冻结）：000985 close/MA120 上下（强/弱）、σ20 高低半区（高/低波动）、市场 60 日收益正负（牛/熊代理）；板块热潮层暂缓（需板块日更，另立合同）；
- 检验：**只问 F1/F3 主效应在各层内符号是否保持**（CI 不跨零）；**禁**比较/寻找"哪个 regime 最强"——R3-B 已判 PricePosition/MarketRegime 无实质调节，这是稳健性预期而非新发现机会。

## 3. 复现判据（冻结）

每事实 × 每数据集：

- **PASS**：符号与冻结一致 且 股票 cluster bootstrap CI 不跨零 且 点估计 ∈ 冻结值的 [0.5, 2.0]×；
- **PARTIAL**：符号一致 + CI 不跨零但量级出带（记录，不判死）；
- **FAIL**：符号翻转或 CI 跨零。

裁决树：F1–F4 全 PASS ⇒ R3/R4 结构晋升候选（用户裁决是否进 Capital Decision 正式状态变量）；任一 FAIL ⇒ 如实记录、分析层禁救援、结构降级为"样本期条件结构"。

## 4. 边界

全部结论 conditional on cohort（OOS-A 为其自身抽样 cohort）；shadow 仍禁 intraday 生产用途（10:00 PIT 表示除外且仅观察）；Profit Mass/Trapped Mass 冻结至出现真实持仓/账户级/Level2/筹码迁移新信息；全部 PIT、非因果、不修改生产。
