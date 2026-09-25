# T7 实施方案：REDUCE 后资本再扩张研究（Capital Re-Expansion）

> 状态：**DRAFT——待用户审计后作为 T7.0 contract 输入冻结**
> 依据：T6 最终冻结链（`0f3783d→50575f5→a4e8402→bf0f44f→52ea1f4→69a5bfd`）+ 用户 T7 方向十五节（2026-09-25）
> 数据事实核查（本方案撰写时实测）：`data/t4/sector_map/csrc_industry_snapshot.json` 为单一 as-of 日期
> 2026-09-21 的 84 证监会行业 × 5,555 股成员映射——**NON-PIT 回溯快照，且无任何动态 sector 指标**；
> e2_sector_context 仅有行业+两融上下文（PIT：T-1 margin）。T7 的 sector 状态必须自行构造（§3.4）。

## 0. 定位与核心问题

**核心问题（唯一）**：发生 REDUCE 以后，什么情况下值得重新承担风险，什么情况下宁可放弃后续
上涨也不应该 ADD？

**研究对象的定性**：不是"真假恢复预测模型"，而是 **False ADD Cost 与 Missed Recovery Cost
之间的可解释、可验证的风险—机会成本交换结构**。两个错误不等价：

| | 后续真恢复 | 后续无恢复 |
|---|---|---|
| **ADD** | 抓住恢复 | **False ADD**（二次 drawdown/再 REDUCE/资本重套/交易成本/terminal failure） |
| **不 ADD / 延迟** | **Missed Recovery**（少赚） | 正确规避 |

**目标命题（待检验，非结论）**：在 REDUCE 后，单日强反弹本身不是充分的资本再扩张条件；
若反弹伴随某些成交/路径结构，立即恢复 exposure 会显著提高 false-ADD 风险；延迟或确认
机制能减少多少二次风险、为此放弃多少真实 recovery upside，形成明确的 frontier。

## 1. 边界与锁（T7 不推翻什么）

1. **只读冻结产物**：T4（E-class 初始风险预算）、T5（C-state/transition/path/P1-P3 operator）、
   T6（全部 frozen claims）。T7 找到更好的 ADD 方法**不回溯修改任何 T6 claim**。
2. **研究入口固定**：T0 → E-class → 持仓 → 恶化 → REDUCE → **T7 从这里开始**。
3. **T7A / T7B 分离**：第一轮只做 **WHEN to re-expand（timing）**，不做 HOW MUCH（sizing）。
   全程固定 `direct_chase | P2_balanced` 为 reference cell（与 T6 一致）。
4. **Policy Lock**：T7.0–T7.4 禁止改动 T5 operator（源码 diff 必须为空）；T7.5 只在
   counterfactual 层模拟 ADD 决策变体，不回写任何生产规则。真正修改 Policy V1 不属于
   T7——T7 交付的是 frontier 证据，改规则是之后的独立决策。

## 2. 阶段总览

| 阶段 | 内容 | 性质 | 冻结产物目录 |
|---|---|---|---|
| T7.0 | Contract + Post-REDUCE Fact Layer（含 sector PIT 审计） | 数据/契约 | `output/research/t7/00_path_factlayer/` |
| T7.1 | Path Anatomy（trajectory 描述性分层） | 研究 | `01_path_anatomy/` |
| T7.2 | Hot-Bounce × Volume × Turnover 正交分层（H7-A 检验） | 研究 | `02_hotbounce/` |
| T7.3 | Recovery Separator + Market/Sector Context（H7-B） | 研究 | `03_separator/` |
| T7.4 | F6 预注册拆解（taxonomy 先冻结） | 研究 | `04_f6_decomposition/` |
| T7.5 | ADD Policy Counterfactual（四 family + frontier） | 决策分析 | `05_policy_counterfactual/` |
| T7.6 | Synthesis（aggregation-only，同 T6.5 模式） | 综合 | `05_synthesis/ → 06_synthesis/` |

每阶段流程沿用 T6 纪律：code → products → Gate → report → 独立审计 → freeze commit；
下一阶段只读上一冻结阶段。报告数字只从 report_data.json；claim 必须有 CI+Holm。

