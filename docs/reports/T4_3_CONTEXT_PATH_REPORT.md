# T4.3 — Context-conditioned Path Layer（市场背景 × T0 状态 → 路径）

**阶段**：T4.3（条件路径研究；非预测模型/选股/择时/策略）
**基线**：T4.2 @ `c605a39`（HEAD 断言一致）；七道 Gate 全 PASS
**开工令**：T4.3 二十七章

---

## 1. 交付物（output/research/t4/context_path/）

`t4_context_state.parquet`（27,422×T0 状态+PIT 市场背景+as-of 分位）、`t4_context_path_outcomes.parquet`（27,422×4 horizon，纯 future、物理分离）、`t4_market_context_contrasts.parquet`（3 轴×4H×6 metric=72 行）、`t4_date_balanced_contrasts.parquet`、`t4_context_interactions.parquet`（4 组预注册 2×2=96 行）、`t4_sector_retrospective_contrasts.parquet`（NON-PIT）、`t4_83class_coverage_diagnostic.csv`、`t4_context_attrition.csv`、`t4_yearly_stability.csv`、四份 audit/manifest/gate json。

代码：`src/t4/path/{build_outcomes,analysis}.py`、`scripts/run_t4_3.py`、`scripts/t4_3_gates.py`。

## 2. 方法要点（与开工令逐条对应）

- **Outcome 口径**：从 V3 冻结 daily 按V4 冻结公式派生六指标（W=(0,H]、r=exp(crl)、runmax 从 1 起算）；H∈{5,10,20} 与 V4 @tau0 **逐事件对账：6 指标 × 3 horizon 值与 null 模式全 exact**（Gate 4），H40 同公式延伸。窗口无有效观测记 null（112 个 F 缺失事件行为与 V4 一致）。
- **市场背景**：三语义轴 raw + **as-of expanding percentile（只用 dates<T0，min 120 天，25/50/75 天然切分）** + history_n 并存；不足 120 天 null 不插补。
- **双 estimand**：event-weighted 与 date-balanced 并列；**two-way 依赖**：date-cluster 与 stock-cluster bootstrap（N=300，seed 固定）并列，区间取较宽者；p 与 CI 同批重采样。Holm 在 metric×horizon×context-axis family 内（contrasts 与 interactions 分 family）。
- **突破密度诊断**：median 24.5 事件/日、p95=136；breadth 分位与当日突破数 Spearman ρ=0.413（p≈0）——强广度日确实产出更多突破，故 DB 口径必须并列。

## 3. Primary 结果一：市场背景 → 路径（Q1→Q4 单调、多 horizon 显著）

median_excess（对市场超额，log）Q4−Q1：

| 轴 | H5 | H10 | H20 | H40 | DB@H20 |
|---|---|---|---|---|---|
| breadth_5d | ~0 | +1.96* | +3.88* | +3.68* | +1.65 |
| amount_yi | −0.3 | +1.02 | +7.07* | +7.15* | +1.92 |
| new_high_20d | +0.28 | +1.79* | +3.22* | +3.44* | +1.85 |

（* Holm<0.05；DB=date-balanced 同向值）

- **方向结构**：三轴 Q1→Q4 全部单调向好；EW 与 DB 符号一致率 **67/72=93.1%**。
- **幅度解释（§十一 强制条款）**：DB 幅度为 EW 的 25–50%——«观察到的结构相当一部分来自事件密度较高的日期»（ρ=0.413 的密度耦合），但方向在日等权口径下保持。**正式引用幅度应以 DB 为主、EW 为机会密度加权参考**。
- **指标分化**：市场环境同时影响收益（+1.7~3.9pp DB@H20）、MDD（breadth Q4 比 Q1 浅 2.3pp@H20）、创新高能力（p_new_high Q4−Q1 +3~5pp）与 ref20 失守率（−7~11pp）——不是单一收益通道。
- **H5 全轴无信号**：条件差异在 10 日后展开。

## 4. ⚠ Primary 结果二：amount 轴被时间趋势污染（降级披露）

