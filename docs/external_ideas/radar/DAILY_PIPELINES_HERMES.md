# Hermes 日更管线交接

状态：**已部署脚本，Hermes cron 接管定时执行**（2026-10-15 起跑；2026-10-19 起调度改为 **22:05 CST**，job `cl-daily-pipelines-2205`）。

调度说明（2026-10-19 核实 Hermes cron 语义后修订）：cron 为单车道（tick 文件锁 + 同步执行），19:30 的 R2 日链会占线 ~2h；**迟到不足一个周期的作业会在锁释放后的首个 tick 补跑**（at-most-once 设计），所以 CL 即使被 R2 顶住也只会延迟、不会丢。挪到 22:05 是为了让常规夜晚不再依赖补跑（周五实测 R2 会话最晚 21:54 结束，留 10 分钟余量）。

## 唯一入口

```bash
cd /root/project/workspace/stock-selector-v2
bash scripts/daily_pipelines.sh
```

建议：A 股交易日 **19:30 CST 之后**执行；非交易日可运行，脚本会跳过重复/不完整数据。Hermes 应保留 stdout/stderr 与 `logs/daily_pipelines.log`。

## 三条管线

退出码：`0`=正常（含容忍跳过）；`2`=A 线致命；`3`=B 线致命；`4`=C 线致命。

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

**B 线已知失败模式——发布时间竞态（2026-10-16 诊断，10-19 根治）**：`etf_sse`/`margin_szse` 按日查询；若跑时（~22:05）交易所尚未发布当日数据，接口回空表，akshare 抛 `KeyError("None of [Index(['序号',…]]")` 或 `Length mismatch: Expected axis has 0 elements`——**签名与"源页面改版"完全相同**。鉴别方法：用已发布日期现场探测（如 `fund_etf_scale_sse(date=前一日)`），能查到即非改版。10-16 晚即属此竞态。

2026-10-19 起采集器已根治：按日流自动回补窗口内（≤10 个自然日）所有缺失的**确认交易日**（交易日历取自 SSE margin 区间流的官方日期；margin 获取失败时退化为周一~周五启发式）。日志语义：

- `etf_sse=924`：本轮写入行数；
- `pending=(YYYYMMDD)`：当日数据未发布（竞态），**不算失败**，次晚自动回补；
- `empty=(YYYYMMDD)`：确认交易日返回零行（按日接口仅保留近期若干交易日），不影响退出码；
- `FAIL empty(published trade day YYYYMMDD)`：已发布交易日空响应 → 源侧问题（页面改版/解析坏），当晚即 FAIL 报警；
- 传输类异常（ConnectionError 等）→ FAIL，入口层整脚本重试一次（dedup-safe）。

人工补洞兜底（超出 10 天窗口的旧洞，dedup-safe）：

```bash
PYTHONPATH=/tmp/aksy /usr/bin/python3 scripts/cl_r6_equityflow_daily.py YYYYMMDD
```

`margin_sse`/`etf_szse` 为区间查询，缺失日期在后续运行中自动补齐，无需人工。2026-10-19 已把四流补齐至 10-08 起（含 10-16 竞态洞与流诞生前的 10-08~10-13 存量洞）。

### C — CF atoms 重放 + Capital Weather（2026-10-16 加入）

`scripts/cf/run_atoms.py`（入口为 `PYTHONPATH=src .venv/bin/python`）

- CF-1 L1/M/L4 原子重放 + 并排 Capital Weather，独立、fail-closed；
- 输出 `data/cf/derived/capital_weather/latest.json`（L1/M/L4 各带 asof）；
- 退出码 `4` = C 线致命；报告时需核对 L1/M/L4 的 asof 是否停滞（落后 ≥2 个交易日要警告）。

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
