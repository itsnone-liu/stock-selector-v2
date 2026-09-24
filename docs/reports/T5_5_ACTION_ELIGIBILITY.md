# T5.5 冻结报告：Action Evidence Layer & Action Eligibility

- **基线**：`ebfc490`（T5.4 冻结）
- **输入**：T5.4 current-state / transition / short-path outcome aggregates
- **输出性质**：证据与资格研究，不是交易指令、动作优先级或仓位模型
- **十道 Gate**：10/10 PASS

## 1. 边界与输入冻结

T5.1–T5.4 全部只读。没有修改 C0–C6、operational state、transition、short-path、outcome clock 或 outcome 定义。T5.5 只读取：

- `t5_current_state_outcomes.parquet`
- `t5_transition_outcomes.parquet`
- `t5_short_path_outcomes.parquet`

没有重新扫描 K 线，没有重新拟合状态规则，没有使用 T5.2 的 market-excess。H20 仍未新造。

## 2. 七类 Action Evidence

每个 evidence row 保留 source level、source key、state/source path、segment、support、event count、coverage、censor missing rate、reliability class 和 sparse flag。

| Evidence axis | T5.4 来源字段 | 解释边界 |
|---|---|---|
| Continuation | H5 future new-high rate | 未来路径描述，不等于 ADD |
| Upside opportunity | H5 future peak return | 剩余机会描述，不等于收益承诺 |
| Downside risk | H5 future MDD | 路径风险描述 |
| Failure risk | H5 future lose-ref20 rate | 结构失败描述 |
| Terminal risk | current-state lifecycle P(end≤5) | 生命周期风险；transition/path 缺少直接 terminal 聚合时不补造 |
| Recovery | H3 forward return | 恢复证据，不等于“好状态” |
| Reliability | support/event count/coverage/censor/sparse/split | 证据质量，不是 outcome score |

当前实现使用 H5 作为主要横截面证据窗口，同时保留 T5.4 的 H1/H3/H10 字段在来源产品中。短中期发生冲突时，证据轴不被压成单一分数；同一 row 的多 horizon 差异留在 T5.4 原始映射中供后续审计。

## 3. Reliability 与 sparse 约束

开发段冻结的最低质量参考为：support≥200、event count≥30、coverage≥85%；high reliability 需要 event count≥100 且 coverage≥90%。任何 sparse row 不产生强资格。C2 的 sparse evidence 继续保留，不能因为标签出现而自动获得动作资格。

`coverage = fwd_ret_5d_log_n / n_rows`，censor/missing rate 显式保存。均值不是把不完整窗口填零后的均值。

## 4. Hierarchy / backoff

层级固定为：

```text
short path → transition → current state
```

实际高层级只有在 development 中同时满足 support/context 可用且相对 current 的 H5 return 差异达到预设 practical increment（0.5 percentage point）时，才标记为有开发增量；否则保留 `backoff_reason=no_stable_dev_increment_or_support`。该选择在 development 后冻结，validation/confirmation 不重新调参。

本阶段不把“层级被选中”解释成动作方向。高层级覆盖与回退率都在 `t5_hierarchy_increment.parquet` 留痕。

## 5. 四个独立、多标签 eligibility

四个标签没有优先级，没有仓位含义，可以同时为 true。

### ADD_ELIGIBLE

需要：continuation 与 upside evidence 达到开发段中位参考，且 downside/terminal evidence 未升高，质量条件满足。它不是 `state=C1` 的直接映射。

### HOLD_ELIGIBLE

需要 continuation 或 recovery 的正向证据，同时 downside、failure、terminal 未升高且质量条件满足。它是独立正向定义，不是其他标签全 false 后的剩余桶。

### REDUCE_ELIGIBLE

由 downside、failure、terminal 中至少一项达到开发段高风险参考，且证据质量满足。它不要求 EXIT，也不把 EXIT 当作 REDUCE 的简单升级。

### EXIT_ELIGIBLE

需要独立的 terminal + failure 联合证据、high reliability、非 sparse。缺少 terminal evidence 时不能获得 EXIT。T5.5 不把 C6 硬编码为 EXIT。

任何标签都不转换为 ADD/HOLD/REDUCE/EXIT 的执行优先级，也不转换为仓位百分比。

## 6. 三段稳定性与冲突披露

产物 `t5_eligibility_split_stability.parquet` 保存每个 source level/key 在 development、validation、confirmation 的标签率、support、coverage 和 reliability。三段均存在，coverage 平均约 96.0%。

资格率不是在 aggregate row 上做“显著性竞赛”，必须与 source coverage、event support 和跨段方向一起读。当前结果显示：

- current-state 的 eligibility 率在 validation 与 development/confirmation 存在变化；
- transition/path 的标签覆盖和方向也有变化；
- EXIT 标签稀少，不能据此冻结“某状态必然退出”；
- short-path 在部分风险证据上覆盖较低，不能因为 development 端更强就自动覆盖 transition/current；
- source-level 与 source-key 的 split stability 已保留，明显的 magnitude/coverage 变化必须在后续动作优先级阶段作为不稳定证据处理。

因此 T5.5 冻结的是**资格构造与审计框架**，不是宣布某个状态已经获得永久动作授权。validation/confirmation 不用于反调阈值；冲突保留，不被压成单一 score。

## 7. 关键审计结果

- 极端收益驱动：证据定义使用聚合均值和 support/coverage/reliability，同时保留 event count；本阶段没有用单项显著性直接授权。
- short-path 复杂度：开发段固定 minimum support=200、最多 40 条；实际来源 27 条路径，未暴力枚举全部序列。
- 高层级覆盖：每个 row 均保存 hierarchy_selected 和 backoff_reason，低支持或无稳定增量时回退。
- OBS_UNAVAILABLE / TERMINAL：继承 T5.4 destination 语义，没有改成普通 C-state。
- censoring：有效 n、coverage、missing rate 显式输出。
- sparse：C2 等 sparse evidence 不产生强资格。
- horizon conflict：T5.4 多 horizon 结果保留，不将 H1/H3/H5/H10 冲突强行合并。

## 8. 产品

目录：`output/research/t5/action_eligibility/`

```text
t5_5_evidence_definition.json
t5_action_evidence.parquet
t5_hierarchy_increment.parquet
t5_action_eligibility.parquet
t5_eligibility_split_stability.parquet
t5_5_manifest.json
t5_5_gates.json
```

## 9. 冻结结论

T5.5 完成了：

```text
frozen state / transition / path outcomes
        ↓
seven evidence dimensions + reliability
        ↓
hierarchy increment / backoff evidence
        ↓
independent multi-label eligibility flags
```

本阶段没有完成、也没有尝试完成：

- action priority / conflict resolution
- 仓位比例或加减仓幅度
- T4.6 + T5 联合回测
- 完整生命周期模拟
- `C6 = EXIT` 或任何 state/action 硬映射

这些边界移交 T5.6。T5.6 必须先处理多标签冲突、稳定性崩塌和 sparse/coverage 约束，再讨论动作决策顺序。
