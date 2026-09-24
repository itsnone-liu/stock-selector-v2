# T4.2 — T0 State Table（T0 时点横截面状态表）

**阶段**：T4.2（状态特征层冻结；不做特征有效性筛选、不碰未来路径）
**基线**：T4.1 @ `ca5e2a8`（HEAD 断言一致）
**开工令**：T4.2 十一章正式开工令

---

## 1. 交付物（output/research/t4/t0_state/）

| 产物 | 内容 |
|---|---|
| `t4_t0_state.parquet` | **PIT 主表**：27,422 行 × 44 列，1 行/事件 |
| `t4_t0_sector_retrospective.parquet` | **行业背景物理分离表**：27,422 行 × 9 列，`pit_eligible=false` 全量标注 |
| `t4_t0_feature_dictionary.csv` | 49 字段机器可读 metadata（family/source/window/max_source_date_rule/pit_eligible/unit/missing_semantics） |
| `t4_t0_field_coverage.csv` | 逐字段 n_valid/n_missing/coverage/missing_reason |
| `t4_t0_reconciliation.json` / `t4_t0_pit_audit.json` / `t4_t0_manifest.json` / `t4_t0_gate_report.json` / `t4_2_determinism.json` | 对账 / PIT 审计 / 血缘 / 六道 Gate / 双跑 |

代码：`src/t4/features/build_t0.py`、`scripts/run_t4_2.py`、`scripts/t4_2_gates.py`。`feature_definition_version=t4_t0_state_v1`。

## 2. 字段族构成（全部 max_source_date ≤ T0）

- **A 价格结构**（V5 svd@tau0 **exact 切片继承**）：distance_to_ref20/60、t0_ref60_breakout、close_vs_anchored_vwap、close_rel_t0_log、drawdown_from_running_peak、days_since_running_peak、new_high_count_t0、ref20_obs_n、anchored_vwap_obs_n。
- **B 基线成交**：pre20_turn_base / t0_turn / mean_turnover_since_t0 / turn_n_to_tau / cum_turnover_raw（V3-V5 冻结）+ **新增** t0_volume / t0_amount / pre20_volume_base / pre20_amount_base（baostock 冻结库确定性计算，口径对齐 V3 pre20：T0 前 20 个有个股数据的市场日均值）。
- **C Normalized Participation**：turnover_load_t0（=V5 turnover_load_to_tau@tau0，**该列同时充当 B 族 t0 turnover ratio——单一定义**）、mean_turnover_load_to_tau、**新增** volume_load_t0（primitive）。
- **D Efficiency（semantic audit 结论）**：V5 已有冻结公式 `efficiency_proxy = price_progress / max(turnover_load, 0.25)`（V5 dictionary 标 exploratory、恒附带 2-D components）。按开工令"已有冻结公式→直接继承"；**tau0 横截面上 price_progress 恒 0 → efficiency_proxy 恒 0，无横截面变异**——如实保留公式与退化事实，原始构成量（price_progress、turnover_load）在表内，未新造任何结果驱动指标。
- **E Context**：market 七列并入**主表**（mkt_ret_20d / mkt_amount_pctile_60d / mkt_breadth_5d / mkt_day_amount_yi / mkt_day_pct_up / mkt_day_eq_ret_median / mkt_day_new_high_20d + stock_ret_20d）——T0 收盘后可知，PIT 合法；sector 四列（industry_gate / sector_ret_20d / sector_vs_mkt_20d / stock_vs_sector_20d）**物理分离**到 companion 表，`is_point_in_time=false`、`retrospective_context_only=true`、`membership_snapshot_date=2026-09-21`，dictionary 机器可读标记（G2 验证 100%）。**行业粒度未升级**（14 门类 + 83 大类映射保留在 T4.1 map，切换留 T4.4）。

## 3. 六道 Gate（全 PASS）

