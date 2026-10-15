# CL-R4 G1 — Opening 数据合同普查（census only，未读任何结果变量）

日期：2026-10-14。方法：仓库全量盘点 + 三数据源实测探针（Gate U 事前实证原则）。

## 仓库盘点结论：**无任何分钟级历史数据**

| 来源 | 实况 | 对 R4 的判定 |
|---|---|---|
| `data/cd/daily_fullmarket/` | 日线（qfq+unadj，volume=手） | 无法提供开盘窗口 |
| `data/r2/market_ext/` | 日线 amount/换手/股本 | 无法提供开盘窗口 |
| `data/r2/daily_update/intraday_*.json` | 生产实时扫描快照：仅 2026-10-08 起 7 个交易日、每日 2–4 个时点（11:35/12:59/13:56 等）、横截面状态字段（px/pct/tier/band），**无分钟 OHLCV、无 9:25/9:30–10:00 amount、无历史深度** | 不可用（快照≠分钟线） |
| `tdx-node`（Windows 节点能力报告） | 已证明：日线 OHLCV、除权、股本、本地 HTTP `get_market_data period="1d"`；**分钟线/竞价从未探测** | 潜在候选，未证明 |
| 系统已装 `mootdx` 0.11.7 | TDX 行情库（可读 vipdoc/行情服务器） | 潜在候选，未证明 |

## baostock 5 分钟线实测（隔离环境 `PYTHONPATH=/tmp/bspy`，不污染主环境）

主环境 numpy 2.2.6 与 pandas 2.0.3 二进制不兼容（baostock 依赖 pandas；R1–R3 脚本纯标准库故未受影响）。

| 合同项 | 实测结果 |
|---|---|
| 频率/每日根数 | 5m，**48 根/日**（09:35,09:40,…,11:30,13:05,…,15:00） |
| 首根 bar | **09:35（覆盖 09:30:00–09:35:00，含集合竞价成交量）** |
| 字段 | date/time/open/high/low/close/volume/**amount** per bar |
| 价格口径 | unadjusted（adjustflag=3），与 R2 冻结的未复权空间一致 |
| 历史深度 | ≥2022-01 实测通过（官方称 5m 自 ~2011） |
| 指数 5m | 000985 可用 |
| **Gate U 单位校验** | Σ(当日 5m amount)/日线 amount：**中位 1.0000，范围 1.000–1.015**（002324/600519/300750 × 2022–2026 多日）——单位一致（元）、bar 覆盖完整 |

## 唯一合同限制：**集合竞价不可分离**

baostock 5m 无独立 9:25 竞价快照；竞价量含于 09:35 首根。用户预注册原则"auction 与 continuous 分开"在此源下**只能降级为**：

\[
OpeningWindow = 09{:}30\text{–}10{:}00\ 连续窗口（含竞价，首根 bar 内）
\]

严格分离需另辟数据源（tdx-node 分钟/竞价探针、或从今日起前向归档），时间成本数量级不同。

## 裁决与分叉（待用户）

**G1 = PARTIAL SUPPORT**：

- **路径 A（推荐）**：接受"含竞价的开盘窗口"口径冻结，baostock 5m 采集 84 股全样本期（~84 次调用，5.1M bar，Σ5m 校验已在 ingestion 内全量复验），R4 按预注册推进；auction 分离降级为 backlog；
- **路径 B**：坚持严格 auction 分离 → 先做 tdx-node/mootdx 分钟能力探针（不保证可用），R4 暂停待数据；
- **路径 C**：前向归档（生产快照升级为分钟落盘），历史不可回溯，R4 延后数月。

路径 A 不损失 R4-Q1/Q2 的任何预注册检验（E_open 基线、λ_opening→close、增量门均只需开盘窗口 amount+价格），仅"竞价 vs 连续"对比一项延后。
