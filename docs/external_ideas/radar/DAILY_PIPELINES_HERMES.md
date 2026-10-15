# Hermes 日更管线交接

状态：**已部署脚本，等待 Hermes 接管定时执行**（2026-10-15）。

## 唯一入口

```bash
cd /root/project/workspace/stock-selector-v2
bash scripts/daily_pipelines.sh
```

建议：A 股交易日 **19:30 CST 之后**执行；非交易日可运行，脚本会跳过重复/不完整数据。Hermes 应保留 stdout/stderr 与 `logs/daily_pipelines.log`。

## 两条管线

### A — R5 OOS-B shadow 增量

`scripts/cl_r5b_daily_append.py`

- 冻结 84 股样本；只查询上次日期之后的 5m/日线数据；
- 每日 48 根 5m、5m 金额与日金额一致性校验；失败按股票 fail-closed；
- 新行追加到 `data/cl_radar/opening_impact_state/shadow_daily.jsonl.gz`；不改写既有行；
- `R5B_LIMIT=1` 可用于单股冒烟测试；正常运行不设该变量；
- 不能在收盘前运行，未完整的当日数据会被跳过。

### B — R6 EquityFlow 数据采集（仅数据，不做研究）

`scripts/cl_r6_equityflow_daily.py`

官方源：

- 上交所 ETF 逐基金份额；
- 深交所 ETF 逐基金份额；
- 上交所融资融券汇总；
- 深交所融资融券汇总。

输出：`data/cl_radar/r6_equityflow/` 下四个 append-only `jsonl.gz` 流。重复运行安全；不构造 panel、不连接 outcome、不运行 G1–G3、不形成 regime。

SZSE 接口存在偶发 ConnectionReset；入口对 B 自动重试一次，采集器本身也可重复运行去重。

## 验证记录

- R6 B 已用 2026-10-14 测试：SSE ETF 922 条、SZSE ETF 3761 条、SSE margin 186 条、SZSE margin 1 条；SZSE 首次连接失败，重试成功；
- R5 A 单股冒烟测试通过：`APPEND rows=0 new_days=0`，不完整/无新可验证交易日时正常 no-op；
- 运行前已修复 baostock 双调用 `get_row_data()` 导致的空行 IndexError，以及 5m 时间字段切片错误；
- A 入口已按 12 股分片执行（offset=0,12,...,72），每片 600 秒硬超时；失败片会记录 `R5 shard offset=... FAIL`，其余片继续。

## 禁止事项

在 OOS-B 60 日闭包前不得用 B 流运行任何 R6 outcome、相关性、G1–G3、regime 或综合资金指数；R6 仍为 `PRE-RESEARCH COMPLETE / MECHANISM VALIDATION NOT AUTHORIZED`。

## 运行边界与已知外部风险（2026-10-15 验收记录）

1. **baostock 当前不可达**（登录即"网络接收错误"，此前为连接重置/超时）；且 2026-10 的 5m/日线数据在其服务端尚未发布（error_code=0 但零行）。两者均为**外部数据源状态**，非脚本缺陷；
2. A 线已具备：增量窗口查询（绝不整年）、每查询 3 次退避重试、登录失败快速退出、12 股分片×600s 硬超时、每股 fail-closed、STATS 审计行（stocks/no_new_trade_day/query_failed/new_rows/maturity_new）、成熟列补写（lambda_next_5/20，按回填同款公式写 maturity_updates.jsonl.gz，历史已有值的行自动跳过）；
3. 验收证据：多次分片实测 RC=0（无新日时正确 no-op + STATS）；公式回归 opening_amount/post_open_lambda 全对、lambda_open 约定与回填一致（前一日未复权收盘，代码级比对两脚本）；**首次真实新增行写入待 baostock 恢复后由 Hermes 首跑自然完成**——首周请人工核对一次 STATS 行（new_rows>0 且 shadow 末日推进）；
4. B 线 SZSE 偶发 ConnectionReset，入口已配一次重试 + 按日期+代码去重。

## 首周人工核对清单（Hermes 接管后）

- 日志出现 `LOGIN FAIL` 连续 ≥3 个交易日 → baostock 层故障，人工介入；
- `STATS` 中 `query_failed` 持续偏高 → 数据源或网络问题；
- baostock 恢复后首个交易日：确认 `APPEND rows>0` 且 shadow_daily 末日推进、maturity_updates 开始产生记录。
