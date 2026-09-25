# T7 实施方案：REDUCE 后资本再扩张研究（Capital Re-Expansion）

> 状态：**DRAFT v2——审计修订版（8b19a96 v1 审计意见全部落地），待用户确认后作为 T7.0 contract 输入冻结**
> v2 核心修订（相对 v1）：①Feature/Outcome **物理三层隔离**（feature builder 永不能读 outcome 表）；
> ②decision horizon 与 outcome observation horizon **分离**（primary decision checkpoints = R+1/2/3/5）；
> ③False ADD 改 **outcome-based 定义**（非 action-based，消除策略自引用）；Missed Recovery 改
> **结构性恢复定义**（非 RECOVERED 样本分位定标）；④C-family 定性为 **derived policy**：T7.2/T7.3
> **DEV-only discovery → Policy Amendment Freeze → VAL/CONF 验证**（新增 G-Policy Derivation
> Isolation）；⑤Sector 拍板路线 A=QUASI-PIT exploratory sidecar，**C/D family 禁引 sector**；
> ⑥W_fa=10、Delay N=3、R+40、F6 五类+mandatory residual 全部冻结；⑦frontier 加 capital
> efficiency side panel；⑧matched diff 措辞=policy-path paired counterfactual。
> 依据：T6 最终冻结链（`0f3783d→50575f5→a4e8402→bf0f44f→52ea1f4→69a5bfd`）+ 用户 T7 方向
> 十五节 + T7 方案 v1 审计十五节（2026-09-25）。
> 数据事实核查（实测）：`data/t4/sector_map/csrc_industry_snapshot.json` = 单一 as-of 2026-09-21
> 的 84 证监会行业 × 5,555 股成员映射（NON-PIT）；全仓库无动态 sector 指标。

## 0. 定位与核心问题

**核心问题（唯一）**：发生 REDUCE 以后，什么情况下值得重新承担风险，什么情况下宁可放弃后续
上涨也不应该 ADD？

**研究对象的定性**：不是"真假恢复预测模型"，而是 **False ADD Cost 与 Missed Recovery Cost
之间的可解释、可验证的风险—机会成本交换结构**。两个错误不等价：

| | 后续真恢复 | 后续无恢复 |
|---|---|---|
| **ADD** | 抓住恢复 | **False ADD**（二次 drawdown/资本重套/交易成本/terminal failure） |
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
   counterfactual 层模拟 ADD 决策变体，不回写任何生产规则。

## 2. 阶段总览与段使用协议（v2 新增：derive/validate 分离链）

```
T7.0  Contract + Fact Layer（三层物理隔离；全段构建，无 outcome 分析）
  ↓
T7.1  Path Anatomy（全段描述性；不产生任何 separator/repair candidate）
  ↓
T7.2  Hot-Bounce Structure          ┐ DEV ONLY（discovery）
T7.3a Separator / Repair Candidate  ┘ Holm 幸存结构 → candidate 冻结清单
  ↓
【Policy Amendment Freeze】C1/C2/D veto/ Delay N/全部阈值写死（contract 增补 commit）
  ↓
T7.3b VAL 首次验证 → CONF 二次确认（验证冻结 candidate，不参与定义）
  ↓
T7.4  F6 预注册拆解（独立预注册；taxonomy 在读 F6 outcome 前冻结；全段报告）
  ↓
T7.5  Policy Counterfactual（Current/Delay/Repair/Veto；DEV 报告 + VAL/CONF primary）
  ↓
T7.6  Synthesis（aggregation-only）
```

**段使用铁律**：T7.2/T7.3a 只用 development；VAL/CONF 在 Policy Amendment Freeze 之前
**不得以任何形式参与 candidate 选择**（G-Policy Derivation Isolation 强制）。T7.5 C-family
是 **derived policy**（非 preregistered policy），报告必须如此标注。

## 3. T7.0 Contract + Post-REDUCE Fact Layer

### 3.1 Anchor 定义（与 T6.2 严格兼容）

- **R0** = 有效 REDUCE 日（连续 REDUCE 前移合并，同 T6.2 contract `recycling` 定义——anchor
  集与 T6.2 cycle 集逐位一致，G8 守恒沿用）。
