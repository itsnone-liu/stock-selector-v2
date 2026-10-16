# CF-HX-2 审计记录 #3：四小库合审（szse-etf-share / ETF_Database / A-Shares-data / TradingWorkbench）

*审计员:* subagent 393bc6e3 · *日期:* 2026-10-16 · 审计含对交易所接口的只读实测验证

## A. zxtcc/szse-etf-share（无 License）

| 字段 | 值 |
|---|---|
| source | SZSE 官方 `www.szse.cn/api/report/ShowReport/data?CATALOGID=scsj_fund_jjgm&jjlb=ETF`（JSON 按代码查询+每页 20 条翻页，实测 metadata pagesize=20） |
| 覆盖 | data/ 4 只 ETF 各 827 行，2023-01-03→2026-06-05，逐日 xlsx（日期/代码/名称/份额(万份)/当日变动/抓取时间，按日期去重 keep=last） |
| 窗口机制 | 官方 6 个月窗口（clientvalidate dateRange），代码保守 180 天分窗 + 窗口间随机休眠 0.8-1.8s |
| **PIT 发现（官方文字证据）** | **接口 footer 原文："T日晚间更新的T日规模仅供参考，以T+1日早间更新的T日规模为准"** —— SZSE 官方自认存在 T晚初步版→T+1晨定案版的修订窗口。**CF-1A 定案建议：SZSE 份额 available_at 取 T+1 晨（定案版）为合同口径；T 晚值若使用须标 PRELIMINARY_MAY_REVISE** |
| 与 akshare 关系 | 上游 main 新增 `fund_scale_daily_szse` 同 CATALOGID（SHOWTYPE=xlsx、无 txtDm、全市场、6 个月限）；本地 1.18.49 走旧 txtDm 路径——同族接口不同访问模式 |

## B. saitoChen/ETF_Database（无 License）

- SQLite 单表 `etf_data(stat_date, sec_code, sec_name, tot_vol, UNIQUE(stat_date,sec_code))`；SSE commonQuery 同 CF 主源（实测 821 只，TOT_VOL 万份）。
- 实际数据仅 2026-03-02→2026-04-10（29 日/116 行）单次批量；配置 5 只实得 4（159949 深市无数据——SSE 接口无深市，与 CF 认知一致）。
- schedule.every().day.at("20:00") 采样——**SSE 份额 20:00 后可查的第三方旁证**。

## C. WZB1320/A-Shares-data（无 License）

- 四表 DDL（src/database/models.py L271-447，DuckDB）：两融=ak.stock_margin_detail_sse（queryMargin.do 同 CF 源）/szse；龙虎榜=ak.stock_lhb_detail_em 20 自然日滚动 UPSERT；北向=个股 stock_hsgt_individual_em（**止于 2024-08-16 政策停发**）+整体 stock_hsgt_hist_em。
- 可复用模式：update_log 水位=数据日而非执行日 + 5 日自愈窗口 + 缺口检测 SQL；龙虎榜 list_type 截断防 PK 覆盖。
- CF 价值：与 TradingWorkbench（东财源）构成**两融双独立上游** external checksum；北向停发日期入 census 断点表。

## D. gaaiyun/TradingWorkbench（**Apache-2.0，唯一可复用代码的库**）

- 数据在 Cloudflare D1 表 fund_flows（18 列双时间双来源：trade_date/ts、source/method/quality，UNIQUE 含 source+adjustment 多源并存）；三只 ETF 两融（东财 RPTA_WEB_RZRQ_GGMX 个基接口）GitHub Actions 北京工作日 20:17 拉取+手动 backfill 21471 行，补到 1638/1580/1522 条（2019-10-21/2020-01-13/2020-04-13→2026-07-27）。
- **日期归一化纪律**：trade_date=Asia/Shanghai 业务日真源（`datetime(ts,'+8 hours')` 回填；README 明令"禁止直接截 UTC 字符串前 10 位"，记载 ts.slice(0,10) 错误审计被证伪案例）；周末行拒绝（全周末载荷→UPSTREAM_SCHEMA 响亮失败）。
- **代理声明原文**（README）："融资账户和份额变化都是资金代理，不能归因到汇金、证金、险资、'国家队'、'主力'或任何具体机构；大于 35% 的相邻份额跳变按拆分或口径变化排除"——与 CF 纪律同构；其 35% 幅度哨兵与 Resonance 折算判据是两种方法（幅度 vs 因子比对），CF 采用后者（Resonance 方法更严谨）。
- 可抄作业优先级：①trade_date/ts 双列+禁截 UTC；②UNIQUE 含 source 多源并存+partial 不得覆盖 complete 的 UPSERT 守卫；③生产验收脚本（周末=0/周五存在/资金日⊆日线日集）；④flow_type×quality/method 语义化（reported/derived/snapshot_unstamped/approximation）；⑤拆分哨兵+mid-rank 分位+60 样本下限；⑥水位=数据日；⑦per-source 降级隔离；⑧date-rot 时钟偏移测试门。
- 东财 RPTA_WEB_RZRQ_GGMX 个基两融接口记录（M 引擎汇总口径之外的 L3 候选）。

## CF-HX-4 语义证明门初判

- TradingWorkbench：Apache-2.0，代码模式可直接借鉴（注明出处）；数据=东财第三方个基口径（对账用，非主源）。
- 其余三库无 License：思想借鉴自行实现。
- SZSE 修订窗口官方原文：进 CF-1A 闭合报告（available_at 定案依据）。

## 增补（完整版报告细节，2026-10-16）

1. **SSE 存在第二份额接口面**（TradingWorkbench 用）：`COMMON_JJZWZ_JJLB_JJXQ_JJGM_CKLSGM_L`（FUND_CODE 按代码查**历史**，SCALE 单位**亿元**，64 页 backfill）——与 CF 主用 `COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L`（按日全市场，万份）互补；单代码长历史回填的候选通道。
2. **深市个基日频限制证据**：159995（深市）份额**无日频官方源**，TradingWorkbench 只落东财 f84 快照（capability 显式拆 SHANGHAI_DERIVED_SHARE_SYMBOLS vs SNAPSHOT_SHARE_SYMBOLS，API 硬拒深市派生份额查询）——SZSE 官方日频=全市场批量口径，无单代码历史接口（与 A 库 txtDm 单代码 JSON 面并存，但后者 6 个月窗）。
3. **名称列非 PIT 陷阱**（ETF_Database）：`update_existing_names()` 把历史行 sec_name 全量刷成当前名；szse-etf-share 的名称列同样是 as-of-crawl 快照——**外部库的名称列一律不可当 PIT 基金名**（CF 的族过滤用当日快照重建正是为此）。
4. TradingWorkbench 成分股篮子模式：最新披露前十大持仓+披露日+coverage<80% 置 null（quality=current_top_10_approximation）——"拿快照回算历史存在成分变更与存活偏差"的显式处理。
5. 两融双独立上游格局确认：A-Shares-data（交易所官方 via akshare queryMargin.do）↔ TradingWorkbench（东财 datacenter RPTA_WEB_RZRQ_GGMX）；两库各自踩过并修复**同一坑**（水位超前于数据）——回填工程共性教训的第二份独立证据。
