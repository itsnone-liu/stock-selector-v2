# R2-0 数据盘点（2026-10-05）

## 已有资产
| 数据 | 位置 | 状态 |
|---|---|---|
| OHLCV+复权 (qfq/unadj/adjust_factor) | data/cd/daily_fullmarket/{code}.json.gz | 完整 2021–2026-09-30，source=tencent_fqkline |
| 国家队/ETF 份额历史 | data/csr8_national_capital/raw/etf_shares/ | 2021-03 起逐日 (357MB) |
| 个股持仓披露历史 | data/csr8_national_capital/raw/holdings/ | sh_XXXXXX__报告期 2021Q1 起 |
| 披露时间表 | data/csr8_national_capital/raw/publication_dates/ | PIT 可用 |

## 本轮新增（已验证可行）
| 数据 | 适配器 | 试点结果 |
|---|---|---|
| amount / outstanding_share(流通盘) / turnover_rate 历史 | src/capital_data/market_daily_ext.py (akshare sina stock_zh_a_daily) | 4/6 成功（000001: 1393 行含完整 amount+float+turnover）；2 只失败已显式记录（No value to decode，待重试/换源） |
| EM 源 stock_zh_a_hist | 同文件旧路径 | 当前网络不可达（RemoteDisconnected），保留为备选 |

## 缺口（按优先级）
1. 全市场 ~5400 只的 market_ext 批量抓取（分批+断点，进行中）
2. 股东户数 / 十大流通股东 ownership_history（akshare stock_zh_a_gdhs / gdfx）
3. 基金季报个股持仓 institutional_holding_summary
4. 龙虎榜 / 大宗 / 融资融券（P1 evidence boost）
5. ETF 申赎明细（现有 etf_shares 已可起步）

## 硬底线执行情况
不造数据（失败显式记录）；不未来信息（抓取止于 2026-09-30）；不静默错误（fails 列表+meta 溯源）。

## R2-0 增量（2026-10-05 晚，goal round 3-4）
| 数据 | 状态 |
|---|---|
| E4 股东户数 22 期全市场（cninfo） | ✅ data/r2/holders/ |
| 机构/国家队画像 84 股×22 季（CSR-8 披露解析） | ✅ data/r2/institutional/ + NATIONAL_TEAM_REGISTRY.json |
| E5 融资余额 SSE 2021–2026 逐日 | ✅ data/r2/margin/（SZSE 源连接重置=SSE_ONLY） |
| amount/turnover/free_float 全市场 | 🔄 3 分片并行抓取中（~960+/5430） |
| 龙虎榜 / 大宗交易 | ❌ EM 源全部超时/断连，标 MISSING（可人工投喂） |