- 研究单元：`(event_id, R0)`。**不要求 A0 存在**（无恢复路径同样是被研究对象）。

### 3.2 产物 schema：三层物理隔离（v2 核心结构修改）

```
t7_0_path_fact.parquet        纯 PIT daily facts（R+1..R+40 窗口内的逐日行情/状态）
        ↓（只读）
t7_0_anchor_features.parquet  只含截至各 decision checkpoint 已知的 trajectory features
        ↓（研究阶段 join 使用）
t7_0_outcomes.parquet         H5/H10/H20 ret、MFE/MAE、terminal failure、false_recovery
                              （继承 T6.3-R1 冻结口径）、cycle type、再 REDUCE/EXIT 时点
```

**硬规则**：feature builder 代码路径**永不 import / 读取 outcome 表**（gate 扫描 import 与
数据依赖图）；outcome builder 可读 path_fact（计算结局）但不产 feature。这比依赖 accessor
纪律更安全——结构天然阻止未来信息进入 feature 侧。

### 3.3 两个 horizon 的分离（v2 新增）

- **Decision horizon**：primary decision checkpoints 冻结为 **R+1 / R+2 / R+3 / R+5**——
  只有这些 checkpoint 的 trajectory 信息可进入 primary ADD decision rule derivation
  （含 T7.2 分层与 C-family 条件）。R+10 及以后仅用于 outcome / path description。
- **Outcome observation horizon**：R+40（冻结）。不为其覆盖 terminal failure 长尾而拉长。

trajectory 变量（全部 decision-time，在 anchor_features 落盘时逐列带 `decision_checkpoint`
元数据标注）：

| 组 | 变量 | 定义要点 |
|---|---|---|
| 反弹 | `max_bounce_Rk`（k∈{1,2,3,5}）, `consec_up_days_Rk` | R0→R+k 窗口内最大反弹 / 连续上涨天数 |
| 量能 | `volume_ratio_Rk`（vs 预注册基准窗 R-20..R-1 均量）, `vol_decay_Rk`, `consec_shrink_days_Rk` | 缩量/放量/衰减速度 |
| 换手 | `turnover_level_Rk`, `turnover_traj`（水平×斜率二元刻画） | T6.3 签名的动态化 |
| 效率 | `eff_pos_share_Rk`（R+1..R+k 内 efficiency>0 天数占比） | 瞬间转正 vs 连续改善 |
| 修复 | `dd_repair_ratio_Rk`, `ref20_repair_Rk` | 结构修复度量，定义冻结禁止后调 |
| 新高 | `new_high_after_R0_Rk` | 价格持续性 |

### 3.4 Sector：路线 A 拍板——QUASI-PIT exploratory sidecar（永久隔离）

- 构造：日线 × 行业映射聚合出 sector_breadth / sector_relative_strength / sector_turnover
  日级指标；标注 **QUASI-PIT**（成员集=2026-09-21 回溯映射，含 survivor/reclassification
  偏差），存独立 `t7_0_sector_sidecar.parquet`（物理上不与 primary 表同文件）。
- 用途：T7.3 conditional 分层与描述，**EXPLORATORY 强制**；primary 主线（Stock PIT + Market
  PIT）零 sector 引用。
- **C/D family 禁止引用任何 sector variable**（即使 T7.3 sector 结果极强）——sector 只能生成
  "值得未来获得真正 PIT sector history 后重新验证"的 exploratory claim。

### 3.5 T7.0 其余任务

- **True Recovery / False ADD 结构性定义审计**（唯一遗留开放项，§14）：目标=尽可能继承
  T6 frozen semantics（dist_ref20 / dd repair / severe_dd_depth_log / T6.3-R1 trigger 口径），
  不重新发明 label；审计产出进 contract 后冻结。
- Gate 增量：G8 守恒（anchor 集==T6.2 cycle 集；三表行数守恒）；**G-Feature/Outcome 隔离**
  （feature builder 依赖图扫描）；G-No Future Feature 首检（cutoff 参数化 accessor，越界
  raise；抽查重放）；沿用 T6 G1-G11。

## 4. T7.1 Path Anatomy（全段描述性）

