# CD-6 — Integrated Capital Decision Engine · Completion Report（第一轮总验收）

*预注册: `cd6_preregistration.json` · 结果: `cd6_results.json` · 引擎: `scripts/cd6_decision_engine.py`（as-of-T 全重算，无回标）*

## 核心结果：逐层 ablation（每笔交易中位相对收益，vs 市场等权）

| 层 | dev ret_rel | holdout ret_rel | MAE (dev) | adverse 率 | 交易数(dev) |
|---|---|---|---|---|---|
| BASE（episode 持有） | −8.6% | −11.6% | −17.5% | 0.92 | 17,447 |
| A（仅 lifecycle） | **−9.2%** | **−15.2%** | −18.2% | 0.92 | 15,071 |
| B（+市场权限） | **−5.9%** | **−3.4%** | −14.4% | **0.32** | 1,844 |
| C（+板块 FADING） | −5.8% | −3.3% | −14.4% | 0.30 | 1,802 |
| D（+NARROWING） | −5.8% | −3.3% | −14.4% | 0.30 | 1,800 |
| E（+成本带） | −5.8% | −3.3% | −14.3% | 0.30 | 1,808 |
| F（+origin） | −5.9% | −3.3% | −14.2% | 0.29 | 1,792 |

## 五个结构性结论（诚实，含否定）

### 1. 市场权限层（L1）是唯一大的边际价值来源——且性价比被证明

B 层：adverse 率 0.91→0.24（holdout）、MAE 大幅改善、ret_rel 减半以上。**代价**：拒绝 96% 入场机会，但 **missed-upside 仅 3.8%**（被拒 episode 的 60d top-decile 率 11.2% vs 合格池 9.9%——被拒组并不显著更强）。用 3.8% 的机会损失换 67pp 的 adverse 改善——**"market = participation permissions" 的功能分工被验收**。

### 2. STRENGTHENING 追高入场是负相对期望——个股层复现 CD-3B 板块反转结构

所有配置的每笔中位相对收益为负。A 层（仅 lifecycle，STRENGTHENING→ENTER 无约束满暴露）**比 BASE 更差**（holdout −15.2% vs −11.6%）。这与 CD-3B 的 EXPANSION 后弱于基线**同构**：横截面相对强势（q67 之上）入场遭遇均值回归。**程序内部一致性发现：追相对强是结构性负期望，无论板块层还是个股层。**

### 3. NARROWING 三种用法无差异（ADD 时点与 NARROWING 几乎不相交）

OFF vs ADD_VETO vs ENTER+ADD_VETO：adds 14,591 → 14,594，全部指标持平。NARROWING 日与 ADD 许可日几乎不重叠——**在当前规则表下 NARROWING 的六个 deferred 用法没有一个产生边际动作差异**。L2_RISK_CONTEXT_V1 的 late-stage-risk-warning 语义在 CD-3B 已被证明（episode 级前瞻），但在本规则表的 ADD/ENTER 决策点上是空触发。如实记录：**"NARROWING 作为 ADD-veto"未获操作化支持**。

### 4. C/D/E/F 层边际贡献微弱但方向一致

板块 FADING（adverse 0.318→0.301）、成本带（MAE 微改善、拒 11 万次入场换 <1pp）、origin-M 收紧（adds −14%、MAE −0.05pp）——每个都正确方向但量级小。**功能分工部分成立**：这些层调节的是风险边际，不是方向。

### 5. 退出/减仓语义工作正常

false-exit 率 0.0%（EXIT 后 20 日内无再 STRENGTHENING——失败/失活退出语义准确）；REDUCE 触发 12,355 次、false-reduce 未超过触发量的合理比例。**lifecycle 层的价值在持有/退出结构，不在入场方向**——与 CD-5D 的时间衰减结构一致。

## 停止规则判定：CD-6D 暂缓

离散 policy **有**稳定价值（B 层 dev/holdout 双重复验）**但入场方向性为负期望**。按冻结停止规则：不进入 CD-6D 调仓位比例"救"。二轮方向（待用户裁定，均为结构性选项非调参）：入场条件重构（非追高型：HOLDING+成本区内 Enter-zone）、ENTER 语义降级为观察候选、或评价轴改绝对风险预算。

## 12 条完成门：全 PASS

PIT-safe ✅（as-of 重算；STRUCTURAL_FAILURE 第 15 日/INACTIVE 第 40 日当日可知，无回标）· CD-0 决策集不变 ✅ · 无 retrospective SW2 ✅ · 无 BUILDING ✅ · position 显式建模（entry_cost 与 episode_cost_proxy 分离）✅ · 会计标签与实时可观察分离 ✅ · 规则先于 holdout 冻结 ✅ · dev/holdout 分报 ✅ · ablation 完整（BASE+A-F）✅ · NARROWING 三用法显式测试 ✅ · 无连续 exposure ✅ · 无隐藏评分（纯规则表）✅

## 程序级结论（第一轮六层总验收）

> **六层架构中：L1 市场权限层被清晰验收（3.8% missed-upside 换 67pp adverse 改善）；L4 lifecycle 的价值在持有/退出结构而非入场方向（false-exit 0.0%）；L2 sector/NARROWING/cost/origin 在当前规则表下是风险边际调节器（方向正确、量级小）；"追相对强入场"在板块与个股两层同构性为负——这是程序最一致的否定结论。**

**全局状态**：`CD-0..CD-6 (Round 1) COMPLETE · CD-6D 暂缓（停止规则）· 二轮方向待裁定 · CSR-8 不变`
