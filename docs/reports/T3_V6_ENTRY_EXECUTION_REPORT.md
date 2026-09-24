# T3 V6 — 状态条件下的四种入场执行研究（Entry Execution Study）

**版本**：T3 V6 @ 基线 c312371（T3 V5 冻结线）
**范围**：入场执行（entry execution）比较研究，**不是**完整交易系统回测（无退出/持仓管理，见 §19；退出研究归 V7）
**数据集终点**：2026-09-18（`DATASET_END`，与 V5 一致；市场日历延伸至 2026-09-23 仅用于终点估值）

---

## 0. 摘要（两问分开回答）

**Policy question（不交易也是策略结果，27,422×4×2 完整机会矩阵）**

| 指标 (w10) | direct_chase_capped | staged_entry | wait_first_pullback | wait_support_hold |
|---|---|---|---|---|
| 入场率 | 48.7% | 99.5% | 71.4% | 39.3% |
| capital return h10 / h20 / h40 (mean, %) | +0.45 / +0.72 / +1.45 | −1.22 / +0.37 / +1.38 | −1.36 / +0.38 / +1.51 | −2.88 / +0.05 / +0.61 |
| 中位等待天数 | 0 | 0 | 4 | 6 |
| P(entry by τ=5) | 0.487 | 0.988 | 0.458 | 0.102 |
| 未入场率 | 51.3%（其中 3.5% cap 挡掉为主） | 0.5% | 28.6% | 60.7% |
| 未入场错失（窗内中位 %） | 4.75 | — | 2.52 | 4.37 |
| 40 日风险敞口天数 (mean) | 18.8 | 22.6 | 24.8 | 12.8 |

配对差（event-level，同事件同窗，双块 cluster bootstrap B=2000，Holm 族=6 对×(窗口×horizon)）：

- h10：direct − support = **+3.34pp**（CI_stock [3.12, 3.56]，CI_date [2.97, 3.71]）；direct 对其余亦全显著为正
- h20：direct − wait_pb = +0.34pp、direct − support = +0.68pp、direct − staged = +0.35pp（均 Holm 显著）
- h40：direct − wait_pb 收敛至 −0.06pp（**不显著**）；direct − support = +0.85pp、wait_pb − support = +0.90pp 仍显著

**Execution question（只有 entered trades，交集 5,207 事件×四策略共同入场）**

- h20 入场后净收益配对差全部落在 ±0.6pp 内、P(Δ>0)≈0.44–0.53：**入场后质量差异很小**
- 入场溢价（fill vs signal close）：四策略中位均 ≈0%（−0.15 ~ 0%），等待策略**没有买到显著折价**
- MAE20 中位：direct −5.17 / wait_pb −4.73 / support −5.28 / staged −3.40pp；MDD20：−9.0 / −9.1 / −9.4 / −6.2pp（staged 分批平滑最深回撤最浅）
- P(20 日内创新高)：direct 0.848 > staged 0.814 > wait_pb 0.770 > support 0.746

**§25 四个候选结构的数据回答（探索性，不预设结论）**

1. **等待无差别**：entered-only 层面基本成立（差 ±0.6pp）；但 policy 层面**不成立**——入场率差异转化为资本收益差（h10 direct−support +3.34pp）。
2. **价格改善 vs 机会成本**：**机会成本主导**。价格改善≈0（gap 中位 0）；机会成本显著（support 未入场 60.7%，其中位错过窗内 +4.37%、post40 max +10.64%；w20 扩窗多入场的批次为负贡献：wait_pb h20 mean 0.38→0.23、support 0.05→−0.22）。
3. **highload 恶化而回调改善**：未获支持。origin participation 二分（lowload n=3,834 / highload n=23,343）内 direct 相对优势均在（lowload Δ +0.66~+0.80，highload Δ +0.28~+0.65）；等待策略 fill 日的 turnover_load 更高（中位 1.86/1.64 vs direct 1.46）但入场后质量无对应改善。
4. **support 等待只增延迟**：**成立**。中位等待 6 天（wait_pb 4 天）、P(entry by τ=5)=0.10（wait_pb 0.46）、入场率最低、h10–h40 全程最差，入场后质量亦无补偿（MAE/MFE/P(nh) 均不占优）。

---

## 1. 研究设计与冻结规范

### 1.1 语义审计（Gate 1 前置）

