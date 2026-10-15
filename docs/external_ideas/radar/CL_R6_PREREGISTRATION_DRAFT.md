# CL-R6 预注册草案 — Market Capital Balance（PRE-RESEARCH 边界版）

状态：**PRE-RESEARCH COMPLETE / MECHANISM VALIDATION NOT AUTHORIZED**（2026-10-15 用户裁决冻结；源提案 `.feishu-files/20261015045001-CL_R6_Market_Capital_Balance_v1.0.md`）
程序状态：**R5 OOS-B = 唯一活跃机制验证主线**。R6 下一步动作须待 OOS-B 60 日闭包联合决策（R6-2 授权或 CLOSE）；若获准仍维持 Atom-first / E1 上限 / 无 Regime / 无综合评分。

## 0. 路线图地位（正式修订，替代 2026-10-15 早前"不开新 CL 主题"裁决）

\[
\boxed{\text{R5 OOS-B = 唯一活跃机制验证主线}}
\qquad
\boxed{\text{R6 = PRE-RESEARCH / SUPPORT AUDIT ONLY}}
\]

R6 当前唯一问题：**"这个题目有没有足够的数据与外部证据值得以后研究？"**——不是"资金状态机制是否成立"。

## 1. Small-N / Episode Evidence Contract（修正硬伤 1）

**有效自由度声明**：2018–2026 名义 ~2,200 交易日，但 Funding 为月度现象（~108 个月），regime transition 级独立宏观 episode 可能仅**个位数到十几个**。禁止把月度状态按日复制后跑大 N 回归/bootstrap 制造虚假窄 CI——R3–R5 统计范式**不适用**于 R6。

证据三级制（替代 large-N inference；显式不采用"无反例"标准——1 个反例可能是 regime 真实异质性，3 次同向也远非规律）：

| 级 | 条件 | 允许的说法 |
|---|---|---|
| **E0** | 独立 episode 太少 / 某状态仅出现 1–2 次 / 单一时期贡献绝大部分变化 / available_at 不可恢复 | **INSUFFICIENT_SUPPORT**，不做机制结论 |
| **E1** | 多个独立 episode 大部分同向 + 非单一特殊时期（2020/2024 等）驱动 + leave-one-episode-out 核心描述不崩溃 | "consistent descriptive structure"，禁说 validated mechanism |
| **E2** | 时间分段、不同政策周期、不同市场周期均现同结构 | MECHANISM CANDIDATE（仍禁模仿 R3 的"小 CI=高可信"叙事） |

总原则：**宏观研究天然比股票日研究证据更弱，不得用统计技术伪装更强。**

## 2. G0 — Data Source Census / Support Gate（修正硬伤 2，插入 R6-0.5）

G0 是 R6 的**生死门**，非准备工作。每个核心原子量逐项核查：

> coverage 起点 / 粒度（日·月·事件）/ 官方源存在 / available_at 可恢复 / 是否修订 / 历史 vintage 可恢复 / 单位稳定 / 定义断点 / 缺失度 / 自动化可持续 / 第二来源交叉验证

**Vintage vs Latest-Revised 区分**（比普通 PIT 更深）：现值社融曾被修订 → 必须回答"当时市场参与者看到的是哪个数字"。不可恢复 → 标记 **REVISION_CONTAMINATED**，不得假装 PIT。

**四轴逐轴裁决（预期不对称）**：
- **Margin**：相对容易；仍查沪深定义一致性、标的扩容、单位断点；
- **ETF**：必须确认历史份额序列能追到多久（今天交易所页面可查≠通过）；
- **Funding**：M1/M2/社融无可靠 available_at/revision 合同 → FundingAxis=UNSUPPORTED，不得拿聚合源硬顶；
- **Supply**：最可能先失败——历史 T 时点"已知的未来解禁"≠ 现在回看的最终解禁记录。**如果失败就失败。**

任一轴 G0 失败不拖累其他轴，逐轴如实记录；轴失败→该轴出局，非全局救援。

## 3. Axis Orthogonality Contract（修正硬伤 3，Gate S 升级）

四轴共享市场级构造项（turnover/breadth/impact-efficiency 同时是候选 state 与候选 outcome），S 门风险高于个股层。**v1 必须附轴-变量正交矩阵**，核心不变式：

\[
\boxed{X_{axis\ constructors} \cap Y_{outcome\ variables} = \varnothing}
\]

