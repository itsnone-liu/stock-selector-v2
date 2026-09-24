# T5.2 冻结报告：路径状态发现（七态候选定义与验证）

- **基线**：62b3feb（T5.1 冻结）+ c6dc354（T5.1 语义勘误）
- **阶段**：T5.2 状态发现（T5 方案阶段顺序第 2 步）
- **范围**：仅定义状态。未实现 ADD/HOLD/REDUCE/EXIT、仓位调整、
  交易回放、T4 初始仓位修改、任何 T5.3–T5.6 逻辑。
- **十道 Gate：10/10 PASS**（`t5_2_gates.json`）

---

## 1. T5.1 语义勘误（先行提交 c6dc354）

按验收裁决写入 manifest+dictionary（不重建数据）：
delta_day=市场交易日推进（停牌不压缩）；row_present=源行存在（非可交易）；
LOAD_EPS=分母有效性守卫（missing + `denominator_below_eps`，禁转 0/1/状态类别）。

## 2. Delta Dependency Audit（硬门禁，先行执行）

`t5_delta_dependency_audit.parquet`（16 数值 primitive × delta 0..40 ×
q10/25/50/75/90，dev 与全样本双口径）。结论：

| 类别 | primitive | 处置 |
|---|---|---|
| 强漂移（累积量） | cum_ret、days_since_peak、new_high_count、max_dd_to_date、dist_to_ref20/60 | **devquant（delta-conditioned）** |
| 平稳 | ret_1/3/5d、efficiency_signed_1/3、efficiency_change_3、turnover_load（δ≥5 后 1.10–1.17 稳定） | 天然锚点/nodrift 引用 |
| 天然结构点 | dist_to_ref20<0（失守）、load≤1（pre20 基准）、ret_3d>0 | anchor |

## 3. 五轴分布与条件证据（dev=2024，56,301 行/3,758 事件）

- **P×E**：高推进+高效率格 dd=2.1%、ret5=+6.0%；低推进+低效率格 dd=8.9%、
  ret5=−5.4%（四格完全分离）。
- **P×V**：负推进下 load>1 格 eff3=−0.0084 vs load≤1 格 −0.0124——
  **"参与增加但推进效率下降"确实存在且可区分**（V4/V5 观察）。
- **pullback×E（单调）**：回撤深度 3%→12%+ 时 eff3 +0.0099→−0.0200、
  收缩率 0.49→0.75、dist_ref20 0.053→0.002。C2/C5/C6 的深度分层有真实结构支撑。

## 4. candidate_state_v1（正式候选）与 v2（敏感性版）

优先级 `C6>C5>C4>C1>C3>C2>C0`（overlap 矩阵见
`t5_state_rule_overlap.parquet`；多命中行 11.7%）：

| code | 语义 | 关键条件（阈值来源） |
|---|---|---|
| C6 | 结构破坏 | dist_to_ref20<0（**anchor**） |
| C5 | 衰减 | eff3<δ-q25 **且** dd≥δ-q75（devquant） |
| C4 | 滞涨 | days_since_peak≥δ-q75 **且** ret5≤δ-q50（devquant） |
| C1 | 强延续 | 21 窗新高（anchor）**且** dd≤δ-q50 **且** cum>0（anchor） |
| C3 | 恢复 | 历史损伤 max_dd≥δ-q75 **且** ret3>0（anchor）**且** repairing（dd<max_dd，frozen） |
| C2 | 健康回调 | dd≥δ-q75 **且** participation_ok（收缩或 load≤1，frozen） |
| C0 | 早期/无主导 | 兜底；reason 区分 early_warmup / warmup_partial_uneval / no_dominant_pattern |

v2 差异：C6 加深回撤分支（dd≥δ-q95）；C4 加推进不足分支（cum≤δ-q25 且 δ≥10）。
**无第三版；无任何阈值扫描**（全部来源四分类登记于 definition JSON）。
v1 全量分布：C0 215k / C6 107k / C1 102k / C5 23k / C4 16k / C3 15k / C2 12k /
STATE_UNAVAILABLE 2,022（仅 adj 缺失；warmup 行按 §十"可判断"边界归 C0 并留 reason）。

## 5. 三段隔离与 purge

- Development 2024（3,758 事件/56,301 行）/ Validation 2025（15,053/239,353）/
  Confirmation 2026（8,611/154,845，**部分年度**：max_delta 覆盖与行均披露于
  split manifest）。
