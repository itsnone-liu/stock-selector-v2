# T3 V4 动态风险集与条件路径比较报告

- 基线：`aa249cc`（T3 V3 轨迹事实层 PASS，27,422 个 lifecycle20 冻结事件）
- 状态：**V4 五道 Gate 全部 PASS**
- 研究性质：**observational conditional association research**。本报告所有数字都是"站在 tau 当天、只使用当时可见状态"与"随后路径"之间的条件关联描述；不是因果推断，不是交易预测模型，不构成买卖规则。
- 版本链：`dynamic_riskset_v1` / `dynamic_forward_v1` / `dynamic_bins_v1` / `dynamic_contrast_v1` / `event_overlap_audit_v1`（见 `output/research/t3_v4/dynamic_run_manifest.json`）。

## 1. 研究问题

从 V3 的"突破之后总体发生了什么"升级为：

> 站在 tau 当天，只根据截至当天已经发生的状态，在同一风险集内，不同状态的事件随后路径有什么差异？

核心不变量：`state information <= asof tau`，`outcome > tau`。禁止用 T20/T40 的已知结果反推 tau=10 的状态组。

## 2. Schema gate：换手率单位先行澄清（开工令前置项）

开工令要求在解释 quartile/阈值之前写死 `cum_turnover_since_t0` 的单位。冻结结论：

- 数据源字段：baostock `turn`，单位为**换手率百分点**（0.6946 = 0.6946%）。
- 实证核验（6 只股票，横跨银行/小盘/成长大盘）：`流通股本 ≈ volume × 100 / turn` 与已知股本之比 0.966–1.031。若 turn 是 0–1 比例，隐含股本将小 100 倍，直接排除。
- 因此：`cum_turnover_since_t0` = **百分点·日累加**（tau=20 中位数 79.77 ≈ 突破以来累计换手 79.77%）；`mean_turnover_since_t0` = 每有效交易日百分点；`turnover_ratio_pre20` / `volume_ratio_pre20` 为无量纲比值。
- 该单位契约写入模块 docstring 与 run manifest（`units_schema_gate` 字段）。

## 3. 风险集与 eligibility（与 outcome horizon 分离）

对每个 `tau ∈ {0,1,5,10,20}`（5/10/20 为 primary，0 为 baseline，1 为 sensitivity；40 不设动态风险集）：

- **基础风险集** = 事件真实走到 tau（市场日历行落在数据集内）。不要求 Y20 存在、不要求创新高、不要求生命周期存活。
- **前向可观测**（per Δ∈{5,10,20}）只由日历可知条件决定：`asof 市场日位置 + Δ ≤ dataset_end 位置`。Gate 3 证明该 flag 是日历的纯函数（137,110 行 0 错配）。
- `is_sample_end` / label availability 只做 attrition 记账，不做筛选。
- tau=20+Δ20 恰好到 T40，全部前向结果均可从 V3 冻结面板派生，无需重算个股。

| tau | 基础风险集 | eligible Δ5 | Δ10 | Δ20 |
|---:|---:|---:|---:|---:|
| 0 | 27,422 | 27,422 | 27,422 | 27,289 |
| 1 | 27,422 | 27,422 | 27,422 | 27,285 |
| 5 | 27,422 | 27,422 | 27,344 | 26,933 |
| 10 | 27,422 | 27,344 | 27,289 | 26,478 |
| 20 | 27,289 | 26,933 | 26,478 | 26,237 |

前向结果端点可用率 ≈ 99.6%（112 个 adj 因子缺失事件 + 少量停牌端点），逐分析单元记录于 `dynamic_attrition.csv`（base → exposure → future → final 四级，tau=20 最大流失 ≈5.3%，无全局 complete-case 删除）。

## 4. 前向结果定义（以 tau 为起点，全部未来事实）

窗口 `W = (tau, tau+Δ]`，`r_t = exp(crl_t − crl_tau)`：