## 3. T7.0 Contract + Post-REDUCE Fact Layer

### 3.1 Anchor 定义（与 T6.2 严格兼容）

- **R0** = 有效 REDUCE 日（连续 REDUCE 前移合并，同 T6.2 contract `recycling` 定义——
  保证 T7 anchor 集与 T6.2 cycle 集逐位一致，G8 守恒沿用）。
- 观察窗：R+1 … R+40（有效观察日；censored 右截断如实标记）。
- 研究单元：`(event_id, R0)`。**不要求 A0 存在**（无恢复路径同样是被研究对象）。

### 3.2 产物 schema

**`t7_0_path_master.parquet`（long）**：`event_id, stock_code, T0_date, segment, E_class,
r0_day, day_offset(R+1..R+40), price_log, ret_1d_log, volume_ratio, turnover_load,
efficiency_signed_3, drawdown_from_peak_log, dist_ref20, mkt_breadth_5d, mkt_new_high_20d,
sector_*（若 §3.4 通过）, resolution_state, censored`。

**`t7_0_anchor_master.parquet`（宽）**：每 (event_id, R0) 一行的预注册 trajectory 摘要
（全部 decision-time，见 §3.3）+ 结局（H5/H10/H20 ret、MFE/MAE after R0、再 REDUCE 日、
EXIT 日、terminal failure、A0 日（若存在）、cycle type、false_recovery（继承 T6.3-R1 冻结
trigger 口径））。

**`t7_contract.json`**：全部预注册（thresholds/path_vars/bins/taxonomy/policy_defs/
statistics_prereg/claim_rules）——T7.0 冻结后与 T6 contract 同等不可变。

### 3.3 Trajectory 变量预注册清单（snapshot → trajectory 是 T7 与 T6 的本质差异）

全部以"截至 R+k 的窗口"定义，decision-time 可得（G-No Future Feature 的检查锚点）：

| 组 | 变量（候选名） | 定义要点 |
|---|---|---|
| 反弹 | `bounce_ret_Rk`, `max_bounce_Rk`, `consec_up_days_Rk` | R0→R+k 收益 / 窗口内最大反弹 / 连续上涨天数 |
| 量能 | `volume_ratio_Rk`（vs 预注册基准窗 R-20..R-1 均量）, `vol_decay_Rk`（首日放量后 2-3 日量比衰减）, `consec_shrink_days_Rk` | 缩量/放量/持续性 |
| 换手 | `turnover_traj_Rk`（高→快速回落 vs 持续高位，预注册斜率/水平二元刻画） | T6.3 签名的动态化 |
| 效率 | `eff_traj_Rk`（瞬间转正 vs 连续改善：R+1..R+k 内 efficiency>0 的天数占比） | |
| 修复 | `dd_repair_ratio_Rk` =（R0 后低点起的恢复幅度）/（R0 前恶化幅度）；`ref20_repair_Rk` = dist_ref20 回正程度 | **定义在此冻结，禁止看结果后调** |
| 新高 | `new_high_after_R0`（是否创 R0 前峰值新高） | 价格持续性 |

### 3.4 Sector PIT 审计（T7.0 Step 0，独立子任务）

实测现状：行业成员映射仅单一 NON-PIT 快照；无动态 sector 指标。两条路线，**T7.0 contract
冻结时由用户拍板**：

- **路线 A（推荐）**：用日线 × 行业映射自行构造 sector 日级指标（sector_breadth /
  sector_relative_strength / sector_turnover），标注 **QUASI-PIT**（成员集含回溯归属偏差：
  2026-09-21 映射回溯应用到全期）。用途限制：T7.3 条件分层 + 描述，**EXPLORATORY 强制**，
  永不进入 primary 结论或规则层（沿用 T6 G9 sector 隔离 gate）。
- **路线 B**：若用户认定回溯偏差不可接受，T7 维持 T6 的 UNAVAILABLE 边界，T7.3 只做
  market context。

### 3.5 T7.0 Gate 增量