- 40 市场日 purge：**事件级 outcome 使用标志**（`outcome_usable_after_purge`）——
  前段尾部事件（其 H10 outcome 越入后段首 state_date−40 日界）在本段 outcome
  评价中剔除；状态赋值不受影响。段间边界日期从冻结指数日历计算，
  全部写入 `t5_2_split_manifest.json`（机器可审计）。
- 规则生成代码（state_axes/state_assign/run_t5_2_dev/define/assign）经 AST 级
  检查无 outcome import/读取（G2/G4）；outcome 仅在 run_t5_2_validation.py 连接。

## 6. 路径验证（Primary H5/H10；H20 无冻结字段——缺口披露，不新造计算）

结构比率跨三年方向完全一致（**Temporal robustness 成立**）：

| 指标(H5) | dev24 | val25 | conf26 |
|---|---|---|---|
| C1 new_high | 67.6% | 71.1% | 71.9% |
| C5 new_high | 7.0% | 8.2% | 11.9% |
| C6 lose_ref20 | 93.6% | 91.1% | 92.4% |
| C2 lose_ref20 | 18.6% | 10.4% | 17.4% |
| C4 lose_ref20 | 32.7% | 30.6% | 39.5% |

Validation（2025）excess H5 双维 cluster 95% CI（event_id+state_date block
bootstrap 999 次，seed 20260924）：C0 [0.97,1.05]%、C1 [0.80,0.95]%、
C2 [0.60,0.94]%、C3 [−0.12,+0.26]%、C4 [0.82,1.05]%、C5 [0.42,0.68]%、
C6 [0.93,1.02]%。C3/C5 稳定偏低（三年相对排名一致）；**状态价值在路径
机制区分而非收益阶梯**（§十二）：C2 未来 median 收益非最高，但失守率最低
（结构完整+参与收缩语义成立）；C3 短窗最弱但正是"修复未完成"的中间态
（其恢复完成率/转移留 T5.3）。

## 7. 稳定性披露

- one-day churn 38.3%（C1 中位 dwell=1：日频新高布尔抖动是主源）；
  C6 dwell 中位 2、均值 3.4（破坏的持续性最高）。
- **日频原始赋值噪声是已知特征，不是缺陷**：状态平滑/滞留约束按阶段顺序
  留 T5.3 转移建模（本阶段只报告，不修改规则去压 churn——那会构成
  outcome-driven 调参）。

## 8. 最低证据核对（§十三）

- Sample adequacy：最小状态 C2 dev 915 行（915/56,301=1.6%）——
  **低于稳健下限，正式冻结前需在 T5.3 入口复核**；其余各态各段 n>1,800。
- Semantic consistency：见 §6 比率方向（C1/C5/C6/C2/C4 全部与名称语义一致）。
- Future-path distinction：new_high/lose_ref20/MDD 至少一类稳定差异 ✓。
- Temporal robustness：三年方向无翻转 ✓。
- State stability：churn 已披露 ✓。

## 9. 产品清单

`t5_candidate_state_daily.parquet`（492,900×32，v1/v2/final+assignable+
reason+matched+resolution+evidence 12 列+purge 标志）、
`t5_state_definition{,_v1,_v2}.json`（规则/阈值/来源/优先级/missing rule/sha）、
`t5_state_distribution.parquet`（年×δ×E 档×态）、
`t5_state_path_validation.parquet`（三段物理标记）、
`t5_state_rule_overlap.parquet`、`t5_state_churn_audit.parquet`、
`t5_state_cluster_ci.parquet`、`t5_delta_dependency_audit.parquet`、
`t5_axes_dev_{distribution,conditional,pullback_eff}.parquet`、
`t5_2_manifest.json`、`t5_2_gates.json`、`t5_2_split_manifest.json`。

## 10. 冻结结论

七态候选定义 v1 通过三段验证：互斥穷尽（492,900 行恰一态+2,022 显式
UNAVAILABLE）、PIT、阈值来源可审计、跨年方向稳定。
**状态≠动作**：任何 ADD/HOLD/REDUCE/EXIT 映射、与 E-class 的因果解释、
状态平滑——全部留待 T5.3+。C2 的 dev 样本量与 C6 的宽边界
（21.8% 行）作为已知限制移交 T5.3 复核。