turnover / breadth / impact-efficiency 在**每个具体实验预注册时**必须显式声明角色（state constructor 或 outcome，二选一），禁两边同用。禁止"高 breadth regime 的未来 breadth 更高"式机械自证。示例矩阵（占位，R6-1 冻结）：

| 变量 | Funding | EquityFlow | Supply | Absorption | Outcome |
|---|---|---|---|---|---|
| M2/社融/信用脉冲 | ✓ | | | | |
| ETF Δshares | | ✓ | | | |
| Margin Δbalance | | ✓ | | | |
| Unlock MV | | | ✓ | | |
| Market turnover | | | | ✓(二选一) | ✓(二选一) |
| Breadth | | | | ✓(二选一) | ✓(二选一) |
| Impact efficiency | | | | ✓(二选一) | ✓(二选一) |
| Index return | | | | | ✓ |

## 3.5 轴范围正式修订（2026-10-15 用户裁决）

- **Supply 轴出局**（公告锚不可恢复，G0 正常发挥作用）：v1 轴 = **FundingContext + EquityFlow + Absorption**；Supply 仅存 Future Ideas/qualitative context；
- **Funding → FundingContext 降级**：仅低频宏观背景；三冻结边界——不参与强机制结论、禁“传导已证实”升级、修订历史值必须标 REVISION_CONTAMINATED；证据上限 E1；禁“当时市场已看到此数因此产生此行为”类 PIT 因果表述；
- **文献边界写入**：外部文献支持的是组成机制，**不支持我们的市场级聚合状态模型**——不得声称“MarketCapitalRegime 已有文献验证”；R6-2 即使获准，证据默认上限 E1；
- 最小链定位：外部金融环境 → 实际资金进入股票 → 市场扩散与推进。

## 4. Atom-first / Regime NON-OPERATIVE（修正硬伤 4）

> **Regime labels are NON-OPERATIVE in R6-v1.**
> No observation is assigned to Regime A/B/C/D.
> No gate is evaluated on regime labels.
> A–D 仅为 conceptual examples，不进代码。

v1 只研究四组原子量及其传导：Funding→EquityFlow、EquityFlow×Supply→Absorption。原子链站不住 → **根本没有必要创建 Regime**（避免在 108 个月里人为切 4 类、每类仅剩二三十个月）。Regime 研究另立版本、另行预注册。

## 5. 当前授权（白名单）

| 阶段 | 允许 | 禁止 |
|---|---|---|
| R6-0 Evidence Atlas | 中国实证论文/数据定义/复现代码/正负结果/条件效应的机制卡；严格区分"作者证明的"与"我们的资金逻辑解释" | 任何本地 outcome 运行 |
| R6-0.5 Data Census | 数据可达性核查；**少量样本数据**下载做 schema/unit/PIT 验证 | 构造完整研究 panel |
| R6-1 Contract Draft | 基于 census 写合同草案 | 运行研究 |

## 6. OOS-B 60 日闭包前绝对禁止清单

完整 2018–2026 panel；Funding×未来市场 outcome 相关；ETF flow 后收益；Supply 后 breadth；调阈值；聚类 regime；PCA；HMM/hidden state；综合资金指数；G1–G5；CD candidate×R6 状态。

**R6 在此期间零"研究结果"，不与 OOS-B 争夺验证预算。**

## 7. 决策点（OOS-B 首批 60 日闭包时）

同时持有 R5 forward 结果（F1/F3/F4）与 R6 的 Atlas+Census+Contract → 裁决：

\[
R6 \to R6\text{-}2\ (\text{Historical Panel})
\quad\text{或}\quad
R6 \to \boxed{CLOSE\ INSUFFICIENT\_SUPPORT}
\]

## 8. 继承纪律（不变）

Gate U/M/S（S 已升级为 §3）；三禁区（M2⇒牛市 / ETF申购⇒国家队 / 解禁⇒实际卖出）；Planned≠Potential≠Realized 三分；FAIL→CLOSE HONESTLY 禁救援清单；Profit Mass/Trapped Mass 维持冻结；命名纪律（无主力/派发/absorption/国家队身份）。

---
交付物命名（本草案生效后）：`CL_R6_EVIDENCE_ATLAS.md`、`CL_R6_DATA_SOURCE_CENSUS.md`、`CL_R6_PIT_CONTRACT.md`（正式版预注册待 OOS-B 闭包决策点后另行冻结）。
