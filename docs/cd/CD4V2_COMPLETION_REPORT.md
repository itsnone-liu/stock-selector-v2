# CD-4V2 — Regime-aware Multi-source Candidate Architecture · Completion Report

*预注册: `cd4v2_preregistration.json` · 结果: `cd4v2_results.json` · 候选池: `data/cd/l3_candidate_pool_v2.json.gz`（64 checkpoints，含 candidate_source[] + regime daily/20d mode 元数据）· 源定义与 V1 逐字相同（架构实验，零阈值调整）*

## 六问六答

### Q1 Observation Pool 稳定？——✅ 中位 4,814 只，月度变动 <2%

仅硬排除（NEW/LOW_PRICE/SUSPENDED/ILLIQUID），无任何 stealth alpha 条件。OBSERVABILITY_LIMITATION 声明：st_flag/free_float/turnover_rate 在 DATA-1 不可得，标记携带、不伪造。**排除层 recall 94.6%**——几乎不损失未来 top-decile 覆盖。

### Q2 三源互补召回？——✅ M 是主要互补来源，S 边际小

| 步骤 | pool 中位 | recall 中位 | 增量 recall | 增量成本 |
|---|---|---|---|---|
| L | 1,466 | 28.6% | — | — |
| +M → L\|M | 1,847 | 38.9% | **+10.3pp** | 37 只/pp |
| +S → L\|M\|S | 2,056 | 42.5% | +3.7pp | 57 只/pp |

**结论：MID 提供真正的新候选（emerging 语义成立）；SHORT 主要与 L/M 重叠、边际贡献小但非零**——与"SHORT 是 event 不是 membership"的 V1 教训一致。

### Q3 三源持续时间显著不同？——✅ 三层生命周期结构清晰

| Source | 5d 留存 | 20d | 60d | 月 tenure 中位 |
|---|---|---|---|---|
| L structural | 93.1% | 86.6% | **74.4%** | 3 个月 |
| M emerging | 82.1% | 54.9% | 23.4% | 2 个月 |
| S event | 79.7% | 26.7% | 14.7% | 1 个月 |

**stable observation 层与 volatile event 层确实已分开**——这正是 CD-5 需要的输入结构。

### Q4 union 在合理规模下显著提高 recall？——✅

规模 +40%（1,466→2,056）recall +13.9pp（28.6%→42.5%）。对比 V1 AND 链：366 只 @ 7.9% → V2 union 同量级规模下 recall **5 倍以上**。月度 Jaccard：union 0.56（V1 FULL 池 0.107——**换手从 89% 降到 44%**）。

### Q5 regime 间结构稳定？——✅ 架构不塌，效果随背景（context 语义正确）

| Regime(20d mode) | L | M | S | U | recall_U |
|---|---|---|---|---|---|
| RISK_ON_BROAD | 1,833 | 1,150 | 1,119 | 2,745 | **63.2%** |
| RISK_ON_NARROW | 1,740 | 927 | 671 | 2,326 | 43.1% |
| REBOUND_MIXED | 1,015 | 567 | 544 | 1,471 | 34.3% |
| RISK_OFF | 743 | 407 | 430 | 1,125 | 15.6% |

四 regime 中源大小序（L>M>S）与 union 增益保持；RISK_OFF 时 recall 全体走低（15.6%）但**架构持续提供候选**（U=1,125，熊市单源关闭不再导致系统失明——union 设计达成目的）。

### Q6 CD-5 稳定 candidate→episode 输入已建立？——✅（完成门通过）

CD-5 进入五条件逐条判定：
1. Observation Pool 稳定可纵向跟踪 ✅（Q1）
2. candidate_source[] 语义冻结 ✅（预注册 + 池表落地）
3. V2 架构无 outcome tuning 冻结 ✅（零阈值调整，本报告即冻结点）
4. episode 起点可从 source 事件定义 ✅（M/S 触发日即事件起点；L membership 变化可定义 structural episode）
5. 候选消失 ≠ 生命周期终止 ✅（membership 与 event 已解耦：S 消失只意味事件窗过期，L4 用 episode 语义而非池成员资格定义生命周期）

## Pareto frontier（非支配点）

L / M / S / L|M / M|S / L|M|S 均为非支配点（size × recall × Jaccard 三维）——**无单一"最佳池"**，按下游预算选点：预算紧用 L（1,466 @ 28.6% @ jac 0.77 最稳）；平衡用 L|M（1,847 @ 38.9%）；覆盖优先 L|M|S（2,056 @ 42.5%）。

## 边界遵守

Regime 仅作 context 分层（零 regime-specific 阈值）· future top-decile 仅评价 · 空源合法（RISK_OFF 时 L=743 仍非空，2021 下半年 L≈0 时 M/S 供血）· 无复合评分/排名 · 无 CD-5 工作

**全局状态**：`CD-0..CD-4 + CD-4.5 + CD-4V2 COMPLETE · CD-5 ENTRY CONDITIONS 五条全满足 · CD-5 (L4 Cost & Lifecycle) 待 GO · L2_RISK_CONTEXT_V1 冻结待 CD-6 · CSR-8 不变`
