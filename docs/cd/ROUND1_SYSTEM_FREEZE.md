# Round 1 System Freeze

**状态：已冻结 · 生产模式：仅影子（SHADOW_ONLY）**

## 1. 权威替代与适用范围

P0 `REDUCED_OUT` 记账缺陷已修复：减仓至零前必须先生成终止交易记录。修复后已对相关结果完整重建；本文件与 `ROUND1_SYSTEM_FREEZE.json` 及修复后的重建产物构成当前权威口径。

因此，修复前 CD-7/CD-7R2 的绝对样本量、收益、MAE、adverse 及机会成本统计均被替代，仅保留为历史审计记录，不得作为当前证据。任何受该缺陷影响的结果，均须以修复后重建为准。

## 2. 结论分类

### 已验证

- `PRIMARY_ZONE` 相对 `CHASE` 的持有风险较低，但绝对收益仍为负：
  - `CHASE`：holdout `n=10821`，`ret_rel -6.60%`，`MAE -7.88%`；
  - `PRIMARY_ZONE`：holdout `n=10532`，`ret_rel -5.02%`，`MAE -5.04%`。
- L0–L4 的 PIT/溯源纪律、市场与行业风险语境、候选池及来源溯源、episode/lifecycle/cost context 等基础设施继续有效。
- 冻结的 lifecycle `HOLD/REDUCE/EXIT` 语义仍适用；即使仓位很小，也不得跳过退出或减仓记录。

### 已拒绝或禁止

- `BUILDING` 作为入场累积推断、`EXPANSION` 作为 alpha 入场、`STRENGTHENING` 作为追高入场：拒绝；追高不得复活。
- `SECONDARY` 入场、`P75 intact` 判别：当前输入下未验证，禁止部署。
- 连续或搜索式 sizing：禁止。
- E-class 作为当前可靠风险排序：不成立。holdout 单调性失败，故不得据此执行 sizing、阈值搜索或资本分配。

### 未解决

- 新数据或结构性新证据下的绝对风险预算；
- 再入场与 add timing；
- `PRIMARY_ZONE` 之外的精确入场时机；
- 具备新、可论证风险排序信号后的 E-class sizing。

## 3. 冻结生产影子政策

- **模式：`NO_ORDER_NO_CAPITAL`**；不下单、不投入资本。
- 入场仅允许满足 **L1 permission 且位于 `PRIMARY_ZONE`**；`SECONDARY` 禁用。
- `CHASE` 仅作对照遥测，不可行动。
- 不执行 E-class sizing；风险预算研究因 holdout 单调性失败停止。
- 继续执行冻结的 `HOLD/REDUCE/EXIT` lifecycle 规则。
- 每项决策、episode 终止、减仓至零及退出均必须产生完整 ledger 记录，确保 `REDUCED_OUT` 不再静默丢失。
- 影子阶段监测结构漂移（候选吞吐、来源构成、生命周期、市场/行业状态、决策分布及 `PRIMARY_ZONE` 频率等），不以短期 P&L 触发日常政策改动。

## 4. Round 1 关闭理由

Round 1 关闭是因为：P0 记账缺陷已修复并完成权威替代；修复后的 holdout 仍只支持“`PRIMARY_ZONE` 相对 `CHASE` 风险较低”，不支持正 alpha 或扩大资本；E-class holdout 单调性失败，触发 sizing stop rule。故研究不再继续扩展为 sizing 或实盘执行，系统转入冻结的无订单、无资本 Shadow Monitoring。

后续仅可在出现新的有效 PIT 信息边界、持续结构漂移、影子证据实质反驳冻结风险结论，或发现新的实现/记账缺陷并完成重建审计时，提出重新审查；任何重新审查都必须发布新的权威替代物。
