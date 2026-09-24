# T5.6B/C 冻结报告：Conflict Ontology、Resolution Rules 与稳定性

- **基线**：`c4a3056`（T5.6A；链：`62b3feb → c6dc354 → af2dac7 → a33c9b5 → ebfc490 → aac1f9f → c4a3056`）
- **输入只读**：T5.5 eligibility/evidence/hierarchy、T5.6A census
- **十道 Gate**：10/10 PASS（`t5_6_gates.json`）

## 1. 0011 语义包含审计（先行，决定 R4 分支）

对照 T5.5 冻结定义的纯逻辑审计：

```text
EXIT_ELIGIBLE  = terminal_positive & failure_positive
                 & reliability=='high' & ~sparse
REDUCE_ELIGIBLE = (downside|failure|terminal)_positive & reliable
```

- EXIT 的 `terminal_positive & failure_positive` **结构性蕴含** REDUCE 的三选一析取；
- `high` ⊂ `reliable`（reliable=high|medium 且均含 ~sparse）。

**结论**：`EXIT_ELIGIBLE ⇒ REDUCE_ELIGIBLE` 是定义级严格蕴含。0011 中 EXIT 自身已独立达到退出资格，REDUCE 是同一风险恶化结构下的较弱共存资格——解析为 `RESOLVED_EXIT` 依据的是包含关系，**不是**"更激进优先"。

同时保留 FRAGILE 标注：0011 全量仅 1 个 source key 有效覆盖、validation 段加权 0 行。

## 2. Resolution rules（R1–R5 + 防御）

| 规则 | vector | 解析 | 依据 |
|---|---|---|---|
| R1 | `0010` | RESOLVED_REDUCE | DIRECT_ACTION，无冲突 |
| R1 | `0100` | RESOLVED_HOLD | DIRECT_ACTION |
| R2 | `1100` | RESOLVED_ADD | SEMANTIC_REINFORCEMENT：ADD 条件在 continuation/upside/风险三轴上包含继续持有的依据并额外要求新增风险所需证据——是 evidence reinforcement 而非动作优先级 |
| R3 | `1010` | CONFLICT_OPPORTUNITY_RISK | 不解析；分布不稳定（dev 1.1%/val 8.9%/conf 1.5%），强行解析会把 validation 局部结构写进规则 |
| R4 | `0011` | RESOLVED_EXIT | TERMINAL_RISK_RESOLUTION（§1 审计）+ FRAGILE 标注 |
| R5 | `0000` | NO_ACTION_EVIDENCE | 多原因分类，永不转 HOLD |
| 防御 | 其余 10 vector | UNRESOLVED_UNSEEN_VECTOR | 当前样本未出现；禁止默认优先级/自动 HOLD，保证未来数据扩展不静默产生错误动作 |

0000 原因分类（可并存）：LOW_RELIABILITY / SPARSE_EVIDENCE / INSUFFICIENT_SUPPORT / CENSOR_LIMITED / COVERAGE_LIMITED / OTHER_INSUFFICIENT。

## 3. 最终解析覆盖（日加权）

| 状态 | 加权占比 |
|---|---:|
| RESOLVED_ADD | 58.32% |
| RESOLVED_REDUCE | 20.40% |
| RESOLVED_HOLD | 8.54% |
| RESOLVED_EXIT | 3.47% |
| **RESOLVED 合计** | **90.75%** |
| CONFLICT_OPPORTUNITY_RISK | 5.93% |
| NO_ACTION_EVIDENCE | 3.34% |

与 T5.6A census 的算术预期（≈90.8/5.9/3.3）精确一致——resolution 没有引入任何覆盖漂移。

## 4. T5.6C 五项稳定性检查

**① 解析覆盖**：见 §3；三段合计闭合 100%。

**② resolved action mix**（dev/val/conf 加权）：

| 状态 | dev | val | conf | 判定 |
|---|---:|---:|---:|---|
| RESOLVED_ADD | 41.2% | 61.7% | 58.0% | 主流稳定 |
| RESOLVED_REDUCE | 27.8% | 17.7% | 23.2% | 稳定第二 |
| RESOLVED_HOLD | 15.5% | 8.7% | 5.4% | 递减=上游 eligibility composition drift（0100 被更多日进入 1100），规则未变——记录为 population drift，非 T5.6 失败 |
| RESOLVED_EXIT | 9.5% | **0.0%** | 8.4% | 见 ④ |

**③ 1010 异常完整保留**：val 8.9% vs dev 1.1%/conf 1.5% 原样进入 CONFLICT_OPPORTUNITY_RISK，未做任何平滑或处理。

**④ 0011 脆弱性单独报告**：source key=1、validation 加权 0 行、exit_fragile=True。语义上可解析，统计支持脆弱——两者同时成立且都已披露。

**⑤ 0000 机制稳定性**：三段原因构成一致——INSUFFICIENT_SUPPORT/SPARSE（全部并存）+ LOW_RELIABILITY 为主体，OTHER_INSUFFICIENT（真实无主导证据日）为最大单项。低 reliability→0000、sparse→0000 的机制在三段均保持。

## 5. 产品

`output/research/t5/action_resolution/`：

- `t5_6a_conflict_census.parquet`（+by_split/by_source_level/by_reliability + manifest）
- `t5_6b_resolution.parquet`（303 行 resolution：status/rule/原因/fragile/basis 全字段）
- `t5_6c_stability.json`
- `t5_6_gates.json`

代码：`scripts/run_t5_6b_resolution.py`、`scripts/gate_t5_6.py`

## 6. 冻结状态集（移交 T5.7 的输入契约）

```text
RESOLVED_ADD / RESOLVED_HOLD / RESOLVED_REDUCE / RESOLVED_EXIT
CONFLICT_OPPORTUNITY_RISK
NO_ACTION_EVIDENCE
UNRESOLVED_UNSEEN_VECTOR
```

T5.7 必须原生支持 CONFLICT_OPPORTUNITY_RISK 与 NO_ACTION_EVIDENCE——前者是"机会与风险同时成立"的合法持仓日（约 5.9%），后者是"模型不知道该改变什么"（约 3.3%），都不是需要消灭的异常。动作优先级、仓位比例、暴露调整全部留 T5.7。
