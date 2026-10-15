# CF-1A Source/PIT Closure — 预注册 Spec v1.0

*Authority:* 用户 2026-10-15 CF-1 GO 裁决（`CF1_GO_RULING_20261015.md`）· *Contract:* `cf0_contract_freeze.json` v2
*Gate order:* **CF-1A 是硬门——L1/M 正式产生状态以前必须完成**。CF-1A 不研究市场，只证明传感器可用。
*环境:* akshare 1.18.88 @ /tmp/aksy（PYTHONPATH，规避主环境 numpy/pandas 二进制不兼容；G8：独立于 OOS-B 环境）

## 0. 范围与禁做

三组传感器：**L1（ETF 份额/成交）· M（两融）· L4（情绪宽度）**。
禁做：状态赋值、跨层特征、未来 outcome 关联、Market Regime、任何市场结论（G4-G7）。

## 1. 逐传感器核查项（11 项/传感器）

官方源身份 / 历史覆盖（起点深度）/ 字段语义 / 单位 / available_at / 发布时点分布 / 缺失语义 / 修订语义 / PIT 重放一致性 / 制度断点（定义变化）/ 新上市-清盘-退出行为。

**核心问题（ETF/两融共用）**：交易日 T 的数据，在 T 日几点以前真实可知？→ 若只能 T+1 获得，CF 日报标 `NOT_YET_OBSERVABLE`，禁止回填伪装当时已知（G2/G6）。

## 2. 继承项（R6-0.5 Census 已核，不重复劳动）

| 项 | 结论 | 来源 |
|---|---|---|
| SSE ETF 份额深度 | `fund_etf_scale_sse(date)` 2012-01-05 起逐日（2018=88只/2025=593只），单位=份，按日查询返回当日基金全集=自然 PIT | CL_R6_DATA_SOURCE_CENSUS.md |
| SZSE ETF 份额 | `fund_scale_daily_szse(start,end,'ETF')` 2018-01-05 实测✓（585行/11日）；2015 空（深度界点待精确定位） | 同上 |
| 两融 SSE | `stock_margin_sse` 官方日线 2018-01-02 起，单位=元，收盘后发布语义 | 同上 |
| 两融 SZSE | 接口可达，单日制查询（全历史 ~2200 次调用可自动化，深度未核） | 同上 |
| 解禁供给 | UNSUPPORTED-for-PIT，不重试 | 同上 |
| 宏观资金 | REVISION_CONTAMINATED，不进 CF-1 | 同上 |

## 3. CF-1A 新增核查（本阶段交付）

### 3.1 ETF（九项清单，用户裁决指定）

effective_date / query_date / available_at / **release_time_distribution（多时点采样实测）** / same-day usable? / T+1 usable? / revision behavior（同一历史日期两次间隔查询对比，检测值是否漂移）/ holiday behavior（非交易日与节后首日查询行为）/ new-delisted fund behavior（按日查询下新上市与清盘基金的出现-消失轨迹）。

### 3.2 两融（四项清单）

融资余额对应交易日 / 官方实际发布时间（SSE/SZSE 官网发布页时点实测）/ 盘中-收盘后-T+1 哪个时点可用 / 历史修订（双查询对比）+ 制度断点表（2019-10 标的扩容、2023 融券新规等，标注定义变化点）。

### 3.3 L4 传感器定源（全新，无先验凭证——风险最高）

| 传感器 | 候选源 | 已知风险 |
|---|---|---|
| 全市场成交额 | 000985/000300 等指数日线聚合 | 低（本地已有部分指数资产） |
| 上涨/下跌家数 | akshare 涨跌家数接口（待探测）；或全市场行情构造 | **中：全市场行情历史是 CD-2 已知阻断缺口**；接口历史深度未证 |
| 涨停/跌停家数、连板高度、炸板率 | 东财涨停池类接口（`stock_zt_pool_em` 族） | **高：此类接口通常只有近期快照，历史回溯深，可能不满足 Support-First** |
| 新开户 | 中登公司披露 | 低频（月），仅背景 |
| 题材扩散速度 | 无直接接口 | v1 可能降级为 qualitative/NOT_AVAILABLE，fail-closed |
| 小微盘指数 | 指数日线 | 低 |

**L4 判定规则**：每个传感器按 11 项核查后给裁决；历史深度不足者**不得**进入 L4 v1 状态机输入集，L4 状态机在 CF-1B 启动前按实际可用传感器重新声明输入集（支持不足的状态降置信度或禁用，禁换窗口抢救）。

## 4. 产出物（CF-1A 完成定义）

1. `docs/cf/CF1A_CLOSURE_REPORT.md`：逐传感器裁决表（SUPPORTED / SUPPORTED-with-lag(标注 T+1) / REVISION_CONTAMINATED / NOT_YET_OBSERVABLE-at-T / UNSUPPORTED）+ 11 项明细 + 证据凭证（查询原文/时间戳/哈希）。
2. PIT 重放证明：同一 as-of 日期两次独立重放，输出完全一致（G3）。
3. 发布时点实测记录：ETF 与两融的 release_time 分布（多时点采样，需跨交易日完成——10-16 起连续观测）。
4. L4 v1 输入集冻结表（基于实际裁决，非愿望清单）。

## 5. 时序

- 静态项（深度/单位/语义/缺失/修订/断点/新清盘行为）：立即可做。
- 发布时点实测：2026-10-16（周五）起跨交易日采样：盘中 11:00 / 尾盘 14:30 / 收盘后 15:30 / 晚间 20:00 / 次晨 08:30 五时点查询当日（T）与前一日（T-1）数据，判定 same-day vs T+1。
- CF-1B 只在 CF-1A 报告归档 + 用户确认后启动。

## 6. 硬失败处理

任一核心传感器 UNSUPPORTED → 对应层在 CF-1B/1C 输出 `INSUFFICIENT_SUPPORT`（fail-closed），不阻塞其他层。