按结局三组（true recovery / false recovery / no recovery，口径继承 T6.3-R1 冻结定义）对比
trajectory 变量分布：median level CI + 组间 diff CI（cluster bootstrap {stock_code, T0_date}，
Holm within family；DEV/VAL/CONF 三段同表呈现）。**明确不产生 separator/repair candidate**
（candidate 只能出自 T7.2/T7.3a 的 DEV discovery）——本阶段是 trajectory 版描述基线。

## 5. T7.2 Hot-Bounce Structure（DEV ONLY）

- **H7-A（预注册假设）**：REDUCE 后的大幅反弹 + 放量 + 高换手组合不是可靠的 repair
  confirmation（与后续更差路径相联系）。
- 分层三维**共用同一 decision clock**（v2 写死，禁漂移）：
  - `bounce = max_bounce_R5`（R+1..R+5 窗口最大反弹）
  - `volume = volume_ratio at the max-bounce day`（最大反弹当日的量比）
  - `turnover = turnover_load at the same max-bounce day`（同日换手）
  三维各按 development 段三分位分 bin（边界冻结于 contract；VAL/CONF 仅应用）。
- 每 cell 报告（DEV）：H5/H10/H20、MFE/MAE after R0、再 REDUCE 率、EXIT 率、terminal
  failure 率、recovery persistence、capital efficiency。
- 预注册 cell 对比（Holm family，DEV only）："强反弹+缩量" vs "强反弹+放量" vs "强反弹+
  放量+高换手"——检验用户经验规则的统计结构。
- 措辞纪律：conditional association；禁"主力出货"等不可观测机制语言。

## 6. T7.3 Separator / Repair Candidate（DEV-only discovery → freeze → VAL/CONF 验证）

- **H7-B（预注册假设）**：热反弹混合两类终局——新资金接力（持续上涨）与原资金反弹退出
  （再恶化）；研究问题是两类终局**能否从可观测量价轨迹分离**，不声称观测"主力"。
- **T7.3a（DEV only）**：conditional on 热反弹 cell，检验 §3.3 持续性变量对后续结局的分离度
  （level CI + diff CI + Holm）。产出 **candidate 冻结清单**（separator candidates + repair
  confirmation candidates，含全部阈值）。
- **【Policy Amendment Freeze】**：T7.3a（及 T7.4 前）结束后的 contract 增补 commit，完整
  写死 C1/C2 condition、D veto 条件、Delay N、全部阈值；此 freeze 前 VAL/CONF 数据不得
  参与任何 candidate 选择。
- **T7.3b（VAL → CONF）**：对冻结 candidate 做第一次/第二次验证（同统计框架，只验证不修改；
  若 VAL 失败，candidate 记 NOT_VALIDATED，不得回 DEV 重选后再用同一 VAL——避免序贯 peeking）。
- Market context：复用 T6.4 冻结 M_STRONG/M_NEUTRAL/M_WEAK（不重定义）。
- Sector sidecar（EXPLORATORY）：同一热反弹，板块同步修复 vs 个股独立反弹的结局差——
  QUASI-PIT 标注 + G-sector 隔离（primary 块零 sector）。

## 7. T7.4 F6 预注册拆解（独立预注册）

- **taxonomy 冻结五类，不增删**（用户拍板）：持续缓慢恶化 / 反复 REDUCE↔ADD / 热反弹后失败 /
  无明显信号突然破坏 / 长期高暴露滞留 + **mandatory residual F6'**（不要求 100% 覆盖，
  F6'=40% 也可接受——比强行解释所有失败更好的纪律）。
- **G-F6 Lock**：taxonomy JSON 于读取任何 F6 outcome 分布之前冻结进 contract commit（sha256
  + 时序 gate 校验）。分类器首中判定（同 T6.3 纪律），禁止看分布后拆残差。
- 全段报告（F6 拆解不参与 policy derivation，无 reuse 风险）。

## 8. T7.5 ADD Policy Counterfactual（唯一触碰 policy 的阶段）

### 8.1 四个 policy family

