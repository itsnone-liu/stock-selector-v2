# Stock Selector v2

本项目是在全新目录中重建的统一股票筛选系统。旧系统位于 `/root/.hermes/hermes-agent/` 和 `release_2026-08-07/`，本项目不修改旧文件，也不替换现有定时任务。

## 目标

统一原来分叉的月线、周线、weeksurge、盘中和板块选股逻辑，并修复：

- 当前周/已完成周依赖 `iloc[-1]` 猜测的问题；
- 周一把上周开盘当本周开盘的问题；
- 腾讯成交量“手”和通达信成交量“股”直接比较的问题；
- 周中把价格收益线性外推到五天的问题；
- 盘中累计量直接和昨日全天量比较的问题；
- `weeksurge_阴线.csv` 实际混入上涨未通过股票的问题；
- B股、ST、低流动性股票缺少统一过滤的问题；
- 数据过期和行情缺失被静默跳过的问题；
- 输出中途覆盖、没有拒绝原因统计的问题；
- 没有自动化测试和回测入口的问题。

## 架构

```text
src/stock_selector/
├── calendar.py            # 显式周边界、交易时段进度
├── config.py              # YAML统一配置
├── models.py              # Quote/RuleResult/诊断模型
├── freshness.py           # 历史数据与实时报价时效闸门
├── indicators.py          # MA/MACD等统一指标
├── data/
│   ├── tdx.py             # 本地通达信历史数据
│   └── realtime.py        # 腾讯实时行情；入口统一换算手→股
├── strategies/
│   ├── risk.py            # B股/ST/上市时间/流动性过滤
│   ├── trend.py           # 月线和周线趋势
│   ├── surge.py           # 唯一的周线形态实现
│   └── buy.py             # 唯一的日线买点实现
├── pipeline.py            # 全市场、盘中、盘后、板块管线
├── backtest.py            # 按买点类型统计未来收益
└── cli.py                 # 统一命令入口
```

## 环境

本机可直接复用 Hermes 虚拟环境：

```bash
cd /root/project/workspace/stock-selector-v2
export PYTHONPATH=src
PY=/root/.hermes/hermes-agent/venv/bin/python3
```

也可在独立虚拟环境中安装：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

## 命令

### 1. 构造证券范围

```bash
$PY -m stock_selector.cli universe
```

### 2. 全市场月线→周线趋势池

```bash
$PY -m stock_selector.cli trends
```

也可从指定CSV开始：

```bash
$PY -m stock_selector.cli trends --pool some_pool.csv
```

### 3. 盘后筛选

```bash
$PY -m stock_selector.cli after-close --pool output/weekly_pool.csv
```

### 4. 盘中筛选

```bash
$PY -m stock_selector.cli realtime --pool output/weekly_pool.csv
```

盘中会生成：

- `surge_realtime.csv`：周线形态通过池；
- `buy_realtime.csv`：最终买点；
- `surge_green_realtime.csv`：只包含形态通过且实时价低于昨收的股票；
- `rejections_realtime.csv`：逐票淘汰阶段与原因；
- `diagnostics_realtime.json`：各阶段通过、拒绝、跳过和行情错误统计。

### 5. 板块选股

板块模式保留旧系统的业务规则：跳过weeksurge，直接做风险过滤和日线买点。

```bash
$PY -m stock_selector.cli board \
  --pool /root/.hermes/hermes-agent/release_2026-08-07/sector/output/board_members.csv \
  --board 电网设备 \
  --realtime
```

### 6. 底部三倍量观察池

每日盘后扫描并刷新池状态：

```bash
$PY -m stock_selector.cli bottom-volume
```

对活跃池运行“小金叉专用通道”（跳过月线多头，保留周线趋势/小金叉→周线形态→日线买点）：

```bash
$PY -m stock_selector.cli bottom-volume --select
$PY -m stock_selector.cli bottom-volume --select --realtime
```

状态文件为`state/bottom_volume_events.csv`；收盘破事件日低点自动失效，60交易日未转化自动过期。

### 7. 回测

```bash
$PY -m stock_selector.cli backtest \
  --pool output/weekly_pool.csv \
  --start 2025-01-01 \
  --end 2026-06-30 \
  --horizons 1,3,5,10
```

输出事件明细和按买点类型汇总的均值收益、胜率。该回测是研究框架，不包含手续费、滑点、涨跌停成交约束，不能直接当实盘结论。

## 关键定义

### 周线锚定

所有周线判断显式分成：

- `completed_week_rows`：本周一以前的数据；
- `current_week_rows`：本周一到当前时点的数据。

不再依据本地数据是否更新来猜 `weekly.iloc[-1]` 是本周还是上周。

### 周中折算

- 价格：使用真实已实现涨幅，不线性外推；
- 成交量：按已完成交易日和当前交易时段比例估算完整周；
- 输出保留 `elapsed_week_fraction`，使估算可审计。

### 盘中缩量

优先比较“今日同一时点累计量 / 昨日同一时点累计量”。若没有同刻历史，只允许使用明确标记的全天投影回退，输出 `volume_method=projected_full_day`，不再把上午累计量直接和昨日全天量比较。

当前腾讯接口只提供今日累计量，尚未建立分钟级历史缓存，因此命令行实时运行默认使用“进度投影回退”。后续积累同刻快照后可向 `daily_buy()` 提供 `same_time_reference_volume`。

### 成交量单位

系统内部统一使用“股”。腾讯接口字段为“手”，在 `TencentQuoteProvider` 边界乘100后才进入规则层。

## 运行归档与同刻量快照

每次运行会在 `output/runs/YYYYMMDD_HHMMSS/<模式>/` 保存不可覆盖的完整归档。盘中累计成交量快照持久化到 `state/intraday_volume_snapshots.csv`；下一交易日运行时会自动匹配上一交易日相近分钟，匹配不到才使用明确标记的全天投影回退。

完整规则定义见 `SPEC.md`；体系消融、大盘regime、评分分位、退出规则和底部通道的历史数据见 `EVALUATION.md`。

## 配置

默认配置：`config/default.yaml`。可传入覆盖配置：

```bash
$PY -m stock_selector.cli --config config/my.yaml realtime --pool output/weekly_pool.csv
```

配置采用深度合并，不需要复制全部默认项。

## 测试

```bash
$PY -m pytest -q
```

当前测试覆盖：

- 周边界显式切分；
- 午间休市和交易进度；
- 周一使用本周今开；
- 实时收益不做五天外推；
- 腾讯手→股换算；
- 盘后昨收定位；
- B股、ST和流动性过滤；
- 原子CSV和股票代码前导零。

## 当前验收

使用旧系统的 `weekbull_输出.csv` 和本地 `/root/tdx_data`，以 `2026-09-15T15:10:00` 为时点完成盘后端到端验收：

- 输入周线池：250只；
- 历史数据新鲜：249只，过期1只；
- 风险过滤通过：221只；
- 排除ST/退市标记23只；
- 排除B股5只；
- weeksurge通过78只；
- 日线买点15只；
- 无异常崩溃，所有拒绝原因落盘。

验收只证明程序链路和边界处理工作正常，不证明策略有效。策略有效性需运行较长区间回测，并按市场阶段做样本外验证。

## 迁移原则

1. 旧程序和旧定时任务暂不动。
2. v2先并行运行一段时间，对比输出和漏选原因。
3. 对盘中缩量建立昨日同刻快照后，再评价该买点。
4. 完成回测和至少数周影子运行后，才考虑切换定时任务。