- G8 守恒：anchor 集 == T6.2 cycle 集（R0 定义一致）；path_master 行数 == anchor×观察窗
  内有效日数。
- G-No Future Feature 首检：每个特征列必须由 cutoff 参数化的 accessor 生成（读 >cutoff
  数据 raise）；gate 抽查若干 (anchor, k) 用真实未来数据重放必须报错/失配。
- 沿用 T6 G1-G11 全框架（lineage/不可变/预注册/no-tuning/统计完整性/重放/anti-story）。

## 4. T7.1 Path Anatomy（描述性）

按结局三组（true recovery / false recovery / no recovery，口径继承 T6.3-R1 冻结定义）对比
§3.3 trajectory 变量分布：median level CI + 组间 diff CI（cluster bootstrap
{stock_code, T0_date}，Holm within family；val+conf primary，dev reference）。
产出：trajectory 变量的"哪些组间在双段分离"基线表——为 T7.2/T7.3 提供描述性基础，
**不产生 separator 主张**。

## 5. T7.2 Hot-Bounce × Volume × Turnover 正交分层（H7-A 检验）

- **H7-A（预注册假设）**：REDUCE 后的大幅反弹 + 放量 + 高换手组合不是可靠的 repair
  confirmation（与后续更差路径相联系）。
- 分层维度三分（各 3 档）：反弹幅度（bounce_ret_R5）× 量能（volume_ratio）× 换手
  （turnover）→ 27 cells。**bin 边界来自 development 段分位数（tertile），冻结于
  contract；val/conf 仅应用**——G-No Threshold Search 的正面满足（无搜索）。
- 每 cell 报告：H5/H10/H20 ret、MFE/MAE after R0、再 REDUCE 率、EXIT 率、terminal
  failure 率、recovery persistence（H10 后回撤不破 R0 低点的比例）、capital efficiency。
- 关键 cell 预注册对比（Holm family）："强反弹+缩量" vs "强反弹+放量" vs "强反弹+放量+
  高换手"（即用户经验规则的统计结构检验——**检验它，不是采纳它**）。
- 明确措辞纪律：所有结论为 conditional association，不写"主力出货"等不可观测机制语言。

## 6. T7.3 Recovery Separator + Market/Sector Context（H7-B）

- **H7-B（预注册假设）**：热反弹中混合两类终局——新资金接力（后续持续上涨）与原资金
  利用反弹退出（后续再恶化）；T7 研究的是**这两类终局能否从可观测量价轨迹进一步分离**，
  不声称能观测"主力"。
- 方法：conditional on 热反弹 cell（T7.2 的强+放+高换手），检验 §3.3 持续性变量
  （价格持续性/量能持续性/换手轨迹/效率轨迹/repair completeness）对后续结局的分离度
  （level CI + diff CI + Holm）。**association-not-prediction 措辞强制**（claim 规则 §11）。
- Market context：复用 T6.4 冻结的 M_STRONG/M_NEUTRAL/M_WEAK（不重定义），检验同签名
  条件下市场层是否修正 trajectory 分离度（描述性 + 交互仅在有预注册对比时检验）。
- Sector context（仅当 §3.4 路线 A 通过）：**同一热反弹，板块同步修复 vs 个股独立反弹**
  的结局差——QUASI-PIT + EXPLORATORY 强制，Gate 沿用 sector 隔离（primary 块零 sector）。

## 7. T7.4 F6 预注册拆解

- **G-F6 Lock**：taxonomy JSON 于读取任何 F6 outcome 分布**之前**冻结进 contract commit
  （sha256 + 时序由 gate 校验）。候选方向（仅为 taxonomy 候选，不是结论）：持续缓慢恶化 /
  反复 REDUCE↔ADD / 热反弹后失败 / 无明显信号突然破坏 / 长期高暴露滞留。
- taxonomy 设计输入 = T6 已知现象（C303/C306）+ T7.0-T7.3 冻结变量体系；分类器为首中
  判定（同 T6.3 F1-F6 纪律），残差类保留（F6'），**禁止看分布后拆残差**。
- 产出：F6 → 预注册子类的分布 + 子类 × 结局关联（val/conf 分离，cluster bootstrap）。