- `fwd_raw_log` / `fwd_mkt_excess_log`：两端有效观测的 log 收益与超额（恒等式 `mex_end − mex_tau`）；
- `future_max_gain` = `max r_t − 1`；
- `future_max_drawdown` = `max(1 − r_t/runmax_t)`，runmax 从 tau 现价起算（同时覆盖"从 tau 价下行"与"途中创新高后回落的峰谷回撤"——两类回撤不再混为一谈）；
- `new_high_within` = ∃t: `crl_t > running_peak_return_tau`（严格超过 tau 前峰值）；`days_to_next_high` 为首次市场日数；
- `lose_ref20_within` / `lose_t0_close_within` / `recover_current_peak_within`：原子布尔事实（`lose_*` 为原始价事实，不依赖复权基准，因子缺失事件上仍可观测）；
- 窗口无有效观测的分量记 null，缺失不填充。

实现勘误（构建期自查发现并修复，已进入冻结产物）：初版 `new_high_within` 误用 `exp(peak_asof)` 直接与 asof 基准比率比较，等价于把阈值抬高/压低 `crl_tau`；对深回撤事件会大量误判创新高（单格 58.6% vs 真值 15.7%）。修复后以独立代码路径全量复算 26,367 行 0 错配。教训已记入项目记忆：相对基准比较必须换算到同一基准。

## 5. 状态维度（预注册四个，不扫字段）

A 价格持续：`drawdown_from_running_peak`、`days_since_running_peak`、`new_high_count_to_tau`、`close_rel_t0_log`；B 参与度：`volume_ratio_pre20`、`turnover_ratio_pre20`、`cum_turnover_since_t0`、`mean_turnover_since_t0`；C 成本位置：`close_vs_anchored_vwap`（含有效观测数）；D 结构位置：`distance_to_ref20`、`distance_to_ref60`、`t0_ref60_breakout`（T0 已知事实，跨 tau 恒定）。

不造 `trend_score` / `health_score` 等综合分；先研究状态空间。tau=0/1 处价格持续类变量部分退化（全员同值 → 四分位退化单格），属预期并在产物中以 n=0 格如实呈现。

状态分布快照（连续层先行，详细见 `dynamic_state_distributions.csv`）：

| tau | dd 中位 | 距峰天数中位 | 累计换手中位 | vs VWAP 中位 | 距 ref20 中位 |
|---:|---:|---:|---:|---:|---:|
| 5 | 2.92% | 3 | 25.21 | −0.49% | +1.57% |
| 10 | 4.71% | 6 | 43.95 | −0.72% | +1.83% |
| 20 | 8.24% | 12 | 79.77 | −1.72% | +1.35% |

## 6. 分箱规则（先连续、后分组；切点预注册）

- quartile：同一 tau 风险集内部 average-rank 分位（ties 同格），不看 outcome 调切点；
- 天然零点：`close_vs_anchored_vwap` / `distance_to_ref20` / `distance_to_ref60` 的 `>0 / <=0`；`volume_ratio_pre20` 的 `>1 / <=1`（secondary）；
- 二维组合（仅此一组）：回撤中位数分割（浅/深）× `turnover_ratio_pre20>1`（保持/衰减）四格；
- 比较顺序固定：primary = `Q4 − Q1`（或 top−bottom），并报告 Q1→Q2→Q3→Q4 单调性；不做 6 对两两比较。

不确定性：所有 primary contrast 同时报告 **code6 聚类** 与 **as-of 日历日聚类** 两套 cluster bootstrap 95% CI（B=1000，per-family 确定性种子，percentile 法）。正式检验仅对 11 个 quartile 变量的 Q4−Q1 中位超额收益差做 Holm 校正（family = metric×tau×Δ）；天然零点/vr1/flag/2d 为描述层，不进 Holm 家族，其 p 值一律 exploratory。bootstrap 双侧 p 下限 = 2/(B+1)=0.002。

`mean_turnover_since_t0` 与 `cum_turnover_since_t0`、`volume_ratio_pre20` 与 `turnover_ratio_pre20` 机械上近似互为拷贝（秩相关≈1），稳定性判断按维度族计数，不按变量个数重复计票。

## 7. 五道 Gate