| Family | 定义 | 性质 |
|---|---|---|
| **A Current** | 冻结 T5 当前 ADD 规则原样 | benchmark |
| **B Delay** | ADD 信号 → 延迟 N=3 有效交易日（primary）；N∈{1,2,3,5} 全报 curve | preregistered |
| **C Repair confirmation** | ADD eligibility + 持续修复证据（条件=Policy Amendment Freeze 写死） | **derived policy**（DEV-only 推导，报告强制标注） |
| **D Hot-bounce veto** | 原规则允许 ADD 时命中"强反弹+放量+高换手"（T7.2 冻结 cell）→ 禁止/延迟 ADD | preregistered（cell 定义 DEV 冻结） |

C/D 均禁引 sector variable（§3.4）。

### 8.2 错误成本定义（outcome-based，v2 重写）

- **False ADD（primary，outcome-based）**：ADD 后 **W_fa=10** 有效观察日内，路径未达到
  True Recovery criterion 且发生预注册 adverse excursion（MAE 门槛，承 T6 severe 语义）。
  **再次 REDUCE / EXIT 只作 secondary diagnostic**——它们是 policy 自身行为，进入 primary
  定义会造成策略自引用。
- **Missed Recovery（primary，结构性定义）**：策略未 ADD（veto/delay 错过）但该 cycle 达到
  True Recovery criterion——**结构性恢复语义**（价格重新站上 pre-R0 reference + 持续 K 日
  不重新跌破；或 dd_repair_ratio ≥ X + ref20 repair + 后续 N 日无再破坏；阈值 DEV-only
  一次定标后冻结），**不用 RECOVERED 样本 outcome 分位动态定标**（循环定义）。
- True Recovery / False ADD 的精确结构定义 = T7.0 定义审计产出（继承 T6 frozen semantics，
  §3.5/§14）。secondary report：W5 / W20。
- 成本度量：False ADD loss = 该 ADD 起至窗口内 adverse excursion 的幅度；Missed Recovery
  upside = 错过的 recovery 段收益。

### 8.3 指标四组（每 policy × 每 segment；v2：capital efficiency 独立 side panel）

收益获取：terminal return / MFE captured / recovery upside captured；
风险：MDD / MAE after ADD / severe failure / terminal failure；
**资本效率（frontier side panel）**：average exposure / exposure-days / capital released days /
return per exposure-day——允许"收益略低但 false-ADD 与资本占用双降"的策略形态被看见；
错误成本：False ADD rate & loss / Missed Recovery rate & upside。

### 8.4 Counterfactual 守恒（G-Counterfactual Conservation）

复用 T5.8 生命周期模拟器（只读 import）：同一 universe / T0 / entry / price clock /
transaction cost，唯一差异 = ADD 触发判定。Gate：各 variant 的 pre-ADD 逐日状态序列逐位
一致（分歧只允许出现在 ADD 决策差异之后）；RNG 同 SeedSequence 子流。

### 8.5 统计与呈现

- **matched within-cycle diff，措辞冻结（v2）**：两 policy 首次 ADD 决策不同后 exposure path
  已分叉，后继不共享 treatment history——统计解释为**"同一 cycle 下完整 policy path 的
  paired counterfactual difference"**，不是"某一次 ADD 的局部 treatment effect"。此句写入
  contract 措辞要求。
- cluster bootstrap {stock_code, T0_date} + Holm within family；DEV 报告 + VAL/CONF primary。
- **Policy frontier（核心交付）**：primary 二维（x=recovery upside captured，y=false-ADD
  risk）+ capital efficiency side panel；四 family 点 + CI。**禁止单轴排名**（claim 双轴强制）。

## 9. T7.6 Synthesis

同 T6.5 模式：aggregation-only、引用完整性（claims + decision_mapping cites 落冻结 registry）、
开放边界如实清单（separator 若未通过验证 / F6' 残差占比 / sector QUASI-PIT / counterfactual
模型假设边界：同 price clock、无滑点变化）。

## 10. Gate 体系汇总

沿用 T6 G1-G11 全框架，**新增六硬 Gate**：