as-of expanding percentile 在**单调趋势变量**上退化：全市场成交额 2024→2026 持续放大，2025 年事件的 amount 分位几乎全在 Q4（2025：Q1=0/Q4=14,578；2026：全 Q4）。该轴的 "Q4−Q1" 实质≈年际时间趋势，无法与 regime 效应分离——**其全部显著行（含 EW 最大值 +7.07pp）从 Primary 解释中移出，标记 trend-contaminated**。breadth_5d 与 new_high_20d 为围绕中枢的振荡量，expanding rank 跨年保持变异，**Primary 市场结论以这两轴为准**。（这不是计算错误，是 PIT expanding 口径在趋势变量上的统计性质——任何后续用 amount 分位的研究都受此约束。）

## 5. Primary 结果三：预注册 interaction（用户特别盯的问题）

四格 median_excess（h20，EW）与 DiD：

| 组合 | hi/hi | lo/hi | hi/lo | lo/lo | DiD (EW) | DiD (DB) | Holm |
|---|---|---|---|---|---|---|---|
| load×breadth | −1.92 | −0.77 | −3.05 | −1.25 | +0.65 | −1.29 | ns |
| load×amount | −2.01 | −0.69 | −7.20 | −3.60 | +2.28 | −1.72 | ns |
| ref60×breadth | −3.11 | −1.10 | −4.32 | −1.86 | +0.45 | +1.32 | ns |
| ref60×new-high | −3.21 | −1.05 | −4.49 | −2.41 | −0.08 | −0.001 | ns |

（单位 pp；hi_load=load>1、hi_ref60=ref60 已突破）

**核心发现（直接回答开工令引言问题）**：

1. **V5 participation load 的负向结构在强、弱市场环境中方向一致地存在**——四格内 hi<lo 恒成立（h5→h40 全部），DiD 中位数≈0、Holm 后无一显著（显著项集中在 p_lose_ref20 且 DB 多不同向）。**load 更像个股层面的独立状态，不是市场 regime 的代理**。
2. **ref60 长结构压力（hi_ref60 更差）同样跨环境稳定**；唯一 Holm 显著的收益 DiD 是 ref60×breadth@H5（+1.26pp，强广度短窗放大 ref60 劣势），h10+ 即消失。
3. **市场层与个股层是两条独立通道**：市场 Q4−Q1 显著（§3）而 stock×market DiD≈0（本节）→ 市场背景不通过放大/逆转个股状态起作用，而是整体平移路径。对状态引擎的含义：**宏观市场层应作为独立条件层纳入，个股状态引擎无需按市场分层重估 load/ref60 语义**。
4. h40 弱流动性放大 load 惩罚（hi−lo 差 −3.66pp vs 强流动性 −1.32pp）方向有趣但不显著，留 exploratory。

## 6. 年度稳定性（internal temporal robustness，非 OOS）

Q4−Q1（median_excess，h20）分年：breadth +0.80/+1.70/+9.06pp（2024/25/26）、new-high +1.18/+2.82/+3.89pp——**方向三年一致**，2026 更强（注意 2026 后段 h40 删失：n_obs_h 逐年 11220/44955/25356）。amount 轴无 2025/2026 Q1 格（§4 趋势退化所致）。

## 7. Sector retrospective companion（NON-PIT，不得入实时系统）

按 2026-09-21 快照回溯，h20 median_excess：14 门类全部为负（−0.4 ~ −6.5pp），R/I/F 最弱、B/E 最强；制造业 n=19,002 占 69.3%，统计权重高度不平衡——**只报 n 与分布，不评最好/最差**。83 大类覆盖诊断已生成（n≥100 的类 43 个）供 T4.4 粒度决策，未做出值对比。

## 8. 七道 Gate（全 PASS）

G1 事件守恒（27,422 双表）/ G2 context PIT（40 事件×3 轴物理截断重算 0 mismatch；短史事件 null）/ G3 状态对账（9 列 exact）/ G4 outcome 对账（6 指标×3H 值+null 模式 exact）/ G5 隔离（context 表无 future 字段、outcome 表无 state 字段）/ G6 依赖与双权（two-way cluster+双 estimand 落盘）/ G7 双跑（as-of 分位与 outcome 全量双跑 hash 一致）。

## 9. 阶段放行

七道 Gate 全 PASS。T4.3 结论冻结：市场背景（breadth/new-high，PIT expanding rank）对 breakout 后路径存在方向三年稳定、日等权口径下仍成立的条件差异；个股 load/ref60 状态与市场背景近乎可加（interaction≈0）。T4.4（Context Structure Discovery：门类 vs 大类粒度、层级结构、PIT 行业数据必要性评估）待开工令。