| Gate | 结果 | 证据 |
|---|---|---|
| 1 Risk-set PIT | **PASS** | 物理截断至 as-of 日后经冻结 V3 builder 重建状态，540 项比较 0 mismatch（覆盖 ordinary / adj 缺失 / sample-end / 换手缺失 / 各 weekday） |
| 2 Forward Isolation | **PASS** | 原始数据独立重算全部前向结果 1,408 项 0 mismatch；面板侧 source_date≤asof 掩码重算 238 项 0 错配；未来端点 source_date 严格 > asof |
| 3 Calendar Eligibility | **PASS** | 137,110 行 eligible flag 与市场日历纯函数 0 错配；产物与 event_labels 列交集为空 |
| 4 Overlap / Dependency | **PASS** | `event_overlap_audit.json` 完整（见 §8） |
| 5 Determinism | **PASS** | 全产物（含 bootstrap）进程内全量双跑，9 项内容 hash 全一致 |

## 8. 事件重叠与日历共同冲击审计

冻结事件宇宙不变（27,422 / 4,781 股 / 单股最多 21 个事件）。**不删除重叠事件**，全部依赖结构进入推断：

- 同股事件对 83,014 对；breakout 间距 `<5` 440 对、`<10` 592 对、`<20` 1,960 对、`<40` 8,250 对、`≥40` 71,772 对；
- 40 日轨迹窗与同股他事件重叠：11,651 对，波及 10,605 个事件（**38.7%**）；
- 前向窗重叠（同 tau 同 Δ 窗口相交）：tau=10/Δ10 档 1,098 个事件（4.0%）；
- 日历 cohort：tau=10 时 644 个 as-of 日，日均 42.6 个事件、单日最多 491 个——共同市场冲击实质存在，正是必须报 date-cluster CI 的原因。

## 9. 条件路径比较：主要发现（conditional association 措辞）

### 9.1 稳定性矩阵（Q4−Q1 中位超额，×100=百分点；`*`=Holm 后显著，`M`=四格单调）

```
                             tau=0        tau=1        tau=5        tau=10       tau=20
                             d5  d10 d20  d5  d10 d20  d5  d10 d20  d5  d10 d20  d5  d10 d20
drawdown_from_running_peak    ·   ·   ·  -0.27-0.83-1.12 -0.39-1.44-2.16 -0.74-1.70-1.78 -0.15+0.16+0.21
                             *   *   *    *   *   *    *   *   *    ·   ·   ·
days_since_running_peak       ·   ·   ·  +0.21+0.07+0.28 +0.11-0.35-0.05 +0.04-0.45+0.40 +0.21+0.84+1.29
                             ·   ·   *    ·   ·   *    ·   ·   **
new_high_count_to_tau         ·   ·   ·  -0.21-0.07-0.28 -0.08+0.32-0.17 -0.04+0.30-0.55 -0.37-0.92-1.37
                             ·   ·   *    ·   ·   ***  ·   ·   **
close_rel_t0_log              ·   ·   ·  -0.40+0.01-0.50 -0.34+0.12-0.13 +0.04+0.30-0.36 -0.60-1.26-1.92
                             ·   ·   *    ·   *   ***  ·   ·   **
volume_ratio_pre20          -1.03-1.66-2.29 -1.23-1.67-2.94 -0.66-0.60-1.30 -0.29+0.04-1.14 -0.77-1.17-1.94
                           **  **  **    **  **  **    *   *   *    ·   ·   *    *   *   *
turnover_ratio_pre20        （与 volume_ratio 数值几乎相同，同维度族）
cum_turnover_since_t0       -2.07-3.44-5.84 -2.43-3.81-6.18 -1.86-3.24-5.12 -1.43-2.53-4.00 -0.74-1.61-2.56
                           **  **  **    **  **  **    **  **  **    **  **  **    **  **  *
mean_turnover_since_t0      （与 cum_turnover 同维度族）
close_vs_anchored_vwap      -1.13-1.70-3.13 -0.60-0.15-0.91 -0.19+0.71+0.66 +0.09+0.60+0.31 -0.21-0.83-1.09
                           **  *   *     *   ·   *    ·   *   *    ·   *   *    ·   ·   *
distance_to_ref20          -1.36-2.12-3.40 -1.15-1.34-2.02 -0.51-0.17-0.77 -0.13-0.06-1.16 -0.60-1.39-2.13
                           **  **  **    **  *   **    *   ·   *    ·   ·   **    *   *   *
distance_to_ref60          +0.12-0.56-1.96 +0.01-0.85-1.82 -0.69-0.75-1.16 -0.33-0.13-0.10 -0.12-0.30-1.02
                           ·   *   **    *   ·   ·    ·   ·   ·    ·   ·   ·    ·   ·   *
```
（tau=0 的价格持续四变量退化（全员同值），无 diff，属预期。）

