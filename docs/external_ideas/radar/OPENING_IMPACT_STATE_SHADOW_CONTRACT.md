# OpeningImpactState — SHADOW 数据合同（v1.0 冻结）

身份：**CROSS-STOCK OOS VERIFIED / FORWARD PENDING（2026-10-15 用户裁决；经 R5 OOS-A 180 股 untouched 复现 F3 −0.0354→−0.0370、F4 +0.0310→+0.0307，等待 OOS-B 首个 60 日闭包）**。不进 CapitalState、不改候选排序/仓位/入场、不进生产决策。禁综合评分（无 OpeningImpactScore，权重无必要）。

## 1. 三个原子量（唯一定义，禁展开派生命名）

| 量 | 定义 | 表示 |
|---|---|---|
| `E_open` | log( Amount_{09:30–10:00} / ExpectedOpeningAmount )，基线=自身前 20 个有效日的开盘窗 amount 均值（PIT） | 10:00 PIT 可知 |
| `Share_open` | **PIT 版**：Amount_open / ADV20_prior(T-1)（10:00 可知的"开盘占预期全日比"）；**EOD 版**：Amount_open / Amount_day（事后真占比，仅研究） | 双版本，字段名区分 |
| `λ̃_open` | 开盘窗内 5m λ = Σ(of·Δc)/Σ(of²)，of=amount×sign(Δclose)，一字板 bar 置 0；无量纲化 ×ADV20_prior/close_prev | 10:00 PIT 可知 |

辅助记录（非状态量）：opening_return（c1000/close_prev−1）、opening_path_efficiency（净位移/路径长度，5m 收盘价序列）、episode_state（CD-5 L4 内外）。

## 2. 双表示合同（严禁混用）

- **10:00 PIT representation**（未来任何 intraday 评估只准用此层字段）：opening_amount、expected_opening_amount、expected_daily_amount(ADV20_prior)、e_open、share_open_pit、opening_return、opening_path_efficiency、lambda_open、episode_state。**严禁出现当天最终成交额/全日量。**
- **EOD research representation**（盘后研究，完整复现 R4）：以上 + daily_amount、daily_effort、opening_share_actual、post_open_lambda（10:00→close 的 λ̃，R4 outcome）。

依据：R4 G4 的 DailyEffort 是全日总量，10:00 不可知；β₂=+0.0310 是 ex-post 分解结果，**不得**当作 10:00 可行动信息使用。

## 3. 三层时间结构（日更表列分组）

- **T 日 10:00 可知**：第 1 节全部 + 双表示合同 PIT 层；
- **T 日收盘后可知**：daily_amount、daily_effort、opening_share_actual、post_open_lambda、close_retention（close/close_1000−1）；
- **未来成熟**（append-only，成熟后回填）：lambda_next_5、lambda_next_20（T+1..T+5/T+20 日线 λ，同 R3 定义）。

## 4. 存储与运行

- 回填：`data/cl_radar/opening_impact_state/shadow_daily.jsonl.gz`（84 股 × 2021-01-04→2026-10-14，仅有效分钟支持日）；
- 前向：**append-only**，每日收盘后追加新交易日行（未来成熟列待成熟后补写，不回改已有值）；
- **R4FreezeDate = 2026-10-14**：此日及以前 = 建模期（R5 OOS-A/C 可用），此日以后 = OOS-B 纯前向区（禁回改、禁重估）；
- 缺数 fail-closed：分钟无效/基线不足 20 日 → 不产出该行，不填零。

## 5. 语义边界

全部量为可观测成交结构（model_derived），无主力/吸筹/派发/absorption 语义；结论 conditional on cohort（84 股建模期 + 180 股 OOS-A 复现）；主链表述（2026-10-15 用户裁决改写，Episode 退回 context variable）：

\[
DailyEffort \leftrightarrow OpeningEffortStructure \leftrightarrow FutureImpactEfficiency
\]

已验证并跨股票复现：DailyEffort→FutureImpactPenalty（R3，OOS-A F1 PASS）；OpeningEffort→PostOpeningPenalty 且 opening timing 在 total effort 外有独立信息（R4，OOS-A F3/F4 PASS）。已判负（永久，禁救援）：Episode×Effort 放大作用 = in-sample cohort-specific structure（R3-B 原样本 −52.4% → OOS-A +19.9% 符号翻转）。

## 6. 执行层定位（2026-10-15 用户裁决追加）

- **身份**：Timing Quality / Execution Context——候选股产生**之后**判断资金推进质量与入场时机的执行层变量；**非选股因子**，禁入候选打分/stock ranking（Impact Efficiency ≠ Future Return）。
- **Shadow Execution Layer**：夜间筛选照旧 → 次日 10:00 每候选显示三量（OpeningEffort / OpeningTiming / PostOpen-Open ImpactEfficiency，后项收盘层补全）+ 描述标签：`normal-normal` / `high-effort·weak-impact` / `high-effort·efficient-timing` / `low-effort·high-displacement`。标签仅描述，禁综合分、禁改变真实决策。
- **反事实决策记录**（每日）：`{date, code, 原决策, shadow若介入会怎样, 实际结果}`——为 DECISION-SHADOW 攒决策质量证据。
- **High-Effort Watch**（持仓观察态）：极端 effort ≠ 更强；观察能否有效新高/成交依赖度/effort-result 背离；禁自动减仓规则。
- **60 日闭包双轨判据**：F1/F3/F4 统计复现 **且** shadow 改善真实决策质量（追高失败率/入场后 MAE/breakout failure/入场等待/加仓质量）→ 才提请 DECISION-SHADOW。