## 8. T7.5 ADD Policy Counterfactual（唯一触碰 policy 的阶段）

### 8.1 四个 policy family（全部预注册）

| Family | 定义 | 回答 |
|---|---|---|
| **A Current** | 冻结 T5 当前 ADD 规则原样 | benchmark |
| **B Delay** | 出现 ADD 信号 → 延迟 N 日（N∈{1,2,3,5} 全部报告成曲线，primary 对比预注册 N=3；不挑最优） | 单纯多等有没有价值 |
| **C Repair confirmation** | ADD eligibility + 持续修复证据；**具体判据在 T7.2/T7.3 冻结后、T7.5 开工前的 contract 增补中预注册**（从预注册胜出结构推导，非临时挑指标） | 确认机制值多少 |
| **D Hot-bounce veto** | 原规则允许 ADD 时，若命中"强反弹+放量+高换手"（T7.2 冻结 cell 定义）→ 禁止/延迟 ADD | 用户经验规则的正式检验 |

### 8.2 预注册错误成本定义（contract 冻结，三选一由 T7.0 定稿）

- **False ADD**（候选口径）：ADD 后 W_fa=10 有效观察日内发生 再次 REDUCE / EXIT /
  episode abs_mdd 触 severe 之一；成本 = 该 ADD 起至下次 REDUCE/EXIT/窗口末的 ret。
- **Missed Recovery**（候选口径）：策略未 ADD 但该 cycle 在窗口内达到真恢复标准
  （候选：H20 from R0 ≥ development 段 RECOVERED cycle 的中位 H20；或 dist_ref20 回正
  且未再 REDUCE）；成本 = 少赚的 ret。
- W_fa 与真恢复标准**禁止网格搜索**，用 development 段一次定标后冻结。

### 8.3 指标四组（每 policy × 每 segment）

收益获取：terminal return / MFE captured / recovery upside captured；
风险：MDD / MAE after ADD / severe failure / terminal failure；
资本效率：average exposure / exposure-days / return per exposure-day / capital released days；
错误成本：False ADD rate & loss / Missed Recovery rate & upside。

### 8.4 Counterfactual 守恒（G-Counterfactual Conservation）

复用 T5.8 生命周期模拟器（只读 import）：所有 policy variant 在**同一 universe、同一 T0、
同一 entry、同一 price clock、同一 transaction cost** 下重放，唯一差异 = ADD 触发判定。
Gate 机制：各 variant 的 pre-ADD 逐日状态序列必须逐位一致（分歧只允许出现在 ADD 决策
差异之后）；RNG 用同 SeedSequence 子流（policy 维度入 enums）。

### 8.5 统计与呈现

- 配对结构：同 cycle 在两 policy 下的结果做 **matched within-cycle diff**，cluster
  bootstrap {stock_code, T0_date} + Holm within family。
- **Policy frontier**（核心交付）：x=recovery upside captured，y=false-ADD 风险
  （rate/loss），四 family 的点 + CI 椭圆——回答"为减少一次 false ADD 要放弃多少真实
  recovery"。**禁止单轴收益排名**（不排冠军，claim 规则强制双轴）。

## 9. T7.6 Synthesis

同 T6.5 模式：aggregation-only（G14 同款断言）、引用完整性（claims + decision_mapping
cites 必须落冻结 registry）、三类开放边界延续（separator 若仍未找到 / F6' 残差 /
sector QUASI-PIT 限制）+ T7 新增边界（counterfactual 的模型假设边界：无滑点变化、
同 price clock）。

## 10. Gate 体系汇总

**沿用 T6 G1-G11 全框架**（lineage sha256 / 上游不可变 / outcome 分离 / segment 隔离 /
预注册+符号+引用+语义 / no-tuning / 守恒 / 统计完整性+NaN 一致性 / 独立重算 / SeedSequence
重放 / anti-story + 跨阶段 registry）。**新增五硬 Gate**：

