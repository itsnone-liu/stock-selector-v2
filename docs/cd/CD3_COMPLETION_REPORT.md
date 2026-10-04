# CD-3 — Sector Path Aggregation, Economic Validation & SW2 Decomposition · Completion Report

*预注册: `cd3a/cd3b/cd3c_preregistration.json` · 产物: `cd3a_path_census.json` / `cd3b_validation.json` / `cd3c_sw2_answers.json` / 路径特征表 285,732 行（sha `59da602f…`）*

## CD-3A 路径表示：无自然路径簇（NO_CLUSTER）

285,732 行 path features（3 窗口 × 全 (sector,T)）。census 判定 occupancy 特征**无多峰**（40-bin 直方图 valley 检验全 NO）→ 按预注册规则**跳过聚类层**——不为聚类而聚类，CD-3B 直接用 CD-2C 路径标签 episode。三窗口特征表保留，供后续任何窗口敏感性使用（无 cherry-picking）。

## CD-3B 前瞻验证：主发现是"风险结构信息成立、alpha 信息不成立"

9,340 episodes（FADING 5,016 / EXPANSION 3,662 / NARROWING 478 / BUILDING 184），匹配基线=同板块×同年×同市场 regime 三分位，dev/holdout 分开：

### NARROWING——最强且双向复验的信号

| | 相对收益中位（H60） | 匹配池 | 60 日内转 FADING 概率 |
|---|---|---|---|
| dev | **−2.48%** | +0.05% | **91.9%** |
| holdout | **−2.74%** | −0.57% | **74.1%** |

LEADERSHIP_NARROWING 确实是 FADING 的强前奏且伴随显著负前瞻——**CD-2 的经济标签获得了真实的路径含义**（风险预警结构）。

### EXPANSION——前瞻弱于基线（反转结构，不是买入信号）

| | H5 | H20 | H60 |
|---|---|---|---|
| dev vs 池 | −0.16% vs −0.16% | −0.46% vs −0.26% | **−1.45% vs −0.34%** |
| holdout vs 池 | −0.22% vs −0.15% | −0.63% vs −0.39% | **−1.67% vs −0.87%** |

"新达 BROAD_STRENGTH+参与扩张"之后 60 日相对表现**差于匹配基线**，且后续 BROAD_STRENGTH 占比中位仅 0.1（状态不延续）。追高板块在结构上不占优。

### FADING：弱负向一致（H60 dev −0.85% vs −0.37%；holdout −1.06% vs −0.89%）；BUILDING：dev 正（H20 +0.75% vs −0.21%）holdout 反号——**未通过复验，如实记录不稳定**。

### CD-3B 结论（结构层）

> **四轴状态体系的信息含量在"状态转移/风险结构"维度成立（NARROWING→FADING 92%/74%），在"前瞻超额收益"维度不成立（EXPANSION 后反而更弱）。** sector state 适合作为市场背景与风险结构刻画，不适合作为 alpha 信号——这正是裁定预判的"否定亦有效"分支。

## CD-3C SW2 分解（RETROSPECTIVE_CURRENT_SW2，语义隔离）

| 问题 | 答案 | 证据 |
|---|---|---|
| Q1 DIVERGENT 日子行业真分裂？ | **YES** | 子行业收益极差中位 dev 1.44% / holdout 1.37% > 匹配池 1.15% / 1.12% |
| Q2 NARROW+HIGH_CONC 对应 1-2 子行业主导？ | YES（带度量限制） | top2_share 中位 1.0——但多数 L2 当日仅含 2-4 个有效 SW2 子行业，正贡献子行业 ≤2 时该指标算术退化为 1.0；"YES"反映主导性但幅度不可靠 |
| Q3 BROAD_STRENGTH 对应子行业广泛一致？ | **L2_BREADTH_FAITHFUL** | 子行业上涨比例中位 1.0（dev/holdout）——L2 广度不掩盖子行业结构 |

escalation 设计被 Q1 验证：DIVERGENT 日确实值得开 SW2 分解（回答"电子强但其实只有半导体设备强"类问题）。

## 解释层（INTERPRETATION，标注不确定性）

- NARROWING 可解释为"行情后段/分歧扩大"的风险预警——**这是唯一获得 dev+holdout 双重复验的经济映射**
- EXPANSION 后的弱势与"扩散高峰已现"一致——解释为参与度峰值后的均值回归，而非资金离场（无主体数据，不下意图结论）
- BUILDING/"吸筹"距离最远：不稳定、样本最小（184 episodes）——**不命名、不使用**
- 证据层级执行：L2 统计关联（本报告）→ L3 经济解释（本节，全部带不确定性标注）；未使用任何主体意图词

## 全局状态

`CD-0 FROZEN · CD-1A/1B/CD-2/CD-3 COMPLETE · CD-4 NOT STARTED · CSR-8 不变`

CD-4 候选问题（待裁定）：NARROWING 风险结构进入 L5 决策背景层的可行性（作为 position-sizing/risk-off 输入而非选股信号）；或转向 L3/L4（成本与生命周期）层补全六层架构。
