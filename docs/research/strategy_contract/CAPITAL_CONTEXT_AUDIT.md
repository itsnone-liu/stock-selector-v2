# capital-observer 背景数据审计（2026-09-17）

数据库：`capital-observer/data/capobs.db`。这里只审计可用性，不把背景直接变成个股准入规则。

## 已可用

| 背景 | 指标/接口 | 本机覆盖 | 可见性 |
|---|---|---|---|
| 宽基ETF份额 | `fact_observation.etf_total_shares`；`/api/v1/etf/shares` | 2024-01-02~2026-09-15，772132行（全ETF，不等于研究只用宽基） | T日晚清算后/T+1可得；盘中不可用 |
| 宽基ETF净创设代理 | `/api/v1/context`：Σ(Δshares×NAV)，NAV缺失回退close | API动态PIT计算 | 实物申赎新增暴露，不等于二级现金买股 |
| 沪深两融 | `margin_fin_balance` | 2018-06-15~2026-09-09，66778行 | 按 available_at PIT；沪深分通道 |
| 指数收盘 | `index_close` | 2023-08-01~2026-09-09，4530行 | 收盘后 |
| EM板块大单代理 | `sf_main_net` | 2026-03-19~2026-09-16，14713行 | 当日盘后；proxy非机构识别 |
| 历史行业映射 | `asset_membership` | 13028行，有效期2021-12-13~2026-09-10 | 可按事件日关联，禁止当前映射回填 |

## 尚不能声称已具备

- 全研究期（2025-01起）的行业大单资金：`sf_main_net`仅自2026-03起。
- `sector:board_margin`、`sector:industry_etf`：context API明确为规划位。
- 完整的市场涨跌广度历史：需从TDX全市场日线离线构建，不能用ETF或指数代替。
- ETF份额变化代表新增ETF暴露规模，但不等同ETF当日二级成交资金，更不等同个股实际被买入金额。

## 最小接入顺序

1. stock-selector自身从TDX按日生成市场/行业收益与广度事实；
2. 按历史`asset_membership`关联行业；
3. 通过PIT接口补宽基ETF净创设、沪深两融；
4. 2026-03后才增加EM板块代理；
5. 缺失保持unknown，所有连接均为左连接；背景最终用于解释和外层仓位实验。
