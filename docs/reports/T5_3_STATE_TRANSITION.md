# T5.3 冻结报告：Raw State 转移、终止与 Transition-aware 治理

- **基线**：`af2dac7`（raw_state_v1；链：`62b3feb → c6dc354 → af2dac7`）
- **状态定义**：T5.2 `t5_state_definition.json` 的 C0–C6 只读；本阶段没有重算或修改
- **十道 Gate**：10/10 PASS（`t5_3_gates.json`）
- **范围**：本阶段没有交易动作、仓位或 outcome 选择；市场超额和未来收益没有进入转移/治理/阶数选择

## 1. Raw state conservation 与 edge 产品

`raw_state_t` 永久来自 T5.2 冻结的 `final_candidate_state`，没有被 operational candidate 覆盖。每个 event×delta origin 生成恰好一条 1-day、3-day、5-day edge，共 `492,900 × 3 = 1,478,700` 条。

`dest_type` 只有：

- `STATE`：C0–C6；
- `OBS_UNAVAILABLE`：`STATE_UNAVAILABLE`，不是第八个市场状态；
- `TERMINAL`：带真实 T5.1 `termination_reason` 的 `TERMINAL_LIFECYCLE_END` 或 `TERMINAL_MAX_HORIZON`。

事件末行没有被丢出分母；它显式连接到 terminal。若 t+3/t+5 越过末行，目的地仍是首个真实 terminal reason，而不是 missing。三个 horizon 的逐行矩阵守恒均 PASS。

## 2. Dwell / run-length

所有连续 raw state 段进入 `t5_state_runs.parquet`，并按 segment、E-class 保存分层结果。中位 dwell（development / validation / confirmation）：

| raw state | dev | val | conf | 备注 |
|---|---:|---:|---:|---|
| C0 | 1 | 2 | 1 | 无主导/早期状态较易变化 |
| C1 | 1 | 1 | 1 | 受 20 日新高布尔值闪烁影响 |
| C2 | 1 | 1 | 1 | **sparse evidence，保留，不合并** |
| C3 | 1 | 1 | 1 | 恢复中间态 |
| C4 | 1 | 1 | 1 | 滞涨态 |
| C5 | 1 | 1 | 1 | 衰减态 |
| C6 | 2 | 2 | 2 | 结构破坏持续性最高 |

C2 的 development 规模仍只有 915 行，对应的 transition、dwell、terminal hazard 已完整报告，但不把它提升为独立动作资格；它继续作为 descriptive raw state。

## 3. C6 structural-break terminal audit

以事件真实末日计算剩余 lifecycle 日数，并将 `LIFECYCLE_END` 与 `MAX_HORIZON` 分开。结果如下（全量 origin 行）：

| state | n | P(any terminal next day) | P(LIFECYCLE_END next day) | P(end ≤3d) | P(end ≤5d) | median remaining (LIFECYCLE_END) |
|---|---:|---:|---:|---:|---:|---:|
| C0 | 215,155 | 2.1% | 2.2% | 14.6% | 25.7% | 10 |
| C1 | 101,977 | 0.9% | 0.7% | 6.0% | 12.7% | 13 |
| C2 | 11,812 | 8.9% | 9.5% | 39.1% | 54.0% | 5 |
| C3 | 15,333 | 5.6% | 5.4% | 22.2% | 34.0% | 8 |
| C4 | 16,214 | 8.4% | 9.3% | 37.1% | 52.9% | 5 |
| C5 | 23,174 | 16.4% | 17.6% | 55.4% | 69.7% | 3 |
| C6 | 107,213 | 13.8% | 14.8% | 46.1% | 58.4% | 4 |

**裁定**：C6 不是纯粹的数据尾部伪影，但它确实主要出现在生命周期末段：出现 C6 时，LIFECYCLE_END 中位剩余 4 个市场日；C5 甚至更接近末端（3 日）。C6 定义不回改。该结果只作为后续动作资格的提前量审计，不构成 T5.3 动作结论。

## 4. Churn 的正式拆解

冻结的 `one_day_reversal` 定义是 `S[t-1] = S[t+1]` 且 `S[t] != S[t-1]`。结果：

- `any_daily_change`：38.31%（延续、恶化、恢复等真实转移也包括在内）；
- `one_day_reversal`：10.37%（真正的一日回摆）；
- 最大变化来源是 C0↔C1（方向边合计约 93k）；其次是 C1↔C3、C2↔C3、C5↔C6、C4↔C5；其余不强行命名为 churn。

C1 归因审计是本阶段关键结果：29,300 个 C1 单日 run 中，28,715 个（**98.0%**）的次日 `is_new_high_20d` 关闭。51,096 次 one-day reversal 中，31,001 次（60.7%）伴随该新高布尔值改变。因此 C1 dwell=1 的主因确实是日频新高布尔闪烁，而不是已经证明的未来收益差异。

## 5. Operational candidate（不覆盖 raw state）

仅因上述状态工程证据，构造最多两版 candidate；两版都单独保存 `operational_state_*`，不覆盖 `raw_state_t`。

### candidate_v1：C1 hysteresis + C6 immediate