### 9.2 发现一：参与度/换手维度是最一致的条件结构（情形 B 候选）

`cum_turnover_since_t0` 的 Q4−Q1 在 **全部 15 个 tau×Δ 格** Holm 后显著、14/15 格单调，量级 −0.7 至 −6.2 个百分点，且在 stock 与 date 两套聚类下方向一致。decile 曲线（tau=10→Δ20）显示清晰剂量梯度：

| decile | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|---|
| 中位超额% | −0.89 | −0.64 | −1.09 | −1.40 | −1.69 | −1.63 | −2.77 | −3.11 | −4.55 | −6.17 |
| 中位 MDD% | 6.9 | 8.2 | 9.3 | 9.9 | 10.6 | 11.0 | 11.9 | 13.2 | 14.5 | 16.9 |
| P(new high) | 0.57 | 0.60 | 0.57 | 0.56 | 0.56 | 0.54 | 0.52 | 0.50 | 0.47 | 0.40 |

描述性读法：**到 tau 为止累计换手越重的事件，随后 Δ 日的中位超额收益越低、未来回撤越深、创新高概率越弱**——收益与下行风险梯度陡峭，创新高能力梯度同向但较平缓，跨 tau、跨 horizon 稳定。措辞为条件关联；不解释为"主力出货"因果。

### 9.3 发现二：结构伸展在 tau=20 集中显现

tau=20 时"伸展类"状态（`close_rel_t0_log` 高、`new_high_count` 多、`distance_to_ref20` 远、深回撤后仍高）一致与更差前向路径相关（−0.9 至 −2.1pp，多数 Holm 后显著）；而 `days_since_running_peak`（久未创新高）在 tau=20 反转为**正**（Δ10 +0.84、Δ20 +1.29pp，Holm 后显著）。decile 曲线（tau=20/Δ10）显示这组"时间消化"事件的组合特征：中位超额从 D1 −1.65% 改善到 D10 −0.56%，但 P(new high) 从 D1 0.79 递减到 D10 0.15——**改善的是中位路径/回撤面，不是短期再突破动能**。描述性读法：突破 20 日后，"高位高热度"事件的后续路径差于"时间消化过、离前高有距离"的事件。

### 9.4 发现三：早期（tau=0/1）主要是热度维度在分层

tau=0/1 处价格持续类变量尚未展开（多数退化或弱），而换手/量比与 `distance_to_ref20` 已经强分层（−1.0 至 −6.2pp，全显著）。`t0_ref60_breakout=True`（T0 同时越过 ref60，n=9,430）的 top−bottom 差在 Δ20 全 tau 序列为 −2.25 / −2.39 / −2.00 / −0.95 / +0.18pp（tau=0→20，描述层，未进 Holm 家族）：双突破事件随后路径条件更差且从 T0 即显现，到 tau=20 收敛消失。

### 9.5 天然零点与二维组合（描述层）

