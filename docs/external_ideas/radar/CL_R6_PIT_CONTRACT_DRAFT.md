# CL-R6 PIT 数据合同草案（R6-1，基于 G0 census）

状态：DRAFT（OOS-B 闭包决策点前不冻结正式版）。来源：`CL_R6_DATA_SOURCE_CENSUS.md` G0 终裁表。

## 1. 轴范围（按 G0 结果收缩）

| 轴 | v1 地位 | 合同要点 |
|---|---|---|
| Margin | 全量 | SSE/SZSE 官方日线；available_at=T 收盘后（次日可用）；单位=元；断点登记：融资标的扩容（2019-08）、融券新规（2023-10）、注册制全面落地（2023-02）——只登记不改值 |
| Funding | 降级使用 | 值=最新修订版 → **全列标 REVISION_CONTAMINATED**；available_at 由官方新闻档案逐期重建（发布日规则：次月 10–15 日，抽查 2020-09→2020-10-14 多源一致）；口径断点（2011 社融口径/2018 M1 修订/2024-12 M1 含个人活期理财新口径）登记后以"断点内比较"为限 |
| EquityFlow/ETF | 待定 | 份额序列未落定——正式合同冻结前置条件：交易所源份额历史核查通过；价格/成交（2012 起）仅作 Absorption 侧市场量 |
| Supply | **v1 出局** | 无公告锚源不建；出局即出局，不以回看数据顶替 |
| Absorption | 本地构造 | 全市场成交额/breadth 由 repo 日线数据构造（与 R1–R5 同源同单位合同）；角色受轴正交矩阵约束（state 或 outcome 二选一） |

## 2. 通用条款

- 每条记录：`observation_date / available_at / source / raw_value / unit / revision_flag`；
- 决策日 T 只准用 `available_at ≤ T`；
- 月度宏观数据在发布日前禁用（哪怕 observation_date 已过）；
- 第三方聚合源（akshare 等）仅开发通道，最终事实源=官方发布 + 交叉验证两源一致；
- 缺失 fail-closed：不填零、不插值；
- 单位合同（Gate U）：亿元/元/亿份 显式列明，进数据前冻结。

## 3. 明确不做（至 OOS-B 决策点）

完整 panel 构造、任何 outcome 观察、G1–G5、Regime 赋值、CD×R6 交叉。

## 4. 决策点输入（交用户）

R6 三份预研产物（Atlas/Census/Contract-Draft）+ R5 OOS-B 60 日结果 → 裁决 R6→R6-2（三轴范围：Margin+Funding(降级)+ETF(若份额落定)+Absorption）或 CLOSE INSUFFICIENT SUPPORT。