- raw C1 当日立即成为 operational C1；
- 前一日 operational C1 且今日 raw=C0、仍满足 `drawdown <= delta-q75` 且 `dist_to_ref20 >= 0` 时，保持 operational C1；
- raw C2/C3/C4/C5/C6 立即透传；特别是 raw C6 当日立即成为 operational C6；
- 其他状态无延迟。

结果（仅状态工程指标）：

| 指标 | raw | candidate v1 | candidate v2 |
|---|---:|---:|---:|
| one-day reversal | 10.37% | 3.23% | 3.08% |
| any daily change | 38.31% | 24.71% | 23.84% |
| C1 median dwell | 1 | 5 | 5 |
| C1 rows | 101,977 | 235,290 | 239,435 |

C1 行数上升是 deliberate hold 的代价，必须显式披露：v1 的 operational C1 语义是“最近已确认强延续且结构仍完整”，不再等同于当天重新触发新高。它不是 raw C1 的改写。

### candidate_v2：v1 + C5 two-day confirmation

v2 仅额外要求连续两日 raw C5 才确认 C5，作为 confirmation 对照。它只比 v1 额外降低约 0.4 个百分点 reversal，却引入至少 1 日 C5 recognition delay。按“风险状态应及时生效”的状态工程标准，**不选 v2 为正式 operational candidate**；C6 两版均零延迟。T5.4 前不得把 v1 当作动作资格证明。

v1 的截断重放只读取当前和过去证据，120 个随机事件、两个截断点 G6=0 mismatch；没有 centered smoothing，也没有用 t+1 或 future outcome。

## 6. First-order vs second-order Markov

训练只使用 development 2024，validation/confirmation 不 refit。二阶模型对 development 未见 context 自动回退一阶；2025 未见 context 比例为 0%，development 有 50 个二阶 context。

| segment | model | n | multiclass Brier | top-1 |
|---|---|---:|---:|---:|
| validation | first-order | 279,871 | 0.5393 | 60.17% |
| validation | second-order + first-order backoff | 279,871 | **0.5262** | **60.67%** |
| confirmation | first-order | 133,064 | 0.5634 | 57.55% |
| confirmation | second-order + backoff | 133,064 | **0.5534** | 57.01% |

二阶 Brier 在 2025 和 2026 方向一致改善；confirmation top-1 轻微下降，已披露，不用单一指标粉饰。context 分解显示：validation 有 52 contexts，其中 41 个改善、8 个变差，25 个 context 各自样本不少于 1,000；最大单一 context 仅占总 Brier 改善约 29.8%。confirmation 最大 context 占约 7.4%。因此改善不是来自极少数 context，稀疏条件可接受。

**Markov 裁定**：四项条件（2025 Brier 改善、2026 方向一致、改善非少数 context、sparse context 可接受）满足，T5.3 transition model 采用二阶 + 一阶 backoff。它描述“当前状态从哪里来”对下一状态分布的增量信息，不是收益等级化。

## 7. E-class 与边界

transition matrix 同时生成 E-class 条件层，用于描述初始 exposure class 与状态动力学的关系；E-class 没有进入 raw 或 operational state 定义。市场背景只保留 robustness 分层。sector 未混入。T5.2 market-excess 的停牌/日历时钟差异本阶段完全不使用；统一 outcome clock 留在 T5.4 之前单独冻结。

## 8. 产品与 Gate

产物位于 `output/research/t5/transition/`：

- `t5_transition_edges.parquet`
- `t5_transition_matrix_1d.parquet` / `_3d.parquet` / `_5d.parquet`
- `t5_transition_by_eclass.parquet`
- `t5_state_runs.parquet`、`t5_dwell_by_eclass.parquet`
- `t5_churn_audit.parquet`
- `t5_terminal_hazard.parquet`
- `t5_markov_order_audit.parquet`
- `t5_operational_state_daily_v1.parquet` / `_v2.parquet`
- `t5_operational_state_definition.json`
- `t5_3_manifest.json`、`t5_3_gates.json`

十道 Gate：Input Freeze、Raw Conservation、Edge Conservation、Temporal Order、Unavailable/Terminal Separation、Churn PIT、Outcome Isolation、Markov Validation、Sparse/Stability、Determinism 均 PASS。

## 9. 冻结结论

1. raw_state_v1 C0–C6 永久保留，未被 transition 或 operational candidate 覆盖；C2 保留并标记 sparse。
2. C6 是接近生命周期终止的结构风险状态，但不回改定义；C6→terminal 的提前量留给 T5.4 资格审计。
3. 38.3% 全变化率拆为 10.4% 一日回摆与大量真实状态演化；C1 单日抖动 98% 由新高布尔闪烁解释。
4. v1 hysteresis 是 outcome-free、PIT、C6 immediate 的候选；v2 的 C5 延迟没有足够状态工程收益，因此不选。
5. 二阶 Markov + 一阶 backoff 通过开发/验证/确认方向与稀疏审计，作为状态动态描述模型冻结；不代表交易动作或未来收益等级。
6. 所有动作资格、统一 outcome clock、仓位和成交仍明确留在 T5.4+。