| Gate | 检查机制 |
|---|---|
| **G-Policy Lock** | T7.0–T7.4：operator 相关源码 diff 为空；T7.5：counterfactual 模块对 T5 import-only |
| **G-No Threshold Search** | 禁数值网格；bin/阈值字面量必须溯源 contract；分位边界标注 development-only 计算路径 |
| **G-No Future Feature** | 三层物理隔离（feature builder 依赖图扫描，永不读 outcome 表）+ cutoff 参数化 accessor 越界 raise + 抽查重放 + 逐列 decision_checkpoint 元数据 |
| **G-F6 Lock** | taxonomy sha256 创建时序校验（contract commit 早于任何 F6 outcome 读取） |
| **G-Counterfactual Conservation** | 各 variant pre-ADD 状态序列逐位一致重放 + 五同断言 |
| **G-Policy Derivation Isolation**（v2 新增） | T7.2/T7.3a 产物只含 DEV 段数据（segment 字段全量断言）；Policy Amendment Freeze 的 sha256 时序早于任何 VAL/CONF 验证产物；C-family 报告强制 derived-policy 标注 |

## 11. Claim Registry 规则（C7xx，enum 沿用 T6 五值）

1. **Association-not-prediction**：separator 类 claim 必须"X 与后续路径相联系"，禁"预测/识别"。
2. **双轴强制**：policy 类 claim 必须同报 false-ADD 轴与 missed-recovery 轴，禁单轴。
3. **Derived-policy 标注**：C-family 相关 claim 必须标注 "derived policy (DEV-only derivation,
   Policy Amendment Freeze <commit_sha>)"。
4. **Sector QUASI-PIT 隔离**：涉 sector claim 一律 EXPLORATORY + 回溯偏差显式标注。
5. **Counterfactual 边界**：T7.5 结论必须带"同 price clock/同 cost 假设下"限定。

## 12. 统计规范

沿用 `src/t6/stats.py`（迁移为共享模块不改语义，迁移过 G10 重放验证）：B=2000、SeedSequence
子流（T7 各阶段 enums 登记 contract）、percentile CI、Holm within family、双 cluster
{stock_code, T0_date}。**段协议按 §2**：T7.2/T7.3a=DEV only；T7.3b=VAL→CONF；T7.5=DEV 报告
+VAL/CONF primary；T7.1/T7.4=全段描述。新增：matched within-cycle paired counterfactual
diff（T7.5）；delay 曲线全家族描述（N∈{1,2,3,5}）。

## 13. 冻结顺序与审计流程

每阶段：code → products → gate → report → 独立审计 → freeze commit；只读上游冻结；T6 全链
sha 校验不变。特殊冻结点：**Policy Amendment Freeze**（T7.3a 后、T7.3b 前的 contract 增补
commit，用户审计确认后才可进入 VAL/CONF 验证）。

## 14. 决策点状态（v2：除一项外全部拍板冻结）

| 决策 | 冻结值 |
|---|---|
| Observation horizon | R+40 |
| Primary decision checkpoints | R+1 / R+2 / R+3 / R+5（R+10+ 仅 outcome/description） |
| False ADD window | W10 primary（W5/W20 secondary report） |
| False ADD 定义性质 | outcome-based（再 REDUCE/EXIT 仅 secondary diagnostic） |
| Delay primary | N=3（N∈{1,2,3,5} curve 全报） |
| Sector | 路线 A：QUASI-PIT sidecar，EXPLORATORY 永久隔离，C/D 禁引 |
| F6 taxonomy | 五类冻结不增删 + mandatory residual F6' |
| C-family 来源 | DEV-only discovery → Policy Amendment Freeze → VAL/CONF 验证（derived policy） |
| Hot-bounce 三维 clock | max_bounce_R5 + 同一 max-bounce day 的 volume_ratio 与 turnover_load |
| **True Recovery / False ADD 结构精确定义** | **唯一遗留**：T7.0 定义审计（继承 T6 frozen semantics：dist_ref20 / dd_repair / severe_dd_depth / T6.3-R1 trigger），审计产物进 contract 冻结 |

---

**一句话收束**：T6 证明了"短期反弹不能证明结构修复，而假恢复路径在 REDUCE 日呈现更热的
短期签名"（条件关联）；T7 把这个知识变成决策问题——**为了减少一次 false ADD，愿意放弃
多少真实 recovery upside**——并在 feature/outcome 物理隔离、DEV-only 推导、outcome-based
错误定义、counterfactual 守恒的纪律下用预注册 frontier 回答它。
