# T5.7 冻结报告：Exposure Adjustment Mapping

- **基线**：`ad7fd2c`（T5.6；链：`62b3feb → c6dc354 → af2dac7 → a33c9b5 → ebfc490 → aac1f9f → c4a3056 → ad7fd2c`）
- **十道 Gate**：10/10 PASS（`t5_7_gates.json`）
- **性质**：执行结构研究，无 P&L、无参数选择、无策略排名

## 1. T5.7A Exposure Contract

```text
x_t = actual_exposure_t / base_risk_budget,  0 ≤ x_t ≤ 1
base_risk_budget = T4.6 initial_exposure_weight（P0=0 / P1=0.25 / P2=0.5 / P3=1.0）
x_0 = 1.0（契约假设：预算自 T0 全额可用；分批成交属 T5.8 联合模拟）
```

- T4 职责：这笔交易最多愿意承担多少风险；T5 职责：生命周期中现在使用预算的多少。
- **P0（5,747 事件，base=0）**：`ZERO_BUDGET` 轨迹（x 恒 0），排除在 operator 统计之外，单独披露。
- **x_0=1 契约的显式后果**：首次 REDUCE 之前的 ADD 全部落入 `ADD_AT_CAP`——诊断中约 21–33% 的 at-cap 率部分源于此假设，属结构披露而非市场信息；真实入场敞口的 x_0 留给 T5.8。

## 2. T5.7B 六类 Exposure Operator（全部冻结）

| Resolution state | 算子 | x_after | reason_code |
|---|---|---|---|
| RESOLVED_ADD | 向 cap 增加 | `x + a(1-x)` | ADD_TOWARD_CAP / **ADD_AT_CAP**（仍是 ADD 决策） |
| RESOLVED_HOLD | 恒等 | `x` | HOLD_IDENTITY |
| RESOLVED_REDUCE | 乘法缩减 | `r·x`，`0<r<1`，单次永不为零 | REDUCE_RETAIN_FRACTION |
| RESOLVED_EXIT | **唯一归零** | `0` | EXIT_EXACT_ZERO，此后 `POST_EXIT_LOCKED` 至 episode 结束 |
| CONFLICT_OPPORTUNITY_RISK | preserve | `x` | **PRESERVE_EXPOSURE_UNDER_CONFLICT** |
| NO_ACTION_EVIDENCE | preserve | `x` | **PRESERVE_EXPOSURE_NO_EVIDENCE** |
| UNRESOLVED_UNSEEN_VECTOR | preserve | `x` | PRESERVE_EXPOSURE_UNSEEN_VECTOR |

三种"数值不变"决策语义严格分离；terminal 行 `EPISODE_TERMINAL_NOT_TRADED`、exposure_after=NA，**不自动清仓**——terminal 液化/删失语义留 T5.8。

**EXIT 锁定**：一旦 RESOLVED_EXIT，暴露锁定 0 至生命周期结束（不研究生命周期内 re-entry）。已作为 invariant 写入 contract。

## 3. Policy family（事前固定，非优化）

T4.6 无动态调整 tranche 可复用（仅初始 weight cap），故冻结：

| Policy | ADD（headroom 份额 a） | REDUCE（保留比例 r） |
|---|---|---|
| P1_conservative | 1/3 | 2/3 |
| P2_balanced | 1/2 | 1/2 |
| P3_decisive | 2/3 | 1/3 |

三者是事前定义的风险响应强度；**T5.7 未依据任何未来收益删除或排序**，选择权在 T5.8。

## 4. Trajectory replay（无 P&L）

1,478,700 行 = 492,900 生命周期日 × 3 policy。operable（base>0 且非 terminal）日 1,126,077。

逐日 effective resolution 按 T5.5 冻结层级回退：short_path（选中时）→ transition（选中时）→ current。

**状态分布（operable 日）**：RESOLVED 89.96%（ADD 619,674 / REDUCE 324,237 / HOLD 59,109 / EXIT 10,041）+ POST_EXIT_LOCKED 14,340；CONFLICT preserve 3.05%；NO_ACTION preserve 5.71%。

口径披露：T5.6 的 90.75/5.93/3.34 是聚合行 n_rows 加权；T5.7 的 89.96/3.05/5.71 是逐日 hierarchy 回退后的分布——逐日回退使部分日落入更低层级的 0000 行，NO_ACTION 份额因此升高。两者都是正确的，口径不同。

## 5. Split diagnostics（结构，非收益）

- **mean exposure** P1 > P2 > P3（保守保留更多）：conf 段 0.663 / 0.622 / 0.596。
- **at-cap 率** 27–33%，三 policy 几乎相同（ADD 触达 cap 的天数集合由 resolution 序列决定，非 policy 强度）。
- **接近零未 EXIT**（x∈(0,0.05)）随激进度上升：P1 dev 4.6% → P3 dev 24.6%——乘法衰减的数学结果；它们仍不是 EXIT（G6 保证只有 EXIT 精确归零），但 T5.8 须决定 near-zero 的执行含义（是否可交易、是否视同退出）。
- **REDUCE 次数**三 policy 相同（332,597/59,770/15,050 每段 ×policy），turnover 由 resolution 序列驱动。
- **POST_EXIT_LOCKED**：conf 4,657 / dev 123 / val 0——继承 0011 的 split 脆弱性。
- **CONFLICT/NO_ACTION preserve** 日数三段稳定存在（3,191/1,095/7,164 与 5,667/3,331/12,444 每段）。

## 6. Invariants（G5/G6/G7 硬验证）

```text
ADD: x' ≥ x（含 AT_CAP 恒等）      REDUCE: 0 < x' < x（严格递减）
HOLD: x' == x                       EXIT:  x' == 0（唯一 action 归零）
preserve 三类: x' == x 且 reason_code 互不相同、绝不改写为 HOLD
全轨迹: 0 ≤ x ≤ 1；无 (lifecycle, day, policy) 重复键
```

实现修正记录：① 首版 REDUCE 的 `max(x·r, 1e-12)` clamp 在 x 极小时锁死递减（130 行违例）——乘法本身严格为正，已移除；② gate 的"精确零"检查由 `np.isclose`（atol=1e-8，把 r³⁰≈5e-15 误判为零）改为严格 `==0.0`；③ preserve 语义码曾误填 T5.6 rule 名，已分列为 `reason_code`（operator 层语义）与 `source_resolution_rule`（T5.6 追溯）。

## 7. 产品

`output/research/t5/exposure_adjustment/`：contract / operator_definition / policy_family / trajectory（1.48M 行）/ operator_usage / split_diagnostics / manifest / gates。

## 8. T5.7 不做（移交 T5.8）

收益回测、策略排名、成本、Sharpe/回撤、policy 选择、terminal 清仓规则、re-entry 语义、真实入场分批 x_0。

```text
T4.6 Initial Exposure → T5.6 Resolution State → T5.7 Exposure Operator → Target Exposure Trajectory ✓
```
