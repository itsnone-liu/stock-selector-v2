# T3 V1 Erratum + V2 Re-gate Report

- 基线：`da933a1`
- V2 条件版：`93afd5e`
- 本次修订：用户裁定后规范勘误与完整双跑重签
- 目标：不重建历史事件宇宙；修正定义职责、字段级覆盖、112 事件语义，并重新验证全部数据层

## 1. 用户裁定固化

1. 27,422 个 lifecycle20 事件宇宙保留；事件定义为 TDX 未复权 close 突破前 20 个 TDX close 的最高值。
2. ref60 降为 A1 趋势强度/位置特征，不是事件成立条件；`a1_ref60_close_margin` 为正式名，旧 `a1_breakout_margin` 仅作 deprecated alias。
3. 112 个因子不可得事件保留。其复权依赖字段缺失；不依赖因子的原始量、换手、原始价字段继续计算。
4. 112 事件不得记作 `security_history_end`；主因按窗口落账为 `data_gap`，细分 `adj_factor_missing`。右边界与数据质量信息并存时，`sample_end` 可作为主因，同时 `is_data_gap_H=true`。
5. 覆盖按字段级报告；增加 `is_sample_end_H`、`is_security_history_end_H`、`is_data_gap_H` 等 audit-only 字段。
6. “六态”更正为九态（3×3），不改状态机。chip 只冻结连续 primitives；成本带/分带保留 audit-only candidate。

规范勘误已追加至 `T3_SUSTAIN_COVERAGE_AUDIT_V1.md` 的 Erratum E-2026-09-23。

## 2. 重生成后的字段级冻结数字

| 字段/检查 | n_valid / 结果 |
|---|---:|
| 事件总数 | 27,422 |
| T0 adjusted factor available | 27,310；不可得 112 |
| A1 ref60 ready | 27,310/27,422 = 99.59% |
| B1 `vol_ratio_20` | 27,422/27,422 |
| chip VWAP 5/10/20 | 各 27,422/27,422 |
| T0 后 20 日换手 partial | 279 |
| T0 后 20 日换手 missing days | 1,202 |
| h5/h10 | none 27,310；data_gap 112 |
| h20 | none 27,177；sample_end 133；data_gap 112；security_history_end 0 |
| h40 | none 26,126；sample_end 1,185；data_gap 111；security_history_end 0 |

`field_coverage_matrix.csv` 是逐字段机器产物，记录每个字段的 valid/missing/coverage/reason counts；不以 family 级单一数字替代。

## 3. Gate B 重定义与结果

### B0 lifecycle20 universe reproduction — PASS

冻结 lifecycle 配置在当前输入上复跑：55,646 lifecycle rows，关键 12 列逐列 0 mismatch；事件数 27,422 = 27,422。TDX snapshot 漂移不影响冻结宇宙。

### B1 ref60 feature integrity — PASS

- 27,310 个可计算事件的 ref60 与 `event_features_a1.a1_ref60` 逐事件一致；
- 可计算事件的 ref60 observation count 全部为 60；
- native lifecycle20 TDX 检查 27,422/27,422；
- lifecycle20 事件中同时高于 ref60 的事件为 9,430/27,422（在 adjusted factor 可用子集内为 9,430/27,310）。该比例只作为保存的状态变量/描述性信息，不在 V2 研究哪个更好。

**诊断脚本更正说明**：条件版阶段 Gate B 脚本曾在每股票多个事件上复用了首个事件 T0 之前的 `prior`，导致后续事件使用陈旧 ref60 窗口，错误报告 18,725/27,422（68.27%）。事件产品 builder 始终按每个事件逐独立取窗，未受影响；本次脚本已修正并重跑，正确值为 9,430。

### B2 ref60 universe reconstruction — descriptive diagnostic

仅保存差异，不作为门禁：lookback=60 重构 16,495；与旧宇宙交集 9,185；old_only 18,237；new_only 7,310；生命周期内 breakout_day 改变 18,237。该诊断不改变 27,422 主宇宙。

## 4. 其他 Gates

| Gate | 重签标准 |
|---|---|
| ID | 27,422 event IDs 唯一、映射全保留 |
| Y40 | 与任务二冻结参考实现逐位一致，max_abs_diff=0 |
| lifecycle20 | B0 全表 0 mismatch |
| ref60 feature | B1 上述可用性/窗长/逐事件一致 |
| high×F | 每股常数性；事件日 TDX↔库一致 |
| PIT | 物理截断重算 0 mismatch；周线不使用未完成周 |
| corrected coverage | 与本 erratum 字段级冻结表一致 |
| determinism | 两次完整构建的六个产品 hash 一致 |

## 5. V2 边界结论

本次修改没有推倒重做，也没有删除 112 个事件。修订后的数据语义区分：事件存在、复权特征可用性、未来标签可用性。`security_history_end` 不再承载因子源不可用问题；B2 不再冒充事件宇宙门禁；成本带不升格为 V2 研究特征。

第二轮完整构建、Gate 证据与 determinism 结果完成并复制到 `docs/reports/T3_V2_*` 后，V2 状态由 CONDITIONAL 转为 **PASSED**；随后等待进入 V3 的明确开工令。
