# T5.6A 冻结报告：Eligibility Conflict Census

- **基线**：`aac1f9f`（T5.5；链：`62b3feb → c6dc354 → af2dac7 → a33c9b5 → ebfc490 → aac1f9f`）
- **性质**：纯描述性 census。本阶段没有做任何 resolution；`ADD+HOLD→ADD`、`REDUCE+EXIT→EXIT`、`0000→HOLD` 一律未发生。
- **输入**（只读）：`t5_action_eligibility.parquet`、`t5_action_evidence.parquet`、`t5_hierarchy_increment.parquet`

## 1. 总体分布：16 种组合只有 6 种实际出现

T5.5 的 303 个 aggregate rows（按日加权 1,344,301 行）：

| vector | 含义 | 聚合行数 | 聚合占比 | **日加权占比** | sparse率 |
|---|---|---:|---:|---:|---:|
| `1100` | ADD+HOLD | 59 | 19.5% | **58.3%** | 0% |
| `0010` | 仅 REDUCE | 85 | 28.1% | 20.4% | 0% |
| `0100` | 仅 HOLD | 38 | 12.5% | 8.5% | 0% |
| `1010` | ADD+REDUCE | 15 | 5.0% | 5.9% | 0% |
| `0011` | REDUCE+EXIT | 2 | 0.7% | 3.5% | 0% |
| `0000` | 无标签 | 104 | 34.3% | **3.3%** | **71.2%** |

- 单标签率 40.6%、多标签率 25.1%、0000 率 34.3%（聚合行口径）；日加权后多标签（含 1100）约 67.7%。
- `1100` 是绝对主流路径：**Opportunity Reinforcement**，且三个 split 加权占比 41–62% 均为第一。

## 2. `0000` 的机制是证据不足，不是市场状态

- 所有 low-reliability 行 100% 落在 `0000`；
- `0000` 行 71.2% 带 sparse 标记，聚合占比高但日加权只有 3.3%；
- 其中约半数（52%）实际是 high reliability——这部分是真实"无主导证据"的市场日（多在 transition 拆分层）。

结论：no-evidence 主要由 support/coverage 门槛过滤产生，T5.6B 应优先做 evidence insufficiency 披露，而不是强行提高 resolution coverage。0000 不能转 HOLD。

## 3. 分段稳定性（日加权 share）

| vector | dev | val | conf | 备注 |
|---|---:|---:|---:|---|
| `1100` | 41.2% | 61.7% | 58.0% | 三段主流，方向稳定 |
| `0010` | 27.8% | 17.7% | 23.2% | 稳定第二大类 |
| `0100` | 15.5% | 8.7% | 5.4% | dev→conf 递减，需在 T5.6C 关注 |
| `0011` | 9.5% | **0.0%** | 8.4% | validation 段消失（EXIT 仅 2 个 source key，脆弱）|
| `1010` | 1.1% | 8.9% | 1.5% | validation 段异常升高，不稳定冲突 |
| `0000` | 4.9% | 3.0% | 3.5% | 稳定低位 |

结构漂移主要来自 reliability 门槛效应（dev 事件支持少，none 聚合占比 45.5% vs val 24.8%）。

## 4. 分层要点

- **source level**：current 层 `1100` 占比最高（41.7%）；transition 层 `0000` 最多（48%——拆分后支持不足）；short_path 层 `0010` 最多（53.1%）。
- **reliability**：high/medium 中 `1100`+`0010` 合计约 57%；low 全部是 `0000`。
- **destination 类型**：OBS_UNAVAILABLE/TERMINAL 只作为 transition source-key 中的显式类别进入 census，未被当作普通 C-state。

## 5. T5.6B 复杂度结论（建议）

Census 结果支持**简单 ontology，不建 16-vector 全表**：

1. **`1100`（约 58% 日权重）不是对立冲突**：T5.5 语义中 ADD 的证据条件（continuation+upside+风险未升）是 HOLD 条件（continuation/recovery+风险未升）的近似超集——同时成立是包含关系（Opportunity Reinforcement）。T5.6B 可用纯证据语义解析为 ADD，无需 outcome。
2. **`1010`（约 5.9%）是真正的 Opportunity–Risk Conflict**，且 split 间不稳定（dev 1.1% vs val 8.9%）——应保留 CONFLICT 状态进入 T5.7，而不是强行解析。
3. **`0011`（约 3.5%）是 Risk Escalation**：EXIT 本身在 T5.5 已是独立联合证据（terminal+failure+high reliability），可按 EXIT 独立性解析，但 validation 段为零暴露其脆弱性，须披露。
4. **`0000`（3.3%）保持 NO_ACTION_EVIDENCE**，主因 evidence insufficiency（sparse/低支持），优先披露而非 resolution。
5. **`0100` 递减趋势**（15.5%→5.4%）提示 HOLD 单标签在后期样本中被 `1100` 吸收，T5.6C 须验证解析规则使用率的 split 稳定性。

## 6. 产品

`output/research/t5/action_resolution/`：

- `t5_6a_conflict_census.parquet`（16-vector 主表，实际 6 行）
- `t5_6a_vector_by_split.parquet`
- `t5_6a_vector_by_source_level.parquet`
- `t5_6a_vector_by_reliability.parquet`
- `t5_6a_manifest.json`

代码：`scripts/run_t5_6a_conflict_census.py`

## 7. 边界确认

- 没有修改 T5.5 eligibility/threshold/hierarchy；
- 没有读取未来 outcome；
- 没有做任何 resolution（含隐式）；
- unresolved/CONFLICT 被视为合法长期状态。

T5.6B 等正式开工令。
