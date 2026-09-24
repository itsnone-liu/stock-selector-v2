# T4.1 — Context 层构建报告（市场/板块日表、行业映射、事件背景）

**阶段**：T4.1（数据接入与质量审计；T0 结果分析、路径标签、仓位决策不在本阶段）
**基线**：T3 V6 @ `28f7aed`（HEAD 断言一致）
**开工令**：`T4研究_代码实施方案.md` §六 第一张任务书

---

## 1. 交付物（output/research/t4/context/）

| 表 | 行数 | 主键 | 说明 |
|---|---|---|---|
| `market_daily.parquet` | 1,386 | date | 2021-01-04→2026-09-18；成交额（亿元）、上涨/下跌/平家数、上涨占比、等权日收益中位、20 日复权收盘新高家数 |
| `sector_daily.parquet` | 19,404 | (date, industry_gate) | 14 个有效门类；成分成交中位数 ≥20 的日行；等权收益中位、上涨占比、成交额 |
| `stock_sector_map.parquet` | 5,555 | code | 证监会行业快照（2026-09-21）：门类+大类双粒度、生效日期字段 |
| `t4_event_context.parquet` | 27,422 | breakout_event_id | 与 V6 事件一对一；T0 as-of 背景（见 §3） |
| `manifest.json` / `gate_report.json` / `t4_1_determinism.json` | | | 配置哈希、五道 Gate、双跑记录 |

代码：`src/t4/context/build.py`、`scripts/run_t4_1.py`、`scripts/t4_1_gates.py`、`scripts/fetch_csrc_industry.py`、`config/t4_context.yaml`。

## 2. 数据源与口径

- **个股层**（市场/板块聚合与相对强弱的原料）：`data/adjustment_baostock/per_stock`（5,240 股，baostock 未复权日线 + `adjustment_v1` 复权因子表）——与 V6 执行层同一冻结库，全本地可复现。
- **市场指数**：TDX `sh999999.day`（V3–V6 冻结源，继承 `market_calendar_and_close` 口径）。
- **行业归属**：baostock `query_stock_industry`（证监会行业分类），快照更新日 **2026-09-21**，5,555 行。
- **创新高口径**：复权收盘 ≥ 前 20 日复权收盘最大值（不使用未复权 high，避免除权假跳）。
- **聚合口径**：等权收益中位（不用市值加权——本地无流通股本）；门类内当日成交个股数 <20 时该板块行不生成（`min_sector_members=20`）。

## 3. `t4_event_context` 特征（全部 as-of T0，仅含 ≤T0 数据）

| 特征 | 覆盖率 | 口径 |
|---|---|---|
| `industry_gate` | 0.9990 | 股票→门类（28 事件无归属，空值保留） |
| `mkt_ret_20d` | 1.0000 | 指数 T0 前 20 市场日收益 |
| `mkt_amount_pctile_60d` | 1.0000 | 市场成交额在 T0 前 60 日内的分位 |
| `mkt_breadth_5d` | 1.0000 | T0 前 5 日上涨占比均值 |
| `sector_ret_20d` | 0.9916 | 板块等权 20 日累计（逐日中位复合） |
| `sector_vs_mkt_20d` | 0.9916 | 板块 − 市场同窗 |
| `stock_ret_20d` | 0.9876 | 个股复权 20 日收益 |
| `stock_vs_sector_20d` | 0.9876 | 个股 − 板块 |

缺失分解：28 事件无行业归属（快照中该股 industry 为空：退市/停牌/未分类，例 000638、002808）；201 事件有归属但板块窗口不足（板块行被 min_members 过滤或窗内无数据）；341 事件个股复权序列窗内断点。**全部保留空值，未填 neutral，未删除事件。**

## 4. Gate 报告（五道全 PASS）

- **G1 事件守恒**：T4 与 V6 事件 ID 差集双向为空；27,422 行；code/breakout_day/end_day 冻结字段逐项一致。
- **G2 时间因果**：映射表 `is_point_in_time=false` 100% 标注；`effective_from=2026-09-21` 一致且晚于数据期末 2026-09-18；40 抽样 `mkt_ret_20d` 以 ≤T0 指数 21 点独立重算 0 mismatch。
- **G3 覆盖率**：见 §3；map 层行业非空率 0.9399。
- **G4 抽样追溯**：30 抽样个股 20 日复权收益独立重算 0 mismatch。
- **G5 复现**：三表双跑 hash 全一致（同一缓存原料两次全量聚合+context 构建）。

## 5. 限制与披露（正式结论使用前必读）

1. **行业映射非历史时点**：证监会分类为 2026-09-21 快照（数据期末之后），`is_point_in_time=false`。历史板块归属不可得，按开工令不冒充——凡使用 `sector_*` 特征的结论均须声明该限制；`industry_gate` 仅作分组用途时风险较低（门类级行业迁移率低），大类/个股级迁移风险更高。
2. **门类粒度偏粗**：C 制造业占事件 69.3%（19,002/27,422）、占 A 股成分绝对多数——C 门类内部异质性大。`industry_class`（83 个大类）已保留在 map 表，T4.4 若需要更细粒度可直接切换，无需重拉数据。
3. **快照 vs 事件宇宙时差**：约 3 个自然日的行业变更风险（2026-09-18→09-21）。
4. 板块等权口径 + min_members=20 过滤：小微门类（O/P/Q/S/H）在部分日期无板块行，相关事件 `sector_*` 为空。
5. 上涨/下跌家数基于 baostock `pctChg`（复权口径涨跌幅）；成交额为全市场成分求和（非交易所官方口径），跨期一致性优先于绝对值精度。

## 6. 阶段放行

T4.1 五道 Gate 全 PASS，双跑复现通过。按开工令 §二，**冻结本阶段产物，T4.2（T0 特征表）可启动**。
