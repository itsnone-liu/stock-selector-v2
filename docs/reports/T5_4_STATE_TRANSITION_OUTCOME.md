# T5.4 冻结报告：State / Transition → Outcome Mapping

- **基线**：`a33c9b5`（T5.3；链：`62b3feb → c6dc354 → af2dac7 → a33c9b5`）
- **目标**：描述当前状态、状态转移和受控短路径对应的未来结果分布；不修改 C0–C6，不定义仓位比例，不定义交易动作。
- **十道 Gate**：10/10 PASS（`output/research/t5/outcome_mapping/t5_4_gates.json`）

## 1. Outcome clock 冻结

本阶段统一采用 T5.1 已冻结的个股 outcome clock：从 origin 收盘后开始，按该股票后续有效复权价格观测计数，窗口为 H1/H3/H5/H10。停牌不被当作零收益；窗口不完整时保留缺失和 `complete_h=False`，不进入对应均值分母。

T5.2 的市场超额没有进入本阶段：个股窗口按有效观测日、市场窗口按日历日，存在时钟差异。因此本阶段不使用 market-excess 做状态、转移或路径选择。统一的 outcome clock 已写入 `t5_4_outcome_clock.json`；市场超额资格证据留待后续统一口径后再研究。

结果表仍保留 T5.1 outcome 的全部可用字段：forward return、peak/MDD、new-high、lose-ref20、complete 和 n_obs。T5.1 没有 H20 冻结字段，本阶段没有新造 H20。

## 2. Current state baseline

`t5_current_state_outcomes.parquet` 同时报告：

- raw `C0–C6`；
- T5.3 outcome-free operational candidate v1；
- development / validation / confirmation；
- n_rows、n_events、每个指标有效样本数和 H5 event-block bootstrap 95% CI。

这一步是 baseline，不把“某个状态最好”作为结论。尤其 C2 继续保留并按 sparse evidence 解读，不能因为样本小而删除或合并。

## 3. Transition outcome

`t5_transition_outcomes.parquet` 将 T5.3 的 primary 1-day edge 与 outcome 在同一 origin 对齐，按：

- `origin raw_state → dest_type/dest_label`；
- operational origin → `dest_type/dest_label`；
- development / validation / confirmation

报告 H1/H3/H5/H10 return、peak、MDD、new-high、lose-ref20 及其有效 n。`STATE_UNAVAILABLE` 保持 `OBS_UNAVAILABLE`，terminal 保持 `TERMINAL_LIFECYCLE_END` / `TERMINAL_MAX_HORIZON`，没有重新归一到 C0–C6。

因此可以直接比较同一目的状态的不同来源路径，例如：进入 C4 之前来自 C3 还是 C5；进入 C5 之前来自 C4 还是其他状态。此处只描述 outcome 分布，不写“好状态/坏状态”的等级化结论，也不生成 ADD/HOLD/REDUCE/EXIT 或仓位。

## 4. Controlled short paths

为避免暴力枚举，短路径发现完全在 development 段进行，使用固定、outcome-free 的约束：

- operational v1 的连续三日状态路径；
- minimum support = 200 origin rows；
- 最多保留 40 条，按 development support 排序并以固定字典序打破并列；
- 没有读取任何 future return、MDD、new-high 或 recovery 字段来选择路径。

本次选出 27 条三状态路径，写入 `t5_short_path_definition.parquet`；随后才在三个时间段分别评价其未来 H1/H3/H5/H10 结果，写入 `t5_short_path_outcomes.parquet`。这不是对所有序列的 outcome-driven threshold search。路径是否值得进入后续动作研究，必须同时考虑 support、跨段覆盖、风险/收益分布和 outcome clock；本阶段不作动作裁定。

## 5. 生命周期结果

`t5_current_state_lifecycle.parquet` 按 current raw state 和三段报告：

- P(event terminal within 1/3/5 market observations)；
- lifecycle-end 条件下 median remaining lifecycle days；
- n_rows / n_events。

它继承 T5.3 的 terminal reason 分离，不把 MAX_HORIZON 当成真实生命周期结束。C6 的 T5.3 结论仍有效：它是接近生命周期尾部的结构状态，但定义不回改；本阶段只是把该风险与未来 outcome 对齐，不把它直接变成动作规则。

## 6. 隔离与不确定性

- raw state 直接读取 T5.2 冻结的 `final_candidate_state`，没有重新赋值；
- operational state 单独列出，未覆盖 raw state；
- development / validation / confirmation 沿用 T5.2/T5.3 事件级隔离；
- aggregate 表保留 `n_rows`、`n_events`、每个 outcome 的有效 n；
- H5 return CI 使用 event block bootstrap（199 draws，固定 seed），不报告只适用于 IID 的参数 p-value；
- transition/path 发现不读取 outcome；outcome 只在映射完成后连接；
- market-excess 时钟差异不被隐藏，统一 outcome clock 前不作为资格证据。

## 7. 产品清单

位于 `output/research/t5/outcome_mapping/`：

- `t5_4_outcome_clock.json`
- `t5_current_state_outcomes.parquet`
- `t5_current_state_lifecycle.parquet`
- `t5_transition_outcomes.parquet`
- `t5_short_path_definition.parquet`
- `t5_short_path_outcomes.parquet`
- `t5_4_manifest.json`
- `t5_4_gates.json`

代码：

- `scripts/run_t5_4_outcome_mapping.py`
- `scripts/gate_t5_4.py`

## 8. 冻结结论与边界

T5.4 完成了从“状态/路径动态”到“未来结果分布”的描述性映射：

1. current raw state 提供 baseline；
2. operational state 用于对照，但不改变 raw state；
3. transition outcome 保留 destination 类型和来源路径；
4. 受控短路径在 development discovery 后跨段评价；
5. future outcome 没有反向污染状态、转移模型或路径发现。

这仍不是动作层。后续若进入动作资格研究，必须先把 outcome clock、删失和依赖结构正式冻结，再讨论 action class；不能把本阶段任何单一状态、转移或路径直接翻译成仓位百分比。
