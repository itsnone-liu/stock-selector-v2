# CD-2 — L2 Sector Observable State Model · Completion Report

*预注册: `cd2a_preregistration.json` + `cd2b2c_preregistration.json` · 阈值: `cd2a_thresholds.json` · 运行: `cd2bc_states_run.json` · 状态表: `data/cd/sector_axes/l2_state_table.json.gz`（115,619 行，sha `f40d55df…` 双跑一致）*

## 交付物

**CD-2A 离散化**（Support-First census → 冻结阈值 → band 表 115,619 行）
**CD-2B 可观察状态**（base_state × modifier，60 组合，全部 support 合格）
**CD-2C 转移语义**（4 条路径标签 + 转移矩阵，零预设循环）

## CD-2A：census 发现的结构事实

| 轴 | 变量 | 阈值方案 | 证据 |
|---|---|---|---|
| RP | rel_eq_mkt | **POOLED** [−0.47%, +0.32%] | 规模漂移 ≤8.1pp |
| Participation | vol_share − vol_share_20d | **SIZE_STRATIFIED** | SMALL 漂移 29.8pp / LARGE 23.9pp——小板块量份额波动天然大 |
| Breadth | advance_frac | **POOLED** [0.294, 0.620] | 漂移 ≤4.4pp（比例统计量规模稳健） |
| Concentration | ret_contrib_top5 | **SIZE_STRATIFIED** | SMALL 漂移 19.6pp（10 只股 top5 基线即 50%） |
| Dispersion | top5_ret − rest_ret | **POOLED** [−0.39%, +0.91%] | 漂移 ≤6.3pp |

分位数取自**开发窗 2021-01..2023-12**（50,735 OK 行），holdout 2024+ 纯应用零拟合；冻结后不许移动（合同条款）。

**ERRATUM-CD2A-1**：part 轴曾误发 LOW/MID/HIGH 标签（预注册规定 FALLING/FLAT/EXPANDING），首版状态引擎因此 EXPANSION/FADING/BUILDING 全为 0——交叉验证（rp×part 表 15,194 天 HIGH×HIGH ≠ 0）定位为标签命名 bug 而非数据结构，原位改写标签、阈值不动、sha 重录（`c17903b2…`）。

## CD-2B：状态分布（98,013 OK 日 + 17,606 INSUFFICIENT_SUPPORT 传播）

| base | 天数 | 占比 |
|---|---|---|
| DIVERGENT | 25,555 | 26.1% |
| BROAD_WEAKNESS | 17,351 | 17.7% |
| NARROW_WEAKNESS | 14,872 | 15.2% |
| BROAD_STRENGTH | 9,253 | 9.4% |
| NARROW_STRENGTH | 7,875 | 8.0% |
| NEUTRAL 系（3 态） | 23,107 | 23.6% |

- **60 个 (base, modifier) 组合全部 support 合格**（≥100 天且 ≥3 板块；0 个 LOW_SUPPORT）
- 最大组合：DIVERGENT|PARTICIPATION_EXPANDING+HIGH_DISPERSION（8,576 天 / 69 板块）
- **观察（结构事实，非解释）**：DIVERGENT 是最大单态——L2 粒度下 top5/rest 分裂日非常常见，这与"83 大类内部异质性高"的 CD-1A census 发现一致，也正是你设计的 SW2 escalation 触发器的存在理由
- 持续性（对角占流入比）：DIVERGENT 30.5% 最高、BROAD_WEAKNESS 19.4%、BROAD_STRENGTH 11.1%——**状态多数是短命的，单日状态远不如路径可靠**（支持你的路径优先裁定）

## CD-2C：路径频次（哪些路径真实反复出现）

| 路径 | 天数 | 占 OK 日 | 支持度 |
|---|---|---|---|
| FADING | 5,924 | 6.0% | 69 板块 |
| EXPANSION | 4,043 | 4.1% | 69 板块 |
| NARROWING | 515 | 0.53% | 稀疏（严格条件：breadth 从 HIGH 收窄 + conc HIGH + base 已收窄） |
| BUILDING | 270 | 0.28% | 最稀（前 4 日全 NEUTRAL 系 + 3/5 日参与扩张） |

转移矩阵 top：DIVERGENT 自转移 7,791 最大；强↔弱直接跳转（BROAD_STRENGTH→BROAD_WEAKNESS 1,889 ≈ 反向 1,873）**双向对称**——无单向"阶段循环"迹象。

**诚实结论（结构层）**：四阶段循环（吸筹→拉升→派发→退潮）**未在 L2 单日状态序列中显形**；状态转移高度弥散、双向对称，BUILDING/NARROWING 这类复合前奏条件极稀。任何"周期"叙事若要成立，必须靠更长的路径聚合（CD-3+ 候选问题），不能靠单日状态机。

## 解释层（INTERPRETATION，明确标注不确定）

- FADING（rp LOW + breadth LOW + participation FALLING）可对应"退潮"——这是四者中唯一单日即可观察的
- EXPANSION（新达 BROAD_STRENGTH + 参与扩张）可对应"扩散式走强"
- NARROWING 可视为"LEADERSHIP_NARROWING"的可观察前奏——**是否派发需后续路径确认**（禁止从单日推断）
- BUILDING 与"吸筹"距离最远：参与扩张但表现未走强，270 天的稀疏支持说明该前奏在 L2 日频上罕见

## 未做（合同边界）

小板块不救（12 个永久 INSUFFICIENT_SUPPORT 传播）· 阈值冻结后不移动 · 无评分无排序 · SW2 仅作 heterogeneity 触发后的分解（未进入主状态生成）· CD-3 未启动

**全局状态**：`CD-0 FROZEN · CD-1A/1B COMPLETE · CD-2 COMPLETE · CD-3 NOT STARTED · CSR-8 不变`