冻结源：`STAGE4_LIFECYCLE_ENTRY_REPLAY_SPEC.md` §5–§11/§10b + `STAGE5_POSNEG_ADJUSTED_SPEC.md` v7.1（§3 K2/K3/K4、§5.3 因子比式、§6 裁定点 G）+ `entry_replay.py`（`RULE_VERSION=entry_replay_stage4_v5`, `run_spec_hash=8ebdc40bacd5bcec`）。

审计结论：**PASS，无未决差异**（`execution_policy_definition_v1.json`）。要点：

- **direct_chase_capped**：breakout_day（T0）收盘触发；若 `close(T0)/close(T0−1)−1`（未复权）> 3.5% 则不追（capped_not_entered）；T1 豁免仅适用于 staged。
- **staged_entry**：30/30/40 三批（T1=breakout_day 收盘信号、T2=首个缩量日、T3=配对 reattack 日）；t3 存在⇒t2 已存在（配对事件保证），缺失批次不补。
- **wait_first_pullback**：突破后首个 `pullback_v2` 回调事件（first_day∈(T0, end_day]）内首个 `shrink_volume=true` 日触发。
- **wait_support_hold**：同一事件的 `stabilization_day` 触发。
- 成交：信号日次市场日开盘（`next_valid_open` daily-bar proxy，5bp 滑点、佣金 0.03% min 5 元、过户费 0.001%、印花税卖出单边 2023-08-28 起 0.0005）；停牌不压缩为 T+1（次市场日无个股行情=该腿不成交）；一字涨停按 `approximate_limit_ratio`（300/301/688=20%、4/8 开头=30%、其余 10%，tol=max(0.001, prev_close×0.0015)）判定买入阻断。
- **capped 行的 fill 字段存 unlimited 反事实是 v7.1 冻结规则，不计为不一致**；unlimited 数据仅用于反事实诊断。

### 1.2 两类 estimand（严格分离）

- **A. Policy-level**：同一事件 T0 同时启动四策略，完整 27,422×4×2 机会矩阵；终态九分类（entered / capped_not_entered / not_triggered_in_window 细分为 no_pullback_in_window / no_shrink_day / no_stabilization / not_triggered_in_window / triggered_but_unfillable / sample_end / data_gap）。**禁止 triggered-only 比较**。
- **B. Trigger-conditioned**：仅 entered 行（入场溢价、entry-clock 收益、MAE/MFE/MDD/new-high）。

### 1.3 双 outcome clock

- **Clock A（entry-relative）**：首笔 fill+5/+10/+20 市场日；组合净值口径（未到 fill 日的批次=现金，不提前扣减）；MFE/MAE/MDD=组合净值路径极值（**MAE 可为正**：表示入场后全程未跌破成交价）；new_high=复权价超越突破日复权收盘；市场超额=组合首腿含滑点因子比 − 市场指数对数差。
- **Clock B（event-relative，Primary）**：T0+10/20/40 市场日统一终点；未入场=现金 0 收益 + `not_entered=true`；终点日停牌沿最后可得行（carried）；恰终点成交=价格收益 0 仅计费用；终点后成交批次=现金。

### 1.4 决策窗口与状态轴

- Primary 决策窗 T0→T10 市场日；T0→T20 为**预登记 sensitivity**（w20 入场率变化已报告，不用于升格结论）。
- `origin_state`=V5 compact_state_v1 @tau0（跨策略公平比较的 Primary 对齐轴）；`entry_state`=fill 日状态（post-origin selection 产物，**只做解释**，不用于跨策略 Primary 对齐）。

---

## 2. 主结果

### 2.1 问题 A：policy-level（完整矩阵）

（见 §0 表）关键补充：

- **h10→h40 的结构**：短窗 direct 优势最大（+3.34pp vs support），h40 对 wait_pb 收敛不显著——等待策略的补偿只在足够长的持有窗内出现，且不足以覆盖其入场率损失（h40 direct 仍 +1.45 vs wait_pb +1.51 的均值差 +0.06pp，配对不显著）。
- **未入场账（现金不是免费）**：support 60.7% 未入场的中位错失=窗内 +4.37%、post40 max +10.64%（对应 avoided post40 min −9.34%）；wait_pb 28.6% 未入场错失 +2.52%/+8.17%（avoided −10.56%）。错失与规避双向存在，净效应由配对差承载。
- **staged 的资本收益劣势来自 t2/t3 批次**：t1 恒成交（fill_rate=1.0），t2/t3 各 19,575/7,941 次；`fraction_invested` 均值 0.625；h10 mean −1.22% 显著差于 direct——早期满仓 direct 在短窗占优，h40 追平。

