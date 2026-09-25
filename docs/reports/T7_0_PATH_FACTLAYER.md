# T7.0 报告：Contract + Post-REDUCE Fact Layer（定义审计 + 三层物理隔离事实层）

> 本阶段只建立研究尺子与事实层，**不含任何研究结论**（"什么样的反弹更好"属 T7.1+）。
> 数字全部来自 `output/research/t7/00_path_factlayer/` 产物与 report_data。
> 上游：T6 最终冻结链（`…→52ea1f4→69a5bfd`），全部只读（G2b 校验 sha 未变）。

## 1. 定义审计（definition registry，全部走 T6_FROZEN 通道）

`t7_0_definition_registry.json`（sha 绑定进 contract）：

**True Recovery = Achievement + Persistence**：
- Achievement(t)：`dist_ref20(t) ≥ 0` AND `drawdown_from_peak_log(t) < severe_dd_depth_log`
  （0.10536，T6 冻结值）——语义="当初触发 REDUCE 的结构性恶化已修复并离开 severe 区"，
  等价于 per-anchor 动态修复比门槛 `1 − severe/det_dd_R0`（深恶化精确、浅恶化平凡）；
- Persistence：其後 **K=5** 个有效观察日内，T6.3-R1 冻结的 F3 失败条件
  （`dist_ref20<0 OR dd≥severe`）不触发——K 与失败条件均继承 T6.3-R1。

**False ADD**：anchor = **policy_add_day**（各 counterfactual policy 自己的 ADD 日，非 T5 A0）；
W_fa=10 内未达成 True Recovery 且 adverse excursion（dd ≥ severe，T6 冻结值）；再 REDUCE/EXIT
仅 secondary diagnostic（action-based 自引用已消除）。

**Missed Recovery**：anchor = **recovery_opportunity**（cycle/R0 clock，非任何 policy ADD 日）；
policy 未暴露且 cycle 达成 True Recovery；成本=recovery upside 未捕获。

**两 clock 分离**写入 registry 并进 G-Counterfactual Conservation 的 clock audit 项。

**Calibration trace（诚实记录）**：最初考虑 X_dd=DEV 无条件中位定标（规则 v1）；诊断发现
2,500 个 DEV anchor 中仅 **26.9%** 在整个 R+1..R+40 窗口内达到任何正修复（中位 cycle 整窗
零修复），任何 ≤中位的无条件分位都退化为 0.0 → achievement 条件退化。解决：改走 T6 severe
界继承（零新增阈值），**T7_DEFINED_DEV_THRESHOLD 通道弃用**（G18 强制校验无 DEV 定标项）。

## 2. 三层物理隔离事实层（G17 强制）

| 表 | 内容 | 行数 |
|---|---|---|
| `t7_0_features_path_fact.parquet` | 纯 PIT 逐日事实（R+1..R+40：close/ret/量比/换手/效率/dd/dist_ref20/mkt 列/resolution_state + **r0_day anchor 归属列**） | 287,795 |
| `t7_0_features_anchor_features.parquet` | decision-time trajectory 特征，checkpoint **仅 R+1/2/3/5**（max_bounce/consec/vol_decay/turnover_traj/eff_pos_share/dd_repair_ratio/ref20_repair/new_high 等，逐变量语义登记 contract） | 31,260 anchors |
| `t7_0_outcomes_outcomes.parquet` | 结局：cycle type（T6.2 继承）/false_recovery（T6.3-R1 继承）/bh_R0_H5-40（T6.2 继承）/MFE/MAE after R0/再 REDUCE/EXIT 时点/terminal_failure（T6.4 口径）/**true_recovery + recovery_established_day**（按 registry 判定） | 31,260 |

- anchor 集 == T6.2 cycle 集**逐位一致**（31,260；G8）；false_recovery 总数 6,953 ==
  T6.3 fired cycles（语义连贯性断言进 G8）。
- features builder 读 T6.2 cycle master 的列白名单 = `event_id/segment/E_class/r0_day`
  （无 type/a0_day/bh_*）；G17 扫描数据调用行 + 白名单 AST 校验 + anchor_features 列集
  不含 outcome 列。

## 3. Sector sidecar（QUASI-PIT，EXPLORATORY ONLY）

`t7_0_sector_sidecar.parquet`：84 证监会行业 × 1,163 行业日 × 5,240 只个股日线聚合
（sector_breadth / sector_ret_1d / sector_ret_20d / sector_turnover）。成员映射 =
2026-09-21 回溯快照（survivor/reclassification 偏差）→ **QUASI-PIT**：仅供 T7.3
EXPLORATORY 条件分层，**禁入 C/D policy family 与任何 primary claim**（G_sector 隔离）。

## 4. 事实层组成（描述性计数，非结论）

true_recovery 判定：9,463 / 31,260 = **30.3%**（val 33.7% / conf 26.6% / dev 24.7%）。
这是尺子定义下的组成事实；其条件结构（何者区分真假恢复）是 T7.2/T7.3 的研究对象，
本阶段不做任何条件分析。

## 5. Gate 结果

`t7_0_gates.json` 全 PASS：G1 lineage（features/outcomes 双 manifest）→ G2b 上游不可变 →
G8 守恒（三表 anchor 一致 + false_recovery 语义连贯）→ **G17 物理隔离** → **G18 定义
溯源**（全 T6_FROZEN，无 DEV 定标项，registry sha 绑定 contract）→ **G19 No-Future-Feature**
（300 anchor 抽查重放 max_bounce_R5 逐位一致 + checkpoint 纪律 R{1,2,3,5}）→ G9b 独立
重判（50 anchor 重放 true_recovery 零 mismatch）→ G_sector sidecar 隔离。

G9b 首跑抓到 path_fact 缺 r0_day 列（同 event 多 anchor 窗口行无法区分归属）→ 已修复
（anchor 归属列加入）并重验——gate 有效性的一次实证。

## 6. 遗留与下一步

- T7.0 冻结后进入 **T7.1 Path Anatomy**（全段描述性，无 candidate 选择）。
- 唯一 contract 内开放点：Policy Amendment Freeze 的具体内容（C1/C2/D 条件）——按段协议
  只能在 T7.2/T7.3a DEV discovery 之后、T7.3b 之前产生。
