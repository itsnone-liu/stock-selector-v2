# CL-2 第一批判定 v1 — 2026-10-14

> 输入：CL-1 分诊（12 family）+ 代码深读（DEEPDIVE_CODE.md，4 仓库 file:line 级）+ 论文深读（DEEPDIVE_PAPERS.md，4 篇全文 + 8 项日线可落地清单）。
> 裁决动词沿用 CAPITAL_LOGIC_MAP §0。本判定为研究阶段判定，不触发任何生产变更。

## 1. Family 裁决总表

| Family | 裁决 | 一句话理由 |
|---|---|---|
| F3 Kyle λ / 推进效率 | **RESEARCH（最高优先）** | 日线构造有学术锚（λ=ΔP 对带符号量斜率，无截距 OLS；Amihud 版交叉验证）；λ 定位=状态/条件变量而非方向因子（原文 FM 截面符号随设定翻转） |
| F1 筹码 CYQ（myhhub） | **RESEARCH（R1 对照消融）** | 对手 baseline 定死（三角核×统一线性衰减）；**对照前必须替对手修 qfq**；四轴消融：核形/典型价(OHLC4 vs HLC3)/衰减律(线性 vs survival)/bin 分辨率 |
| F5 Wyckoff 五评分 | **RESEARCH（OBSERVE 轨道）** | 五个日线评分公式全透明可移植、A股处理认真；缩量承接部分 **ALREADY_COVERED**（R2-8B M2_DPE/M4_VPHASE 同构，已核）；照搬公式不照搬总分 |
| F6 AVWAP | **RESEARCH（并入 R1/R2）** | 机械结构锚（ATR14×2.5 zigzag，确认日入 PIT 轴）可移植；典型价差异并入 R1 消融轴；锚点族冻结候选：swing确认/突破日/解禁日/定增上市日 |
| F7 Volume Profile | **MERGED→R1** | POC/value-area 概念与 CD-5 直方图对账即可，不独立立项 |
| F8 处置效应/浮盈 cohort | **RESEARCH（第二波）** | 机制文献最厚（处置簇+realization utility+中国证据）；Q6 关口：与 EI-2 DTC 的区分=cohort 分布 vs 单一距离 |
| F2 PIN/VPIN | **PARKED（数据门控）** | 纯 OHLCV 估不了 PIN；需资金流分型管线（东财四档同构替代）+合成数据单测；R2-0 无此数据，新采集=独立决策 |
| F4 OFI/CVD 盘中工具 | **ARCHIVED（思想已吸收）** | log 平稳化+粗粒度符号错分两条思想入袋；L2 解锁前不再看 |
| F9 分钟K（free-stockdb） | INFRA lead | EI-5P 已覆盖前瞻第二级；历史回看缺口仍在，独立数据项目 |
| F10 LLM agent / F11 Kaggle / F12 书单 | lead | 数据接线参考/特征工程参考/雷达线索 |

## 2. 三个进入 RESEARCH 的专题及其第一步

### R5-λ（推进效率，第一优先）
- **锚**：λ 日线回归量（无截距 OLS：Δclose_adj ~ OF；OF=amount×sign(Δclose_adj)，一字板置 0 单独计数）+ Amihud 版交叉验证。
- **形**：冲击凹性 β（log|ret| ~ β·log(amount/ADV)，β<1 ⇒ 效率递减）——效率指标取**边际斜率**而非平均斜率。
- **用法**：λ/signedflow 做条件区分度检验（配合成本/筹码状态），不做方向因子。
- **诚实边界**：2607.01377 是 2026 单作者 arXiv v1，效应符号不稳——**引用其构造方法，不引用其方向结论**。
- 8 项日线构造清单见 DEEPDIVE_PAPERS.md §5（全部 ≤ 日线 OHLCV+成交额）。

### R1-筹码对照（第二优先）
- 外部 baseline（修 qfq 后）vs CD-5 成本上下文，同一评价框架：预测后续行为/路径（不是比回测收益）。
- 四轴消融设计；外部实现的两处缺陷（不复权、换手饱和）作为"为什么我们不用它"的实证记录。

### R4-Wyckoff 五评分（第三优先，OBSERVE 轨道）
- absorption/dry_up/breakout_quality/supply_pressure/failed_breakout 按原公式移植为特征，进每日交叉验证累积。
- 缩量承接不再重做（R2-8B M2/M4 已覆盖同构逻辑）。

## 3. 标志性研究问题（提议预注册，待 GO）

**桥实验：同样的钱在不同筹码状态下推动效果不同吗？**
响应变量=日线 λ（及边际斜率）；条件变量=成本带位置/筹码集中度/获利盘分层（CD-5 已有）。
这是 CL 方案"双层验证"第一层（机制验证）的第一个实例：先验证 Concentration→PriceImpact 的中介关系，再看决策价值。全部日线可算，可先 84 股试点再全市场。
预期意义：若成立，它连接体系最强的格（成本/筹码）与最薄的格（推进时机），且不依赖任何新数据。

## 4. 过程结论（雷达 v0 运行一轮后的元信息）

- SNR：GitHub 35-40%，arXiv ≈55%；关键词碰撞需要人工分诊，不可省。
- 外部实现两大通病：**复权缺失**（4 中 2）、**确认日≠发生日**（锚点类构造）——已写入雷达操作规程（CL1_TRIAGE §5）。
- 深读子代理模式有效：file:line 级公式提取 + 对照本仓库已有实验（R2-8B 同构发现即由此而来）。