| Gate | 检查机制 |
|---|---|
| **G-Policy Lock** | T7.0–T7.4：`git diff <t5_freeze> -- src/ operators 相关路径` 为空；T7.5：counterfactual 模块对 T5 代码 import-only（写操作扫描） |
| **G-No Threshold Search** | T6 G7 扩展：禁止数值网格循环；所有 bin/阈值旁的字面量必须出现在 contract 文本（0/1 豁免沿用）；分位边界必须标注 development-only 计算路径 |
| **G-No Future Feature** | 特征 accessor 强制 (df, cutoff) 签名，读越界 raise；gate 抽查若干 (anchor,k) 用 +1 日 cutoff 重放必须失配；path_master 每特征带 decision_offset 元数据 |
| **G-F6 Lock** | taxonomy sha256 与首份 F6 outcome 产物的创建时序校验（contract commit 早于读取）；taxonomy 文本 diff 为空 |
| **G-Counterfactual Conservation** | 各 policy variant pre-ADD 状态序列逐位一致重放比对 + universe/T0/entry/cost 五同断言 |

## 11. Claim Registry 规则（C7xx，enum 沿用 T6 五值）

新增四条强制规则（其余沿用 T6 claim_rules）：

1. **Association-not-prediction**：separator 类 claim 措辞必须为"X 与后续路径相联系"，
   禁止"X 预测/识别真假恢复"。
2. **双轴强制**：policy 类 claim 必须同时报 false-ADD 轴与 missed-recovery 轴坐标，
   禁止单轴（收益或风险）表述。
3. **Sector QUASI-PIT 隔离**：涉 sector 的 claim 一律 EXPLORATORY + 成员映射回溯偏差
   显式标注（不可分析 ≠ 无效应 的 T6 教训延续）。
4. **Counterfactual 边界**：T7.5 结论必须带"同 price clock/同 cost 假设下"限定词，
   不外推到执行层改善。

## 12. 统计规范

沿用 `src/t6/stats.py`（将迁移/引用为共享模块，不改语义——迁移本身过 G10 重放验证）：
B=2000、seed 派生 SeedSequence 子流（T7 各阶段定义自己的 enums 并在 contract 登记）、
percentile CI、Holm within family、双 cluster {stock_code, T0_date}、val+conf primary /
dev reference。新增：matched within-cycle diff（T7.5 配对 bootstrap）；delay 曲线为
描述性全家族（N∈{1,2,3,5} 全报）。

## 13. 冻结顺序与审计流程

```
T7.0 contract+factlayer → 用户审计 → freeze commit
  ↓ （每阶段：code→products→gate→report→审计→freeze commit；只读上游冻结）
T7.1 → T7.2 → T7.3 → T7.4 → T7.5 → T7.6
```

- commit 推 github main；output/research/t7 产物 `git add -f`（小 json/parquet 入库，
  大 parquet 只入 manifest sha）。
- 用户为每阶段唯一审计者；审计可要求 R1（解释层修正优先，统计重跑仅限计算 bug）。
- T6 全链保持只读——任何 T7 阶段 gate 都会校验 T6 冻结产物 sha 未变。

## 14. 待用户在 T7.0 contract 冻结时拍板的开放决策点

1. **观察窗长度**：R+40（本方案默认）是否够（terminal failure 的长尾可能超出）。
2. **W_fa（False ADD 窗口）与真恢复标准**：§8.2 三候选中选定（development 一次定标）。
3. **Delay primary N**：默认 N=3，可改（一次定，不搜索）。
4. **Sector 路线 A/B**：QUASI-PIT 构造 + EXPLORATORY，或维持 UNAVAILABLE。
5. **F6 taxonomy 候选清单**：§7 五方向是否增删（冻结前最后机会）。
6. **C family repair 判据的推导来源**：限定为 T7.2/T7.3 预注册对比中 Holm 幸存的
   结构（contract 增补时点冻结）。

---

**一句话收束**：T6 证明了"短期反弹不能证明结构修复，而假恢复路径在 REDUCE 日呈现更热
的短期签名"（条件关联）；T7 把这个知识变成决策问题——**为了减少一次 false ADD，愿意
放弃多少真实 recovery upside**——并用预注册的 counterfactual frontier 回答它。
