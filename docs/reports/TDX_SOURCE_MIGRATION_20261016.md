# TDX 数据源接入与替换报告（2026-10-16）

## 执行原则

仅替换 TDX 行情协议能够等价覆盖的字段和周期；不因“统一数据源”而伪造复权、行业、财务或资金披露字段。所有新路径 fail-closed，并保留 `source_id`。

## 本次已完成

### 1. 正式数据层

新增：

- `stock_selector.data.tdx_live.TdxLiveClient`
- `stock_selector.data.tdx_r4.fetch_r4_days`
- `stock_selector.decision.minutes.TdxLiveMinuteProvider`

特点：

- 纯 Python stdlib，无 pytdx、pandas ABI 或外部 HTTP 依赖；
- op11 会话 + op052d count-based 分页；
- amount/volume 按当前主站的 IEEE float32 解码；
- 日线 volume 手→股，分钟 volume 原始即股；
- 网络失败、历史超出保留期、bar 不完整均返回缺失，不合成数据。

### 2. R4 OOS-B 日更

`scripts/cl_r5b_daily_append.py` 的活跃增量链已从 baostock 切换为：

```text
TDX 052d 5m + TDX raw daily + daily_fullmarket qfq
```

保留门禁：

- 每日必须 48 根 5m；
- Σ5m amount / daily amount ∈ [0.95, 1.05]；
- Σ5m volume / daily volume ∈ [0.999, 1.001]；
- qfq 当日值必须已落入 `daily_fullmarket`，缺失则 fail-closed；
- 新 shadow 行写 `source_id=tdx_052d_v1`。

成熟期 `lambda_next_5/20` 也改从 `daily_fullmarket + market_ext` 读取，不再登录 baostock。

真实只读烟测：000001 的 2026-10-15、2026-10-16 均返回 48 根，amount 比例约 1.0。

### 3. 盘中 1m 与实时 Quote

`TdxLiveMinuteProvider.minute_frame()` 已符合现有分钟 provider 合同：

```text
index: pandas DatetimeIndex
columns: open, high, low, close, volume, amount
attrs.source_id = tdx_052d_1m_v1
```

可直接供 `quote_from_minutes()` 使用。超出约两个月保留期时返回 None，不使用 synthetic fallback。

新增 `TdxQuoteProvider` 并将 `Pipeline.run_realtime/run_board/run_bottom_channel` 的默认行情源从腾讯 HTTP 改为 TDX：当前价、今开、昨收、累计 volume/amount 均从同一 TDX 数据链产生。北京市场当前不支持，显式返回 source error，不隐藏回退腾讯。

### 4. 日更入口

`scripts/daily_pipelines.sh` 的 R5 分片不再加载 `/tmp/bspy`，避免 baostock/pandas ABI 和 17021 服务挂起。R6 资金流任务仍保留 `/tmp/aksy`，见下方不可替换项。

## 数据源迁移矩阵

| 数据域 | 原源 | TDX 能力 | 处置 |
|---|---|---|---|
| 本地日线 OHLCVA | 本地 TDX `.day` | 原生 | 保持 TDX 主源 |
| 网络日线补抓/校验 | 腾讯/新浪/baostock | 052d 完整历史 | 后续统一到 TDX |
| 近期 1m | 缺失/本地空 lc1 | 052d 约两个月 | 已接入 provider |
| 近期 5m/OOS-B | baostock | 052d 约一年 | 已替换 |
| 盘中 Quote | HTTP quote/降级 | TDX 1m | provider 已就位，消费入口可启用 |
| VolumeClock profile | 无真实分钟 | TDX 1m | 收集 ≥20 日后启用 |
| qfq/hfq | baostock/腾讯/新浪因子层 | 行情通道无等价复权因子 | 暂保留既有物化层，不远程回退 |
| 换手率/free-float | baostock/扩展层 | 052d 无流通股本 | 暂不替换 |
| 行业分类/成分 | baostock/akshare/静态快照 | 行情通道无 PIT 分类 | 保留冻结物化数据 |
| ETF 份额、融资融券、龙虎榜、股东披露 | akshare/官方站 | 普通行情通道无等价字段 | 不替换，属于非行情数据域 |
| 新浪复权事件 | 新浪 hfq.js | 052d 无公司行动事件 | 冻结历史证据保留；活跃行情链不再依赖 |

## 哪些旧代码不改

冻结研究和证据产物不进行源重写，包括 `adjustment_baostock`、新浪复权交叉审计、CSR/Phase I 封存价格库等。它们的来源身份已经是研究合同的一部分，机械替换会破坏可复现性。

本次迁移针对活跃运行链，而不是重写历史事实。

## 验证

新增测试：

- float32 成交字段；
- 日线手→股；
- 市场映射；
- 1m provider provenance/fail-closed；
- R4 适配器完整日和 qfq 缺失门禁。

针对性及相关决策/CLI 回归：42 项通过。

## 后续可行工作

1. CLI/服务配置中提供 `minute_provider=tdx_live` 开关并默认启用；
2. 建立本地 1m 缓存，避免相同股票/日期重复下载；
3. 满 20 个完整日后物化 VolumeClock profile；
4. 将仍在活跃运行的网络日线补抓脚本改为 TDX，但禁止改写冻结研究仓；
5. R6 非行情数据域继续逐项寻找官方直连源，不用行情 TDX 强行代替。