- `close_vs_anchored_vwap` 的 above/below0：tau=10/Δ10 时 above0 组中位超额 −0.82% vs below0 −1.48%（top−bottom +0.67pp，date 聚类 CI (0.23,+1.06)%），且 above0 组 P(new high) 明显更高（0.67 vs 0.23）——价格在成本代理之上与更好的路径面同现；但该 diff 在不同 tau/Δ 间方向不稳（tau=5 +0.35、tau=10 +0.28、tau=20 −0.46pp @Δ20），仍属描述层。
- 二维四格（浅/深回撤 × 保持/衰减参与，Δ20）：三个 primary tau 下最优格均为 **shallow_decay**（tau=5：−0.37%；tau=10：−1.01%；tau=20：−1.16%），最差格均为 **deep_keep**（−2.74% / −2.89% / −2.92%）；"参与衰减"格在浅、深两组中一致优于"参与保持"格。与发现一方向一致。

### 9.6 整体路径基准（无条件）

全体事件的前向路径中位（超额）：tau=10/Δ20 为 −2.0% 附近；P(new high) 从 tau=0/Δ5 的 0.71 单调衰减到 tau=20/Δ5 的 0.23。任何条件组的解释都应相对这一基准。

## 10. V4 判读（对应开工令情形 A/B/C）

- **不满足情形 A**（几乎无稳定差异）：至少"参与度/换手"一个维度族展现跨 tau、跨 Δ、跨指标（收益/回撤/创新高）方向一致、双聚类稳健、Holm 后存活的条件结构。
- **情形 B 候选（可进入 V5）**：参与度维度族（`cum_turnover_since_t0` 为代表；volume/turnover ratio 为同族佐证）＋ tau=20 的结构伸展区（`close_rel_t0_log` / `new_high_count_to_tau` / `days_since_running_peak`）。二者描述的是同一枚硬币的两面：**热度消化程度**。
- **仍属情形 C（探索性，不升格）**：anchored VWAP 天然零点、t0_ref60 旗标、tau≤10 的回撤分位（tau=20 处符号翻转）。这些只有单点/单窗/部分指标显著，保持描述性记录。
- 边界重申：以上全部为 conditional association。同一牛市 cohort、同股多事件等依赖结构已按 §8 处理，但不改变观测性质；未做任何因果识别。

## 11. 产物清单（state 与 future 物理分文件）

| 产物 | 行数 | 内容 |
|---|---:|---|
| `dynamic_riskset.parquet` | 137,110 | event×tau：as-of 状态 + 日历 eligibility（sha256 7aa0fd4f…） |
| `dynamic_forward_outcomes.parquet` | 406,720 | event×tau×Δ：纯未来结果（9ff494e1…） |
| `dynamic_state_bins.parquet` | 2,330,870 | event×tau×var×binset 分箱（76faf81c…） |
| `dynamic_contrasts.parquet` | — | 预注册对比 + 双聚类 CI + Holm（d2b8124e…） |
| `dynamic_contrasts_2d.parquet` | — | 二维四格（3cc0ec8b…） |
| `dynamic_conditional_curves.parquet` | — | decile 条件曲线（0c8364f1…） |
| `dynamic_attrition.csv` / `dynamic_state_distributions.csv` | — | 流失账 / 状态分布 |
| `event_overlap_audit.json` / `dynamic_integrity_gates.json` / `dynamic_determinism_check.json` / `dynamic_run_manifest.json` | — | 审计与门禁证据 |

已知无害瑕疵（如实披露）：`t0_ref60_breakout` 对 112 个 adj 因子缺失事件取 False（无第三类）；这些事件因无复权基准进不了任何 n_final，不影响对比格。

## 12. 禁止事项自查

未训练任何模型（无 XGBoost/LGBM/classifier/feature selection/importance）；未做阈值寻优（所有切点预注册或天然零点）；未按 outcome 删样本；未用未来生命周期定义当前存活；未形成买卖规则；未比较四种入场策略；未改动 V2/V3 口径；`event_labels` 全程未 import/join（Gate 3 结构性证明）。

## 13. 边界：V5 之前的判断

V4 的结论是：**突破后的路径并非对当时状态不可分——热度/伸展状态携带稳定的条件路径差异，其中"参与度消化程度"最强**。若进入 T3 V5（状态组合与实时判别框架），应从参与度维度族＋tau=20 结构伸展区出发做状态合并研究；四种入场策略比较仍留待状态模型稳定之后。在此之前，本报告所有分组差异不构成入场或规避建议。
