# CSR-8 Phase I / I2 — Contextual Layer Preregistration & Cluster-Robust Analysis Design

*Contract:* `i2_contextual_preregistration.json` · **PREREGISTRATION ONLY — 设计冻结，不跑任何 contextual 结果**
*Authority:* 用户三裁定 2026-10-04 ← Phase H final freeze `9dfc516` ← third readout `3f46515` ← I1 atlas `cee5efd`

## 冻结的三条裁定（写入合同）

1. **taxonomy_v3 = NO-GO**。I1 的 20 例非主导中 E=0——问题不是缺类别，而是 stock 层把分级/混态证据压成过粗二元表达。未来若改，只能是 **representation refinement**（分级/混态表达），永不扩类别。
2. **3 个 REVERSED = sampling-dependent structure**。机制证据已确定性闭合（共享 cell-8；T=2021-04-06 的 9 例同构成员把 cell-8 中位数 −0.0362→−0.0088；仅取 epoch-1 精确复现 64 语料符号 d=+0.0224）。不得再作"市场结构反转"解释。
3. **I1 结构性结论**：未发现需要 taxonomy_v3 的新资金类型；发现 stock 层表达粒度不足 + 观察日聚类对结构统计的实质影响。下一步修研究设计与解释层，不堆分类。

## Context 规范（两 Tier + 明确 DEFERRED）

### C1 Sampling context（Tier-1，语料内确定性，零新数据）
`obs_date` / `date_cluster_id` / `date_multiplicity`（已知簇：2021-04-06=9 例、2021-03-08=7 例、其余 ≤3）/ `epoch` / `paired_ordinal`（同实体 N±64）/ `same_date_same_cell_count`。

### C2 Market context（Tier-2，仅 packet 内 PIT-safe 两融层）
**设计审计事实**：每个 packet 携带单一市场端点（margin_sse/szse）的 20 条日度快照，obs ≤ T−1、avail ≤ T；**packet 内不存在大盘指数序列与行业序列**。

- `margin_balance_regime_20d` = sign(窗口末−窗口首 融资余额)——杠杆参与温度 modifier
- `margin_buy_intensity_latest` = 窗口内三分位——次级 modifier
- **禁止**：国家资金/主力归因（CSR-4 MULTI 口径：两融参与者混合）、因果语言、改写资金标签

**DEFERRED（I2 不引入，I3 不得临时替换）**：`broad_index_regime`、`sector_regime`——需外部 PIT 数据 + 单独用户授权 + 冻结溯源 erratum。

## 分析政策（R1–R8 硬规则）

| # | 规则 |
|---|---|
| R1 | 资金状态定义 Phase I 内**不可变**；context 只作 modifier |
| R2 | **naive 与 cluster-aware 必须并列双列报告**，naive-only 报告无效 |
| R3 | **date-dedup 聚合**：每个 (T, cell) 的成员案例收敛为一个值（案例 R5 中位）；cell 统计一律跨**日期**计算。同日 k 例 = 1 份证据，不是 k 份 |
| R4 | **date-cluster robustness 硬门**（升级理论层的唯一通道）：(a) naive 方向成立 ∧ (b) date-dedup 方向不变 ∧ (c) leave-max-cluster-out 方向不变 ∧ (d) **每侧 ≥5 个不同观察日**。任一失败 → 冻结为 sampling-dependent（REVERSED 先例） |
| R5 | 唯一可测 R4 升级的关系 = 3 个预注册 PRESERVED 目标；其余对永远是探索性 |
| R6 | PIT 硬线：context 变量必须 avail ≤ T；失败即弃用并披露，绝不用 T 后数据修补 |
| R7 | 两融只作杠杆温度；禁单一主体归因 |
| R8 | taxonomy_v3 NO-GO 全 Phase I 有效；representation refinement 只能在 I3 作为**提案**设计，实施需新裁定 |

## 设计审计（在 I3 之前完成并冻结）

- **schema probe**：o7/o50/o100/o119/o128 五包验证两融窗口结构一致；无指数/行业数据 → Tier 划分有据
- **R4(d) 可行性预报（预注册的预期，不是结果）**：
  - `NOT_DISCLOSED (74 日) vs NO_PIT (4 日)`——**NO_PIT 侧仅 4 个观察日，天然不满足 R4(d) ≥5**；在本语料下该关系**无论去聚类方向如何都不可能通过硬门**，只能停留在"描述性语料结构"。此失败已预注册为预期，I3 时不得惊讶、也不得放宽门槛
  - `E4 vs E8`：11 日 vs 8 日（可测）；`E8 vs E9`：8 日 vs 11 日（可测）

## I3 执行清单（冻结、未运行）

1. 从 I1 atlas 重建 C1（确定性）；2. 从 packet evidence 计算 C2（确定性、PIT-safe）；3. 三个预注册关系按 R2 双列重算（naive / date-dedup / leave-max-cluster-out）；4. 过 R4 硬门分类（theory-layer eligible / sampling-dependent）；5. 仅描述性 context 分层交叉表（带禁止解释横幅）；6. 无新关系、无标签变更、DEFERRED 层保持 DEFERRED。

**变更控制**：本合同随 commit 冻结；任何改动需 append-only erratum + 显式用户授权。