1. **事件守恒**：27,422/27,422、ID unique、双向差集 0、code/breakout_day/end_day 与 V6 一致。
2. **T0 因果**：30 抽样物理截断（≤T0 重算 pre20_volume_base / volume_load_t0）0 mismatch；sector 族 100% 非 PIT 标注（含 membership 属信息链的语义：价格虽历史、归类非时点→整族 retrospective）；dictionary pit 标记机器可读。
3. **冻结对账**：39 个继承列逐项 exact（数值 rtol=1e-12；null 模式一致）；load identity（t0_turn/pre20_turn_base ≡ turnover_load_t0）通过率 1.000。
4. **研究隔离**：schema 扫描未来字段命中 0；构建源码 IO 血缘不含任何 V6 execution outcome 文件（初版曾误报——命中是模块自带的禁列常量，已改为检查实际 read_parquet/read_csv 目标）。
5. **覆盖率**：49 字段计数守恒；volume_valid=false 行 t0_turn 保持 null（不填 neutral）；最低覆盖 stock_ret_20d=0.9876。
6. **确定性**：双跑两表 hash 一致；manifest 记录 V6/V5/T4.1 血缘+快照日期+特征版本。

## 4. T0 状态分布（仅描述，开工令 §九 范围）

| 特征 | p5 | p50 | p95 | 备注 |
|---|---|---|---|---|
| turnover_load_t0 | 0.79 | 1.62 | 4.31 | >2 占 34.3%（T0 换手≥基线两倍） |
| volume_load_t0 | 0.80 | 1.63 | 4.29 | 与 turnover_load r=0.998（口径互证） |
| distance_to_ref20 | 0.002 | 0.017 | 0.099 | log 口径突破幅度 |
| distance_to_ref60 | −0.260 | −0.044 | +0.079 | ref60 突破占比 34.5%（9,430） |
| mkt_ret_20d | −3.67 | +2.53 | +7.94 | 市场背景跨牛熊 |
| mkt_breadth_5d | 0.378 | 0.527 | 0.682 | |
| stock_ret_20d | +0.84 | +6.81 | +36.19 | 突破股 T0 前 20 日涨幅 |

- **load × ref60 共现**（无方向预设）：load 四分位内 ref60 已突破占比 q1 29.9% → q4 43.1%——高参与度与更长周期位置突破同现，仅记录。
- **高相关结构**：tau0 退化列与其源列 r=1.0（预期，dictionary 已标 degenerate）；turnover_load≈volume_load（0.998）；个股水平量能与自身基线强相关（0.87-0.92，规模效应）。
- **extreme QA**：turnover_load_t0>10 或 volume_load_t0>10 共 60 行（保留原值）；close_vs_anchored_vwap>1.0 共 2 行（V5 继承分布，anchored_vwap_obs_n 在 tau0 恒 1——该字段在 T0 的信息量≈当日均价位置，dictionary 标注）。

## 5. §四 固定解释：相对强势是 breakout 构造的基线事实

T0 前 20 日个股相对市场超额：中位 **+5.22pp**、均值 +9.07pp、p5 −2.91pp（相对板块超额中位 +8.39pp 见 T4.1）。**这首先由 breakout 样本构造决定**（20 日新高突破者必然已跑赢），不能解释为"相对强势导致突破成功"或"板块相对强度具有预测价值"。本表只记录分布；条件关系留给后续阶段检验。

## 6. 限制与披露

1. Sector 族为 2026-09-21 快照归类，**retrospective_context_only**：任何实时判别或 PIT 主研究不得读取（机器可读标记已在 dictionary 与 companion 双层落地）。
2. tau0 退化字段（close_rel_t0_log、drawdown、days_since_peak、new_high_count、price_progress、efficiency_proxy、mean_* 系列）保留以满足冻结族完整性，横截面研究应使用非退化子集。
3. B 族 volume/amount 基线覆盖 0.9918（226 事件 pre-T0 有效行不足 20）——null 保留。
4. t0_ref60_breakout 覆盖 0.9959（112 事件 ref60 观测不足，与 V5 adj 缺失 112 一致）。

## 7. 阶段放行

六道 Gate 全 PASS。**«T0 时点到底知道什么»已冻结**；T4.3（Context-conditioned Path Layer：T0 状态 × T5/T10/T20/T40 路径连接，先研究状态演化）待用户开工令。