### 2.2 问题 B：trigger-conditioned（entered only）

- **入场溢价 ≈ 0**：fill vs signal close 中位 direct −0.12% / staged −0.02% / wait_pb −0.15% / support −0.13%；25 分位也仅 −0.5~−0.76%。**等待在成交价上几乎不产生折价**（回调事件的缩量/止跌日价格≈signal 收盘）。
- 入场后 20 日：四策略中位收益 −1.17~+0.12pp、配对差 ±0.6pp 内；MDD20 中位 −6.2~−9.4pp；P(new-high h20) direct 0.848 最高（早入场更常再创新高）。
- **entry_state 条件（解释性，不排序）**：structural_break 格四策略全负（中位 −2.2~−2.5pp）——waiting 策略 6,861/4,294 笔（wait_pb/support）在 fill 日状态已为 structural_break；continuation / high_participation_extension 格 direct 中位 +1.65/+1.82pp 最好。**这是"等待期间让坏消息发生"的形态证据**。

### 2.3 状态条件与 origin 对齐（披露）

- **T0 结构轴无变异**：origin_structure 在全部 27,422 事件上均为 intact（突破日定义上 20 日结构必完好）——V5 四格在 origin 处**退化为 participation 二分**（lowload 3,834 / highload 23,343）。两格内配对（w10 h20，Holm 显著）：lowload direct−wait_pb +0.66 [0.32,1.01]、direct−support +0.80、direct−staged +0.75；highload direct−support +0.65 [0.50,0.81]、direct−staged +0.28、wait_pb−support +0.36。**direct 的相对优势在 lowload 格更大**；highload 格内优势收窄但仍为正——没有出现"highload 时等待反而改善"的交叉。
- 七态 origin cohort（exploratory）：continuation / HPE / structural_pressure 三格的显著对与全样本方向一致（direct−support：+0.73 / +0.59 / +1.03）。
- **年度分层（internal temporal robustness，非 OOS）**：2024（n=15,032）四策略全负（direct −1.11 最优）；2025（n=60,212）全正（direct +1.63 ≈ wait_pb +1.65）；2026（n=34,444）全负（direct −0.08 最优）。**方向年度稳定**（direct ≥ waiting 在 3/3 年成立）；2021/2022/2023 在 T3 事件宇宙为空（突破事件 2024 年起才有），如实披露。

### 2.4 执行层诊断

- **3.5% chase cap 反事实**（仅诊断）：cap 挡掉 51.3%（14,042/27,422，与 stage4 记忆的 close 理论 49.3% 同量级）；被挡事件窗内中位涨幅 +4.75%、post40 max 中位 +11.14%、post40 min 中位 −11.84%——**cap 丢掉的中位机会为正但双向风险并存**；不扫描其他阈值（开工令禁）。
- **一字涨停阻断**：556/98,780 成交尝试（0.56%）被阻（staged 占 504：t1 一字 429+t2 17+t3 58；direct 16 / wait_pb 17 / support 19）；被阻行 post40 max 中位 **+32.8%**（min −5.12%）——涨停把最强的机会挡在门外，是 direct/staged 的系统性负面选择，量化幅度如上。
- **same-close vs next-open 敏感性**：h20 差 mean +0.019pp / median −0.012pp（n=70,226）——**执行假设不敏感**；same-close 为非 primary 诊断口径，不可实时执行。
- **fill_delay 恒 1 市场日**；停牌压缩检查 0 例；`execution_fillability_audit.parquet` 含每次尝试的 signal/intended/actual/gap/proxy 字段全链。

---

## 3. 完整性与可复算（九道 Gate 全 PASS）

`execution_integrity_gates.json`：G1 Policy Definition / G2 Execution Clock（fill_date>signal_date 除 _sc 诊断列，delay≡1）/ G3 Trigger PIT（120 抽样物理截断重算 0 mismatch）/ G4 State PIT（origin 全量 + entry 4,000 抽样 vs V5 as-of 0 mismatch）/ G5 Opportunity Matrix（219,376=27,422×4×2 全记录，attrition 守恒）/ G6 No-entry Accounting（missed 独立复算 0 mismatch，exposure+cash≡40）/ G7 Fill Audit（intended≡次市场日、fill_price=open×1.0005 复算）/ G8 Paired Dependency（6 对配对交集 n 复算一致、双块 CI、Holm 族完整、稀疏门禁生效）/ G9 Determinism-Replay（双跑三 frame hash 一致 + 30 事件截断重放执行层 0 mismatch）。

