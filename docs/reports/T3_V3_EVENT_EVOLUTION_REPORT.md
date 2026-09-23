# T3 V3 事件内状态演化报告

- 基线：`a7cfbb9`（T3 V2 正式冻结）
- 状态：**V3 轨迹事实层 PASS**
- 研究边界：只建立截至 tau 的轨迹事实，不按未来结果分组，不训练模型、不做 IC/显著性/阈值优化、不形成交易规则。

## 1. 交付范围

以冻结的 27,422 个 lifecycle20 事件为唯一事件宇宙，按 V2 上证市场交易日历生成完整 `tau=0..40` 面板。tau 是市场日序，不是个股有效成交观测序号；个股停牌、无行、无量或无复权因子时，tau 继续推进，字段保持 missing，不 forward-fill、不压缩。

| 产物 | 行数 | 语义 |
|---|---:|---|
| `event_path_daily.parquet` | 1,124,302 = 27,422×41 | 唯一 as-of-tau 日级轨迹事实层 |
| `event_path_checkpoints.parquet` | 164,532 = 27,422×6 | 从 daily 筛选 tau=0/1/5/10/20/40，不另算 |
| `event_path_summary.parquet` | 27,422 | 从 daily 派生的回顾性完整观察窗摘要，不作为 tau 时点输入 |
| `trajectory_field_coverage.csv` | 48 个字段 | 每字段 valid/missing/coverage |
| `trajectory_pit_audit.json` | — | 多 tau 物理截断证据 |
| `trajectory_integrity_gates.json` | — | 五 Gate 证据 |
| `trajectory_determinism_check.json` | — | 双跑 hash 证据 |

V3 构建脚本未导入、未 join `event_labels`，因此没有使用 y5/y10/y20/y40、winner、successful_breakout 等未来结果标签。

## 2. Primary primitives

### 2.1 价格状态

daily 保存：`close_rel_t0_log`、`mkt_excess_rel_t0_log`、`distance_to_ref20`、`distance_to_ref60`、`running_peak_return`、`drawdown_from_running_peak`、`max_drawdown_to_tau`、`new_high_count_to_tau`、`days_above_t0_to_tau`、`peak_tau`、`days_since_running_peak`。

ref20 沿用 lifecycle 原始突破位置（未复权原始 close 前 20 日高）；ref60 沿用 V2 A1 的 60 个有效复权观测参考位。两者没有被重新定义，也没有改变生命周期事件宇宙。

### 2.2 量能、换手与成本

固定使用 T0 之前的 20 个量有效历史观测作为 `volume_ratio_pre20`、`amount_ratio_pre20`、`turnover_ratio_pre20` 的基准；基准不随 tau 重置。另保存 `cum_turnover_since_t0`、`mean_turnover_since_t0`、`volume_peak_ratio_to_tau`、`turnover_peak_ratio_to_tau`。

事件锚定 VWAP `anchored_vwap_t0_to_tau` 从 T0 开始；rolling VWAP 5/10/20 保持 V2 的历史滚动窗语义，并逐 tau 记录有效观测数。两者物理分列，不使用人为成本带。

### 2.3 原子状态事实

daily 保存 `below_t0_close`、`below_ref20`、`below_ref60`、`new_post_breakout_high`、`drawdown_from_peak`、`recovered_previous_peak`；summary 另保存这些事实的首次 tau。既有 lifecycle annotation 没有被重新运行或用来重构轨迹状态机。

## 3. 五道核心 Gate

| Gate | 结果 | 证据 |
|---|---|---|
| Calendar Gate | **PASS** | 1,124,302 行；每事件恰好 41 行；tau 严格为 0..40 |
| T0 Anchor Gate | **PASS** | 82,266 项与 V2 A1/B1/chip 重叠字段检查，浮点容差 1e-12，0 mismatch |
| Path PIT Gate | **PASS** | 51 个事件×tau 组合，覆盖 tau=0/1/5/10/20/40；物理截断 0 mismatch |
| Path Invariant Gate | **PASS** | running peak、累计新高、累计高于 T0 日数、最大回撤等 0 个违反 |
| Missing/Censor Gate | **PASS** | 16,955 个日历内个股无行被保留；无 forward-fill/zero-fill；source_date 因果约束 PASS |
| Determinism | **PASS** | 3 个轨迹产品双跑 hash 完全一致 |

PIT 抽样包含普通事件、adj_factor_missing 事件、sample_end 事件、换手缺失候选以及不同星期的 T0。对于每个抽样事件，先将单股数据物理截断到 T+tau，再重建该 tau 行与全量构建结果比较。

## 4. 字段级事实覆盖快照

全 daily 面板共 1,124,302 行。部分字段的全体分布快照如下；这些数字是覆盖与轨迹形态描述，不是成功/失败比较：

| 字段 | valid | median | q25 | q75 |
|---|---:|---:|---:|---:|
| `close_rel_t0_log` | 1,102,771 | -0.00409 | -0.07843 | 0.06117 |
| `mkt_excess_rel_t0_log` | 1,102,771 | -0.01351 | -0.08372 | 0.04679 |
| `drawdown_from_running_peak` | 1,102,771 | 0.06665 | 0.01775 | 0.14403 |
| `max_drawdown_to_tau` | 1,119,710 | 0.10854 | 0.05475 | 0.18706 |
| `cum_turnover_since_t0` | 1,124,302 | 68.23455 | 28.95553 | 140.68230 |
| `anchored_vwap_t0_to_tau` | 1,113,270 | 16.70626 | 8.74623 | 32.51422 |

这些 quantile 仅描述全体可用轨迹字段的数值分布；本阶段没有按照未来收益、生命周期结果或 ref60 状态拆组解释。

## 5. 明确禁止事项检查

- 没有按 y40/y20 或任何未来标签筛选事件。
- 没有创建 winner/loser、successful/failed breakout、top-return 标签。
- 没有训练回归/分类模型，没有 IC、feature importance 或显著性检验。
- 没有优化阈值、创建健康量能评分或交易规则。
- 没有修改 lifecycle20、ref60 或 V2 字段。
- daily 与 summary 物理分离；checkpoints 由 daily 筛选派生。

## 6. 进入 V4 的边界

V3 交付的是可复算的“突破后资金行为电影”事实层。V4 才可以在 tau=5/10/20 的存活条件下建立动态 risk set，并比较当时可见状态与后续路径。V3 本身不做这种条件比较；本报告不把任何轨迹形态解释为好坏或 alpha。
