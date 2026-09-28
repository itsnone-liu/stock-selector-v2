# T3 专项通道与研究边界 — 核对与修复证据（iteration 1）

任务书 hash `3ed7f3bc098d`，T3 六项要求逐条核对。

## 1) 底部三倍量观察池

- 事件定义（`strategies/bottom.py::bottom_volume_signal`）：深回撤≥30%（250日高点）、
  低位平台（≤60日低点上方15%，前20日累计涨幅∈[-20%,+15%]）、三倍量（当日量/前5日均量≥3，
  且前5日均量/前60日均量≤1.3）、涨幅≥6%收阳收高（收盘位于振幅上60%）。与
  `config/default.yaml::bottom_volume` 一致。
- 状态机（`bottom_pool.py::BottomPoolStore`）：active → invalidated（事件日后任一收盘
  跌破事件日最低价，记录失效日）/ expired（事件后可见交易日数 > `expiry_trading_days=60`）/
  converted（`--select` 通道买点命中回写转化日）。`mark_converted` 只作用于 active 行。
- **修复（asof 边界）**：`refresh()` 原先直接用 `daily[daily.index > 事件日]`，未受显式
  asof 约束——数据源若提前含 asof 之后的未来行，会把 active 事件错误判成
  invalidated/expired。已改为 `(index > 事件日) & (index <= asof)`，与信号管线同一约定。
  回归：`test_pool_refresh_ignores_future_bars_beyond_asof`、
  `test_pool_refresh_expires_only_on_bars_visible_at_asof`（含过期计数边界：可见 60 根
  仍 active，61 根 expired）。
- **修复（CLI fail-loud）**：`bottom-volume --realtime`（不带 `--select`）原先被静默忽略。
  现解析期即报错（`_RealtimeRequiresSelect`，exit 2）。回归：
  `test_cli_rejects_bottom_realtime_without_select`。
- `--select` 专用通道（`run_bottom_channel`）：跳过月线多头，要求周线趋势（小金叉）+
  周线形态 + 日线买点；suffix `bottom_close`/`bottom_realtime`；买点 CSV 非空时回写
  converted。

## 2) 各模式输出字段与隔离

- 盘后/盘中：`{surge,buy,surge_green,rejections}_{close|realtime}.csv` +
  `diagnostics_{close|realtime}.json`。
- 板块：`skip_surge` → suffix `board_close`/`board_realtime`，surge 阶段以
  `board_mode_skips_surge` 显式 PASS 记账，统一数据闸门与买点保留。
- bottom-volume：扫描写 `bottom_pool_active.csv`、`bottom_new_events_YYYYMMDD.csv`、
  `bottom_scan_diagnostics_YYYYMMDD.json`；通道复用信号管线输出并以
  `bottom_close`/`bottom_realtime` 后缀隔离。空池只写诊断（`pool_size:0`）不崩溃。
- backtest：独立固定名 `backtest_events.csv` + `backtest_summary.json`（按买点类型分组
  的均值/胜率），与信号模式文件名零重叠。SUMMARY 无实盘化措辞（研究语义见
  EVALUATION.md）。

## 3) 可追溯性与不可覆盖归档

- `output.reserve_run_dir`：`mkdir(exist_ok=False)` 原子占位，同秒同名追加 `-2`/`-3`；
  回归 `test_reserve_run_dir_is_collision_safe`、`test_run_bottom_scan_archive_is_collision_safe`
  （首次归档 sentinel 逐字节保留）。
- 每次运行归档 `runs/<YYYYMMDD_HHMMSS>/<mode>/`：信号通道归档
  `{surge,buy,green,rejections}.csv + diagnostics.json`；`trends`/`bottom_scan` 同规则。
  归档目录名由该次运行显式 `asof` 决定（`test_run_trends_archive_records_explicit_asof`）。
- 固定名/日期名文件为"最新指针"（SPEC §12 明示可替换），逐次证据只在 runs/。
- `intraday_volume_snapshots.csv`（state/）：逐行含 `quote_timestamp`/`captured_at` 可追溯，
  同 (date,minute,code) 去重 keep-last，历史日期全量保留；`state/*` 已 gitignore。
- 池状态文件 `state/bottom_volume_events.csv`：同 (代码,事件日) 去重 keep-first，同日重扫
  不重复落池（fixture e2e 验证）。

## 4) 研究脚本与生产数据边界

- `.gitignore`：`data/` 整树不入库（唯一例外 `data/t4/sector_map/csrc_industry_snapshot.json`
  为跟踪的行业快照）；`output/research/`、`state/*` 不入库。
- `git ls-files` 复核：无 `.env`/key/secret/credential/token 类文件被跟踪。
- 研究脚本（`scripts/`，169 个）写 `output/research/**`（gitignored），不写生产
  `state/`；长任务带断点/SHA 校验（如 `csr8_ingest_rt.py` H1 FAILED-resume + SHA256
  复核、`build_t7_0_features.py` 结果列白名单物理隔离）。`build_identify_features.py`
  等以 `low_memory` 分块读取大面板。

## 5) 专项测试与 fixture 端到端（不改 data/、不联网）

- 专项：`test_bottom.py`(7) + `test_pipeline_archives_t3.py`(12) + `test_snapshots.py`(2)
  + `test_benchmarks_v2.py`(0 新增) = 21 passed / 0 failed（JUnit `/tmp/t3-special.xml`）。
- fixture e2e（/tmp 工作区）：盘后扫描 → 事件落池（600001，量倍数 3.37，active）→
  诊断 `bottom_volume_launch=1`；小金叉通道对事件票给出可见拒绝
  `weekly_trend_not_passed`（rejections_bottom_close.csv）；同秒重扫归档
  `bottom_scan-2` 且首次归档字节不变；同日重扫池内仍 1 条（去重）。
- CLI 干跑：`bottom-volume --help`、`backtest --help` 正常；`bottom-volume --realtime`
  （无 --select）exit 2 且报错信息指明用法。

## 6) 全量回归

`PYTHONPATH=src ... -m pytest -q --junitxml=/tmp/t3-full.xml`
→ **454 passed / 0 failed / 0 errors / 0 skipped**（T2 基线 451 + 本轮新增 3）。

## 改动范围

- `src/stock_selector/bottom_pool.py`：refresh 显式 asof 边界。
- `src/stock_selector/cli.py`：--realtime 跨参数校验（fail loud）。
- `tests/test_bottom.py`：+3 回归。
未触碰 `data/`、凭据、无关模块。