**统计口径**：two-way cluster bootstrap（stock 块 + breakout_day 块）percentile 95%，B=2000，seed=20260919；Holm 族=(cohort, window, horizon)；裁定点 G 稀疏门禁（min_events=100 / stocks=30 / dates=30）；单格显著默认 exploratory，主结论只引用 all-cohort Holm 显著对。

**前瞻台账**：`prospective_execution_ledger.parquet` 109,688 行（27,422×4 policy×window10 首笔基线 + hash 链验证 0 mismatch），全部标注 `in_sample_replay`；as-of 单调性验证通过。V6 冻结后新事件按 outcome 成熟度由独立脚本追加。

---

## 4. 披露与方法学边界

1. **daily-bar execution proxy**：全部成交按日线路径模拟（次市场日开盘+5bp 滑点），一字涨停用 `approximate_limit_ratio` 近似；未建模盘中限价单与集合竞价。
2. **数据源迁移**：执行价层由 TDX 迁移至 T3 冻结库 baostock 未复权行情（含 open）；收益层由 `unadjusted_exploratory` 升级为 STAGE5 §5.3 复权因子比式：`R_net=(gross−sell_fee)/(notional+buy_fee)−1`，`gross=notional×(sell_fill_raw×F_exit)/(buy_fill_raw×F_entry)`。112 个事件 T0 复权因子缺失（与 V5 insufficient_data 112 一致）：执行层照常模拟、收益层置 null 并打 `adj_factor_missing_t0` 标记，**不剔除出矩阵**。
3. **MFE/MAE/MDD 口径**：组合净值路径极值（fill 起窗）；MAE>0 表示入场后全程未跌破成交价（非错误）；MDD 相对窗内滚动峰值。
4. **不研究退出**：所有结果为统一 mark-to-market 终点，不含止盈止损；将"direct 更优"解读为交易系统结论是越界（V7 议题）。
5. **2021–2023 无事件**：T3 宇宙突破事件始于 2024；年度分层仅 2024/2025/2026。
6. compact 七态**不排序**；origin 四格因结构轴 T0 无变异退化为二分（如实呈现）；entry_state 仅解释性使用。
7. missed-move 描述是 outcome 层记账，**不改变任何 trigger 定义**。
8. w20 更优/更差的数字均为预登记 sensitivity，不得升格为 primary 结论。

---

## 5. 结论与 V7 建议（§26）

在 T3 事件宇宙、统一 mark-to-market、无退出的研究边界内：

- **直接入场（capped）在 policy 层面占优**：h10–h20 全部 Holm 显著，h40 对 wait_pb 收敛；其优势来源**不是入场后质量**（estimand B 差异 ±0.6pp），而是入场率与时机。
- **等待的补偿假设均未获支持**：价格改善≈0、机会成本显著、highload 无交叉改善、support 等待主要增加延迟与错失。
- **staged 的价值在回撤控制**（MDD20 −6.2 vs −9.0pp，MAE 最浅），资本收益不占优。
- 执行摩擦整体温和（涨停阻断 0.57% 但事后涨幅大；same-close 差异 <0.02pp）。

**V7 议题（本报告不预判）**：退出/持仓管理；届时 direct 的短窗优势是否被退出规则吞并、等待策略在特定退出下的补偿是否显性化，均需在 V7 框架内重新检验。若 V7 沿用本结论，执行层可直接简化（用户 §26：若四入场差异很小则简化执行——本研究的 estimand B 表明**入场执行方式对入场后质量的影响很小，差异集中在入场率/时机层**）。

---

## 附录：产物清单（output/research/t3_v6/）

`execution_opportunity_panel.parquet`（219,376 行主矩阵）、`execution_entries.parquet`（146,141）、`execution_tranches.parquet`、`execution_entry_paths.parquet`、`execution_policy_outcomes.parquet`、`execution_state_contrasts.parquet`（216 组配对）、`execution_attrition.csv`、`execution_fillability_audit.parquet`（206,074 次尝试）、`execution_no_entry_accounting.parquet`、`execution_annual_contribution.parquet`、`prospective_execution_ledger.parquet`、`execution_policy_definition_v1.json`、`execution_integrity_gates.json`、`execution_pit_audit.json`、`execution_determinism.json`、`state_run_manifest.json`。

代码：`src/stock_selector/research/t3_v6.py`（`RULE_VERSION=execution_policy_v1`）、`scripts/run_t3_v6.py`（断言 HEAD==c312371，全量双跑 518s）、`scripts/t3_v6_gates.py`。
